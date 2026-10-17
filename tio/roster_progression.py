"""Fresh-character starters, durable random city hires and tutorial progress.

No existing save is backfilled: grant_starters requires the trusted creation
boundary explicitly. Random offers are stored per account/city until hired;
refresh/reconnect never rerolls a quoted offer or revives a consumed ID.
"""
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import random
from xml.etree import ElementTree

from .ability_progression import policy
from .db_transaction import transaction
from .hiring import HireStore
from .owned_pets import OwnedPetStore
from .protocol.city_catalogs import encode_pet_shop,decode_pet_shop
from .protocol.pet_info import PetInfo,SCHEMAS,decode_pet_info,encode_pet_info
from .protocol.item_list import encode_item_list
from .wallets import WalletStore

RANDOM_OFFER_BASE=0x40000000
MALE=('Alex','Boris','Chris','Dan','Evan','Frank','Greg','Jack','Mark','Rick','Sam','Victor')
FEMALE=('Alice','Anna','Claire','Diana','Eva','Helen','Jane','Kate','Lena','Maya','Nina','Rose')
SURNAMES=('Stone','Fox','Reed','Hunter','North','Black','Ward','Lane','Woods','Cross','Gray','Wolf')
DOG_NAMES=('Rex','Rocky','Scout','Buddy','Lucky','Ranger','Bolt','Ace','Bruno','Shadow','Max','Toby')
TUTORIAL_EVENTS=('move','attack','end_turn','enemy_killed')
TUTORIAL_TIPS=('Сделайте ход: выберите своего бойца и переместитесь на соседнюю клетку.',
               'Выберите оружие и атакуйте учебную мишень.',
               'Завершите ход, чтобы восстановить очки действия.',
               'Победите учебного противника и вернитесь в город.')


def roster_expansion():return tuple(tuple(row) for row in policy()['roster_expansion'])


@lru_cache(maxsize=1)
def _looks():
    from .appearance import CATALOG,TYPES
    result={}
    for group in ElementTree.parse(CATALOG).getroot():
        if group.attrib['type'] not in TYPES:continue
        for option in group:
            if option.attrib.get('premium','false')=='true':continue
            for resource in option.text.split():
                result.setdefault((group.attrib['type'],int(resource)),[]).append(int(option.attrib['id']))
    return result


def random_appearance(resource,rng):
    if resource not in (1,2):return None
    from .appearance import TYPES
    defaults=(resource,0 if resource==1 else 8,0,1,0,0)
    return bytes(rng.choice(_looks().get((kind,resource),(default,)))
                 for kind,default in zip(TYPES,defaults))


def random_name(resource,rng,used=()):
    used={name.decode('cp1251').casefold() if isinstance(name,bytes) else name.casefold() for name in used}
    for attempt in range(100):
        name=rng.choice(DOG_NAMES) if resource in (3,4,5) else rng.choice(FEMALE if resource==2 else MALE)+' '+rng.choice(SURNAMES)
        if attempt>=20:name+=' '+str(attempt)
        if name.casefold() not in used:return name.encode('cp1251')
    raise ValueError('Случайные имена исчерпаны')


