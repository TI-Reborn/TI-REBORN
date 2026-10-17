"""Phase8 native TLS QA using the retained ordinary phase5/6 pair.

No provisioning, administrative saves, deployment, payments, clock changes or
synthetic TownInfo broadcasts. Real travel may encounter native PvE; leave
normally and retry within a fixed real-time bound. Run after root releases the QA slot
and the exact phase7/8 deployment proofs exist. No graphical-client claim.
"""
import argparse
from datetime import datetime,timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shlex
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_hosted_clan_completion import deployment_hashes,census,zones,ERROR_PREFIX,native_error
from tools.verify_hosted_economy_completion import EconomyNetwork,status,one
from tools.verify_hosted_stage7 import Stage7Fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP,require
from tools.verify_game_tls_hosted import tls_context
from tio.protocol.item_action import ItemAction,encode_item_action
from tio.protocol.player_top100 import SORTS,encode_request,decode_ratings
from tio.protocol.town_info import decode_town_info
from tio.protocol.system_message import decode_current_town

TRAVEL_SECONDS=155
MAX_TRAVEL_SECONDS=180
MAX_ROAD_ENCOUNTERS=3
RANK_FIELDS=('0x8c4bbc','0x8c4bd0','0x8c4be3','0x8c4bf6')
PROTECTED_TABLES=('battle_rewards','player_battle_statistics','experience_battle_audit','rank_battle_audit','soldier_ratings')


WORLD_STATE=OWNERSHIP+r'''
import hashlib,time
from dataclasses import replace
from tio.locations import TOWNS,MAP_SPEED
from tio.world_completion import city_coefficients,policy
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.ranks import project,rank_id
from tio.weapon_proficiency import ProficiencyRules,SAVED,BASE,CAPS,number
from tio.passive_stats import project_saved_pet
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 states=[]
 def rows(table,account):
  if table not in tables:return []
  fields=[r[1] for r in db.execute('PRAGMA table_info('+table+')')]
  return [dict(zip(fields,r)) for r in db.execute('SELECT * FROM '+table+' WHERE account=?',(account,))]
 def digest(table,account):
  values=sorted(map(repr,db.execute('SELECT * FROM '+table+' WHERE account=?',(account,)))) if table in tables else []
  return dict(rows=len(values),sha256=hashlib.sha256(json.dumps(values).encode()).hexdigest())
 for account in names:
  point=db.execute('SELECT town_id,x,y FROM character_locations WHERE account=?',(account,)).fetchone()
  route=db.execute('SELECT x,y,tx,ty,started,arrives FROM map_journeys WHERE account=?',(account,)).fetchone()
  matches=[r[0] for r in db.execute('SELECT match_id FROM battle_checkpoint_members WHERE account=?',(account,))] if 'battle_checkpoint_members' in tables else []
  audit=[dict(match=r[0],level=r[1],dogs=r[2]) for r in db.execute('SELECT match_id,level,dogs FROM world_encounter_audit WHERE account=? ORDER BY created',(account,))] if 'world_encounter_audit' in tables else []
  hp=[]
  ranks=rows('soldier_ranks',account)
  rank_states={r['pet_id']:(r['points'],r['debt']) for r in ranks}
  commander=min(rank_states) if rank_states else None
  for identity,human,raw in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)):
   pet=decode_pet_info(raw,human_equipment=bool(human));f=pet.fields
   stable=encode_pet_info(replace(pet,fields={**f,'0x8c4ab1':0}))
   escaped=encode_pet_info(replace(pet,fields={**f,**{key:0 for key in ('0x8c4ab1','0x8c4bbc','0x8c4bd0','0x8c4be3','0x8c4bf6')}}))
   diagnostic_legacy=all(number(f[key])==10 for key in SAVED) and all(f[key]==0 for key in CAPS)
   normalized=ProficiencyRules().normalize(raw,bool(human)) if diagnostic_legacy else raw
   normalized_pet=decode_pet_info(normalized,human_equipment=bool(human))
   normalized_escape=encode_pet_info(replace(normalized_pet,fields={**normalized_pet.fields,**{key:0 for key in ('0x8c4ab1','0x8c4bbc','0x8c4bd0','0x8c4be3','0x8c4bf6')}}))
   city=decode_pet_info(project_saved_pet(db,account,identity,raw,bool(human)),human_equipment=bool(human)).fields
   projection_ok=identity in rank_states and raw==project(raw,bool(human),rank_states[identity][0],commander_rank=rank_id(rank_states[commander][0]),debt=rank_states[identity][1])
   hp.append(dict(id=identity,current=f['0x8c4ab1'],maximum=f['0x8c4a07'],immutable_profile_sha256=hashlib.sha256(stable).hexdigest(),escape_profile_sha256=hashlib.sha256(escaped).hexdigest(),rank_projection_valid=projection_ok,diagnostic_legacy=diagnostic_legacy,raw_profile_sha256=hashlib.sha256(raw).hexdigest(),normalized_initial_expected_pkt_sha256=hashlib.sha256(normalized).hexdigest(),normalized_initial_expected_escape_sha256=hashlib.sha256(normalized_escape).hexdigest(),native_city_proficiency_vector=[city[key] for key in (*SAVED,*BASE,*CAPS)]))
  protected_tables=('battle_rewards','player_battle_statistics','experience_battle_audit','rank_battle_audit','soldier_ratings')
  states.append(dict(town=point[0] if point else 3,point=list(point) if point else None,route=list(route) if route else None,matches=matches,encounters=audit,health=hp,ranks=ranks,receipts={t:rows(t,account) for t in protected_tables},protected={t:digest(t,account) for t in protected_tables}))
 foreign={}
 for table in ('character_locations','map_journeys','world_encounter_state','world_encounter_audit','world_encounter_biomes'):
  if table not in tables:continue
  rows=sorted(repr(r) for r in db.execute('SELECT * FROM '+table+' WHERE account NOT IN (?,?)',names))
  foreign[table]=dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
 now=time.time();p=policy()
 rates={str(t):[city_coefficients(t,now=now-1),city_coefficients(t,now=now),city_coefficients(t,now=now+1)] for t in (2,3,4,5,8,18)}
 print(json.dumps(dict(states=states,foreign=foreign,centers={str(t):[(b[0]+b[2])//2,(b[1]+b[3])//2] for t,b in TOWNS.items()},rates=rates,utc=now,speed=MAP_SPEED,locations=p['locations'],encounters_enabled=json.loads(pathlib.Path('config/world_encounters.json').read_text())['enabled'],proficiency_policy_sha256=hashlib.sha256(pathlib.Path('config/weapon_proficiency.json').read_bytes()).hexdigest())))
'''


