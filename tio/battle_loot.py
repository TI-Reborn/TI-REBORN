"""Battle-local crates. Random tables are explicit local balance, not server data."""

from .db_transaction import connect
from dataclasses import replace
import json
from pathlib import Path
import random
import xml.etree.ElementTree as ET
from .protocol.item_list import ItemRecord,decode_item_list,encode_item_list
from .protocol.battle_loot import encode_container,encode_open_container_state
from .protocol.action_points import encode_action_points
from .item_stacking import merge_stacks
from .inventory_capacity import validate_capacity

ROOT=Path(__file__).resolve().parents[1]


def match_id_floor(combat):
    """First free match-unique item ID for battle-created items.

    Native wire IDs are globally unique within the match: the client keeps the
    saved items of every mercenary it knows, so a battle item that reuses a
    reserve/warehouse ID resolves to the wrong owner. Reserve the selected
    squad, excluded personal gear, every saved pet, the account sequence and
    the warehouse; battle items start no lower than 0x60000000.
    """
    from contextlib import closing
    floor=max(0x60000000,1+max((i.instance_id for p in (*combat.inventories.values(),
                                *getattr(combat,'personal_inventories',{}).values())
                                for i in decode_item_list(p)[1]),default=0))
    for path,account in set(combat.persistence.values()):
        with closing(connect(path)) as db:
            for packet, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(account,)):
                floor=max(floor,1+max((i.instance_id for i in decode_item_list(packet)[1]),default=0))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='item_sequences'").fetchone():
                row=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(account,)).fetchone()
                if row:floor=max(floor,row[0])
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='warehouse_items'").fetchone():
                highest=db.execute('SELECT MAX(instance_id) FROM warehouse_items WHERE account=?',(account,)).fetchone()[0]
                floor=max(floor,1+(highest or 0))
    return floor