def profile(template,identity,resource,name,appearance=None):
    """Manual first-level baseline; opaque fixture fields remain preserved."""
    human=resource in (1,2,6)
    base=decode_pet_info(template,human_equipment=True)
    from .level_progression import RULES
    from .weapon_proficiency import ProficiencyRules,SAVED,BASE,bits,HUMAN_SKILLS
    from .weight import base_capacity
    fields={**base.fields,'0x8c43eb':identity,'0x8c446f':resource,'0x8c4489':name,
            '0x8c4aef':1,'0x8c4b05':0,'0x8c4a07':RULES['initial_hp'][str(resource)],
            '0x8c4ab1':RULES['initial_hp'][str(resource)],'0x8c4a1b':8 if resource==6 else 9 if human else 11,
            '0x8c4a2f':14 if resource==6 else 15 if human else 17,'0x8c4b57':base_capacity(resource,1),
            '0x8c4b6d':0,'0x8c44a6':0,'0x8c4ac5':0,'0x8c4bbc':1,'0x8c4bd0':0,
            '0x8c4be3':0,'0x8c4bf6':20,'0x6d0203':int(appearance is not None)}
    if appearance is not None:
        from .appearance import FIELDS
        if len(appearance)!=6:raise ValueError('Invalid recruit appearance')
        fields.update(dict(zip(FIELDS,appearance)))
    for index,(saved,initial) in enumerate(zip(SAVED,BASE)):
        fields[saved]=fields[initial]=bits(35 if index in (HUMAN_SKILLS if human else (0,)) else 0)
    schema=SCHEMAS[(human,bool(fields['0x6d0203']),bool(fields['0x8c4565']))]
    packet=ProficiencyRules().normalize(encode_pet_info(PetInfo(human,{key:fields.get(key,0) for key,_,_ in schema})),human)
    OwnedPetStore.validate(packet,encode_item_list(identity,()),human)
    return packet


def _schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS random_hire_offers(account TEXT NOT NULL,town_id INTEGER NOT NULL,resource INTEGER NOT NULL,candidate_id INTEGER NOT NULL,packet BLOB NOT NULL,PRIMARY KEY(account,town_id,resource),UNIQUE(account,candidate_id))')
    db.execute('CREATE TABLE IF NOT EXISTS character_roster_creation(account TEXT PRIMARY KEY,starter_ids TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS character_tutorials(account TEXT PRIMARY KEY,step INTEGER NOT NULL DEFAULT 0,match_id TEXT,completed INTEGER NOT NULL DEFAULT 0,observed_events INTEGER NOT NULL DEFAULT 0)')
    if 'observed_events' not in {r[1] for r in db.execute('PRAGMA table_info(character_tutorials)')}:
        db.execute('ALTER TABLE character_tutorials ADD COLUMN observed_events INTEGER NOT NULL DEFAULT 0')
        db.execute('UPDATE character_tutorials SET observed_events=(1<<step)-1')


