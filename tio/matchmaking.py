"""Server-owned survival queue, without player-created rooms.

Survival groups two to four humans within a manual level band, preferring
larger common squads. A short configured window lets a pair gain more players.
An isolated survival search receives a transient opponent after one minute.
The caller must start a scene before consuming a returned match proposal.
"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from .protocol.pet_info import decode_pet_info


@dataclass(frozen=True)
class SearchTicket:
    character_id: int
    actors: tuple[int,...]
    levels: tuple[int,...]
    joined_at: float
    mode: int = 0
    pool: str = 'starter'


@dataclass(frozen=True)
class MatchProposal:
    first: SearchTicket
    second: SearchTicket | None
    members: tuple[SearchTicket, ...] = ()

    def __post_init__(self):
        members = self.members or ((self.first,) if self.second is None else (self.first, self.second))
        if (not isinstance(members, tuple) or not members or members[0] is not self.first
                or (self.second is None and len(members) != 1)
                or (self.second is not None and (len(members) < 2 or members[1] is not self.second))
                or len({ticket.character_id for ticket in members}) != len(members)):
            raise ValueError('Invalid match proposal members')
        object.__setattr__(self, 'members', members)

    @property
    def uses_bot(self):return self.second is None

    @property
    def soldiers(self):
        """The common admitted prefix; saved squad selections stay untouched."""
        return min(len(ticket.actors) for ticket in self.members)


class SurvivalQueue:
    def __init__(self,*,clock=time.monotonic,bot_delay=5,level_span=2,group_wait=None,survival_bot_delay=None):
        if group_wait is None or survival_bot_delay is None:
            policy = json.loads((Path(__file__).resolve().parents[1]/'config/survival.json').read_text())
            if group_wait is None:group_wait = policy['group_wait_seconds']
            if survival_bot_delay is None:survival_bot_delay = policy.get('bot_wait_seconds',60)
        if (any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0 for value in (bot_delay, level_span, group_wait,survival_bot_delay))):
            raise ValueError('Invalid matchmaking policy')
        self.clock=clock;self.bot_delay=bot_delay;self.level_span=level_span;self.group_wait=group_wait
        self.survival_bot_delay=survival_bot_delay
        self.tickets={}

    def join(self,character_id,roster,*,mode=0,pool='starter'):
        from .battle_modes import mode_rules
        policy=mode_rules(mode)
        if type(character_id) is not int or character_id<=0:raise ValueError('Authenticated character required')
        slots={};ids=set()
        for owner,packet,inventory in roster:
            resource=int.from_bytes(packet[5:9],'little')
            if resource not in (1,2,3,4,5,6):raise ValueError('Unsupported actor resource')
            pet=decode_pet_info(packet,human_equipment=resource in (1,2,6)).fields
            if pet['0x8c43eb']!=owner or owner in ids:raise ValueError('Invalid owned roster')
            ids.add(owner);slot=pet['0x8c44a6']
            if slot not in (1,2,3):continue
            if slot in slots or pet['0x8c4ab1']==0:raise ValueError('Invalid selected squad')
            slots[slot]=(owner,pet['0x8c4aef'])
        if not slots:raise ValueError('Select a squad before searching')
        selected=tuple(slots[s] for s in sorted(slots))
        actors=tuple(a for a,_ in selected);levels=tuple(l for _,l in selected)
        policy.validate(len(actors))
        if mode == 0:
            from .battle_modes import level_band
            if len({level_band(level) for level in levels}) != 1:
                raise ValueError("Fighters must belong to the same level range")
        previous=self.tickets.get(character_id)
        if previous is not None:
            if (previous.actors,previous.levels,previous.mode,previous.pool)!=(actors,levels,mode,pool):raise ValueError('Cancel search before changing squad or mode')
            return previous
        ticket=SearchTicket(character_id,actors,levels,self.clock(),mode,pool)
        self.tickets[character_id]=ticket
        return ticket

    def cancel(self,character_id):
        return self.tickets.pop(character_id,None) is not None

    def propose(self,character_id):
        first=self.tickets.get(character_id)
        if first is None:return None
        from .battle_modes import level_band, mode_rules
        if first.mode == 0:
            candidates=[other for other in self.tickets.values()
                if other.mode==0 and other.pool==first.pool and other.character_id!=character_id
                and level_band(other.levels[0])==level_band(first.levels[0])]
            if candidates:
                # Manual p15: try the largest common squad first. Extra seats
                # must not force a lower squad size when a larger one can match.
                soldiers=max(min(len(first.actors),len(t.actors)) for t in candidates)
                eligible=sorted((t for t in candidates if len(t.actors)>=soldiers),
                                key=lambda t:(t.joined_at,t.character_id))
                limit=mode_rules(0).max_players
                members=(first,*eligible[:limit-1])
                oldest=min(t.joined_at for t in members)
                if len(members)<limit and self.clock()-oldest<self.group_wait:return None
                return MatchProposal(first,members[1],members)
            if self.clock()-first.joined_at>=self.survival_bot_delay:return MatchProposal(first,None)
        elif self.clock()-first.joined_at>=self.bot_delay:return MatchProposal(first,None)
        return None

    def consume(self,proposal):
        """Call only after successful scene preparation; reject stale proposals."""
        from .battle_modes import level_band, mode_rules
        if not isinstance(proposal, MatchProposal):raise ValueError('Invalid match proposal')
        members=proposal.members
        first=proposal.first
        if first.mode==0:
            mode_rules(0).validate_players(len(members)+int(proposal.uses_bot))
            if proposal.uses_bot and self.propose(first.character_id)!=proposal:
                raise ValueError('Stale or premature bot proposal')
            if any(t.mode!=0 or t.pool!=first.pool or level_band(t.levels[0])!=level_band(first.levels[0]) for t in members):
                raise ValueError('Incompatible match proposal')
        elif len(members)!=1 or not proposal.uses_bot:
            raise ValueError('Invalid training match proposal')
        if any(self.tickets.get(t.character_id) is not t for t in members):raise ValueError('Stale match proposal')
        for ticket in members:del self.tickets[ticket.character_id]
