"""Persistent world-map travel along roads using original1B/1D/1E.

Locations sit where the road-layout map (2026-10-29) draws them. A journey
follows the road polyline; the server sends one 1D per road turn and the
native client interpolates each straight leg. Speed36 at the user's request.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
import json
import math
import sqlite3
import struct
import time
from .protocol.system_message import encode_current_town, encode_open_town_view
from .protocol.town_info import diagnostic_town_info, encode_town_info
from .protocol.map_route import route_words
from .roads import ROADS, leg_index, path_length, point_along
from .world_layout import normalize_characters

from .cities import CITIES
TOWNS = {i:city.bounds for i,city in CITIES.items()}
TOWNS[9] = (-121, -449, -47, -317)
from .crystal_market import POLICY as MINING_POLICY
MINE_LOCATIONS={v['id']:v for v in MINING_POLICY['locations']}
TOWNS.update({i:tuple(v['bounds']) for i,v in MINE_LOCATIONS.items()})
SHOOTING_RANGE = 17
TOWNS[SHOOTING_RANGE] = (3, -179, 52, -85)
BASE_LOCATIONS={6:(-482,-341,-433,-245),11:(210,158,258,251),12:(334,168,382,265)}
TOWNS.update(BASE_LOCATIONS)
from .world_completion import location_bounds,location as world_location,policy as world_policy
TOWNS.update(location_bounds())
BASE_LOCATIONS.update({r['id']:tuple(r['bounds']) for r in world_policy()['locations']
                       if r['kind']=='base' and r['capture']})
MAP_SPEED = 36  # Original MyCharInfo1A u16 -> character+8, map units/second.
# The next turn leaves the server this early, so the client starts the new
# leg before it reaches the corner even with poll and network jitter.
TURN_LEAD = .2


def center(town):
    """Map point of a character inside the town: the end of the town's road."""
    point=ROADS.anchor(town)
    if point is None:raise ValueError(f'Location {town} has no road')
    return point


class Journey:
    """A timed drive along a polyline; position depends only on the clock."""
    def __init__(self,path,started,arrives):
        self.path=tuple(tuple(p) for p in path);self.started=started;self.arrives=arrives
        self.length=path_length(self.path)

    @classmethod
    def from_row(cls,x,y,tx,ty,started,arrives,path):
        return cls(json.loads(path) if path else ((x,y),(tx,ty)),started,arrives)

    @property
    def goal(self):return self.path[-1]

    def driven(self,now):
        if self.arrives<=self.started:return self.length
        return self.length*min(1,max(0,(now-self.started)/(self.arrives-self.started)))

    def point(self,now):return point_along(self.path,self.driven(now))

    def leg(self,now):
        """Index of the leg the client should drive now (with the turn lead)."""
        return leg_index(self.path,self.driven(now+TURN_LEAD))

    def movement(self,character_id,now,route=0):
        x,y=map(round,self.point(now))
        tx,ty=map(round,self.path[min(self.leg(now)+1,len(self.path)-1)])
        gx,gy=map(round,self.goal)
        return movement_packet(character_id,x,y,destination=(tx,ty),target=town_at(gx,gy) or 0,route=route)

    def announce(self,character_id,now):
        """Current turn plus the whole dashed route, one route word per 1D."""
        return tuple(self.movement(character_id,now,word) for word in route_words(self.path))


def nearest_city(x,y):
    """Closest enabled city center; mines and the shooting range are not cities."""
    return min((*CITIES,9),key=lambda town:((center(town)[0]-x)**2+(center(town)[1]-y)**2,town))


def movement_packet(character_id,x,y,*,destination=None,target=0,route=0):
    # False final bool preserves rendered floats and enables native interpolation.
    # The original reader discards both Z fields; the global-map patch keeps
    # them: a route word (tio.protocol.map_route, 0: none) and the journey's
    # final location (0: none) to outline it.
    tx,ty=destination if destination is not None else (x,y)
    return struct.pack('<BIiiIiiiB',0x1d,character_id,x,y,route,tx,ty,target,int(destination is None))


def stop_packet(character_id,x,y):
    return struct.pack('<BIiii',0x1e,character_id,x,y,0)


