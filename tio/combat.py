"""First combat rules on original49/4B packets and inventory30.

No magazines/reload. Base+uniform[0,rnd] damage and circular blast are LOCAL
rules, not recovered server formulas. Projectile scatter uses original spread
radii and the explicit distribution policy in config/combat_rules.json. Native
miss/critical results; saved mines/burns use config/special_items.json.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
from types import MappingProxyType
from functools import lru_cache
from pathlib import Path
import json
import random
import sqlite3
from .protocol.item_list import decode_item_list,encode_item_list
from .protocol.battle_attack import (AttackHit,AttackResult,encode_attack_result,
                                     RESULT_NORMAL,RESULT_MISS,RESULT_CRITICAL)
from .protocol.action_points import encode_action_points
from .visibility import clear_sight,visible_actors,field_sight
from .combat_distance import combat_distance

from .medical_items import medical_items

MEDICAL_ITEMS = medical_items()


@lru_cache(maxsize=1)
def combat_rules():
    value=json.loads((Path(__file__).resolve().parents[1]/'config/combat_rules.json').read_text(encoding='utf-8'))
    if value['enemy_kill_sight_bonus']!=1 or value['scatter_distribution']!='accuracy_then_uniform_disk':
        raise ValueError('Unsupported combat policy')
    if value['scatter_geometry']!='squared_euclidean' or value['scatter_invalid_cells']!='exclude':
        raise ValueError('Unsupported projectile geometry')
    if value['scatter_radii_manual']!={'316':3,'317':2,'340':1}:
        raise ValueError('Invalid manual scatter radii')
    return value


class Combat:
    def __init__(self,field,catalog,*,rng=None):
        self.field,self.catalog=field,catalog
        from .rule_catalogs import armor_catalog
        self.armor=armor_catalog()
        self.rng=rng or random.Random()
        self.inventories={}
        self.enhancement_caps={}
        self.persistence={}
        # Battle IDs may differ from account-local saved pet IDs in shared PvP.
        self.storage_ids={}
        self.human={}
        self.resources={}
        self.statistics={}
        self.rank_profiles={}
        self.rank_kills=[]
        # One enemy death grants one battle-only sight increment. Victim IDs
        # remain in this ledger even if an owner subsequently leaves the field.
        self.sight_kill_victims=set()
        from .level_progression import BattleExperience
        self.experience=BattleExperience()
        self.initial_proficiencies={}
        from .achievements import BattleAchievements
        self.achievements=BattleAchievements()
        self.rental_tax_units={}
        from .rule_catalogs import proficiency_rules
        self.proficiency_rules=proficiency_rules()
        from .rule_catalogs import enhancement_rules
        self.enhancement_rules=enhancement_rules()
        self.proficiencies={}
        self.miner_defense={}
        self.dog_bonuses={}
        self.weapon_accuracy_bonuses={}
        self.human_critical_bonuses={}
        self.weight_capacities={}
        self.temporary_items=set()
        # Towns with no carried equipment use an empty battle copy. Exact
        # personal packets remain separately available to both sides of CAS.
        self.personal_inventories={}
        self.display_unarmored_bonuses={}
        self.repair_selections={}
        self.exchange_sessions={}
        self.premium_wear_remainders={}
        self.learned={}
        self.skill_lists={}
        self.mines={}
        self.hazard_damage={}
        self.burns={}
        self.mine_sequence=1

    def stage_equipment_batch(self,owner,request,turn_key):
        from .equipment_batch import stage
        return stage(self,owner,request,turn_key)

    def commit_equipment_batch(self,owner,request,turn_key,*,view=None):
        from .equipment_batch import commit
        return commit(self,owner,request,turn_key,view=view)

    def cancel_equipment_batch(self,owner,*,batch_id=None,forget_receipts=False):
        from .equipment_batch import cancel
        return cancel(self,owner,batch_id=batch_id,forget_receipts=forget_receipts)

    def stage_kill_sight(self,states,kills):
        """Stage manual p39 sight together with HP/AP; never write city PetInfo."""
        awarded=set(getattr(self,'sight_kill_victims',{victim for _,victim in self.rank_kills}))
        changed=set()
        for killer,victim in kills:
            if victim in awarded:continue
            awarded.add(victim)
            actor=states.get(killer,self.field._actors.get(killer))
            if actor is None:continue
            sight=min(255,actor.sight_radius+combat_rules()['enemy_kill_sight_bonus'])
            if sight!=actor.sight_radius:
                states[killer]=replace(actor,sight_radius=sight)
                changed.add(killer)
        return awarded,frozenset(changed)

    def scatter_impact(self,weapon_id,origin,target,accuracy):
        """Original spread radius; distribution/edge handling are server policy.

        One legacy accuracy roll selects the requested cell. On failure choose
        uniformly among other passable in-map cells in the spread disk. Rockets
        also require their original clear flight ray. Grenade flight remains
        the existing arc policy; blast LOS is checked from the actual endpoint.
        """
        combat_rules()
        spread=int(self.catalog.sources[weapon_id].get('spread',0))
        if not 0<=spread<=255:raise ValueError('Invalid projectile scatter radius')
        if not spread or self.rng.randrange(100)<accuracy:return target
        field=self.field;tx,ty=target
        cells=[(x,y) for y in range(max(0,ty-spread),min(field.height,ty+spread+1))
               for x in range(max(0,tx-spread),min(field.width,tx+spread+1))
               if (x,y)!=target and (x-tx)**2+(y-ty)**2<=spread**2
               and (x,y) not in field.blocked
               and (weapon_id!=316 or field_sight(field,origin,(x,y)))]
        # The requested landing cell was validated before sampling. A one-cell
        # pocket has no admissible deviation and deterministically keeps it.
        return cells[self.rng.randrange(len(cells))] if cells else target

    def hazard_packets(self,owner):
        from .battle_hazards import known_mines
        return (known_mines(self,owner),)

    def deploy_mine(self,owner,request,*,view=None):
        from .battle_hazards import deploy
        return deploy(self,owner,request,view=view)

    def after_move(self,actor_id,path=()):
        from .battle_hazards import after_move
        return after_move(self,actor_id,path)

    def turn_effects(self,owner,actor_ids):
        from .battle_hazards import turn_effects
        from .battle_item_effects import begin_turn
        return (*begin_turn(self,owner,actor_ids),*turn_effects(self,owner,actor_ids))

    @property
    def field(self):return self._field

    @field.setter
    def field(self,field):
        # Scene builders replace provisional fields. Capture new NPC owners at
        # that boundary, retaining earlier ownership for any combat history.
        owners=dict(getattr(self,'actor_owners',{}))
        for identity,actor in field._actors.items():
            if identity in owners and owners[identity]!=actor.owner_id:
                raise ValueError('Battle actor ownership cannot change')
            owners[identity]=actor.owner_id
        self.actor_owners=MappingProxyType(owners)
        self._field=field

    def register(self,actor_id,inventory,*,human,path=None,account=None,pet_packet=None):
        actor=self.field._actors.get(actor_id)
        if actor is None and path is not None:raise ValueError('Persistent actor must belong to the field')
        if actor is not None:
            if actor_id in self.actor_owners and self.actor_owners[actor_id]!=actor.owner_id:
                raise ValueError('Battle actor ownership cannot change')
            if actor_id not in self.actor_owners:
                self.actor_owners=MappingProxyType({**self.actor_owners,actor_id:actor.owner_id})
        owner,items,unknown=decode_item_list(inventory)
        if owner!=actor_id:raise ValueError('Combat inventory actor mismatch')
        if len({i.instance_id for i in items})!=len(items) or any((i.count<1 and not (i.template_id==52 and i.count==0)) or i.equipped not in (0,1) for i in items):
            raise ValueError('Invalid combat inventory')
        self.inventories[actor_id]=inventory
        from .enhancement_limits import pet_cap
        self.enhancement_caps[actor_id]=pet_cap(pet_packet,human) if pet_packet is not None else 3
        from .rental import rental_tax_units
        self.rental_tax_units[actor_id]=rental_tax_units(inventory)
        self.human[actor_id]=human
        from .protocol.pet_info import decode_pet_info
        from .ranks import signed
        rank_fields=decode_pet_info(pet_packet,human_equipment=human).fields if pet_packet is not None else {}
        self.rank_profiles[actor_id]=(rank_fields.get('0x8c4aef',1),signed(rank_fields.get('0x8c4bd0',0)))
        self.resources[actor_id]=decode_pet_info(pet_packet,human_equipment=human).fields['0x8c446f'] if pet_packet is not None else (1 if human else 3)
        if path is not None:self.persistence[actor_id]=(path,account)
        self.weight_capacities.pop(actor_id,None)
        if pet_packet is not None:
            from .equipment_bonuses import training_profile,bonuses
            b=bonuses(inventory,self.resources[actor_id])
            self.proficiencies[actor_id]=self.proficiency_rules.normalize(training_profile(pet_packet,human) if b['melee'] else pet_packet,human)
            self.initial_proficiencies.setdefault(actor_id,self.proficiencies[actor_id])
            # Projected PetInfo includes level growth and learned carry bonuses.
            capacity=decode_pet_info(pet_packet,human_equipment=human).fields['0x8c4b57']
            if capacity>0:self.weight_capacities[actor_id]=capacity-b['carry']
        # Projected PetInfo already accounts for whether armor is worn.
        self.miner_defense[actor_id]=(decode_pet_info(pet_packet,human_equipment=human).fields['0x8c4ac5']
                                     if pet_packet is not None and self.resources[actor_id]==6 else 0)

    def configure_armor_display(self,actor_id,learned,catalog):
        # Keep the naked perk available when armor is removed during battle.
        if self.resources[actor_id]==6:
            self.display_unarmored_bonuses[actor_id]=sum(
                catalog.get(e.ability_id,e.level).number('value')
                for e in learned if e.ability_id==24)

    def exclude_personal_equipment(self,actor_id,catalog,template,*,pet_packet=None):
        """Prepare an empty birth-time copy without changing the saved soldier.

        Persistent actors are reprojected from their actual unmodified saved
        PetInfo. Transient actors require that same base packet from the scene
        factory. The returned native template and learned list replace the
        equipped scene projections; all serialization precedes memory mutation.
        """
        from copy import copy
        from .protocol.pet_info import decode_pet_info
        from .protocol.battle_soldier import decode_battle_soldier,encode_battle_soldier,HUMAN_EQUIPMENT_FIELDS
        from .protocol.abilities import encode_abilities
        from .passive_stats import project_passives
        from .dog_abilities import catalog_for_play
        from .weapon_effects import battle_skills
        from tools.battle_actor_fixture import actor_packet
        actor=self.field.actor(actor_id);human=self.human[actor_id]
        personal=getattr(self,'personal_inventories',{})
        if actor_id in personal or self.field._ability_turns[actor_id]!=0:
            raise ValueError('Personal equipment exclusion is allowed only at scene birth')
        old=self.inventories[actor_id];identity,items,flag=decode_item_list(old)
        if identity!=actor_id or {i.instance_id for i in items}&self.temporary_items:
            raise ValueError('Personal equipment cannot contain temporary supplies')
        stored_id=self.storage_ids.get(actor_id,actor_id)
        if actor_id in self.persistence:
            path,account=self.persistence[actor_id]
            with closing(connect(path)) as db:
                row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                               (account,stored_id)).fetchone()
            if row is None or bool(row[0])!=human or row[2]!=encode_item_list(stored_id,items,flag):
                raise ValueError('Personal equipment changed before scene admission')
            if pet_packet is not None and pet_packet!=bytes(row[1]):
                raise ValueError('Equipment exclusion requires the saved base profile')
            pet_packet=bytes(row[1])
        if pet_packet is None:raise ValueError('Transient actor requires its base profile')
        base=decode_pet_info(pet_packet,human_equipment=human).fields
        if base['0x8c43eb']!=stored_id or base['0x8c446f']!=self.resources[actor_id]:
            raise ValueError('Equipment exclusion profile identity differs')
        if (template.fields['0x8c5088'],template.fields['0x8c50ea'])!=(actor_id,actor.owner_id):
            raise ValueError('Equipment exclusion template identity differs')
        empty=encode_item_list(actor_id,(),flag)
        local_empty=encode_item_list(stored_id,(),flag)
        learned=self.learned.get(actor_id,())
        from .restored_abilities import catalog_with_restored
        catalog=catalog_for_play(catalog_with_restored(catalog))
        profile=project_passives(self.proficiency_rules.normalize(pet_packet,human),human,learned,catalog,
                                 inventory=local_empty)
        # register/configure write dictionaries only; stage them on a shallow
        # projection so a failed native serializer leaves the live copy intact.
        staged=copy(self)
        names=('inventories','enhancement_caps','rental_tax_units','human','rank_profiles','resources',
               'persistence','weight_capacities','proficiencies','initial_proficiencies','miner_defense',
               'learned','human_critical_bonuses','weapon_accuracy_bonuses','display_unarmored_bonuses','skill_lists')
        for name in names:setattr(staged,name,dict(getattr(self,name)))
        staged.initial_proficiencies.pop(actor_id,None)
        staged.register(actor_id,empty,human=human,pet_packet=profile)
        staged.configure_accuracy(actor_id,learned,catalog)
        staged.configure_armor_display(actor_id,learned,catalog)
        entries=battle_skills(learned,empty,human);staged.skill_lists[actor_id]=entries
        fields=decode_pet_info(profile,human_equipment=human).fields
        state=replace(actor,health=fields['0x8c4ab1'],max_health=fields['0x8c4a07'],
            action_points=staged.turn_budget(actor_id,self.field._turn_points[actor_id]),
            sight_radius=8 if self.resources[actor_id]==6 else 9 if human else 12,
            weapons=self.catalog.equipped(empty,human=human,resource=self.resources[actor_id]))
        native=decode_battle_soldier(actor_packet(profile,actor.owner_id,local_empty,human=human,
            actor_id=actor_id,name=template.fields['0x8c5116'],x=actor.x,y=actor.y,
            team=template.fields['0x8c5187'],color=template.fields['0x8c5173']),human_equipment=human)
        equipment=HUMAN_EQUIPMENT_FIELDS.values() if human else ('0x8c543f','0x8c546e','0x8c549d')
        native=replace(native,fields={**native.fields,**{k:0 for k in equipment},
            '0x8c57bb':state.health,'0x8c566a':state.max_health,'0x8c571d':state.action_points,
            '0x8c5694':self.field._turn_points[actor_id],'0x8c567f':state.sight_radius,
            '0x8c5731':staged.displayed_armor(actor_id),'0x8c57e7':0,
            '0x8c57d0':staged.weight_capacity(actor_id) if actor_id in staged.weight_capacities else fields['0x8c4b57']})
        encode_battle_soldier(native);skills=encode_abilities(actor_id,entries)
        for name in names:setattr(self,name,getattr(staged,name))
        self.personal_inventories={**personal,actor_id:old}
        self.field._actors[actor_id]=state
        return native,skills

    def displayed_armor(self,actor_id):
        if actor_id in getattr(self,'npc_defense',{}):return self.npc_defense[actor_id]
        from .armor_display import total
        from .protocol.pet_info import decode_pet_info
        from .miner_abilities import naked
        human=self.human[actor_id];profile=self.proficiencies.get(actor_id)
        base=decode_pet_info(profile,human_equipment=human).fields['0x8c4ac5'] if profile else 0
        if actor_id in self.display_unarmored_bonuses:
            base=self.display_unarmored_bonuses[actor_id] if naked(self.inventories[actor_id]) else 0
        from .battle_item_effects import armor_bonus
        return total(base,self.inventories[actor_id],human,self.enhancement_caps[actor_id])+armor_bonus(self,actor_id)

    def defense(self,actor_id):
        if actor_id in getattr(self,'npc_defense',{}):return self.npc_defense[actor_id]
        inventory=self.inventory_packet(actor_id) if actor_id in self.inventories else None
        from .miner_abilities import naked
        from .battle_item_effects import armor_bonus
        return (self.armor.defense(inventory,human=self.human.get(actor_id,True))
                + (self.miner_defense.get(actor_id,0) if naked(inventory) else 0)
                + self.dog_bonuses.get(actor_id,{}).get(15,0)+armor_bonus(self,actor_id))

    def configure_accuracy(self,actor_id,learned,catalog):
        self.learned[actor_id]=tuple(learned)
        self.human_critical_bonuses[actor_id]=sum(catalog.get(e.ability_id,e.level).number('value')
            for e in learned if e.ability_id==4) if self.resources[actor_id] in (1,2) else 0
        # Native TSActor.GetAccuracyBonus a83c38: perk10 for melee,
        # perk17 for light weapons. Dog perk18 is configured separately.
        self.weapon_accuracy_bonuses[actor_id]={
            {10:'Melee',17:'Light'}[e.ability_id]:catalog.get(e.ability_id,e.level).number('value')
            for e in learned if e.ability_id in (10,17)
        } if self.human[actor_id] else {}

    def cast_slash(self,owner,request,*,view=None):
        if request.ability_id!=22 or request.unknown_u32!=0:raise ValueError('Unsupported slash request')
        from .protocol.battle_attack import AttackRequest
        return self.attack(owner,AttackRequest(request.actor_id,request.x,request.y),view=view,_slash=True)

    def cast_deathbite(self,owner,request,*,view=None):
        if request.ability_id!=26 or request.unknown_u32!=0:raise ValueError('Invalid deathbite request')
        from .protocol.battle_attack import AttackRequest
        return self.attack(owner,AttackRequest(request.actor_id,request.x,request.y),view=view,_deathbite=True)

    def cast_subgrenade(self,owner,request,*,view=None):
        if request.ability_id!=27 or request.unknown_u32!=0:raise ValueError('Invalid subgrenade request')
        from .protocol.battle_attack import AttackRequest
        return self.attack(owner,AttackRequest(request.actor_id,request.x,request.y),view=view,_subgrenade=True)

    def skill_packets(self,actor_id):
        from .weapon_effects import battle_skills
        from .protocol.abilities import encode_abilities
        entries=battle_skills(self.learned.get(actor_id,()),self.inventories[actor_id],self.human[actor_id])
        previous=self.skill_lists.get(actor_id,())
        self.skill_lists[actor_id]=entries
        if entries==previous or not any(e.ability_id in (9,27) for e in (*entries,*previous)):return ()
        return (encode_abilities(actor_id,entries),)

    def inventory_packet(self, actor_id, packet=None):
        from .enhancement_limits import project_inventory
        return project_inventory(self.inventories[actor_id] if packet is None else packet,
                                 self.enhancement_caps[actor_id])

    def turn_budget(self, actor_id, maximum):
        from .weight import inventory_weight, turn_ap
        if actor_id not in self.weight_capacities:return maximum
        return turn_ap(maximum,inventory_weight(self.inventories[actor_id]),self.weight_capacity(actor_id))

    def weight_capacity(self, actor_id: int, inventory: bytes | None = None) -> int:
        from .equipment_bonuses import bonuses
        packet = self.inventories[actor_id] if inventory is None else inventory
        return self.weight_capacities[actor_id]+bonuses(packet,self.resources[actor_id])['carry']

    def weight_packet(self, actor_id, packet=None):
        from .weight import inventory_weight, encode_weight
        if actor_id not in self.weight_capacities:return None
        inventory=self.inventories[actor_id] if packet is None else packet
        capacity=self.weight_capacity(actor_id, inventory)
        return encode_weight(actor_id,min(0xffffffff,inventory_weight(inventory)),capacity)

    def equip(self,owner,action,*,view=None):
        if action.pet_id not in self.inventories or action.pet_id not in self.field._actors:
            raise ValueError('Unknown combat actor')
        a=self.field.actor(action.pet_id)
        if a.owner_id!=owner or not a.health:
            raise ValueError('Invalid equipment actor')
        old=self.inventories[a.actor_id]
        _,items,unknown=decode_item_list(old)
        selected=next((i for i in items if i.instance_id==action.instance_id),None)
        from .durability import broken
        if selected is not None and broken(selected) and not selected.equipped:
            raise ValueError('Сломанный предмет нельзя экипировать')
        from .equipment import armor_rules
        armor=armor_rules()
        if selected is not None and selected.template_id in armor:
            return self._equip_armor(a,action,old,items,unknown,selected,armor,view)
        if not self.human.get(a.actor_id):raise ValueError('Dog cannot equip human weapons')
        if action.target_mask not in (None,16,128):raise ValueError('Unsupported equipment target')
        if selected is None or selected.count!=1 or selected.template_id not in self.catalog.weapons:
            raise ValueError('Owned individual weapon required')
        if selected.template_id in (300,333,337) or (self.catalog.sources[selected.template_id].get('freaks_only')=='1') != (self.resources[a.actor_id]==6):
            raise ValueError('Unsupported equipment weapon')
        equip=not (action.option==255 and selected.equipped)
        if equip:
            if (action.target_mask or 16)==16 and any(i.equipped and i.template_id==334 and i.client_slot==4 for i in items):
                raise ValueError('Для жилета смертника нужно освободить основную руку')
            from .enhancement_limits import required_level
            from .protocol.pet_info import decode_pet_info
            profile=self.proficiencies.get(a.actor_id)
            level=decode_pet_info(profile,human_equipment=True).fields['0x8c4aef'] if profile is not None else 1
            if level<required_level(selected):raise ValueError('Weapon requires level '+str(required_level(selected)))
        slot=action.target_mask or 16
        updated=[]
        for i in items:
            if i.instance_id==selected.instance_id:
                i=replace(i,unknown_u8_01=int(equip),location_raw=slot if equip else 0)
            elif equip and i.equipped and i.client_slot==slot:
                i=replace(i,unknown_u8_01=0,location_raw=0)
            updated.append(i)
        inventory=encode_item_list(a.actor_id,updated,unknown)
        state=replace(a,weapons=self.catalog.equipped(inventory,human=True,resource=self.resources[a.actor_id]))
        self._persist_inventory(a.actor_id,old,inventory)
        self.inventories[a.actor_id]=inventory
        from .rental import rental_tax_units
        self.rental_tax_units[a.actor_id]=max(self.rental_tax_units.get(a.actor_id,0),rental_tax_units(inventory))
        self.field._actors[a.actor_id]=state
        if view is not None:
            t=view.templates[a.actor_id]
            fields=dict(t.fields)
            for mask,key in ((16,'0x8c52cf'),(128,'0x8c52f5')):
                fields[key]=next((i.template_id for i in updated if i.equipped and i.client_slot==mask),0)
            view.templates[a.actor_id]=replace(t,fields=fields)
        return self.inventory_packet(a.actor_id)

    def _equip_armor(self,a,action,old,items,unknown,selected,armor,view):
        rule=armor[selected.template_id];slot=rule['slot']
        equip=not (action.option==255 and selected.equipped)
        if selected.count!=1 or action.target_mask not in (None,slot):raise ValueError('Invalid armor placement')
        if a.action_points<2:raise ValueError('Insufficient action points to equip armor')
        if equip:
            resource=self.resources[a.actor_id]
            if selected.template_id==334 and any(i.equipped and i.client_slot==16 for i in items):
                raise ValueError('Для жилета смертника нужно освободить основную руку')
            allowed=resource==6 if rule.get('miner') else resource in (3,4,5) if rule['dog'] else resource in (1,2)
            if not allowed or (rule.get('female') and resource!=2):raise ValueError('Incompatible armor')
            from .protocol.pet_info import decode_pet_info
            from .enhancement_limits import required_level
            profile=self.proficiencies.get(a.actor_id)
            level=decode_pet_info(profile,human_equipment=self.human[a.actor_id]).fields['0x8c4aef'] if profile else 1
            if level<max(rule['level'],required_level(selected)):raise ValueError('Armor requires a higher level')
        updated=[]
        for i in items:
            if i.instance_id==selected.instance_id:i=replace(i,unknown_u8_01=int(equip),location_raw=slot if equip else 0)
            elif equip and i.equipped and set(rule.get('covers',(slot,))) & set(armor.get(i.template_id,{}).get('covers',(i.client_slot,))):
                i=replace(i,unknown_u8_01=0,location_raw=0)
            updated.append(i)
        inventory=encode_item_list(a.actor_id,updated,unknown)
        self._persist_inventory(a.actor_id,old,inventory)
        self.inventories[a.actor_id]=inventory
        from .equipment_bonuses import bonuses
        sight_delta=bonuses(inventory,self.resources[a.actor_id])['sight']-bonuses(old,self.resources[a.actor_id])['sight']
        self.field._actors[a.actor_id]=replace(a,action_points=a.action_points-2,sight_radius=a.sight_radius+sight_delta)
        if view is not None:
            template=view.templates[a.actor_id];fields=dict(template.fields)
            for mask,key in ((1,'0x8c525b'),(4,'0x8c531b'),(8,'0x8c5341')) if self.human[a.actor_id] else ((4,'0x8c546e'),):
                fields[key]=next((i.template_id for i in updated if i.equipped and i.client_slot==mask),0)
            view.templates[a.actor_id]=replace(template,fields=fields)
        return self.inventory_packet(a.actor_id)

    def use_medical(self,owner,action):
        from .protocol.health import encode_health
        if action.pet_id not in self.inventories:raise ValueError('Unknown combat actor')
        a=self.field.actor(action.pet_id)
        if a.owner_id!=owner or not a.health:raise ValueError('Invalid treatment actor')
        old=self.inventories[a.actor_id]
        _,items,unknown=decode_item_list(old)
        item=next((i for i in items if i.instance_id==action.instance_id),None)
        if item is None or item.template_id not in MEDICAL_ITEMS or action.option!=255:
            raise ValueError('Unsupported medical item action')
        if item.template_id==32 and self.resources[a.actor_id] not in (3,4,5):
            raise ValueError('Dog meat requires a dog')
        power,cost=MEDICAL_ITEMS[item.template_id]
        if a.health>=a.max_health:raise ValueError('Health is already full')
        if a.action_points<cost:raise ValueError('Insufficient action points')
        updated=tuple(replace(i,unknown_u32_01=i.count-1) if i==item else i
                      for i in items if i!=item or i.count>1)
        inventory=encode_item_list(a.actor_id,updated,unknown)
        from .ranked_loadout import extra
        remainders=dict(getattr(self,'ranked_remainders',{}))
        power+=extra(self,a.actor_id,0,power,remainders)
        state=replace(a,health=min(a.max_health,a.health+power),action_points=a.action_points-cost)
        replies=(encode_health(a.actor_id,state.health),encode_action_points(a.actor_id,state.action_points),self.inventory_packet(a.actor_id,inventory))
        self._persist_inventory(a.actor_id,old,inventory)
        if hasattr(self,'ranked_remainders'):self.ranked_remainders=remainders
        self.inventories[a.actor_id]=inventory
        self.field._actors[a.actor_id]=state
        return replies

    def swap_weapons(self,owner,actor_id,*,view=None):
        if actor_id not in self.inventories:raise ValueError('Unknown combat actor')
        a=self.field.actor(actor_id)
        if a.owner_id!=owner or not a.health or not self.human[actor_id]:
            raise ValueError('Invalid weapon swap actor')
        if a.action_points<1:raise ValueError('Insufficient action points')
        old=self.inventories[actor_id]
        _,items,unknown=decode_item_list(old)
        for slot in (16,128):
            if sum(i.equipped and i.client_slot==slot for i in items)>1:
                raise ValueError('Ambiguous weapon slot')
        if not any(i.equipped and i.client_slot in (16,128) for i in items):
            raise ValueError('No weapon to swap')
        updated=tuple(replace(i,location_raw=128 if i.client_slot==16 else 16)
                      if i.equipped and i.client_slot in (16,128) else i for i in items)
        inventory=encode_item_list(actor_id,updated,unknown)
        state=replace(a,action_points=a.action_points-1,weapons=self.catalog.equipped(inventory,human=True,resource=self.resources[a.actor_id]))
        replies=(self.inventory_packet(actor_id,inventory),encode_action_points(actor_id,state.action_points))
        self._persist_inventory(actor_id,old,inventory)
        self.inventories[actor_id]=inventory
        self.field._actors[actor_id]=state
        if view is not None:
            t=view.templates[actor_id]
            fields=dict(t.fields)
            for slot,key in ((16,'0x8c52cf'),(128,'0x8c52f5')):
                fields[key]=next((i.template_id for i in updated if i.equipped and i.client_slot==slot),0)
            view.templates[actor_id]=replace(t,fields=fields)
        return replies

    def persistent_inventory(self,packet,temporary_ids=None):
        owner,items,flag=decode_item_list(packet)
        temporary=self.temporary_items if temporary_ids is None else temporary_ids
        personal=getattr(self,'personal_inventories',{})
        if owner in personal:
            _,original,_=decode_item_list(personal[owner])
            if any(i.instance_id in temporary for i in original):
                raise ValueError('Personal equipment cannot be classified as temporary')
            if any(i.instance_id not in temporary for i in items):
                raise ValueError('Restricted battle inventory contains a persistent item')
            return personal[owner]
        return encode_item_list(owner,tuple(i for i in items if i.instance_id not in temporary),flag)

    def _persist_inventory(self,actor_id,old,inventory,trained=None,*,temporary_ids=None,_db=None):
        if actor_id in self.persistence:
            if _db is None:
                path,_=self.persistence[actor_id]
                with closing(connect(path)) as db,db:
                    db.execute('BEGIN IMMEDIATE')
                    self._persist_inventory(actor_id,old,inventory,trained,temporary_ids=temporary_ids,_db=db)
                return
            old=self.persistent_inventory(old)
            inventory=self.persistent_inventory(inventory,temporary_ids)
            stored_id=self.storage_ids.get(actor_id,actor_id)
            if stored_id!=actor_id:
                _,old_items,old_flag=decode_item_list(old)
                _,new_items,new_flag=decode_item_list(inventory)
                old=encode_item_list(stored_id,old_items,old_flag)
                inventory=encode_item_list(stored_id,new_items,new_flag)
            path,account=self.persistence[actor_id]
            db=_db
            changed=db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=? AND inventory_packet=?',
                (inventory,account,stored_id,old)).rowcount
            if changed!=1:raise ValueError('Combat inventory changed outside battle')
            # Reserve IDs of persistent supplies split during a transfer.
            if temporary_ids is not None:
                db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')
                next_id=max((i.instance_id for i in decode_item_list(inventory)[1]),default=0)+1
                db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',(account,next_id))
            if trained is not None:
                from .weapon_proficiency import SAVED,BASE,CAPS,skill_signature
                from .protocol.pet_info import decode_pet_info,encode_pet_info
                human=self.human[actor_id]
                row=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,stored_id)).fetchone()
                current=self.proficiency_rules.normalize(row[0],human)
                if skill_signature(current,human)!=skill_signature(self.proficiencies[actor_id],human):
                    raise ValueError('Combat proficiency changed outside battle')
                pet=decode_pet_info(row[0],human_equipment=human)
                new=decode_pet_info(trained,human_equipment=human).fields
                merged=encode_pet_info(replace(pet,fields={**pet.fields,**{k:new[k] for k in (*SAVED,*BASE,*CAPS)}}))
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(merged,account,stored_id))

    def _persist_batch(self,changes,*,trained=None,repair_audit=None,temporary_ids=None,expected_profiles=None):
        paths={str(self.persistence[i][0]) for i in changes if i in self.persistence}
        if len(paths)>1:raise ValueError('Battle accounts must share one database')
        if not paths:return
        with closing(connect(next(iter(paths)))) as db,db:
            db.execute('BEGIN IMMEDIATE')
            for identity,packet in changes.items():
                if expected_profiles is not None and identity in self.persistence:
                    from .protocol.pet_info import decode_pet_info
                    from .weapon_proficiency import skill_signature
                    _,account=self.persistence[identity]
                    stored_id=self.storage_ids.get(identity,identity)
                    row=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',
                                   (account,stored_id)).fetchone()
                    human=self.human[identity];expected=expected_profiles[identity]
                    if row is None or bool(row[0])!=human:
                        raise ValueError('Combat equipment profile changed outside battle')
                    current=self.proficiency_rules.normalize(row[1],human)
                    if (skill_signature(current,human)!=skill_signature(expected,human)
                        or decode_pet_info(current,human_equipment=human).fields['0x8c446f']
                           !=decode_pet_info(expected,human_equipment=human).fields['0x8c446f']):
                        raise ValueError('Combat equipment profile changed outside battle')
                self._persist_inventory(identity,self.inventories[identity],packet,
                    (trained or {}).get(identity),temporary_ids=temporary_ids,_db=db)
            if repair_audit is not None:
                identity,audit=repair_audit
                if identity in self.persistence:
                    from .repair import record
                    record(db,self.persistence[identity][1],self.storage_ids.get(identity,identity),audit)

    def repair(self,owner,packet):
        from .protocol.repair import decode_repair,repair_message
        from .durability import repair_inventory
        identity,target=decode_repair(packet)
        actor=self.field.actor(identity)
        if actor.owner_id!=owner or not actor.health:raise ValueError('Living owned repair actor required')
        selection=self.repair_selections.get(owner)
        if packet[0]==0x7e and (selection is None or selection[0]!=identity):
            raise ValueError('Сначала выберите ремкомплект')
        loot=getattr(self.field,'loot',None);allocated=[]
        def allocate():
            # Match-wide allocator; committed only after persistence succeeds.
            if loot is None or loot.next_id>0xffffffff:raise ValueError('Item identity space exhausted')
            allocated.append(loot.next_id);return loot.next_id
        inventory,audit=repair_inventory(self.inventories[identity],target,
            selection[1] if packet[0]==0x7e else None,allocate=allocate)
        if actor.action_points<1:raise ValueError('Insufficient action points')
        from .protocol.action_points import encode_action_points
        replies=(self.inventory_packet(identity,inventory),encode_action_points(identity,actor.action_points-1),repair_message(112))
        self._persist_batch({identity:inventory},repair_audit=(identity,audit),
                            temporary_ids=self.temporary_items if allocated else None)
        self.inventories[identity]=inventory
        if allocated:loot.next_id=allocated[-1]+1
        self.field._actors[identity]=replace(actor,action_points=actor.action_points-1)
        self.repair_selections.pop(owner,None)
        return replies

    def attack(self,owner,request,*,view=None,_slash=False,_deathbite=False,_subgrenade=False):
        from . import battle_item_effects as effects
        effects.initialize(self)
        if not any((_slash,_deathbite,_subgrenade)):
            if request.actor_id in self.item_effects['recon_selection']:
                replies=effects.recon_target(self,owner,request)
                return replies+(() if view is None else view.refresh())
            replies=effects.attack(self,owner,request,view=view)
            if replies is not None:return replies
        random_state=self.rng.getstate() if hasattr(self.rng,'getstate') else None
        try:
            return effects._atomic(self,lambda:self._attack(owner,request,view=view,_slash=_slash,_deathbite=_deathbite,_subgrenade=_subgrenade),views=(view,))
        except BaseException:
            if random_state is not None:self.rng.setstate(random_state)
            raise

    def _attack(self,owner,request,*,view=None,_slash=False,_deathbite=False,_subgrenade=False):
        f=self.field
        if request.actor_id not in f._actors or request.actor_id not in self.inventories:
            raise ValueError('Unknown combat actor')
        a=f.actor(request.actor_id)
        if a.owner_id!=owner or a.health is None or a.health<=0:raise ValueError('Invalid attacker')
        if not f.inside(request.x,request.y):raise ValueError('Target outside map')
        old=self.inventories[a.actor_id]
        _,items,unknown=decode_item_list(old)
        equipped=[i for i in items if i.equipped==1 and i.client_slot==16] if self.human[a.actor_id] else []
        if len(equipped)>1:raise ValueError('Ambiguous primary weapon')
        item=equipped[0] if equipped else None
        from .durability import broken,wear_inventory
        if item is not None and broken(item):raise ValueError('Сломанное оружие нельзя использовать')
        if item is not None and item.template_id==324 and item.unknown_words[0]<9:
            raise ValueError('Недостаточно топлива огнемёта')
        weapon_id=item.template_id if item else (337 if self.resources[a.actor_id]==6 else 300 if self.human[a.actor_id] else self.catalog.npc_defaults.get(self.resources[a.actor_id],333))
        if weapon_id in (321,325) and item is not None and not any((_slash,_deathbite,_subgrenade)):
            from .protocol.battle_mines import MineDeploy
            return self.deploy_mine(owner,MineDeploy(a.actor_id,item.instance_id,request.x,request.y),view=view)
        if weapon_id==340:raise ValueError('Subgrenade ammunition is used through Groza ability27')
        if _subgrenade:
            if weapon_id!=339:raise ValueError('Subgrenade requires equipped Groza')
            weapon_id=340
        w=self.catalog.weapons.get(weapon_id)
        if w is None:raise ValueError('Unsupported primary weapon')
        slash_rule=None
        if _slash:
            from .miner_abilities import rules
            slash_rule=f._slash_rules.get((a.actor_id,22))
            if self.resources[a.actor_id]!=6 or slash_rule is None:raise ValueError('Learned miner slash required')
            if weapon_id!=rules()['hammer_id']:raise ValueError('Slash requires the equipped hammer')
            if f._ability_turns[a.actor_id]<f._cooldowns.get((a.actor_id,22),0):raise ValueError('Ability is cooling down')
        bite_rule=None
        if _deathbite:
            bite_rule=f._dog_rules.get((a.actor_id,26))
            if self.resources[a.actor_id] not in (3,4,5) or bite_rule is None:raise ValueError('Learned dog deathbite required')
            if f._ability_turns[a.actor_id]<f._cooldowns.get((a.actor_id,26),0):raise ValueError('Ability is cooling down')
        active_rule=slash_rule or bite_rule
        active_id=22 if slash_rule else 26 if bite_rule else 27 if _subgrenade else 0
        ap_cost=active_rule[1] if active_rule else w.attack_ap
        from .weapon_effects import THROWN,BLAST,DIRECT_TYPES
        grenade=weapon_id in BLAST
        thrown=weapon_id in THROWN
        source=self.catalog.sources[weapon_id]
        if not grenade and source.get('weaponAttack') not in DIRECT_TYPES:
            raise ValueError('Weapon effect is not implemented')
        if a.action_points<ap_cost:raise ValueError('Insufficient action points')
        distance=combat_distance((a.x,a.y),(request.x,request.y))
        # CFG minRange is the reference distance for damage/accuracy, not a
        # forbidden close-range zone. The original client sends49 below it.
        if not 1<=distance<=w.max_range:raise ValueError('Target outside weapon range')
        if _subgrenade and distance<4:raise ValueError('Subgrenade minimum range is four cells')
        known=visible_actors(f,owner)
        impact=(request.x,request.y)
        victims=[v for v in f._actors.values() if v.health is not None and v.health>0
                 and (v.x,v.y)==(request.x,request.y)]
        if weapon_id==324:
            from .flamethrower import victims as flame_victims
            victims=flame_victims(f,a,(request.x,request.y))
        elif source.get('weaponAttack')=='Minigun':
            # Manual p39/p61: choose a direction on empty ground; everyone
            # in the burst can be hit, including unseen actors and allies.
            # Each ray respects static obstacles/doors and dynamic smoke.
            from .combat_rolls import area_victims
            from .battle_item_effects import clear_item_sight
            victims=[v for v in area_victims(f,a,(request.x,request.y),w.max_range,
                                           int(source.get('radius',1)))
                     if clear_item_sight(self,(a.x,a.y),(v.x,v.y))]
        elif not grenade:
            if len(victims)!=1 or f.allied(victims[0].owner_id,owner) or victims[0].actor_id not in known:
                raise ValueError('Visible enemy required')
            if not field_sight(f,(a.x,a.y),(request.x,request.y)):raise ValueError('Shot is blocked')
            from .battle_item_effects import clear_item_sight
            if not clear_item_sight(self,(a.x,a.y),(request.x,request.y)):raise ValueError('Дым закрывает линию выстрела')
        else:
            if (request.x,request.y) in f.blocked:raise ValueError('Grenade landing cell blocked')
            if weapon_id==316 and not field_sight(f,(a.x,a.y),(request.x,request.y)):
                raise ValueError('Rocket path is blocked')
            # Ability27 SplashRange2 overrides item340's legacy radius3.
            radius=2 if _subgrenade else int(source['radius'])
        if slash_rule:
            # Manual p66: all surrounding actors, including allies. Rounded
            # melee distance1 includes the eight adjacent cells, never self.
            victims=[v for v in f._actors.values() if v.actor_id!=a.actor_id and v.health is not None and v.health>0
                     and combat_distance((a.x,a.y),(v.x,v.y))==1
                     and clear_sight((a.x,a.y),(v.x,v.y),f.blocked)]
        practice=getattr(f,'practice',None)
        consume_id=weapon_id if thrown or _subgrenade else w.ammo_id
        if weapon_id==323:
            from .battle_hazards import rules
            consume_id=rules()['grenade_launcher_ammo']
        count=1 if thrown or _subgrenade else w.bullets_count
        if not thrown and weapon_id!=324 and source.get('weaponAttack') in ('Bullet','Minigun','Rocket') and consume_id is None:
            raise ValueError('Ammo rule missing')
        remaining=count if consume_id is not None else 0
        candidates=[i for i in items if i.template_id==consume_id and (not thrown or i.instance_id==item.instance_id)]
        if sum(i.count for i in candidates)<remaining:raise ValueError('Insufficient ammunition')
        if grenade:
            accuracy_bonus=self.weapon_accuracy_bonuses.get(a.actor_id,{}).get(w.weapon_type,0)
            impact=self.scatter_impact(weapon_id,(a.x,a.y),impact,self.catalog.accuracy(weapon_id,distance,accuracy_bonus))
            victims=[v for v in f._actors.values() if v.health is not None and v.health>0
                     and (v.x-impact[0])**2+(v.y-impact[1])**2<=radius**2
                     and clear_sight(impact,(v.x,v.y),f.blocked)]
        if practice is not None:practice.validate_attack(victims)
        updated=[]
        for i in items:
            take=min(i.count,remaining) if i in candidates else 0
            remaining-=take
            # The mine drill's count is its crystal payload, so zero is a
            # valid, still-owned tool. Attacking must not discard that tool.
            if i.count>take or (i.template_id==52 and i.count==0):
                updated.append(replace(i,unknown_u32_01=i.count-take))
        inventory=encode_item_list(a.actor_id,tuple(updated),unknown)
        states={a.actor_id:replace(a,action_points=a.action_points-ap_cost,
                                  weapons=self.catalog.equipped(inventory,human=self.human[a.actor_id],resource=self.resources[a.actor_id]))}
        hits=[]
        attack_flags=RESULT_NORMAL
        visible_landed=False
        landed=False
        profile=self.proficiencies.get(a.actor_id)
        skill=None if profile is None else self.proficiency_rules.value(profile,self.human[a.actor_id],w.weapon_type)
        if skill is not None and w.weapon_type=='Melee':
            from .equipment_bonuses import bonuses
            skill=min(200,skill+bonuses(inventory,self.resources[a.actor_id])['melee'])
        if skill is not None:skill=min(skill,getattr(self,'ranked_limits',{}).get(a.actor_id,200))
        from .ranked_loadout import extra
        ranked_remainders=dict(getattr(self,'ranked_remainders',{}))
        statistics={owner:dict(values) for owner,values in self.statistics.items()}
        rank_kills=[]
        achievement_outcomes=[]
        experience_damage=[]
        worn_damage={}
        seen_before=visible_actors(f,owner)
        def counters(owner):
            return statistics.setdefault(owner,dict(kills=0,losses=0,damage_dealt=0,damage_received=0))
        for victim in victims:
            distance=combat_distance((a.x,a.y),(victim.x,victim.y))
            dog=self.dog_bonuses.get(a.actor_id,{}) if weapon_id==333 else {}
            # Manual p104 caps final weapon accuracy at95%, including bonuses.
            # Proficiency scales damage/training, not accuracy (manual p106).
            accuracy_bonus=dog.get(18,0)+self.weapon_accuracy_bonuses.get(a.actor_id,{}).get(w.weapon_type,0)
            accuracy=self.catalog.accuracy(weapon_id,distance,accuracy_bonus)
            from .armor import mitigate
            from .weapon_proficiency import damage_endpoint
            effective=min(item.unknown_bytes_03[0],self.enhancement_caps[a.actor_id]) if item is not None else 0
            bonus=self.enhancement_rules.bonus(effective) if not _subgrenade and item is not None and item.template_id in self.enhancement_rules.items else 0
            low=w.damage_base+bonus
            high=w.damage_base+w.damage_random+bonus
            if not grenade:
                low,high=self.catalog.distance_damage(weapon_id,distance,bonus)
            if skill is not None:
                low,high=damage_endpoint(low,skill),damage_endpoint(high,skill)
            chance=(int(source.get('critical',0))+self.human_critical_bonuses.get(a.actor_id,0)
                    if self.resources[a.actor_id] in (1,2,6) else
                    int(source.get('critical',0))+dog.get(4,0) if a.actor_id in self.dog_bonuses else 0)
            if grenade:
                raw=low+self.rng.randint(0,high-low);hit=True;critical=False
            else:
                from .combat_rolls import burst
                raw,hit,critical=burst(self.rng,low,high,accuracy,max(1,w.bullets_count),min(100,chance))
            landed=landed or hit
            if slash_rule:raw=raw*slash_rule[0]//100
            if bite_rule:raw=bite_rule[0]*(2 if critical else 1) if hit else 0
            defense=self.defense(victim.actor_id)
            reduced,absorbed=mitigate(raw,defense)
            bonus_damage=extra(self,a.actor_id,1,reduced,ranked_remainders)
            bonus_absorbed=extra(self,victim.actor_id,2,reduced,ranked_remainders)
            reduced=max(0,reduced-bonus_absorbed)+bonus_damage
            absorbed+=bonus_absorbed
            if victim.actor_id in self.inventories:worn_damage[victim.actor_id]=reduced
            damage=min(victim.health,reduced)
            experience_damage.append((victim,damage))
            updated_actor=states.get(victim.actor_id,victim)
            states[victim.actor_id]=replace(updated_actor,health=victim.health-damage)
            counters(victim.owner_id)['damage_received']+=damage
            if not f.allied(victim.owner_id,owner):
                counters(owner)['damage_dealt']+=damage
                if damage==victim.health:
                    counters(owner)['kills']+=1
                    rank_kills.append((a.actor_id,victim.actor_id))
            if damage==victim.health:counters(victim.owner_id)['losses']+=1
            outcome=RESULT_MISS if not hit else RESULT_CRITICAL if critical else RESULT_NORMAL
            if not f.allied(victim.owner_id,owner):
                achievement_outcomes.append((victim,hit,critical,damage==victim.health,victim.actor_id in seen_before))
            # Ordinary attacks read the global result; a skill can miss one
            # recipient and hit another, so it reads the per-recipient result.
            if not active_id and not grenade and (view is None or victim.actor_id in view.visible):
                visible_landed=visible_landed or hit
                attack_flags=RESULT_CRITICAL if attack_flags==RESULT_CRITICAL or critical else RESULT_NORMAL if visible_landed else RESULT_MISS
            if view is None or victim.actor_id in view.visible:
                additional=min(damage,bonus_damage)
                hits.append(AttackHit(victim.actor_id,damage-additional,victim.health-damage,flags=outcome,additional_damage=additional,absorbed_damage=absorbed))
        from .premium import current as premium_current
        premium_kinds={i:premium_current(*self.persistence[i])[0] if i in self.persistence else 0 for i in {a.actor_id,*worn_damage}}
        wear_remainders=dict(self.premium_wear_remainders)
        changes={a.actor_id:wear_inventory(inventory,weapon=None if item is None or thrown else item.instance_id,weapon_ap=ap_cost,
            half_wear=premium_kinds[a.actor_id]==3,remainders=wear_remainders)}
        for identity,damage in worn_damage.items():
            if damage:
                worn=wear_inventory(changes.get(identity,self.inventories[identity]),armor_damage=damage,
                    half_wear=premium_kinds[identity]==3,remainders=wear_remainders)
                if worn!=self.inventories[identity] or identity==a.actor_id:changes[identity]=worn
        loot=getattr(f,'loot',None)
        death_loot=loot.stage_deaths(states,changes) if loot is not None else None
        inventory=changes[a.actor_id]
        updated=decode_item_list(inventory)[1]
        for identity,packet in changes.items():
            from .equipment_bonuses import bonuses
            sight_delta=bonuses(packet,self.resources[identity])['sight']-bonuses(self.inventories[identity],self.resources[identity])['sight']
            states[identity]=replace(states.get(identity,f.actor(identity)),weapons=self.catalog.equipped(packet,
                human=self.human[identity],resource=self.resources[identity]),sight_radius=f.actor(identity).sight_radius+sight_delta)
        sight_awards,sight_changed=self.stage_kill_sight(states,rank_kills)
        result=AttackResult(a.actor_id,(a.x,a.y),(request.x,request.y),weapon_id,tuple(hits),skill_id=active_id,flags=attack_flags,impact=impact)
        replies=[encode_attack_result(result),encode_action_points(a.actor_id,states[a.actor_id].action_points),self.inventory_packet(a.actor_id,inventory)]
        replies.extend(self.inventory_packet(i,p) for i,p in changes.items() if i!=a.actor_id and p!=self.inventories[i])
        if active_rule:
            from .protocol.ability_status import AbilityStatus,encode_ability_status
            replies.append(encode_ability_status(a.actor_id,[AbilityStatus(active_id,active_rule[3],3,active_rule[2])]))
        trained=None if profile is None or getattr(self,'wager',False) else self.proficiency_rules.train(profile,self.human[a.actor_id],w.weapon_type,ap_cost,landed,
            multiplier=1.5 if premium_kinds[a.actor_id]==1 else 1)
        skill_template=skill_packet=None
        if view is not None and trained is not None:
            from .weapon_proficiency import battle_fields
            from .protocol.battle_soldier import encode_battle_soldier
            t=view.templates[a.actor_id]
            from .equipment_bonuses import project
            fields={**t.fields,**battle_fields(project(trained,self.human[a.actor_id],inventory),self.human[a.actor_id])}
            if a.actor_id in getattr(self,'ranked_limits',{}):
                from .ranked_loadout import limit_display
                fields=limit_display(fields,self.ranked_limits[a.actor_id])
            if a.actor_id in self.weight_capacities:
                from .weight import inventory_weight
                fields.update({'0x8c57e7':min(65535,inventory_weight(inventory)),
                               '0x8c57d0':self.weight_capacity(a.actor_id)})
            if not any(i.equipped and i.client_slot==16 for i in updated):
                fields['0x8c52cf' if self.human[a.actor_id] else '0x8c543f']=0
            skill_template=replace(t,fields=fields)
            state=states[a.actor_id]
            skill_packet=encode_battle_soldier(replace(skill_template,fields={**fields,
                '0x8c519b':state.x,'0x8c51af':state.y,'0x8c57bb':state.health,
                '0x8c566a':state.max_health,'0x8c571d':state.action_points,
                '0x8c5694':f._turn_points[a.actor_id],'0x8c567f':state.sight_radius}))
        # Serialization precedes persistence and memory mutation. CAS rejects
        # concurrent city edits instead of overwriting the player's inventory.
        old_armor={i:self.displayed_armor(i) for i in changes}
        self._persist_batch(changes,trained={a.actor_id:trained})
        if hasattr(self,'ranked_remainders'):self.ranked_remainders=ranked_remainders
        self.premium_wear_remainders=wear_remainders
        if trained is not None:self.proficiencies[a.actor_id]=trained
        self.inventories.update(changes)
        f._actors.update(states)
        self.sight_kill_victims=sight_awards
        if death_loot is not None:
            loot.boxes.update(death_loot[0]);loot.ground.update(death_loot[1])
        self.statistics=statistics
        if weapon_id==319:
            from .battle_hazards import add_fire
            add_fire(self,a,impact,radius)
        if weapon_id==324:
            from .battle_hazards import add_burns
            add_burns(self,a,weapon_id,(victim.actor_id for victim,damage in experience_damage if damage>0))
        if practice is None:
            before_xp=dict(self.experience.totals)
            self.rank_kills.extend(rank_kills)
            for victim,damage in experience_damage:self.experience.damage(self,a,victim,damage)
            from .battle_item_effects import freeze_experience,freeze_rank_kills
            event_time=__import__('time').time()
            freeze_experience(self,before_xp,now=event_time)
            freeze_rank_kills(self,rank_kills,now=event_time)
            self.achievements.attack(a,f._ability_turns.get(a.actor_id,0),weapon_id,w.weapon_type,achievement_outcomes)
        from .battle_item_effects import refresh_sight
        replies.extend(refresh_sight(self))
        if active_rule:f._cooldowns[(a.actor_id,active_id)]=f._ability_turns[a.actor_id]+active_rule[2]
        if view is not None:
            if skill_template is not None:view.templates[a.actor_id]=skill_template
            if not any(i.equipped and i.client_slot==16 for i in updated):
                t=view.templates[a.actor_id]
                key='0x8c52cf' if self.human[a.actor_id] else '0x8c543f'
                view.templates[a.actor_id]=replace(t,fields={**t.fields,key:0})
            from .armor_display import encode_armor
            from .durability import refresh_template
            for identity in changes:
                if identity in view.templates:refresh_template(self,view,identity)
                if old_armor[identity]!=self.displayed_armor(identity):
                    replies.append(encode_armor(identity,self.displayed_armor(identity)))
            replies.extend(view.refresh())
            if ((trained is not None and trained!=profile) or a.actor_id in sight_changed) and a.actor_id in view.visible and f.actor(a.actor_id).health:
                replies.extend(view.snapshot_packets(a.actor_id))
        replies.extend(self.skill_packets(a.actor_id))
        return tuple(replies)
