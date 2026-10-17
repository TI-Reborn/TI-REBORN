"""In-memory waiting-room lifecycle. Wire handlers are deliberately separate.

Rooms last for the server process. Stakes are not charged here; wagered games
require a separate settlement implementation before wire integration.
"""
from dataclasses import dataclass, replace
from threading import RLock
from .protocol.arena import ArenaCreateRequest, encode_create_request


@dataclass(frozen=True)
class WaitingRoom:
    room_id: int
    owner_id: int
    request: ArenaCreateRequest
    members: tuple[int, ...]


class ArenaRooms:
    def __init__(self):
        self._lock = RLock()
        self._next_id = 1
        self._rooms = {}
        self._membership = {}

    def create(self, character_id: int, request: ArenaCreateRequest) -> WaitingRoom:
        encode_create_request(request)  # validate every wire-sized value
        if not 0 < character_id <= 0xffffffff:
            raise ValueError('Invalid character ID')
        if not 1 <= request.players_count <= 8:
            raise ValueError('Room capacity must fit the eight client slots')
        if request.stake:
            raise ValueError('Wager settlement is not implemented')
        with self._lock:
            existing = self._membership.get(character_id)
            if existing is not None:
                room = self._rooms[existing]
                if room.owner_id == character_id and room.request == request:
                    return room  # duplicate creation must not make another room
                raise ValueError('Character already belongs to a room')
            room = WaitingRoom(self._next_id, character_id, request, (character_id,))
            self._next_id += 1
            self._rooms[room.room_id] = room
            self._membership[character_id] = room.room_id
            return room

    def join(self, room_id: int, character_id: int) -> WaitingRoom:
        if not 0 < character_id <= 0xffffffff:
            raise ValueError('Invalid character ID')
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                raise ValueError('Room does not exist')
            existing = self._membership.get(character_id)
            if existing == room_id:
                return room
            if existing is not None:
                raise ValueError('Character already belongs to a room')
            if len(room.members) >= room.request.players_count:
                raise ValueError('Room is full')
            room = replace(room, members=room.members + (character_id,))
            self._rooms[room_id] = room
            self._membership[character_id] = room_id
            return room

    def leave(self, character_id: int) -> tuple[int, ...]:
        """Remove a member; owner's departure closes the room and releases all.

        This is local server policy, not a recovered original owner-transfer rule.
        Returned IDs identify the participants needing a wire update.
        """
        with self._lock:
            room_id = self._membership.pop(character_id, None)
            if room_id is None:
                return ()
            room = self._rooms[room_id]
            if room.owner_id == character_id:
                del self._rooms[room_id]
                for member in room.members:
                    self._membership.pop(member, None)
            else:
                self._rooms[room_id] = replace(room, members=tuple(m for m in room.members if m != character_id))
            return room.members

    def snapshot(self) -> tuple[WaitingRoom, ...]:
        with self._lock:
            return tuple(self._rooms.values())
