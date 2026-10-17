"""Authoritative flag capture and simultaneous score ticks.

Three flags, 1000-point cap, elimination before points: original TIO rules.
Radius 2 (Manhattan), 5 points/flag/actor turn: explicit emulator policy.
"""
from dataclasses import dataclass


@dataclass
class ControlPoints:
    positions: tuple
    owners: list
    scores: list
    radius: int=2
    rate: int=5
    limit: int=1000

    def capture(self,field):
        for index,(x,y) in enumerate(self.positions):
            present={field.teams[a.owner_id] for a in field._actors.values()
                     if a.health and abs(a.x-x)+abs(a.y-y)<=self.radius}
            if len(present)!=1:continue
            side=next(iter(present));old=self.owners[index]
            self.owners[index]=side if old is None or old==side else None

    def increments(self):
        return tuple(self.rate*self.owners.count(side) for side in (0,1))

    def advance(self,field):
        self.capture(field)
        self.scores[:]=[min(self.limit,n+gain) for n,gain in zip(self.scores,self.increments())]

    def outcome(self,field):
        sides={field.teams[a.owner_id] for a in field._actors.values() if a.health}
        if len(sides)<=1:return next(iter(sides)) if sides else 2
        full=[side for side,n in enumerate(self.scores) if n>=self.limit]
        return 2 if len(full)==2 else full[0] if full else None
