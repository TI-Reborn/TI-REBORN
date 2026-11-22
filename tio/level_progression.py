"""Original cumulative level thresholds; explicitly local damage-XP policy.

Database helpers participate in the caller's reward transaction. The client
returns level0 at its upper sentinel, so cumulative XP must stay below it.
"""

from .db_transaction import connect
from bisect import bisect_right
from collections.abc import Collection
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
from .protocol.pet_info import decode_pet_info, encode_pet_info

RULES=json.loads((Path(__file__).resolve().parents[1]/'config/level_progression.json').read_text(encoding='utf-8'))
FLOORS=tuple(RULES['level_floors'])
MAX_XP=RULES['native_upper_sentinel']-1
LEVEL='0x8c4aef'
XP='0x8c4b05'
if (len(FLOORS)!=20 or FLOORS[0]!=0 or any(type(x) is not int or x<0 for x in FLOORS)
        or any(a>=b for a,b in zip(FLOORS,FLOORS[1:])) or MAX_XP<=FLOORS[-1]):
    raise ValueError('Invalid native experience table')


def level_for_xp(xp):
    if type(xp) is not int or not 0<=xp<=MAX_XP:raise ValueError('Experience outside native range')
    return bisect_right(FLOORS,xp)


def normalize(packet,human):
    """Repair old level-only saves without demoting manually raised fighters."""
    pet=decode_pet_info(packet,human_equipment=human);f=dict(pet.fields)
    old=f[LEVEL]
    if not 1<=old<=20:raise ValueError('Invalid saved level')
    xp=max(FLOORS[old-1],min(MAX_XP,f[XP]));level=level_for_xp(xp)
    base=RULES['initial_hp'].get(str(f['0x8c446f']))
    if base is None:raise ValueError('Unsupported persistent fighter species')
    # Preserve legacy diagnostic health above the manual baseline. Applying
    # migration repeatedly must never add the same level growth twice.
    maximum=max(f['0x8c4a07']+(level-old)*RULES['hp_per_level'],base+(level-1)*RULES['hp_per_level'])
    f.update({LEVEL:level,XP:xp,'0x8c4a07':maximum})
    return encode_pet_info(replace(pet,fields=f))


def sync(db,account):
    for owner,human,raw in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(account,)).fetchall():
        packet=normalize(raw,bool(human))
        if packet!=raw:db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,account,owner))


class BattleExperience:
    def __init__(self,policy=None):
        self.policy=dict(RULES['local_damage_policy'] if policy is None else policy)
        if any(type(v) is not int or v<0 for v in self.policy.values()):raise ValueError('Invalid XP policy')
        if not 0<self.policy['minimum_strength_percent']<=self.policy['maximum_strength_percent']:
            raise ValueError('Invalid opponent strength bounds')
        self.totals={}
        self.used_health={}

    def strength(self,combat,actor_id):
        from .ranks import rank_id
        from .protocol.item_list import decode_item_list
        level,rank=combat.rank_profiles.get(actor_id,(1,0))
        packet=combat.inventories.get(actor_id)
        equipped=[] if packet is None else [i for i in decode_item_list(packet)[1] if i.equipped]
        upgrade=Fraction(sum(min(i.unknown_bytes_03[0],combat.enhancement_caps.get(actor_id,25)) for i in equipped),max(1,len(equipped)))
        return level,rank_id(rank),upgrade

    def factor(self,own,opponent):
        c=self.policy
        percent=100+sum((b-a)*c[k] for a,b,k in zip(own,opponent,
            ('level_difference_percent','rank_difference_percent','equipment_upgrade_difference_percent')))
        return Fraction(max(c['minimum_strength_percent'],min(c['maximum_strength_percent'],percent)),100)

    def damage(self,combat,attacker,victim,damage):
        if damage<=0 or combat.field.allied(attacker.owner_id,victim.owner_id):return
        c=self.policy
        used=self.used_health.get(victim.actor_id,0)
        eligible=max(0,min(damage,victim.max_health*c['victim_hp_budgets_per_battle']-used))
        self.used_health[victim.actor_id]=used+eligible
        if not eligible:return
        a,b=self.strength(combat,attacker.actor_id),self.strength(combat,victim.actor_id)
        for actor,other,identity,rate in ((a,b,attacker.actor_id,c['xp_per_damage_dealt']),
                                         (b,a,victim.actor_id,c['xp_per_damage_received'])):
            self.totals[identity]=self.totals.get(identity,Fraction(0))+eligible*rate*self.factor(actor,other)

    def report(self,combat,owner,*,actor_ids: Collection[int] | None = None) -> dict[int, int]:
        eligible = combat.persistence if actor_ids is None else actor_ids
        return {i:min(MAX_XP,int(self.totals.get(i,0))) for i,a in combat.field._actors.items()
                if a.owner_id==owner and i in eligible}