class RecruitmentStore(HireStore):
    def __init__(self,path,catalogs,template,*,rng=None):
        super().__init__(path,catalogs,template)
        self.template_packet=template;self.rng=rng or random.SystemRandom()
        with transaction(path) as db:_schema(db)

    def available(self,account):
        if not isinstance(account,str) or not account:raise ValueError('Account required')
        with transaction(self.path) as db:return self._available(db,account)

    def _available(self,db,account):
        from .cities import CITIES,town_in
        town=town_in(db,account)
        if town not in (*CITIES,9):return ()
        resources=sorted({c.resource_type for c in self.catalogs.candidates if (c.resource_type==6)==(town==9)})
        result=[]
        for resource in resources:
            row=db.execute('SELECT packet FROM random_hire_offers WHERE account=? AND town_id=? AND resource=?',(account,town,resource)).fetchone()
            if row is None:
                maximum=max(RANDOM_OFFER_BASE-1,
                    db.execute('SELECT COALESCE(MAX(candidate_id),0) FROM random_hire_offers WHERE account=?',(account,)).fetchone()[0],
                    db.execute('SELECT COALESCE(MAX(candidate_id),0) FROM hired_candidates WHERE account=?',(account,)).fetchone()[0])
                identity=maximum+1
                if identity>0xffffffff:raise ValueError('Candidate IDs exhausted')
                used=[decode_pet_info(p,human_equipment=bool(h)).fields['0x8c4489']
                      for h,p in db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=?',(account,))]
                used.extend(decode_pet_shop(p)[0].name for (p,) in db.execute('SELECT packet FROM random_hire_offers WHERE account=?',(account,)))
                name=random_name(resource,self.rng,used);appearance=random_appearance(resource,self.rng)
                template=next(c for c in self.catalogs.candidates if c.resource_type==resource)
                from .level_progression import RULES
                from .weapon_proficiency import bits,HUMAN_SKILLS
                human=resource in (1,2,6)
                stats=tuple(bit for index in range(8) for bit in (bits(35 if index in (HUMAN_SKILLS if human else (0,)) else 0),)*2)
                offer=replace(template,unknown_u32_01=identity,name=name,unknown_u8=1,optional_bytes=appearance,
                              stat_float_bits=stats,unknown_u16_01=RULES['initial_hp'][str(resource)],
                              unknown_u32_03=policy()['hire_credits'][str(resource)])
                packet=encode_pet_shop((offer,))
                db.execute('INSERT INTO random_hire_offers VALUES (?,?,?,?,?)',(account,town,resource,identity,packet))
            else:offer=decode_pet_shop(row[0])[0]
            result.append(offer)
        return tuple(result)

    def hire(self,account,candidate_id):
        if not isinstance(account,str) or not account:raise ValueError('Account required')
        with transaction(self.path) as db:
            offers=[offer for offer in self._available(db,account) if offer.candidate_id==candidate_id]
            if len(offers)!=1:raise ValueError('Неизвестное или устаревшее предложение найма')
            offer=offers[0]
            from .services import level
            expansion=level(db,account,2)
            if not 0<=expansion<=len(roster_expansion()):raise ValueError('Неверный сервис расширения отряда')
            count,highest=db.execute('SELECT COUNT(*),COALESCE(MAX(pet_id),0) FROM owned_pets WHERE account=?',(account,)).fetchone()
            if count>=policy()['base_roster_capacity']+(roster_expansion()[expansion-1][0] if expansion else 0):
                raise ValueError('Отряд заполнен')
            historical=db.execute('SELECT COALESCE(MAX(pet_id),0) FROM hired_candidates WHERE account=?',(account,)).fetchone()[0]
            identity=max(highest,historical)+1
            if identity>0xffffffff:raise ValueError('Pet IDs exhausted')
            pet=profile(self.template_packet,identity,offer.resource_type,offer.name,offer.optional_bytes)
            inventory=encode_item_list(identity,())
            if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?',
                          (offer.price_credits,account,offer.price_credits)).rowcount!=1:
                raise ValueError('Недостаточно кредитов для найма')
            db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(account,identity,int(offer.resource_type in (1,2,6)),pet,inventory))
            db.execute('INSERT INTO hired_candidates VALUES (?,?,?)',(account,candidate_id,identity))
            db.execute('DELETE FROM random_hire_offers WHERE account=? AND candidate_id=?',(account,candidate_id))
            wallet=WalletStore(self.path).ensure(account)
        return pet,inventory,wallet


def grant_starters(path,account,template,*,created=False,rng=None):
    """Call only after a NEW character's main actor was created durably.

    Root passes created=True at its trusted creation boundary in the same
    gameplay transaction. Login, prepare/resume and migrations must passFalse.
    """
    if not created:return ()
    rng=rng or random.SystemRandom()
    with transaction(path) as db:
        _schema(db)
        row=db.execute('SELECT starter_ids FROM character_roster_creation WHERE account=?',(account,)).fetchone()
        if row:return tuple(json.loads(row[0]))
        character=db.execute('SELECT 1 FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
        owned=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)).fetchall()
        if character is None or len(owned)!=1 or owned[0][0]!=1 or not owned[0][1]:
            raise ValueError('Стартовый отряд создаётся только вместе с новым персонажем')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='hired_candidates'").fetchone() is None:
            db.execute('CREATE TABLE hired_candidates(account TEXT NOT NULL,candidate_id INTEGER NOT NULL,pet_id INTEGER NOT NULL,PRIMARY KEY(account,candidate_id))')
        if db.execute('SELECT 1 FROM hired_candidates WHERE account=?',(account,)).fetchone():
            raise ValueError('Existing hire history cannot receive starters')
        used=[decode_pet_info(owned[0][2],human_equipment=True).fields['0x8c4489']]
        identities=[]
        for identity in range(2,2+policy()['extra_starter_mercenaries']):
            resource=rng.choice(policy()['starter_resources']);name=random_name(resource,rng,used);used.append(name)
            pet=profile(template,identity,resource,name,random_appearance(resource,rng));inventory=encode_item_list(identity,())
            db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(account,identity,1,pet,inventory))
            # Preserve lifetime IDs and permit later dismissal of an empty
            # secondary starter; the main actor retains its existing guard.
            db.execute('INSERT INTO hired_candidates VALUES (?,?,?)',(account,0x20000000+identity,identity))
            identities.append(identity)
        db.execute('INSERT INTO character_roster_creation VALUES (?,?)',(account,json.dumps(identities)))
        db.execute('INSERT INTO character_tutorials(account,step,completed) VALUES (?,0,0)',(account,))
        return tuple(identities)


