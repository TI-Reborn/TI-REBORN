"""One durable route for a consenting party; coordinates never come from peers."""
from contextlib import closing
import math
import secrets
import struct
import time

from .db_transaction import connect, transaction
from .cities import CITIES
from .locations import (LocationStore, MAP_SPEED, center, town_at, town_packets,
                        leave_town_packet, movement_packet, stop_packet)
from .protocol.world_bootstrap import encode_open_map_view, encode_restore_city_controls


class PartyTravel:
    def __init__(self, path, parties, contracts, *, clock=time.time):
        self.path, self.parties, self.contracts, self.clock = path, parties, contracts, clock
        self.locations = LocationStore(path, clock=clock)
        with transaction(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS travel_party_journeys (
                party_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL,
                tx INTEGER NOT NULL, ty INTEGER NOT NULL, started REAL NOT NULL,
                arrives REAL NOT NULL, nonce TEXT NOT NULL,
                town_id INTEGER, instance_id TEXT)''')

    def route(self, party_id):
        with closing(connect(self.path)) as db:
            return db.execute('SELECT x,y,tx,ty,started,arrives,nonce,town_id,instance_id '
                              'FROM travel_party_journeys WHERE party_id=?', (party_id,)).fetchone()

    def point(self, owner):
        party = self.parties.info(owner)
        route = self.route(party['id']) if party else None
        if not route:
            return self.locations.position(owner), None
        x, y, tx, ty, started, arrives = route[:6]
        fraction = min(1, max(0, (self.clock()-started)/(arrives-started)))
        return (x+(tx-x)*fraction, y+(ty-y)*fraction), route

    def travel(self, owner, packet, *, busy=False):
        if len(packet) != 9 or packet[0] != 0x1b:
            raise ValueError('Некорректные координаты маршрута')
        x, y = struct.unpack_from('<ii', packet, 1)
        if not (-512 <= x <= 511 and -512 <= y <= 511):
            raise ValueError('Цель находится за пределами карты')
        with transaction(self.path) as db:
            party = self.parties.info(owner)
            if not party or party['leader'] != owner:
                raise ValueError('Маршрутом группы управляет лидер')
            if busy or party['state'] not in ('city', 'travelling', 'at_target'):
                raise ValueError('Сначала завершите бой')
            if party['state'] == 'city':
                party = self.parties.validate_departure(party['id'], connection=db)
            # A private marker is resolved only against this party's instance.
            contract = self.contracts.active(party['id'])
            target = contract['target'] if contract else None
            bounds = target['bounds'] if target else ()
            private = bool(bounds and bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3])
            town = None if private else town_at(x, y)
            if town is not None and town not in CITIES:
                raise ValueError('Группа может войти в город или в цель своего контракта')
            if private:
                x, y = (bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2
            elif town is not None:
                x, y = center(town)
            (sx, sy), _ = self.point(owner)
            now = self.clock(); duration = math.hypot(x-sx, y-sy)/MAP_SPEED
            # No independently writable map_journeys projection: group route
            # is the sole source of truth, including on process restart.
            for member in party['members']:
                db.execute('DELETE FROM map_journeys WHERE account=?', (member['owner'],))
                self.locations._save(db, member['owner'], None, sx, sy)
            self.parties.change_state(party['id'], 'travelling', party['state'], connection=db)
            if contract and contract['state'] == 'accepted':
                self.contracts.transition(contract['id'], 'accepted', 'travelling')
            db.execute('INSERT OR REPLACE INTO travel_party_journeys VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (party['id'], sx, sy, x, y, now, now+max(duration, .000001),
                        secrets.token_hex(8), town, contract['id'] if private else None))
        self.arrive(owner)

    def arrive(self, owner):
        with transaction(self.path) as db:
            party = self.parties.info(owner)
            route = self.route(party['id']) if party else None
            if not route or self.clock() < route[5]:
                return False
            x, y, town, instance = route[2], route[3], route[7], route[8]
            for member in party['members']:
                self.locations._save(db, member['owner'], town, x, y)
            db.execute('DELETE FROM travel_party_journeys WHERE party_id=?', (party['id'],))
            if town is not None:
                db.execute('UPDATE travel_party_groups SET town_id=? WHERE id=?', (town, party['id']))
            state = 'city' if town is not None else 'at_target'
            self.parties.change_state(party['id'], state, 'travelling', connection=db)
            contract = self.contracts.active(party['id'])
            if instance and contract and contract['id'] == instance and contract['state'] == 'travelling':
                self.contracts.transition(instance, 'travelling', 'arrived')
            return True


class PartyLocations:
    """Session adapter preserving existing city gates and individual travel."""
    def __init__(self, base, travel):
        self.base, self.travel_service = base, travel
        self.path, self.clock = base.path, travel.clock
        self._sent = {}

    _position = staticmethod(LocationStore._position)
    _save = staticmethod(LocationStore._save)

    def current(self, owner):
        party = self.travel_service.parties.info(owner)
        return None if party and party['state'] != 'city' else self.base.current(owner)

    def position(self, owner):
        return tuple(round(v) for v in self.travel_service.point(owner)[0])

    def travelling(self, owner):
        party = self.travel_service.parties.info(owner)
        return bool(self.travel_service.route(party['id'])) if party else self.base.travelling(owner)

    def resume(self, owner, character_id):
        if not self.travel_service.parties.info(owner):
            return self.base.resume(owner, character_id)
        if self.current(owner) is not None:
            return ()
        point, route = self.travel_service.point(owner)
        x, y = map(round, point)
        party = self.travel_service.parties.info(owner)
        self._sent[owner] = (x, y, party['state'], route[6] if route else None)
        return (leave_town_packet(), encode_open_map_view(),
                movement_packet(character_id, x, y, destination=route[2:4])
                if route else stop_packet(character_id, x, y))

    def travel(self, owner, packet, character_id, *, busy=False):
        if not self.travel_service.parties.info(owner):
            return self.base.travel(owner, packet, character_id, busy=busy)
        self.travel_service.travel(owner, packet, busy=busy)
        return self.refresh(owner, character_id)

    def refresh(self, owner, character_id):
        party = self.travel_service.parties.info(owner)
        if not party:
            self._sent.pop(owner, None)
            return self.base.refresh(owner, character_id)
        self.travel_service.arrive(owner)
        party = self.travel_service.parties.info(owner)
        point, route = self.travel_service.point(owner)
        x, y = map(round, point)
        signature = (x, y, party['state'], route[6] if route else None)
        previous = self._sent.get(owner); self._sent[owner] = signature
        if previous == signature or previous is None and party['state'] == 'city':
            return ()
        if route:
            leaving = previous is None or previous[2] == 'city'
            return (*((leave_town_packet(), encode_open_map_view()) if leaving else ()),
                    movement_packet(character_id, x, y, destination=route[2:4]))
        town = self.current(owner)
        arrival = town_packets(town, self.path, clock=self.clock) if town is not None else ()
        if arrival:
            # Restore the native character/chat state before the original
            # F0/117 town-view command opens the city controls.
            arrival = (*arrival[:-1], encode_restore_city_controls(), arrival[-1])
        return (stop_packet(character_id, x, y),
                *arrival)
