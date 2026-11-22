"""Authoritative grid movement with explicitly supplied local movement costs.

Costs/passability come from server scene preparation, not client requests.
Original terrain and action-point balance is not yet recovered.
"""
from dataclasses import dataclass, replace
from .combat_distance import rounded_radius_squared
from .protocol.battle_move import BattleMove, encode_battle_move


@dataclass(frozen=True)
class BattleActor:
    actor_id: int
    owner_id: int
    x: int
    y: int
    action_points: int
    health: int | None = None
    max_health: int | None = None
    sight_radius: int = 9
    weapons: tuple = ()


class BattleField:
    def __init__(self, width, height, actors, *, blocked=(), step_cost, teams=None, transparent_obstacles=None):
        if not 1 <= width <= 255 or not 1 <= height <= 255 or step_cost <= 0:
            raise ValueError('Invalid grid or movement cost')
        self.width, self.height, self.step_cost = width, height, step_cost
        self.blocked = frozenset(blocked)
        self.transparent_obstacles = None if transparent_obstacles is None else frozenset(transparent_obstacles)
        self.teams = dict(teams or {})
        if any(not self.inside(x,y) for x,y in self.blocked):
            raise ValueError('Blocked cell outside grid')
        self._actors = {}
        self._turn_points = {}
        self._ability_turns = {}
        self._cooldowns = {}
        self._healing_rules = {}
        self._slash_rules = {}
        self._dog_rules = {}
        occupied = set()
        for actor in actors:
            if (actor.actor_id in self._actors or actor.actor_id <= 0 or actor.owner_id <= 0
                    or not 0 <= actor.action_points <= 255 or not self.inside(actor.x,actor.y)
                    or (actor.x,actor.y) in self.blocked | occupied):
                raise ValueError('Invalid actor placement')
            self._actors[actor.actor_id] = actor
            if type(actor.sight_radius) is not int or not 0 <= actor.sight_radius <= 255:
                raise ValueError('Invalid actor sight radius')
            if (actor.health is None)!=(actor.max_health is None) or (actor.health is not None and
                    not 0<=actor.health<=actor.max_health<=65535):
                raise ValueError('Invalid actor health')
            self._turn_points[actor.actor_id] = actor.action_points
            self._ability_turns[actor.actor_id]=0
            occupied.add((actor.x,actor.y))

    def inside(self,x,y):
        return 0 <= x < self.width and 0 <= y < self.height

    def actor(self, actor_id):
        return self._actors[actor_id]

    def weapon_ap_cost(self, nominal_cost: int) -> int:
        return 0 if getattr(self, 'practice', None) is not None else nominal_cost

    def actor_ids(self, owner_id):
        return tuple(sorted(a.actor_id for a in self._actors.values() if a.owner_id == owner_id))

    def side(self, owner_id):
        # Untagged survival owners remain mutually hostile.
        return ('team', self.teams[owner_id]) if owner_id in self.teams else ('owner', owner_id)

    def allied(self, first, second):
        return self.side(first) == self.side(second)

    def living_sides(self):
        return {self.side(a.owner_id) for a in self._actors.values() if a.health is not None and a.health > 0}

    def living_actor_ids(self, owner_id):
        return tuple(i for i in self.actor_ids(owner_id) if self.actor(i).health != 0)

    def can_exit(self, owner_id: int) -> bool:
        """Native 95DC30 checks the inner border for every living owned actor."""
        return all(a.x in (1, self.width - 2) or a.y in (1, self.height - 2)
                   for a in self._actors.values() if a.owner_id == owner_id and a.health != 0)

    def remove_owner(self, owner_id):
        """Release departed actors' cells and their saved AP budgets."""
        removed = self.actor_ids(owner_id)
        for actor_id in removed:
            del self._actors[actor_id]
            del self._turn_points[actor_id]
            del self._ability_turns[actor_id]
            self._cooldowns={key:value for key,value in self._cooldowns.items() if key[0]!=actor_id}
            self._healing_rules={key:value for key,value in self._healing_rules.items() if key[0]!=actor_id}
            self._slash_rules={key:value for key,value in self._slash_rules.items() if key[0]!=actor_id}
            self._dog_rules={key:value for key,value in self._dog_rules.items() if key[0]!=actor_id}
        return removed

    def prepare_turn(self, owner_id, actor_ids):
        """Validate the entire selection before restoring the local turn budget."""
        from .protocol.action_points import encode_action_points
        updates = {}
        for actor_id in actor_ids:
            actor = self._actors.get(actor_id)
            if actor is None or actor.owner_id != owner_id:
                raise ValueError('Turn actor does not belong to character')
            if actor.health==0:
                raise ValueError('Dead actor cannot receive a turn')
            maximum=self._turn_points[actor_id]
            combat=getattr(self,'combat',None)
            points=combat.turn_budget(actor_id,maximum) if combat is not None else maximum
            updates[actor_id] = replace(actor, action_points=points)
        if not updates:
            raise ValueError('Turn requires actors')
        replies = tuple(encode_action_points(a.actor_id,a.action_points) for a in updates.values())
        self._actors.update(updates)
        for actor_id in updates:self._ability_turns[actor_id]+=1
        return replies

    def configure_dog_healing(self,owner_id,actor_id,resource_type,learned,catalog):
        """Prepare a rule from a trusted saved roster before battle starts.

        Do not inherit missing cooldowns from another rank. Higher ranks need
        an explicit recovered definition before they can be used in battle.
        """
        actor=self._actors.get(actor_id)
        if actor is None or actor.owner_id!=owner_id or resource_type not in (3,4,5):
            raise ValueError('Owned dog required')
        if self._ability_turns[actor_id]!=0:raise ValueError('Ability rules cannot change during battle')
        entries=[e for e in learned if e.ability_id==23]
        if len(entries)!=1:raise ValueError('One learned healing skill required')
        entry=entries[0];definition=catalog.get(23,entry.level)
        amount,ap,cooldown=(definition.number(k) for k in ('value','AP','Cooldown'))
        if any(type(v) is not int or v<=0 for v in (amount,ap,cooldown)):
            raise ValueError('Incomplete healing rank parameters')
        if not 1<=entry.level<=255 or ap>255 or cooldown>0xffffffff:
            raise ValueError('Healing rule exceeds native field widths')
        self._healing_rules[(actor_id,23)]=(amount,ap,cooldown,entry.level)

    def cast_healing(self,owner_id,request,*,with_packets=False):
        rule=self._healing_rules.get((request.actor_id,request.ability_id))
        if rule is None:raise ValueError('Ability is not prepared for battle')
        updated,key,ready=self._prepare_healing(owner_id,request,amount=rule[0],ap_cost=rule[1],reuse_turns=rule[2])
        result=updated
        if with_packets:
            from .protocol.health import encode_health
            from .protocol.action_points import encode_action_points
            from .protocol.ability_status import AbilityStatus,encode_ability_status
            from .protocol.battle_attack import AttackResult,encode_attack_result
            # Serialize all notifications before committing any HP/AP/cooldown.
            result=(encode_attack_result(AttackResult(updated.actor_id,(updated.x,updated.y),(updated.x,updated.y),333,skill_id=23)),
                    encode_health(updated.actor_id,updated.health),
                    encode_action_points(updated.actor_id,updated.action_points),
                    encode_ability_status(updated.actor_id,[AbilityStatus(request.ability_id,rule[3],3,rule[2])]))
        self._actors[updated.actor_id]=updated
        self._cooldowns[key]=ready
        return result

    def configure_miner_slash(self,owner_id,actor_id,resource_type,learned):
        from .miner_abilities import rules
        actor=self._actors.get(actor_id)
        entries=[e for e in learned if e.ability_id==22]
        if actor is None or actor.owner_id!=owner_id or resource_type!=6:
            raise ValueError('Owned miner required')
        if self._ability_turns[actor_id]!=0:raise ValueError('Rules cannot change during battle')
        if len(entries)!=1 or entries[0].level not in range(1,5):raise ValueError('One learned slash rank required')
        rank=entries[0].level; data=rules()
        self._slash_rules[(actor_id,22)]=(data['slash_percent'][rank-1],data['slash_ap'],data['slash_cooldown'],rank)

    def ability_status_packets(self,owner_id,actor_ids):
        """Absolute cooldown snapshots, sent before YourTurn enables input."""
        from .protocol.ability_status import AbilityStatus,encode_ability_status
        replies=[]
        for actor_id in sorted(set(actor_ids)):
            actor=self._actors.get(actor_id)
            if actor is None or actor.owner_id!=owner_id:raise ValueError('Owned actor required')
            entries=[]
            combat=getattr(self,'combat',None)
            if combat is not None:
                from .weapon_effects import battle_skills
                if any(e.ability_id==27 for e in battle_skills((),combat.inventories[actor_id],combat.human[actor_id])):
                    entries.append(AbilityStatus(27,1,4,0))
            for (owner_actor,ability_id),rule in sorted({**self._healing_rules,**self._slash_rules,**self._dog_rules}.items()):
                if owner_actor!=actor_id:continue
                left=max(0,self._cooldowns.get((actor_id,ability_id),0)-self._ability_turns[actor_id])
                entries.append(AbilityStatus(ability_id,rule[3],3 if left else 4,left))
            if entries:replies.append(encode_ability_status(actor_id,entries))
        return tuple(replies)

    def heal_self(self,owner_id,request,*,amount,ap_cost,reuse_turns):
        updated,key,ready=self._prepare_healing(owner_id,request,amount=amount,ap_cost=ap_cost,reuse_turns=reuse_turns)
        self._actors[updated.actor_id]=updated
        self._cooldowns[key]=ready
        return updated

    def _prepare_healing(self,owner_id,request,*,amount,ap_cost,reuse_turns):
        """Server-approved skill rule; ArenaService must first validate turn.

        Cooldown N allows reuse at the Nth following turn of this actor.
        This turn-count policy is local until the original semantics are known.
        No client supplied prices, levels or health amounts are accepted here.
        """
        actor=self._actors.get(request.actor_id)
        if actor is None or actor.owner_id!=owner_id:raise ValueError('Actor does not belong to character')
        if request.unknown_u32!=0 or (request.x,request.y)!=(actor.x,actor.y):raise ValueError('Self skill requires own cell')
        if any(type(v) is not int for v in (amount,ap_cost,reuse_turns)) or amount<=0 or ap_cost<=0 or reuse_turns<1:
            raise ValueError('Invalid healing rule')
        if actor.health is None or actor.max_health is None:raise ValueError('Actor health is not initialized')
        if actor.health==0:raise ValueError('Dead actor cannot heal')
        if actor.health==actor.max_health:raise ValueError('Actor is already healthy')
        turn=self._ability_turns[actor.actor_id];key=(actor.actor_id,request.ability_id)
        if turn<self._cooldowns.get(key,0):raise ValueError('Ability is cooling down')
        if actor.action_points<ap_cost:raise ValueError('Insufficient action points')
        updated=replace(actor,health=min(actor.max_health,actor.health+amount),action_points=actor.action_points-ap_cost)
        return updated,key,turn+reuse_turns

    def move(self, owner_id, request):
        actor = self._actors.get(request.actor_id)
        if actor is None or actor.owner_id != owner_id:
            raise ValueError('Actor does not belong to character')
        if actor.health==0:raise ValueError('Dead actor cannot move')
        path = tuple(request.path)
        # Some path builders include the origin; it is not a charged step.
        if path and path[0] == (actor.x, actor.y):
            path = path[1:]
        if not path:
            raise ValueError('Movement requires a destination')
        occupied = {(a.x,a.y) for a in self._actors.values()
                    if a.actor_id != actor.actor_id and a.health != 0}
        x,y = actor.x,actor.y
        for nx,ny in path:
            if not self.inside(nx,ny) or (nx,ny) in self.blocked:
                raise ValueError('Destination is blocked or outside grid')
            if max(abs(nx-x),abs(ny-y)) != 1:
                raise ValueError('Path contains a nonadjacent step')
            if nx != x and ny != y and ((nx,y) in self.blocked or (x,ny) in self.blocked):
                raise ValueError('Diagonal path cuts a blocked corner')
            x,y = nx,ny
        cost = len(path)*self.step_cost
        if cost > actor.action_points:
            raise ValueError('Insufficient action points')
        # Validate geometry and budget for the entire request, but resolve live
        # occupancy only along the part actually travelled. A hidden enemy in
        # the unused tail must not reject a move that stops at first contact.
        from .visibility import visible_actors, field_sight
        known = visible_actors(self, owner_id)
        hidden_enemies = tuple(a for a in self._actors.values()
                          if a.health != 0 and not self.allied(a.owner_id, owner_id)
                          and a.actor_id not in known)
        sight_limit = rounded_radius_squared(actor.sight_radius)
        x,y = actor.x,actor.y
        for index, (nx, ny) in enumerate(path):
            blocked = (nx,ny) in occupied
            corner = nx != x and ny != y and ((nx,y) in occupied or (x,ny) in occupied)
            if blocked or corner:
                if not index:
                    raise ValueError('Destination is occupied' if blocked else 'Diagonal path cuts an occupied corner')
                path = path[:index]
                break
            # Other observers stay put. Only the moving actor can reveal a
            # previously hidden enemy; use the same radius and ray as the view.
            if any((nx-a.x)**2+(ny-a.y)**2 <= sight_limit and
                   field_sight(self, (nx, ny), (a.x, a.y)) for a in hidden_enemies):
                path = path[:index+1]
                break
            x,y = nx,ny
        combat=getattr(self,'combat',None)
        if combat is not None:
            from .battle_hazards import stop_path
            path=stop_path(combat,path)
        x, y = path[-1]
        cost = len(path)*self.step_cost
        reply = encode_battle_move(BattleMove(actor.actor_id,path))
        self._actors[actor.actor_id] = replace(actor,x=x,y=y,action_points=actor.action_points-cost)
        return reply