def tutorial_status(path,account):
    with transaction(path) as db:
        _schema(db)
        row=db.execute('SELECT step,match_id,completed,observed_events FROM character_tutorials WHERE account=?',(account,)).fetchone()
    if row is None:return None
    step,match,completed,events=row
    if not 0<=step<=len(TUTORIAL_EVENTS) or not 0<=events<1<<len(TUTORIAL_EVENTS) or bool(completed)!=(step==len(TUTORIAL_EVENTS)):
        raise ValueError('Invalid tutorial progress')
    return {'step':step,'match_id':match,'completed':bool(completed),
            'observed_events':events,
            'tip':None if completed else TUTORIAL_TIPS[step]}


def tutorial_begin(path,account,match_id):
    if not isinstance(match_id,str) or not 1<=len(match_id)<=64:raise ValueError('Invalid tutorial match identity')
    with transaction(path) as db:
        _schema(db)
        row=db.execute('SELECT match_id,completed FROM character_tutorials WHERE account=?',(account,)).fetchone()
        if row is None or row[1]:raise ValueError('Tutorial is unavailable for this save')
        if row[0] not in (None,match_id):raise ValueError('Tutorial already belongs to another battle')
        db.execute('UPDATE character_tutorials SET match_id=? WHERE account=?',(match_id,account))
    return tutorial_status(path,account)


def tutorial_progress(path,account,match_id,event,*,observed=False):
    if not observed:raise ValueError('Tutorial requires a server-observed battle action')
    if event not in TUTORIAL_EVENTS:raise ValueError('Unknown tutorial action')
    with transaction(path) as db:
        _schema(db)
        row=db.execute('SELECT step,match_id,completed,observed_events FROM character_tutorials WHERE account=?',(account,)).fetchone()
        if row is None or row[1]!=match_id:raise ValueError('Tutorial battle differs from owned mission')
        if not row[2]:
            # An early critical kill must not leave a later kill step waiting
            # for an already dead target. Record server-observed facts in any
            # order while the tips still guide the first unfinished action.
            events=row[3]|(1<<TUTORIAL_EVENTS.index(event))
            step=next((i for i in range(len(TUTORIAL_EVENTS)) if not events&(1<<i)),len(TUTORIAL_EVENTS))
            db.execute('UPDATE character_tutorials SET step=?,completed=?,observed_events=? WHERE account=?',
                       (step,int(step==len(TUTORIAL_EVENTS)),events,account))
    return tutorial_status(path,account)


def tutorial_leave(path,account,match_id):
    """Release a closed training scene, preserving verified facts for resume."""
    with transaction(path) as db:
        _schema(db)
        if db.execute('UPDATE character_tutorials SET match_id=NULL WHERE account=? AND match_id=?',
                      (account,match_id)).rowcount!=1:
            raise ValueError('Tutorial battle differs from owned mission')
    return tutorial_status(path,account)
