"""Distance-based, account-owned world encounters on the authoritative server."""
from contextlib import closing
from pathlib import Path
import json, logging, random, time
from .db_transaction import connect, transaction

POLICY=json.loads((Path(__file__).resolve().parents[1]/'config/world_encounters.json').read_text(encoding='utf-8'))
LOG=logging.getLogger('tio.server')


def reward(report,result,*,escaped=False):
    if report.get('kind')!='infected_dogs' or set(report) not in ({'kind','level','dogs','credits'},{'kind','level','dogs','credits','loot_version'}):
        raise ValueError('Invalid encounter reward report')
    if 'loot_version' in report and (type(report['loot_version']) is not int or report['loot_version']!=1):raise ValueError('Invalid encounter loot version')
    if not all(type(report[k]) is int for k in ('level','dogs','credits')) or not (1<=report['level']<=20 and 2<=report['dogs']<=4 and 0<=report['credits']<=10000):
        raise ValueError('Invalid encounter reward bounds')
    gross=report['credits'] if result==1 and not escaped else 0
    return gross,json.dumps(dict(version=1,encounter=report,outcome=result,escaped=escaped),sort_keys=True)


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS world_encounter_state (
        account TEXT PRIMARY KEY, distance REAL NOT NULL DEFAULT 0,
        last_event REAL, route_start REAL, progress REAL NOT NULL DEFAULT 0)''')
    db.execute('''CREATE TABLE IF NOT EXISTS world_encounter_audit (
        match_id TEXT PRIMARY KEY, account TEXT NOT NULL, created REAL NOT NULL,
        x INTEGER NOT NULL,y INTEGER NOT NULL,level INTEGER NOT NULL,dogs INTEGER NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS world_encounter_biomes (account TEXT PRIMARY KEY,biome TEXT NOT NULL)')
    db.execute('''CREATE TABLE IF NOT EXISTS encounter_loot_awards (
        match_id TEXT NOT NULL,account TEXT NOT NULL,template_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,destination TEXT NOT NULL,PRIMARY KEY(match_id,account,template_id))''')


def return_defeated(db,account,match_id,health):
    """Move a dead encounter squad within its once-only settlement transaction."""
    if not health or any(hp>0 for hp in health.values()):return
    point=db.execute('SELECT x,y FROM world_encounter_audit WHERE match_id=? AND account=?',(match_id,account)).fetchone()
    if point is None:raise ValueError('Defeated encounter position missing')
    from .locations import LocationStore,nearest_city,center
    town=nearest_city(*point)
    LocationStore._save(db,account,town,*center(town))
    db.execute('DELETE FROM map_journeys WHERE account=?',(account,))


def accumulate(db,account,journey,now):
    """Consume actual elapsed road distance once, including before rerouting."""
    if journey is None:return
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='world_encounter_state'").fetchone():return
    db.execute('INSERT OR IGNORE INTO world_encounter_state(account) VALUES (?)',(account,))
    start,previous=db.execute('SELECT route_start,progress FROM world_encounter_state WHERE account=?',(account,)).fetchone()
    began=journey.started;progress=journey.driven(now)
    delta=max(0,progress-(previous if start==began else 0))
    db.execute('UPDATE world_encounter_state SET distance=distance+?,route_start=?,progress=? WHERE account=?',
               (delta,began,progress,account))


class EncounterService:
    def __init__(self,path,arena,locations,*,clock=time.time,rng=None,policy=None):
        self.path,self.arena,self.locations=path,arena,locations
        self.clock=clock;self.rng=rng or random.SystemRandom();self.policy=dict(POLICY if policy is None else policy)
        self.next_check=0
        with closing(connect(path)) as db,db:schema(db)

    def tick(self,account,character,name,*,busy=False):
        now=self.clock()
        if not self.policy['enabled'] or busy or now<self.next_check:return None
        self.next_check=now+1
        if any(character in room.members for room in self.arena.rooms.snapshot()):return None
        if character in self.arena._completed and character in self.arena._return_maps and character not in self.arena._map_returned:return None
        # A checkpoint, paused journey and encounter audit are committed together.
        manager=getattr(self.arena,'_durable',None)
        from contextlib import nullcontext
        with (manager.unit() if manager else transaction(self.path)):
            with closing(connect(self.path)) as db:
                point,route=self.locations._position(db,account,now)
                if route is None:return None
                accumulate(db,account,route,now)
                distance,last=db.execute('SELECT distance,last_event FROM world_encounter_state WHERE account=?',(account,)).fetchone()
                step=self.policy['distance_per_roll'];rolls=int(distance//step)
                if rolls<1:return None
                db.execute('UPDATE world_encounter_state SET distance=? WHERE account=?',(distance%step,account))
                from .locations import TOWNS
                margin=self.policy['safe_margin'];x,y=map(round,point)
                if any(a-margin<=x<=c+margin and b-margin<=y<=d+margin for a,b,c,d in TOWNS.values()):return None
                if last is not None and now-last<self.policy['cooldown_seconds']:return None
                if self.rng.random()>=1-(1-self.policy['chance_per_roll'])**rolls:return None
                from .owned_pets import OwnedPetStore
                from .matchmaking import SurvivalQueue
                try:ticket=SurvivalQueue().join(character,OwnedPetStore(self.path).list(account))
                except ValueError:return None  # No living selected squad: travel remains available.
                from .abilities import AbilityCatalog,AbilityLevel
                source=json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
                catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
                from tools.encounter_scene import prepare_encounter
                previous=db.execute('SELECT biome FROM world_encounter_biomes WHERE account=?',(account,)).fetchone()
                biomes=[b for b in self.policy['biomes'] if previous is None or b!=previous[0]]
                seed=self.rng.randrange(2**63);biome=biomes[seed%len(biomes)]
                prepared=prepare_encounter(self.path,account,ticket,catalog,seed=seed,policy=self.policy,biome=biome)
                prepared.field.return_position=(x,y)
                room,replies=self.arena.start_survival(character,name,prepared)
                self.locations._save(db,account,None,x,y)
                db.execute('DELETE FROM map_journeys WHERE account=?',(account,))
                db.execute('UPDATE world_encounter_state SET distance=0,last_event=?,route_start=NULL,progress=0 WHERE account=?',(now,account))
                match=self.arena._match_ids[room.room_id]
                encounter=prepared.field.encounter_report
                db.execute('INSERT INTO world_encounter_audit VALUES (?,?,?,?,?,?,?)',(match,account,now,x,y,encounter['level'],encounter['dogs']))
                db.execute('INSERT INTO world_encounter_biomes VALUES (?,?) ON CONFLICT(account) DO UPDATE SET biome=excluded.biome',(account,biome))
                from .locations import stop_packet
                LOG.info('world_encounter_started account=%s match=%s x=%d y=%d dogs=%d level=%d',account,match,x,y,encounter['dogs'],encounter['level'])
                return (room,prepared),(stop_packet(character,x,y),*replies)
