"""Persistent world-map travel using original1B/1D/1E and native interpolation.

City bounds come from base/towns.cfg. Speed12 doubles the prior speed6 again
at the user's request; historical server speed is not recovered.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
import math
import sqlite3
import struct
import time
from .protocol.system_message import encode_current_town, encode_open_town_view
from .protocol.town_info import diagnostic_town_info, encode_town_info

from .cities import CITIES
TOWNS = {i:city.bounds for i,city in CITIES.items()}
TOWNS[9] = (-90, -460, -64, -434)
from .crystal_market import POLICY as MINING_POLICY
MINE_LOCATIONS={v['id']:v for v in MINING_POLICY['locations']}
TOWNS.update({i:tuple(v['bounds']) for i,v in MINE_LOCATIONS.items()})
SHOOTING_RANGE = 17
TOWNS[SHOOTING_RANGE] = (-25, -268, 1, -242)
BASE_LOCATIONS={6:(-434,-370,-414,-350),11:(63,-3,83,18),12:(241,-175,261,-155)}
TOWNS.update(BASE_LOCATIONS)
from .world_completion import location_bounds,location as world_location,policy as world_policy
TOWNS.update(location_bounds())
BASE_LOCATIONS.update({r['id']:tuple(r['bounds']) for r in world_policy()['locations']
                       if r['kind']=='base' and r['capture']})
MAP_SPEED = 12  # Original MyCharInfo1A u16 -> character+8, map units/second.


def center(town):
    x1,y1,x2,y2=TOWNS[town]
    return ((x1+x2)//2,(y1+y2)//2)


def nearest_city(x,y):
    """Closest enabled city center; mines and the shooting range are not cities."""
    return min((*CITIES,9),key=lambda town:((center(town)[0]-x)**2+(center(town)[1]-y)**2,town))


def movement_packet(character_id,x,y,*,destination=None):
    # False final bool preserves rendered floats and enables native interpolation.
    tx,ty=destination if destination is not None else (x,y)
    return struct.pack('<BIiiiiiiB',0x1d,character_id,x,y,0,tx,ty,0,int(destination is None))


def stop_packet(character_id,x,y):
    return struct.pack('<BIiii',0x1e,character_id,x,y,0)


def leave_town_packet():
    # F0/97 ->7d2de6: clear current town(-1), close town menus, return to map.
    return struct.pack('<BII',0xf0,97,0)


def town_packets(town,path=None,*,clock=time.time):
    world=world_location(town)
    levels=MINING_POLICY['bands'][MINE_LOCATIONS[town]['band']][:2] if town in MINE_LOCATIONS else (CITIES[town].levels if town in CITIES else tuple(world['levels']) if world is not None else (1,20))
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
    def __init__(self,path,*,clock=time.time):
        self.path=path;self.clock=clock;self._sent={};self._coefficient_sent={}
        with closing(connect(path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS character_locations (account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            columns={r[1] for r in db.execute('PRAGMA table_info(character_locations)')}
            for column in ('x','y'):
                if column not in columns:db.execute('ALTER TABLE character_locations ADD COLUMN '+column+' REAL')
            db.execute('CREATE TABLE IF NOT EXISTS map_journeys (account TEXT PRIMARY KEY,x REAL NOT NULL,y REAL NOT NULL,tx INTEGER NOT NULL,ty INTEGER NOT NULL,started REAL NOT NULL,arrives REAL NOT NULL)')

    def current(self,account,*,connection=None):
        if connection is not None:
            row=connection.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
            return 3 if row is None else row[0] if row[0] in TOWNS else None
        with closing(connect(self.path)) as db:
            return self.current(account,connection=db)

    @staticmethod
    def _position(db,account,now):
        route=db.execute('SELECT x,y,tx,ty,started,arrives FROM map_journeys WHERE account=?',(account,)).fetchone()
        if route:
            x,y,tx,ty,started,arrives=route
            fraction=min(1,max(0,(now-started)/(arrives-started)))
            return (x+(tx-x)*fraction,y+(ty-y)*fraction),route
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
        with closing(connect(self.path)) as db:
            point,route=self._position(db,account,self.clock())
        if self.current(account) is not None:return ()
        x,y=map(round,point)
        self._sent[account]=(x,y)
        return (leave_town_packet(),movement_packet(character_id,x,y,destination=route[2:4])) if route else (leave_town_packet(),stop_packet(character_id,x,y))

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
            (sx,sy),route=self._position(db,account,now)
            from .world_encounters import accumulate
            accumulate(db,account,route,now)
            previous=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
            leaving=previous is None or previous[0] in TOWNS
            duration=math.hypot(x-sx,y-sy)/MAP_SPEED
            db.execute('DELETE FROM map_journeys WHERE account=?',(account,))
            if duration<1e-9:
                self._save(db,account,town,x,y)
            else:
                self._save(db,account,None,sx,sy)
                db.execute('INSERT INTO map_journeys VALUES (?,?,?,?,?,?,?)',(account,sx,sy,x,y,now,now+duration))
        if duration<1e-9:
            return (stop_packet(character_id,x,y),*(town_packets(town,self.path,clock=self.clock) if town is not None else ()))
        start=(round(sx),round(sy));self._sent[account]=start
        return (*( (leave_town_packet(),) if leaving else ()),movement_packet(character_id,*start,destination=(x,y)))

    def refresh(self,account,character_id):
        """Emit sparse position corrections; the original renderer smooths them.

        Only arrival/rerouting writes the DB. Absolute timestamps resume travel
        after disconnect; access to city services changes only on arrival.
        """
        now=self.clock()
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            point,route=self._position(db,account,now)
            if route is None:
                row=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
                town=row[0] if row else 3
                if town not in CITIES:return ()
                from .world_completion import city_coefficients
                signature=(town,city_coefficients(town,now=now)['epoch'])
                previous=self._coefficient_sent.get(account)
                self._coefficient_sent[account]=signature
                return () if previous is None or previous==signature else (town_packets(town,clock=lambda:now)[0],)
            x,y=map(round,point)
            if now>=route[5]:
                from .world_encounters import accumulate
                x,y=route[2:4];town=town_at(x,y)
                from .world_completion import require_travel
                # A pre-extension map journey may end inside Prison's rectangle.
                # Finish it on the map, without opening the restricted town or
                # inventing a sentence; new requests cannot target Prison.
                if town==10:town=None
                require_travel(db,account,town)
                accumulate(db,account,route,now)
                self._save(db,account,town,x,y)
                db.execute('DELETE FROM map_journeys WHERE account=?',(account,))
                self._sent.pop(account,None)
        if now>=route[5]:
            # Territory projection opens its own transaction. Release the
            # arrival writer before reading/synchronizing that shared state.
            return (stop_packet(character_id,x,y),*(town_packets(town,self.path,clock=self.clock) if town is not None else ()))
        if self._sent.get(account)==(x,y):return ()
        self._sent[account]=(x,y)
        return (movement_packet(character_id,x,y,destination=route[2:4]),)