def world_state(fixture,*,timeout=None):
    if timeout is None:return fixture.remote(WORLD_STATE,fixture.ownership_payload())
    require(0<timeout<=10,'Bounded read-only travel observation required')
    command='cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(WORLD_STATE)
    result=subprocess.run(['ssh','-i',fixture.key,'-o','BatchMode=yes','-o','ConnectTimeout=5','root@'+fixture.host,command],input=json.dumps(fixture.ownership_payload()),capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    require(result.returncode==0,'Bounded read-only world observation failed')
    return json.loads(result.stdout)


def bounded_native(network,deadline,operation,*args):
    """Bound packet reads as well as socket waits, restoring original transport."""
    originals=[]
    try:
        for peer in network.peers.values():
            if not hasattr(peer,'receive'):continue  # Offline fake, never a socket.
            original=peer.receive;transport=peer.sock;raw=getattr(transport,'raw',transport)
            timeout=raw.gettimeout();originals.append((peer,original,raw,timeout))
            raw.settimeout(min(5,max(.001,deadline-time.monotonic()),timeout if timeout is not None else 5))
            def receive(original=original,raw=raw,timeout=timeout):
                remaining=deadline-time.monotonic();require(remaining>0,'Ordinary native travel read bound exhausted')
                raw.settimeout(min(remaining,5,timeout if timeout is not None else 5));return original()
            peer.receive=receive
        require(time.monotonic()<deadline,'Ordinary native travel operation bound exhausted')
        return operation(*args)
    finally:
        for peer,original,raw,timeout in originals:peer.receive=original;raw.settimeout(timeout)


def pin_world_release(phase8,hashes):
    """Join hosted source parity to the independently executed native model."""
    folder=ROOT/'reports/gameplay-completion/stage8-world/client'
    validation=json.loads((folder/'catalog-validation.json').read_text(encoding='utf8'))
    release=json.loads((folder/'release.json').read_text(encoding='utf8'))
    deployed=json.loads(Path(phase8).read_text(encoding='utf8'))
    expected=validation['world_client_release']
    require(validation.get('passed') is True and release.get('passed') is True,'Reviewed native catalogue release required')
    require(release.get('world_client_release')==expected and deployed.get('world_client_release')==expected,'World deployment/native catalogue release chain differs')
    require(hashes.get('config/world_completion.json')==expected['policy_sha256'] and hashes.get('evidence/zones_diagnostic.xml')==expected['runtime_sha256'],'Hosted world policy/XML differs from native proof')
    require(hashlib.sha256((folder/'native-proof.json').read_bytes()).hexdigest()==expected['native_proof_sha256'],'Executed original reader/consumer evidence changed')
    return expected


def travel_request(point):
    require(isinstance(point,(tuple,list)) and len(point)==2 and all(type(n) is int and -512<=n<=511 for n in point),'Native destination outside verified map')
    return struct.pack('<Bii',0x1b,*point)


def town_observation(packet,rates):
    value=decode_town_info(packet)
    require(value.town_id in (3,4,18),'Observe only actual visited ordinary towns')
    require(1<=value.unknown_bytes[0]<=value.unknown_bytes[1]<=20 and value.final_bool==1,'Native TownInfo levels/visibility differ')
    require(all(math.isfinite(struct.unpack('<f',struct.pack('<I',n))[0]) for n in value.unknown_float_bits),'Nonfinite native coefficients')
    candidates=rates[str(value.town_id)]
    match=next((r for r in candidates if tuple(struct.unpack('<I',struct.pack('<f',float(Fraction(r[k]))))[0] for k in ('influence','experience','profit'))==value.unknown_float_bits),None)
    require(match is not None,'Real UTC native influence/experience/profit differs')
    require(value.unknown_bools==(0,0 if value.town_id==4 else 1,0),'Native drop/dragin/quitzone differs')
    if value.town_id==4:require(value.unknown_bytes[:2]==(4,20),'Outpost battle LV gate differs')
    return dict(town=value.town_id,levels=list(value.unknown_bytes[:2]),booleans=dict(zip(('drop','dragin','quitzone'),value.unknown_bools)),float_bits=list(value.unknown_float_bits),real_utc_coefficients=match,sha256=hashlib.sha256(packet).hexdigest())


def added_rows(before,after,keys):
    old={tuple(r[k] for k in keys):r for r in before};new={tuple(r[k] for k in keys):r for r in after}
    require(len(old)==len(before) and len(new)==len(after),'Duplicate ordinary escape receipt')
    require(all(new.get(k)==v for k,v in old.items()),'Existing ordinary receipt changed or disappeared')
    return [v for k,v in new.items() if k not in old]


def unchanged_foreign_rows(before,after):
    """A newly initialized empty schema key is not a foreign player mutation."""
    require(all(after.get(table)==value for table,value in before.items()),'Foreign owner rows changed or disappeared')
    added=sorted(after.keys()-before.keys());empty=dict(rows=0,sha256=hashlib.sha256(json.dumps([]).encode()).hexdigest())
    require(all(after[table]==empty for table in added),'New table contains changed foreign owner rows')
    return added


def escape_receipts(initial,final,report):
    """Authorize only newly audited, actually requested, zero-reward escapes."""
    authorized=[]
    for index,(a,b) in enumerate(zip(initial['states'],final['states'])):
        audits=added_rows(a['encounters'],b['encounters'],('match',));ids={r['match'] for r in audits}
        requested={match for event in report.get('road_encounters',()) if event['account']==index and event.get('native_escape_requests',0)>0 for match in event['match_ids']}
        require(ids<=requested,'Road settlement has no observed native escape request')
        additions={table:added_rows(a['receipts'][table],b['receipts'][table],('pet_id',) if table=='soldier_ratings' else ('match_id','pet_id') if table in ('rank_battle_audit','experience_battle_audit') else ('match_id',)) for table in PROTECTED_TABLES}
        require({r['match_id'] for r in additions['battle_rewards']}==ids,'Road audit and actual reward receipt differ')
        for row in additions['battle_rewards']:
            calculation=json.loads(row['calculation']);audit=next(r for r in audits if r['match']==row['match_id'])
            encounter=calculation.get('encounter',{})
            require(row['result']==0 and row['credits']==row['gross']==row['rental_tax']==0 and calculation.get('outcome')==0 and calculation.get('escaped') is True,'Ordinary escape received reward or different outcome')
            require(encounter.get('kind')=='infected_dogs' and encounter.get('level')==audit['level'] and encounter.get('dogs')==audit['dogs'],'Escape receipt belongs to another encounter')
        for table in ('player_battle_statistics','experience_battle_audit','rank_battle_audit'):
            require(all(r['match_id'] in ids for r in additions[table]),'Unrelated personal progression receipt appeared')
        for row in additions['player_battle_statistics']:
            require(row['result']==0 and row['kills']==row['damage_dealt']==0 and 0<=row['deaths']<=len(a['health']) and row['damage_received']>=0,'Escape contains offensive battle statistics')
        for row in additions['experience_battle_audit']:
            require(row['gain']==0 and row['xp_before']==row['xp_after'] and row['level_before']==row['level_after'],'Escape granted experience')
        old_ranks={r['pet_id']:r for r in a['ranks']};new_ranks={r['pet_id']:r for r in b['ranks']}
        require(old_ranks.keys()==new_ranks.keys(),'Escape changed rank roster')
        cursor={identity:r['points'] for identity,r in old_ranks.items()}
        pending=list(additions['rank_battle_audit'])
        while pending:
            row=next((r for r in pending if r['pet_id'] in cursor and r['before_points']==cursor[r['pet_id']]),None)
            require(row is not None,'Escape rank audit does not follow saved points')
            event=next(r for r in report['road_encounters'] if r['account']==index and row['match_id'] in r['match_ids'])
            health={p['id']:p['current'] for p in event.get('settled_health',())}
            require(row['pet_id'] in health,'Rank penalty lacks actually observed escape health')
            require(row['earned']==row['restored']==0 and row['penalty']==(20 if health[row['pet_id']]>0 else 0) and row['after_points']==max(-0x7fffffff,row['before_points']-row['penalty']),'Unexpected rank reward/penalty in escape')
            cursor[row['pet_id']]=row['after_points'];pending.remove(row)
        for identity,old in old_ranks.items():
            require(new_ranks[identity]=={**old,'points':cursor[identity]},'Unaudited saved rank change')
        participants={r['pet_id'] for r in additions['rank_battle_audit']}
        require(all(r['pet_id'] in participants for r in additions['experience_battle_audit']),'Unowned escape experience receipt')
        require(all(r['rating']==0 and r['pet_id'] in participants for r in additions['soldier_ratings']),'Escape changed earned PvP rating')
        old_health={p['id']:p for p in a['health']};new_health={p['id']:p for p in b['health']}
        require(old_health.keys()==new_health.keys(),'Escape changed saved health roster')
        for identity,old in old_health.items():
            new=new_health[identity]
            # An old all-10/zero-cap diagnostic snapshot was already projected
            # canonically in the city. Zero-XP settlement can persist that exact
            # existing normalization. Never mask weapon skills or other fields.
            expected=old['normalized_initial_expected_escape_sha256'] if ids and old.get('diagnostic_legacy') else old['escape_profile_sha256']
            require(new['maximum']==old['maximum'] and new['escape_profile_sha256']==expected and new['rank_projection_valid'],'Escape changed profile outside health/audited rank')
            if ids and old.get('diagnostic_legacy'):
                require(not new.get('diagnostic_legacy') and old['native_city_proficiency_vector']==new['native_city_proficiency_vector'],'Diagnostic normalization changed effective native city skills')
            if not ids:require(new['immutable_profile_sha256']==old['immutable_profile_sha256'],'Unaudited native rank projection changed')
        authorized.append(dict(match_ids=sorted(ids),initial_protected=a['protected'],protected=b['protected'],profile_changes_allowed=bool(ids),rank_penalties=sum(r['penalty'] for r in additions['rank_battle_audit'])))
    return authorized


def retained_assets(before,after,*,encounter,escapes=None):
    """Travel never excuses economic loss; exceptions need exact escape proof."""
    unchanged_foreign_rows(before['foreign'],after['foreign'])
    require(before['payments']==after['payments'] and before['service']==after['service'],'Payment ledger or service changed')
    require(len(before['states'])==len(after['states']),'World QA changed account roster')
    if encounter:require(escapes is not None and len(escapes)==len(before['states']),'Exact ordinary escape proof required')
    for index,(a,b) in enumerate(zip(before['states'],after['states'])):
        for key in ('account','wallet','securities','items','tutorial','bank_receipts','marks','shop','sales','orders','messages','mail_items','mail_receipts','sc_receipts','private_receipts'):
            require(a[key]==b[key],'Ordinary world QA changed protected personal asset '+key)
        require([(p['id'],p['level'],p['xp']) for p in a['pets']]==[(p['id'],p['level'],p['xp']) for p in b['pets']],'World QA granted synthetic levels/XP or changed roster')
        if encounter and escapes[index]['profile_changes_allowed']:
            require(a['protected']==escapes[index]['initial_protected'] and b['protected']==escapes[index]['protected'],'Personal settlement differs from exact escape proof')
            # All differences are now verified by the exact new receipt rows.
            normalized={**b,'pets':a['pets'],'protected':a['protected']}
            require(a==normalized,'Ordinary escape changed another personal saved field')
        else:require(a==b,'Views/travel without own audited escape changed personal saved state')


def progress(label,**fields):print(json.dumps(dict(phase=label,**fields,credentials_printed=False)),flush=True)


def drain(network):
    for peer in tuple(network.peers.values()):network.ping(peer)


def observe_town(network,index,town,state,report):
    packets=[p for p in network.received[index] if p.startswith(b'\xc8\x2d') and struct.unpack_from('<H',p,2)[0]==town]
    require(packets,'Actual current/arrival TownInfo missing')
    observed=town_observation(packets[-1],state['rates']);observed['account']=index
    report.setdefault('actual_town_info',[]).append(observed)
    currents=[p for p in network.received[index] if p.startswith(b'\xf0'+struct.pack('<I',98))]
    require(currents and decode_current_town(currents[-1])==town,'Native current-town transition missing')


def travel(network,fixture,index,town,report,*,seconds=TRAVEL_SECONDS,max_encounters=MAX_ROAD_ENCOUNTERS):
    require(type(seconds) in (int,float) and 0<seconds<=MAX_TRAVEL_SECONDS and type(max_encounters) is int and 1<=max_encounters<=MAX_ROAD_ENCOUNTERS,'Ordinary travel bound invalid')
    began=time.monotonic();deadline=began+seconds
    before=world_state(fixture,timeout=min(10,seconds));start=len(network.received[index]);target=before['centers'][str(town)]
    known={r['match'] for r in before['states'][index]['encounters']};encounters=0;announced=0
    require(not before['states'][index]['matches'],'Ordinary travel cannot begin inside a retained battle')
    leg=dict(account=index,town=town,arrived=False,native_1b_1e=False,ordinary_clock=True,request_sha256=hashlib.sha256(travel_request(target)).hexdigest(),requests=0,encounters=0)
    report.setdefault('travel',[]).append(leg)
    def send_route():
        bounded_native(network,deadline,network.command,index,travel_request(target));leg['requests']+=1
    def read_world():return world_state(fixture,timeout=min(10,deadline-time.monotonic()))
    def incomplete(reason):
        leg.update(limitation=reason,elapsed_seconds=round(time.monotonic()-began,3))
        return False
    if time.monotonic()>=deadline:return incomplete('ordinary real-time bound exhausted during initial observation')
    send_route()
    while True:
        if time.monotonic()>=deadline:return incomplete('ordinary real-time travel bound exhausted')
        bounded_native(network,deadline,drain,network)
        if time.monotonic()>=deadline:return incomplete('ordinary real-time travel bound exhausted while draining')
        current=read_world();owned=current['states'][index]
        fresh=[r for r in owned['encounters'] if r['match'] not in known]
        if fresh or owned['matches']:
            require(len(fresh)==1 and set(owned['matches'])<={r['match'] for r in fresh},'Retained scene has no unique fresh owned road audit')
            known.update(r['match'] for r in fresh);encounters+=len(fresh);leg['encounters']=encounters
            event=dict(account=index,target=town,actual_audits=fresh,match_ids=[r['match'] for r in fresh],no_admin_reset=True,native_escape_requests=0,map_paused_after_escape=False)
            report.setdefault('road_encounters',[]).append(event)
            progress('ordinary_road_encounter_exit',account=index,target=town)
            for _ in range(2):
                bounded_native(network,deadline,network.command,index,b'\x2a\x01');event['native_escape_requests']+=1
                bounded_native(network,deadline,drain,network)
            while time.monotonic()<deadline:
                current=read_world();owned=current['states'][index]
                if not owned['matches'] and owned['route'] is None and owned['point'] is not None:
                    event['map_paused_after_escape']=True;event['actual_paused_point']=owned['point'];event['settled_health']=[dict(id=p['id'],current=p['current']) for p in owned['health']];break
                time.sleep(min(.8,max(0,deadline-time.monotonic())))
                if time.monotonic()<deadline:bounded_native(network,deadline,drain,network)
            else:return incomplete('owned encounter cleanup exceeded real-time bound')
            if encounters>=max_encounters:return incomplete('ordinary road encounter retry bound exhausted')
            if time.monotonic()>=deadline:return incomplete('ordinary real-time travel bound exhausted after escape')
            send_route();continue
        if owned['town']==town and owned['route'] is None:
            packets=network.received[index][start:]
            require(any(p[:1]==b'\x1e' for p in packets),'Native arrival stop1E missing')
            observe_town(network,index,town,current,report)
            leg.update(arrived=True,native_1b_1e=True,point=owned['point'],elapsed_seconds=round(time.monotonic()-began,3))
            return True
        if time.monotonic()>announced:
            progress('ordinary_map_travel',account=index,target=town,seconds_remaining=max(0,round(owned['route'][5]-current['utc'])) if owned['route'] else None);announced=time.monotonic()+15
        time.sleep(min(.8,max(0,deadline-time.monotonic())))


def top_page(network,index,selector,baseline,report,*,offline=False):
    time.sleep(.3);prefix=bytes((0xa5,selector))
    reply=network.ask_matching(index,encode_request(selector),lambda p:p.startswith(prefix));packet=one(reply,prefix);actual=decode_ratings(packet)
    require(actual==decode_ratings(bytes.fromhex(baseline['tops'][str(selector)])),'Shared actual earned Top100 differs')
    offline_rows=[r.name.hex() for r in actual[1] if r.name!=network.fixture.names[index].encode()] if offline else []
    report.setdefault('top100',[]).append(dict(account=index,selector=selector,count=len(actual[1]),offline_rows=len(offline_rows),sha256=hashlib.sha256(packet).hexdigest()))
    return packet


def travel_completion(report):
    required=((0,4),(0,3),(1,18),(1,3))
    observed={(row['account'],row['town']) for row in report.get('travel',()) if row['arrived'] and row['native_1b_1e']}
    missing=[dict(account=index,town=town) for index,town in required if (index,town) not in observed]
    return dict(required_arrivals=4,actual_arrivals=4-len(missing),missing_arrivals=missing,completed=not missing)


def run(fixture,args,report,hashes):
    before=status(fixture,hashes);require(before['connections']==0 and not any(before['idle'].values()),'Hosted QA slot is occupied')
    baseline=census(fixture,world=True);initial=world_state(fixture)
    require(all(not s['matches'] and not s['route'] for s in initial['states']),'Preserved route or scene needs separate ordinary recovery before fresh world proof')
    require(all(s['town']==3 for s in initial['states']),'World probe starts from actual Reservation; never reset location')
    network=EconomyNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        progress('offline_shared_top100');assets=network.attach(0);require([assets.credits,assets.gold]==before['states'][0]['wallet'],'Native wallet differs')
        report['zones']=[dict(account=0,**zones(one(network.received[0],b'\xb9\x03zones\0')))];observe_town(network,0,3,initial,report)
        require(report['zones'][0]['sha256']==hashes['evidence/zones_diagnostic.xml'],'Network zones differ from actual released server XML')
        first={s:top_page(network,0,s,baseline,report,offline=True) for s in SORTS}
        require(any(r['offline_rows'] for r in report['top100']),'No actual offline public player was observed')
        assets=network.attach(1);require([assets.credits,assets.gold]==before['states'][1]['wallet'],'Second native wallet differs')
        report['zones'].append(dict(account=1,**zones(one(network.received[1],b'\xb9\x03zones\0'))));observe_town(network,1,3,world_state(fixture),report)
        require(report['zones'][1]['sha256']==report['zones'][0]['sha256'],'Shared native zones differ between real owners')
        for selector in SORTS:require(top_page(network,1,selector,baseline,report)==first[selector],'Shared standings differ between real accounts')
        require(top_page(network,0,0,baseline,report)==first[0],'Standings replay changed unchanged score')
        reply=network.ask_matching(0,b'\xa4\xff',lambda p:p.startswith(ERROR_PREFIX));native_error(one(reply,ERROR_PREFIX));report['invalid_top_selector_rejected']=True
        for i in (0,1):
            for retry in range(2):
                # Verified native33. Both impossible IDs prevent the local-ID
                # alias of actor1 on another real account from proving anything.
                reply=network.ask_matching(i,encode_item_action(ItemAction(0xffffffff,0xfffffffe,255)),lambda p:p.startswith(ERROR_PREFIX));native_error(one(reply,ERROR_PREFIX))
                report.setdefault('invalid_equipment_requests',[]).append(dict(account=i,retry=retry,original_33=True,unowned_actor_item_rejected=True))
        protected=status(fixture,hashes);retained_assets(before,protected,encounter=False)
        if not args.read_only:
            progress('outpost_real_travel_level_gate')
            if travel(network,fixture,0,4,report):
                for retry in range(2):
                    reply=network.ask_matching(0,b'\xba\x03\0\1',lambda p:p.startswith(ERROR_PREFIX));message=native_error(one(reply,ERROR_PREFIX))
                    require('уров' in message.casefold(),'Outpost LV1 rejected for unexpected reason')
                    report.setdefault('outpost_battle_gate',[]).append(dict(retry=retry,actual_level=1,required=[4,20],native_ba03_rejected=True))
            else:report['outpost_travel_gate']='Ordinary journey did not arrive within its recorded retry/time bound'
            travel(network,fixture,0,3,report)
            progress('detroit_real_travel')
            if travel(network,fixture,1,18,report):
                reply=network.ask_matching(1,b'\xba\x03\0\1',lambda p:p.startswith(ERROR_PREFIX));message=native_error(one(reply,ERROR_PREFIX));require('уров' in message.casefold(),'Detroit LV1 rejected for unexpected reason')
                report['detroit_battle_gate']=dict(actual_level=1,native_ba03_rejected=True)
            else:report['detroit_travel_gate']='Ordinary journey did not arrive within its recorded retry/time bound'
            travel(network,fixture,1,3,report)
            report['travel_completion']=travel_completion(report);report['travel_incomplete']=not report['travel_completion']['completed']
        else:report['travel_incomplete']=True;report['travel_gate']='Explicit --read-only: no native1B request'
    finally:
        for i in tuple(network.peers):
            try:network.command(i,b'\x2a\x01')
            except Exception:pass
        network.close();report['tls_channels']=[c.metadata() for c in network.connections]
    deadline=time.monotonic()+190
    while True:
        after=status(fixture,hashes)
        if after['connections']==0 and not any(after['idle'].values()):break
        require(time.monotonic()<deadline,'Owned disconnect cleanup deadline exceeded');time.sleep(.2)
    final=world_state(fixture);escapes=escape_receipts(initial,final,report)
    retained_assets(before,after,encounter=bool(report.get('road_encounters')),escapes=escapes)
    initialized_empty_tables=unchanged_foreign_rows(before['foreign'],after['foreign'])
    initialized_empty_world_tables=unchanged_foreign_rows(initial['foreign'],final['foreign'])
    require(all(not s['matches'] for s in final['states']),'Owned road checkpoint survived ordinary cleanup')
    report.update(passed=True,source_sha256=hashes,cleanup=dict(connections=after['connections'],idle=after['idle'],integrity=after['integrity']),final_ordinary_locations=final['states'],ordinary_escape_proof=[dict(account=i,match_ids=s['match_ids'],rank_penalties=s['rank_penalties']) for i,s in enumerate(escapes)],initialized_empty_foreign_tables=initialized_empty_tables,initialized_empty_world_tables=initialized_empty_world_tables,wallets_inventory_ownership_preserved=True,foreign_state_preserved=True,service_unchanged=True,clock_driven_world_state_changed=before['claims']!=after['claims'])


def self_test():
    from tio.protocol.town_info import TownInfoBase,encode_town_info
    rates={'4':[dict(town_id=4,epoch=1,influence='0',experience='3/4',profit='1')]}
    bits=tuple(struct.unpack('<I',struct.pack('<f',n))[0] for n in (0,.75,1))
    packet=encode_town_info(TownInfoBase(4,0,(4,20,0,0),(0,0,0),bits,(0,0,0),1))
    require(town_observation(packet,rates)['real_utc_coefficients']['experience']=='3/4','Rational/native float order differs')
    require(travel_request((-512,511))==struct.pack('<Bii',0x1b,-512,511),'Verified travel ABI differs')
    complete=travel_completion(dict(travel=[dict(account=i,town=t,arrived=True,native_1b_1e=True) for i,t in ((0,4),(0,3),(1,18),(1,3))]))
    require(complete['actual_arrivals']==4 and complete['completed'],'Four actual arrivals rule differs')
    for invalid in (0,MAX_TRAVEL_SECONDS+1):
        try:travel(None,None,0,4,{},seconds=invalid)
        except AssertionError:pass
        else:raise AssertionError('Unbounded real travel accepted')
    return dict(passed=True,network_actions=0,real_native_codecs=True,no_synthetic_town_push=True,maximum_leg_seconds=MAX_TRAVEL_SECONDS,default_leg_seconds=TRAVEL_SECONDS,maximum_encounters_per_leg=MAX_ROAD_ENCOUNTERS,required_actual_arrivals=4)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--self-test',action='store_true');p.add_argument('--read-only',action='store_true');p.add_argument('--fixture',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--deployments',type=Path,default=ROOT/'reports/gameplay-completion');p.add_argument('--phase7',type=Path,default=ROOT/'reports/gameplay-completion/stage7-clans/deployment.json');p.add_argument('--phase8',type=Path,default=ROOT/'reports/gameplay-completion/stage8-world/deployment.json')
    p.add_argument('--host',default='185.184.42.88');p.add_argument('--server-name',default='ti-reborn.com');p.add_argument('--login-port',type=int,default=29512);p.add_argument('--session-port',type=int,default=29513);p.add_argument('--loopback-session-port',type=int,default=28513);p.add_argument('--ca-file',type=Path)
    args=p.parse_args(argv)
    if args.self_test:print(json.dumps(self_test()));return 0
    if not args.fixture or not args.output:p.error('Preserved private fixture and fresh output required')
    if args.output.exists():p.error('Preserve prior evidence; select fresh output')
    require(all(1<=n<=65535 for n in (args.login_port,args.session_port,args.loopback_session_port)),'Invalid transport port')
    report=dict(passed=False,utc=datetime.now(timezone.utc).isoformat(),probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),kind='world native TLS, two retained ordinary accounts',limitations=['no graphical clients','LV1 cannot establish positive Outpost/Detroit LV4–20 multiplayer battle','training19–22 needs eight naturally eligible real accounts; no bulk fixtures','no prison sentence or paid clan action','actual road encounters can interrupt real map travel'],native_mapping=dict(source='docs/WORLD_CATALOG_NATIVE.md',proof_sha256=hashlib.sha256((ROOT/'reports/gameplay-completion/stage8-world/client/native-proof.json').read_bytes()).hexdigest()),isolated_outpost_evidence='reports/gameplay-completion/stage8-world/outpost-validation.json')
    try:
        hashes=deployment_hashes(args.deployments,args.phase7,args.phase8);report['world_client_release']=pin_world_release(args.phase8,hashes);fixture=Stage7Fixture.load(args.fixture)
        require(fixture.host==args.host and fixture.prefix=='qsfc5dfe28' and fixture.backup,'Retained designated ordinary pair required');run(fixture,args,report,hashes)
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__;report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
        if isinstance(error,AssertionError):report['reason']=str(error)[:200]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,graphical_clients_started=0)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