def leave_town_packet():
    # F0/97 ->7d2de6: clear current town(-1), close town menus, return to map.
    return struct.pack('<BII',0xf0,97,0)


def location_levels(town: int) -> tuple[int, int]:
    """Share the advertised world level band with location-based services."""
    if town in MINE_LOCATIONS:
        band = MINING_POLICY['bands'][MINE_LOCATIONS[town]['band']]
        return band[0], band[1]
    if town in CITIES:
        return CITIES[town].levels
    world = world_location(town)
    return tuple(world['levels']) if world is not None else (1, 20)


def town_packets(town,path=None,*,clock=time.time):
    world=world_location(town)
    levels = location_levels(town)
    from .world_completion import city_coefficients
    factors=city_coefficients(town,now=clock())
    # Original consumer labels: Influence, Experience, Profit; IEEE754 f32.
    bits=tuple(struct.unpack('<I',struct.pack('<f',float(Fraction(factors[k]))))[0]
               for k in ('influence','experience','profit'))
    info=replace(diagnostic_town_info(),town_id=town,
                 unknown_bytes=(*levels,0,0),unknown_float_bits=bits,
                 unknown_bools=(0,int(world['carry_items'] if world else True),0),final_bool=1)
    packet=encode_town_info(info)
    if path is not None and town in (*BASE_LOCATIONS,*MINE_LOCATIONS):
        from .territories import TerritoriesStore
        from server.territory_service import encode_zone_info
        store=TerritoriesStore(path,clock=clock)
        state=store.info(town)
        packet=encode_zone_info(replace(info,unknown_bytes=(*state['levels'],0,0)),state,now=int(clock()),path=path)
    return (packet,encode_current_town(town),encode_open_town_view())


def town_at(x,y):
    return next((i for i,(x1,y1,x2,y2) in TOWNS.items() if x1<=x<=x2 and y1<=y<=y2),None)