def settle_experience(db,account,match_id,report,*,keep_full_health: bool = False):
    db.execute('''CREATE TABLE IF NOT EXISTS experience_battle_audit (
        account TEXT NOT NULL, match_id TEXT NOT NULL, pet_id INTEGER NOT NULL,
        xp_before INTEGER NOT NULL, gain INTEGER NOT NULL, xp_after INTEGER NOT NULL,
        level_before INTEGER NOT NULL, level_after INTEGER NOT NULL,
        PRIMARY KEY(account,match_id,pet_id))''')
    for owner,gain in sorted(report.items()):
        if type(gain) is not int or not 0<=gain<=MAX_XP:raise ValueError('Invalid battle experience')
        if db.execute('SELECT 1 FROM experience_battle_audit WHERE account=? AND match_id=? AND pet_id=?',(account,match_id,owner)).fetchone():continue
        row=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        if row is None:raise ValueError('Experience recipient missing')
        human,raw=row
        pet=decode_pet_info(normalize(raw,bool(human)),human_equipment=bool(human));f=dict(pet.fields)
        before=f[XP];old=f[LEVEL];after=min(MAX_XP,before+gain);level=level_for_xp(after)
        growth = (level-old)*RULES['hp_per_level']
        if keep_full_health and f['0x8c4ab1'] == f['0x8c4a07']:
            f['0x8c4ab1'] += growth
        f.update({XP:after,LEVEL:level,'0x8c4a07':f['0x8c4a07']+growth})
        # Current HP is retained even at zero. Perk HP is projected separately.
        from .weapon_proficiency import ProficiencyRules
        packet=ProficiencyRules().normalize(encode_pet_info(replace(pet,fields=f)),bool(human))
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,account,owner))
        db.execute('INSERT INTO experience_battle_audit VALUES (?,?,?,?,?,?,?,?)',
                   (account,match_id,owner,before,after-before,after,old,level))


def result_packets(path,account,match_id,combat,view,*,actor_ids: Collection[int] | None = None):
    """Update native actor XP before4C subtracts gain to detect a promotion."""
    from .protocol.binary import Writer
    from .protocol.battle_over import SoldierExperience
    from .weapon_proficiency import BASE,SAVED,battle_fields
    from .passive_stats import project_saved_pet
    from .protocol.battle_soldier import encode_battle_soldier
    updates=[];records=[]
    # Stored pet IDs are account-local; shared battle actor IDs are global.
    # Filter persistence by account before inversion because opponents may both
    # own pet1, and mirrored bots can reuse the same saved source fighter.
    actors={}
    if actor_ids is None:
        actor_ids = tuple(i for i, (_, saved_account) in combat.persistence.items() if saved_account == account)
    for identity in actor_ids:
        local=combat.storage_ids.get(identity,identity)
        if local in actors:raise ValueError('Ambiguous battle experience recipient')
        actors[local]=identity
    with closing(connect(path)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='experience_battle_audit'").fetchone():return (),()
        rows=db.execute('SELECT pet_id,gain,xp_after FROM experience_battle_audit WHERE account=? AND match_id=? ORDER BY pet_id',(account,match_id)).fetchall()
        for owner,gain,xp in rows:
            if owner not in actors:raise ValueError('Battle experience actor missing')
            identity=actors[owner]
            human,raw=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
            human=bool(human)
            projected=project_saved_pet(db,account,owner,raw,human)
            f=decode_pet_info(projected,human_equipment=human).fields
            if view is not None and identity in view.templates:
                actor=combat.field.actor(identity);t=view.templates[identity]
                fields={**t.fields,**battle_fields(projected,human),'0x8c5134':f[LEVEL],'0x8c514b':xp,
                    '0x8c566a':f['0x8c4a07'],'0x8c57d0':f['0x8c4b57'],
                    '0x8c5847':f['0x8c4bbc'],'0x8c585c':f['0x8c4bd0'],
                    '0x8c519b':actor.x,'0x8c51af':actor.y,'0x8c57bb':actor.health,
                    '0x8c571d':actor.action_points,'0x8c5694':combat.field._turn_points[identity]}
                from .avatars import soldier_avatar
                updates.append(encode_battle_soldier(replace(t,fields=soldier_avatar(combat.field,identity,fields))))
            # 4E attribute2 is the original experience/model+602C update.
            updates.append(Writer().u8(0x4e).u32(identity).u32(1).u32(2).u32(xp).u8(0).build())
            initial=combat.initial_proficiencies.get(identity,projected)
            old=decode_pet_info(initial,human_equipment=human).fields
            # Original reader's old-skill order differs from the full profile.
            previous=tuple(old[BASE[i]] for i in (0,1,4,3,2,5,7))
            profile=tuple(f[k] for pair in zip(SAVED,BASE) for k in pair)
            records.append(SoldierExperience(identity,gain,previous,profile))
    return tuple(updates),tuple(records)