class BattleLoot:
    def __init__(self,combat,positions,*,level=1,rng=None):
        self.combat=combat
        self.policy=json.loads((ROOT/'config/battle_loot.json').read_text())
        self.rng=rng or random.Random()
        self.level=max(1,level)
        self.boxes={tuple(p):None for p in positions}
        self.opened=set()
        self.ground=set()
        self.sessions={}
        self.next_id=match_id_floor(combat)
        self.metadata={int(n.get('id')):{'name':n.get('name'),**{v.get('key'):v.get('val') for v in n.findall('value')}}
                       for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()}
        from .equipment import armor_rules
        rules=armor_rules()
        self.weapons=[i for i,v in self.metadata.items() if i in combat.catalog.weapons
                      and i not in (300,333,337,317) and v.get('weaponAttack') in ('Bullet','None')
                      and v.get('image') and not self.special(v)
                      and int(v.get('level_required',0))<=self.level]
        self.armors=[i for i,v in self.metadata.items() if i in rules and not rules[i]['dog']
                     and not self.special(v) and rules[i]['level']<=self.level]
        if not self.weapons or not self.armors:raise ValueError('Empty loot equipment pool')

    @staticmethod
    def special(values):
        return any(values.get(k)=='1' for k in ('special','cant_buy_in_private_store','freaks_only')) or values.get('name','').endswith(' SE')

    def _allocate(self):
        if self.next_id>0xffffffff:raise ValueError('Loot ID space exhausted')
        result=self.next_id;self.next_id+=1
        return result

    def _roll(self):
        weapon=self.rng.choice(self.weapons)
        choices=[(weapon,1),(self.rng.choice(self.armors),1),
                 (self.rng.choice((9,34)),self.rng.randint(*self.policy['medical_units']))]
        ammo=int(self.metadata[weapon].get('ammo_id',0))
        if ammo:
            choices.append((ammo,int(self.metadata[ammo].get('packamount',1))*self.rng.randint(*self.policy['ammo_packs'])))
        if self.rng.random()<self.policy['extra_grenade_chance']:choices.append((317,1))
        items=tuple(ItemRecord(self._allocate(),i,b'\0\0',n,0,0,(int(self.metadata[i].get('durability',0)),)*3,b'\0'*4,None,b'\0'*3) for i,n in choices)
        self.combat.temporary_items.update(i.instance_id for i in items)
        return items

    def _actor(self,owner,actor_id,position,*,deposit=False):
        actor=self.combat.field._actors.get(actor_id)
        if actor is None or actor.owner_id!=owner or not actor.health:raise ValueError('Living owned actor required')
        if not self.combat.human.get(actor_id):raise ValueError('Dogs cannot open containers')
        if deposit and position==(actor.x,actor.y):return actor
        if position not in self.boxes:raise ValueError('No container at this position')
        if position in self.ground and (position!=(actor.x,actor.y) or not self.boxes[position]):
            raise ValueError('Stand on the backpack to pick it up')
        if max(abs(actor.x-position[0]),abs(actor.y-position[1]))>1:raise ValueError('Move next to the crate')
        return actor

    def open(self,owner,request,turn,*,view=None):
        position=(request.x,request.y)
        actor=self._actor(owner,request.actor_id,position)
        # The native client sends no close packet for an unchanged window.
        # Every new46 therefore opens/reopens; TCP already orders delivery.
        session=(position,turn,(actor.x,actor.y))
        first_open=position not in self.opened and position not in self.ground
        cost=self.policy['reopen_ap' if position in self.opened or position in self.ground else 'unseal_ap']
        if actor.action_points<cost:raise ValueError('Insufficient action points to open crate')
        if self.boxes[position] is None:self.boxes[position]=self._roll()
        actor=replace(actor,action_points=actor.action_points-cost)
        self.combat.field._actors[actor.actor_id]=actor
        self.opened.add(position);self.sessions[actor.actor_id]=session
        if view is not None:view.loot_states[position]=True
        if first_open:self.combat.achievements.add(owner,'crates')
        return (encode_action_points(actor.actor_id,actor.action_points),
                self.combat.inventory_packet(actor.actor_id),
                *((encode_open_container_state(*position),) if first_open else ()),
                encode_container(actor.actor_id,*position,self.boxes[position]))

    def transfer(self,owner,request,turn,*,view=None):
        position=(request.x,request.y)
        actor=self._actor(owner,request.actor_id,position,deposit=True)
        opened=self.sessions.get(actor.actor_id)==(position,turn,(actor.x,actor.y))
        direct=not opened and position==(actor.x,actor.y) and not request.withdrawals and (position not in self.boxes or position in self.ground)
        if not opened and not direct:raise ValueError('Open this container during the current turn first')
        if not request.deposits and not request.withdrawals:
            self.sessions.pop(actor.actor_id,None)
            return (self.combat.inventory_packet(actor.actor_id),)
        # Empty-cell inventory is opened locally by silver.dll9B8012, without46.
        # Settings9DC881 initializes its cost (+0A) to2; no charge for cancelling.
        cost=2 if direct and request.deposits else 0
        if actor.action_points<cost:raise ValueError('Insufficient action points to drop items')
        old=self.combat.inventories[actor.actor_id]
        _,items,flag=decode_item_list(old)
        bag={i.instance_id:i for i in items};box={i.instance_id:i for i in (self.boxes.get(position) or ())}
        if set(bag)&set(box):raise ValueError('Duplicate item ownership')
        deposited={i for i,n in request.deposits};withdrawn={i for i,n in request.withdrawals}
        if (len(deposited)!=len(request.deposits) or len(withdrawn)!=len(request.withdrawals)
                or deposited&withdrawn):raise ValueError('Duplicate transfer selection')
        for pairs,source in ((request.deposits,bag),(request.withdrawals,box)):
            for identity,count in pairs:
                empty_drill=identity in source and source[identity].template_id==52 and source[identity].count==count==0
                if identity not in source or not (empty_drill or 0<count<=source[identity].count):raise ValueError('Unavailable loot quantity')
                if source[identity].template_id==52 and count!=source[identity].count:
                    raise ValueError('A drill and its crystals must be transferred whole')
                if source[identity].equipped:raise ValueError('Unequip item before depositing')
                from .item_boosters import nontransferable
                if source is bag and nontransferable(source[identity].template_id):raise ValueError('Предметный бустер нельзя оставлять в ящике')
                if source[identity].optional_u32 is not None or any(source[identity].unknown_bytes_02[2:]):
                    raise ValueError('Marked or rented equipment cannot be left in a crate')
        temporary=set(self.combat.temporary_items)
        next_id=self.next_id
        def move(pairs,source,destination):
            nonlocal next_id
            for identity,count in pairs:
                item=source[identity]
                if count==item.count:source.pop(identity)
                else:
                    source[identity]=replace(item,unknown_u32_01=item.count-count)
                    if next_id>0xffffffff:raise ValueError('Loot ID space exhausted')
                    if identity in temporary:temporary.add(next_id)
                    item=replace(item,instance_id=next_id,unknown_u32_01=count);next_id+=1
                if source is bag and identity not in temporary:
                    from .durability import wear
                    item=wear(item,(item.unknown_words[0]+1)//2)
                    # Account-local inventory IDs may coincide across players.
                    # Give deposited permanent items a unique match identity.
                    if item is not None:
                        if next_id>0xffffffff:raise ValueError('Loot ID space exhausted')
                        item=replace(item,instance_id=next_id);next_id+=1
                if item is not None:destination[item.instance_id]=item
        move(request.deposits,bag,box);move(request.withdrawals,box,bag)
        # Do not combine temporary supplies with permanent ammunition, even if
        # an old save happens to have identical zero durability/opaque flags.
        def merge(values):
            values=tuple(values)
            return (*merge_stacks(i for i in values if i.instance_id not in temporary),
                    *merge_stacks(i for i in values if i.instance_id in temporary))
        merged=merge(bag.values());newbox=merge(box.values())
        validate_capacity(items,merged,limit=self.policy['inventory_slots'])
        inventory=encode_item_list(actor.actor_id,merged,flag)
        if any(i.template_id==52 and i.instance_id in withdrawn for i in merged) and actor.actor_id in self.combat.weight_capacities:
            from .weight import inventory_weight
            if inventory_weight(inventory)>self.combat.weight_capacity(actor.actor_id):
                raise ValueError('Not enough carrying capacity for the drill and crystals')
        # Transfer confirmation refreshes ItemList;47 is reserved for opening,
        # because its native consumer would reopen an already closed dialog.
        encode_container(actor.actor_id,*position,newbox)
        reply=self.combat.inventory_packet(actor.actor_id,inventory)
        self.combat._persist_inventory(actor.actor_id,old,inventory,temporary_ids=temporary)
        self.combat.temporary_items=temporary
        self.combat.inventories[actor.actor_id]=inventory
        self.boxes[position]=newbox;self.next_id=next_id
        if direct and request.deposits:self.ground.add(position)
        self.combat.field._actors[actor.actor_id]=replace(actor,action_points=actor.action_points-cost)
        self.sessions.pop(actor.actor_id,None)
        return (*((encode_action_points(actor.actor_id,actor.action_points-cost),) if cost else ()),reply,
                *(view.refresh() if view is not None else ()))

    def stage_deaths(self,states,changes):
        """Prepare loot alongside combat inventories, before the shared DB commit."""
        boxes={};ground=set()
        for identity,state in states.items():
            if state.health or not self.combat.field.actor(identity).health or identity not in self.combat.inventories:continue
            packet=changes.get(identity,self.combat.inventories[identity])
            _,items,flag=decode_item_list(packet)
            dropped=tuple(replace(i,unknown_u8_01=0,location_raw=0) for i in items if i.instance_id in self.combat.temporary_items)
            if not dropped:continue
            position=(state.x,state.y)
            boxes[position]=(*boxes.get(position,self.boxes.get(position) or ()),*dropped)
            if position not in self.boxes or position in self.ground:ground.add(position)
            changes[identity]=encode_item_list(identity,tuple(i for i in items if i.instance_id not in self.combat.temporary_items),flag)
            encode_container(identity,*position,boxes[position])
        return boxes,ground

    def visible_updates(self,owner,remembered,*,field=None):
        from .visibility import field_sight
        from copy import copy
        field=field or self.combat.field
        observers=[a for a in field._actors.values() if a.health and field.allied(a.owner_id,owner)]
        replies=[]
        for p in sorted(self.ground | self.opened):
            state=bool(self.boxes[p]) if p in self.ground else True
            if remembered.get(p,False)==state:continue
            sight_field=field
            if p in field.blocked:
                sight_field=copy(field);sight_field.blocked=field.blocked-{p}
            if not any((a.x-p[0])**2+(a.y-p[1])**2<=a.sight_radius**2 and
                       field_sight(sight_field,(a.x,a.y),p) for a in observers):continue
            replies.append((bytes((0x44,*p,0,0)) if state else bytes((0x45,*p))) if p in self.ground
                           else encode_open_container_state(*p))
            remembered[p]=state
        return tuple(replies)