class LocationStore:
    def __init__(self,path,*,clock=time.time,roads=ROADS):
        self.path=path;self.clock=clock;self.roads=roads;self._sent={};self._coefficient_sent={}
        with closing(connect(path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS character_locations (account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            columns={r[1] for r in db.execute('PRAGMA table_info(character_locations)')}
            for column in ('x','y'):
                if column not in columns:db.execute('ALTER TABLE character_locations ADD COLUMN '+column+' REAL')
            db.execute('CREATE TABLE IF NOT EXISTS map_journeys (account TEXT PRIMARY KEY,x REAL NOT NULL,y REAL NOT NULL,tx INTEGER NOT NULL,ty INTEGER NOT NULL,started REAL NOT NULL,arrives REAL NOT NULL)')
            if 'path' not in {r[1] for r in db.execute('PRAGMA table_info(map_journeys)')}:
                db.execute('ALTER TABLE map_journeys ADD COLUMN path TEXT')
            normalize_characters(db,{town:center(town) for town in TOWNS})

    def current(self,account,*,connection=None):
        if connection is not None:
            row=connection.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
            return 3 if row is None else row[0] if row[0] in TOWNS else None
        with closing(connect(self.path)) as db:
            return self.current(account,connection=db)

    @staticmethod
    def _position(db,account,now):
        """Point and the active Journey (or None) of an account."""
        route=db.execute('SELECT x,y,tx,ty,started,arrives,path FROM map_journeys WHERE account=?',(account,)).fetchone()
        if route:
            journey=Journey.from_row(*route)
            return journey.point(now),journey
        row=db.execute('SELECT town_id,x,y FROM character_locations WHERE account=?',(account,)).fetchone()
        if row is None:return center(3),None
        if row[1] is None or row[2] is None:return center(row[0] if row[0] in TOWNS else 3),None
        return (row[1],row[2]),None

    def position(self,account):
        with closing(connect(self.path)) as db:
            return tuple(round(v) for v in self._position(db,account,self.clock())[0])

    def travelling(self,account,*,connection=None):
        if connection is not None:
            return connection.execute('SELECT 1 FROM map_journeys WHERE account=?',(account,)).fetchone() is not None
        with closing(connect(self.path)) as db:
            return self.travelling(account,connection=db)

    @staticmethod
    def _save(db,account,town,x,y):
        db.execute('INSERT INTO character_locations VALUES (?,?,?,?) ON CONFLICT(account) DO UPDATE SET town_id=excluded.town_id,x=excluded.x,y=excluded.y',
                   (account,town if town is not None else -1,x,y))

    def resume(self,account,character_id):
        now=self.clock()
        with closing(connect(self.path)) as db:
            point,journey=self._position(db,account,now)
        if self.current(account) is not None:return ()
        if journey is None:
            self._sent.pop(account,None)
            return (leave_town_packet(),stop_packet(character_id,*map(round,point)))
        self._sent[account]=(journey.started,journey.leg(now))
        return (leave_town_packet(),*journey.announce(character_id,now))

    def travel(self,account,packet,character_id,*,busy=False):
        if len(packet)!=9 or packet[0]!=0x1b:raise ValueError('Expected map coordinates1B')
        if busy:raise ValueError('Leave battle or matchmaking before travelling')
        if not account:raise ValueError('Account required')
        x,y=struct.unpack_from('<ii',packet,1)
        if not (-512<=x<=511 and -512<=y<=511):raise ValueError('Destination outside world map')
        town=town_at(x,y)
        if town is not None:x,y=center(town)
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            from .world_completion import require_travel
            require_travel(db,account,town)
            start,route=self._position(db,account,now)
            from .world_encounters import accumulate
            accumulate(db,account,route,now)
            previous=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
            leaving=previous is None or previous[0] in TOWNS
            path=self.roads.plan(start,(x,y))
            journey=Journey(path,now,now+path_length(path)/MAP_SPEED)
            db.execute('DELETE FROM map_journeys WHERE account=?',(account,))
            if journey.length<1e-9:
                self._save(db,account,town,x,y)
            else:
                self._save(db,account,None,*start)
                db.execute('INSERT INTO map_journeys VALUES (?,?,?,?,?,?,?,?)',
                           (account,*start,x,y,now,journey.arrives,json.dumps(journey.path)))
        if journey.length<1e-9:
            self._sent.pop(account,None)
            return (stop_packet(character_id,x,y),*(town_packets(town,self.path,clock=self.clock) if town is not None else ()))
        self._sent[account]=(journey.started,journey.leg(now))
        return (*( (leave_town_packet(),) if leaving else ()),*journey.announce(character_id,now))

    def refresh(self,account,character_id):
        """Send each road turn once; arrival is the only travel DB write.

        Absolute timestamps resume travel after disconnect; access to city
        services changes only on arrival.
        """
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            point,journey=self._position(db,account,now)
            if journey is None:
                row=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
                town=row[0] if row else 3
                if town not in CITIES:return ()
                from .world_completion import city_coefficients
                signature=(town,city_coefficients(town,now=now)['epoch'])
                previous=self._coefficient_sent.get(account)
                self._coefficient_sent[account]=signature
                return () if previous is None or previous==signature else (town_packets(town,clock=lambda:now)[0],)
            if now>=journey.arrives:
                from .world_encounters import accumulate
                x,y=map(round,journey.goal);town=town_at(x,y)
                from .world_completion import require_travel
                # A pre-extension map journey may end inside Prison's rectangle.
                # Finish it on the map, without opening the restricted town or
                # inventing a sentence; new requests cannot target Prison.
                if town==10:town=None
                require_travel(db,account,town)
                accumulate(db,account,journey,now)
                self._save(db,account,town,x,y)
                db.execute('DELETE FROM map_journeys WHERE account=?',(account,))
                self._sent.pop(account,None)
        if now>=journey.arrives:
            # Territory projection opens its own transaction. Release the
            # arrival writer before reading/synchronizing that shared state.
            return (stop_packet(character_id,x,y),*(town_packets(town,self.path,clock=self.clock) if town is not None else ()))
        signature=(journey.started,journey.leg(now))
        if self._sent.get(account)==signature:return ()
        self._sent[account]=signature
        return (journey.movement(character_id,now),)
