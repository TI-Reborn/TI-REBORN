"""Shared team assembly and FIFO matching. No automatic all-bot opponents."""
from dataclasses import dataclass, field
from threading import RLock
import time


@dataclass
class TeamLobby:
    identity: int
    captain: int
    mode: int
    band: int
    soldiers: int
    members: list
    ready: set = field(default_factory=set)
    searching: bool = False
    bots: int = 0
    queued_at: float = 0
    pool: str = 'starter'

    @property
    def capacity(self):return 2 if self.mode == 1 else 4


class TeamLobbies:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = RLock()
        self.rooms = {}
        self.membership = {}
        self.next_id = 1

    def room(self, member):
        return self.rooms.get(self.membership.get(member))

    def create(self, member, mode, band, soldiers, *, pool='starter'):
        if mode not in (1,4) or band not in range(5) or not 1 <= soldiers <= (3 if mode == 1 else 1):
            raise ValueError('Недопустимые параметры команды')
        with self.lock:
            previous = self.room(member)
            if previous:
                if previous.captain == member and (previous.mode,previous.band,previous.soldiers,previous.pool)==(mode,band,soldiers,pool):return previous
                raise ValueError('Сначала покиньте текущую команду')
            room = TeamLobby(self.next_id,member,mode,band,soldiers,[member],pool=pool)
            self.next_id += 1
            self.rooms[room.identity] = room
            self.membership[member] = room.identity
            return room

    def join(self, identity, member, band, soldiers, *, pool='starter'):
        with self.lock:
            room = self.rooms.get(identity)
            if room is None or room.searching:raise ValueError('Команда уже ищет бой или закрыта')
            if room.pool!=pool:raise ValueError('Команда находится в другом типе города')
            if self.room(member) is room:return room
            if self.room(member):raise ValueError('Сначала покиньте текущую команду')
            if (band,soldiers)!=(room.band,room.soldiers):raise ValueError('Нужны тот же диапазон уровней и число бойцов')
            if len(room.members)>=room.capacity:raise ValueError('Команда заполнена')
            room.members.append(member)
            room.ready.clear()  # A changed lineup requires fresh consent.
            self.membership[member] = identity
            return room

    def set_ready(self, member, ready):
        with self.lock:
            room = self.room(member)
            if room is None:raise ValueError('Вы не состоите в команде')
            if type(ready) is not bool:raise ValueError('Недопустимая готовность')
            if ready:room.ready.add(member)
            else:
                room.ready.discard(member)
                room.searching=False;room.bots=0
            return room

    def start(self, member):
        with self.lock:
            room = self.room(member)
            if room is None or room.captain!=member:raise ValueError('Поиск запускает только создатель команды')
            if room.searching:return room
            if set(room.members)!=room.ready:raise ValueError('Все участники должны подтвердить готовность')
            missing=room.capacity-len(room.members)
            if not room.members:raise ValueError('В команде нужен хотя бы один игрок')
            room.bots=missing;room.searching=True;room.queued_at=self.clock()
            return room

    def pairs(self):
        with self.lock:
            waiting=sorted((r for r in self.rooms.values() if r.searching), key=lambda r:(r.queued_at,r.identity))
            pairs=[];used=set()
            for first in waiting:
                if first.identity in used:continue
                candidates=[r for r in waiting if r.identity not in used and r is not first and
                            (r.mode,r.band,r.pool)==(first.mode,first.band,first.pool)]
                # Manual: opposing Team squads may differ in size. Prefer the
                # largest common squad, then FIFO; admission trims only this
                # battle's tickets. Teammates still join with equal squad sizes.
                other=min(candidates,key=lambda r:(-min(first.soldiers,r.soldiers),r.queued_at,r.identity)) if candidates else None
                if other:
                    used.update((first.identity,other.identity));pairs.append((first,other))
            return tuple(pairs)

    def consume(self, first, second):
        with self.lock:
            if first is second or any(self.rooms.get(r.identity) is not r or not r.searching for r in (first,second)):
                raise ValueError('Команды изменились во время подбора')
            for room in (first,second):
                del self.rooms[room.identity]
                for member in room.members:self.membership.pop(member,None)

    def leave(self, member, target=None):
        with self.lock:
            room=self.room(member)
            if room is None:return ()
            target=member if target is None else target
            if target!=member and room.captain!=member:raise ValueError('Исключать игроков может только создатель')
            if target not in room.members:raise ValueError('Игрок не состоит в вашей команде')
            affected=tuple(room.members)
            if target==room.captain:
                del self.rooms[room.identity]
                for player in room.members:self.membership.pop(player,None)
            else:
                room.members.remove(target);self.membership.pop(target,None)
                room.ready.clear();room.searching=False;room.bots=0
            return affected
