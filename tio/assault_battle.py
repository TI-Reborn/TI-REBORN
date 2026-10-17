"""Shared three-flag Assault4 score, advanced once per complete battle cycle."""
from dataclasses import dataclass


@dataclass
class AssaultPoints:
    positions: tuple
    owners: list
    scores: list
    round: int=0
    radius: int=2

    def capture(self,field):
        # Native authored flags are blocked scenery cells. Their adjacent
        # approach radius and contested neutralization are emulator policy.
        for index,(x,y) in enumerate(self.positions):
            present={field.teams[a.owner_id] for a in field._actors.values()
                if a.health and abs(a.x-x)+abs(a.y-y)<=self.radius}
            if len(present)!=1:continue
            side=next(iter(present));old=self.owners[index]
            self.owners[index]=side if old is None or old==side else None

    def increments(self):
        # Administration's Assault4 guide: one/two/three flags =>4/10/18 OF.
        return tuple((0,4,10,18)[self.owners.count(side)] for side in (0,1))

    def advance(self,field):
        self.capture(field)
        self.scores[:]=[n+gain for n,gain in zip(self.scores,self.increments())]
        self.round+=1

    def outcome(self,field):
        alive={field.teams[a.owner_id] for a in field._actors.values() if a.health}
        return (next(iter(alive)) if alive else 2) if len(alive)<=1 else None
