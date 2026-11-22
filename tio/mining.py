"""Authoritative drill lifecycle. Combat supplies remain battle-local."""
from dataclasses import dataclass,replace
from .crystal_market import POLICY
from .protocol.item_list import ItemRecord,decode_item_list,encode_item_list
from .protocol.mining import occurrence
from .protocol.action_points import encode_action_points

def minimum_victory_crystals(level: int) -> int:
    return 200 if level >= 11 else 100


def band(levels):
    if not levels:raise ValueError('Select one to three fighters')
    for row in POLICY['bands']:
        if all(row[0]<=level<=row[1] for level in levels):return tuple(row)
    raise ValueError('Mine squads require levels 4-6, 7-10, 11-15 or 16-20 in one range')


@dataclass
class Deposit:
    identity:int
    position:tuple
    initial:int
    left:int
    extracted:int=0
    carried:int=0
    drill:object=None
    installer:int|None=None

    def packet(self):
        return occurrence(self.identity,*self.position,self.drill is not None,self.initial,self.left,self.extracted,self.carried)


class MiningBattle:
    def __init__(self,field,layout,total,role,owner,*,shared=False):
        self.field,self.layout,self.total,self.role,self.owner=field,layout,total,role,owner
        self.round=0;self.last_tick=0;self.exit_blocked_until=0;self.extracted_amount=None
        self.shared=shared
        self.roles={};self.exit_blocked_until_by_owner={};self.extracted_amounts={}
        self.exited=set();self.raider_entries=set();self.lift_blocked_until=0
        self.next_actor_id=0x40000001
        self.register_owner(owner,role)
        self.sent_deposits={}
        self.deposits={p:Deposit(i+1,p,total//len(layout.deposits)+(i<total%len(layout.deposits)),
                                  total//len(layout.deposits)+(i<total%len(layout.deposits))) for i,p in enumerate(layout.deposits)}
        loot=field.loot
        drill=ItemRecord(loot._allocate(),52,b'\0\0',0,0,0,(1,1,1),bytes(4),None,bytes(3))
        field.combat.temporary_items.add(drill.instance_id)
        loot.boxes={layout.arena.containers[0]:(drill,)}

    def register_owner(self,owner,role):
        """Freeze a role and the lift's round deadline for one admission.

        Disconnects do not unregister admissions. Rebinding the same owner is
        idempotent, including after extraction, and cannot refresh the lock.
        """
        if type(owner) is not int or owner<=0 or type(role) is not int or role not in (1,2,3):
            raise ValueError('Invalid mining owner or role')
        if owner in self.roles:
            if self.roles[owner]!=role:raise ValueError('Mining role cannot change during an instance')
            return False
        self.roles[owner]=role;self.extracted_amounts[owner]=None
        if self.shared and role==2:
            self.raider_entries.add(owner)
            self.lift_blocked_until=max(self.lift_blocked_until,self.round+5)
            for member in self.roles:
                self.exit_blocked_until_by_owner[member]=self.lift_blocked_until
        self.exit_blocked_until_by_owner[owner]=self.lift_blocked_until
        if self.shared:self.field.teams[owner]=1 if role==2 else 0
        self.exit_blocked_until=self.exit_blocked_until_by_owner[self.owner]
        return True

    def visible(self,owner,position):
        from .visibility import clear_sight
        x,y=position
        return any(a.health and self.field.allied(a.owner_id,owner)
                   and (a.x-x)**2+(a.y-y)**2<=a.sight_radius**2
                   and clear_sight((a.x,a.y),position,self.field.blocked)
                   for a in self.field._actors.values())

    def packets(self,owner=None):
        """Reveal only observed deposits; do not disclose remote drill changes.

        Original B016 creates a persistent occurrence. Previously explored
        deposits retain their last known state, like other explored terrain.
        """
        owner=self.owner if owner is None else owner
        sent=self.sent_deposits.setdefault(owner,{})
        replies=[]
        for p,d in self.deposits.items():
            if not self.visible(owner,p):continue
            packet=d.packet()
            if sent.get(p)!=packet:
                replies.append(packet);sent[p]=packet
        return tuple(replies)

    def _actor(self,owner,identity):
        a=self.field._actors.get(identity)
        if owner not in self.roles or owner in self.exited or a is None or a.owner_id!=owner or not a.health:
            raise ValueError('Living owned mine fighter required')
        # Native 8143f4 has no species gate; original assets also contain the
        # dog's carried-drill model. Crate opening retains its separate rule.
        if a.action_points<1:raise ValueError('Insufficient action points')
        return a

    def _update(self,a,items,flag,deposit):
        combat=self.field.combat
        inventory=encode_item_list(a.actor_id,items,flag)
        # Drill IDs are temporary; this must not insert anything in city bags.
        combat._persist_inventory(a.actor_id,combat.inventories[a.actor_id],inventory)
        combat.inventories[a.actor_id]=inventory
        self.field._actors[a.actor_id]=replace(a,action_points=a.action_points-1)
        return (combat.inventory_packet(a.actor_id),encode_action_points(a.actor_id,a.action_points-1),*self.packets(a.owner_id))

    def install(self,owner,action):
        a=self._actor(owner,action.pet_id)
        if action.option!=255:raise ValueError('Invalid drill action')
        near=[d for p,d in self.deposits.items() if max(abs(p[0]-a.x),abs(p[1]-a.y))<=1 and self.visible(owner,p) and d.drill is None and d.left>0]
        if not near:raise ValueError('Move next to an unoccupied crystal deposit')
        _,items,flag=decode_item_list(self.field.combat.inventories[a.actor_id])
        drill=next((i for i in items if i.instance_id==action.instance_id and i.template_id==52),None)
        if drill is None:raise ValueError('Drill not in inventory')
        d=min(near,key=lambda d:d.identity)
        snapshot=(d.drill,d.extracted,d.carried,d.installer)
        d.drill=drill;d.extracted=d.carried=drill.count
        d.installer=a.actor_id
        try:return self._update(a,tuple(i for i in items if i!=drill),flag,d)
        except Exception:
            d.drill,d.extracted,d.carried,d.installer=snapshot;raise

    def pickup(self,owner,identity,x,y,amount):
        a=self._actor(owner,identity);d=self.deposits.get((x,y))
        if d is None or d.drill is None or max(abs(x-a.x),abs(y-a.y))>1:raise ValueError('Approach the installed drill')
        if not self.visible(owner,(x,y)):raise ValueError('Drill is outside squad sight')
        if not d.carried<=amount<=d.extracted:raise ValueError('Invalid crystal pickup amount')
        _,items,flag=decode_item_list(self.field.combat.inventories[a.actor_id])
        from .weight import inventory_weight
        capacity=self.field.combat.weight_capacity(a.actor_id)
        drill=replace(d.drill,unknown_u32_01=amount)
        if inventory_weight(encode_item_list(a.actor_id, (*items, drill), flag)) > capacity:
            raise ValueError('Not enough carrying capacity for the drill and crystals')
        from .inventory_capacity import validate_capacity
        validate_capacity(items,(*items,drill),limit=self.field.loot.policy['inventory_slots'])
        snapshot=(d.drill,d.extracted,d.carried,d.installer)
        d.drill=None;d.extracted=d.carried=0
        d.installer=None
        try:return self._update(a,(*items,drill),flag,d)
        except Exception:
            d.drill,d.extracted,d.carried,d.installer=snapshot;raise

    def advance(self,generation):
        if generation<=self.last_tick:return ()
        self.last_tick=generation;self.round+=1
        for d in self.deposits.values():
            if d.drill is None or not d.left:continue
            from .implants import active
            from .protocol.pet_info import decode_pet_info
            combat=self.field.combat
            actor=self.field._actors.get(d.installer)
            profile=combat.proficiencies.get(d.installer) if actor is not None and actor.health else None
            effects=active(decode_pet_info(profile,human_equipment=combat.human[d.installer]).fields,
                           combat.inventories[d.installer]) if profile else {}
            taken=min(d.left,(self.total//10)*(100+effects.get('mining',0))//100)
            d.left-=taken;d.extracted+=taken
        # The shared hub refreshes every owner's view after the round commits.
        # Do not consume the primary owner's deposit cache ahead of that fanout.
        return () if self.shared else self.packets()

    def at_exit(self, owner: int) -> bool:
        if owner not in self.roles:
            return False
        actors = [self.field.actor(i) for i in self.field.living_actor_ids(owner)]
        exits = self.layout.raider_exits if self.roles[owner] == 2 else self.layout.lift
        return bool(actors) and all((a.x, a.y) in exits for a in actors)

    def can_quit(self, owner: int) -> bool:
        """A drill permits menu extraction; living opponents require the exit zone."""
        if owner not in self.roles or owner in self.exited:
            return False
        if self.round < self.exit_blocked_until_by_owner[owner]:
            return False
        opponent_alive = any(other not in self.exited and self.field.living_actor_ids(other)
                             and (role == 2) != (self.roles[owner] == 2)
                             for other, role in self.roles.items())
        if opponent_alive and not self.at_exit(owner):
            return False
        return any(item.template_id == 52
                   for actor in self.field.living_actor_ids(owner)
                   for item in decode_item_list(self.field.combat.inventories[actor])[1])

    def exit(self,owner,*,menu=False):
        if owner not in self.roles:raise ValueError('Invalid extraction owner')
        if owner in self.exited:return self.extracted_amounts[owner]
        blocked=self.exit_blocked_until_by_owner[owner]
        if owner==self.owner:blocked=max(blocked,self.exit_blocked_until)
        if self.round<blocked:raise ValueError('Lift is blocked')
        actors=[self.field.actor(i) for i in self.field.living_actor_ids(owner)]
        if menu:
            if not self.can_quit(owner):raise ValueError('Для выхода нужен бур. Дождитесь снятия блокировки; при живом противнике приведите отряд к выходу')
        elif not self.at_exit(owner):raise ValueError('Bring every living fighter to your exit')
        drills=[i for a in actors for i in decode_item_list(self.field.combat.inventories[a.actor_id])[1] if i.template_id==52]
        amount=sum(i.count for i in drills)
        self.extracted_amounts[owner]=amount;self.exited.add(owner)
        if owner==self.owner:self.extracted_amount=amount
        return amount


from server.battle_journal import private_field
for _name in ('pickup','advance','exit'):
    setattr(MiningBattle,_name,private_field(getattr(MiningBattle,_name)))
