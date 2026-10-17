"""Prepare/apply only the reviewed native lobby rows under a narrow city guard.

An optional one authenticated stationary city or Mine13 session may disconnect by
the already-authorized brief restart. No battle, escrow, ranked reservation,
owned QA session, unknown socket or travelling online character is admitted.
The established stopped-DB backup, full fingerprint and code-only rollback
remain intact. This wrapper never uploads/restores a player database.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import hashlib
import inspect
import json
from pathlib import Path
import re
import sqlite3
import time

from tools import deploy_gameplay_completion as established
from tools import deploy_stage4_economy as transaction

ROOT=established.ROOT
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011'
DEPLOYMENT=FOLDER/'server-city-lobby-deployment'
SOURCES={
    'server/team_arena.py':('9f2303a8331c8bae0faa46b558a3884070ce2df0c658913a8f1b44ccf38ed773',
                           '21ac51dfa56a8f868e222ab6b07725b03777dd4b63859d454c6cc37827f1c761'),
    'server/wager_arena.py':('4cf769a3c6aa6784a066b4bf9bcc48966157b0fb002e884bccfb271053fd8d01',
                            'a26bd6a66968492e12cbe9747662beb85a6741ca77d53a03ea68256a3401a99e'),
}
QUALIFICATION_SHA='bad17bc2b4c30bb58f88960f7c5e2ca0bf6717331cf337adc839ee59c207e697'
RUNTIME_PROOF=FOLDER/'runtime-native-lobby-departure/validation-final.json'
PROTECTED_RUNTIME=('server/multi.py','server/runtime.py','server/battle_journal.py',
    'server/battle_reconnect.py','server/presence.py','tio/battle_checkpoints.py',
    'tio/battle_settlement.py','tio/wagers.py','tio/locations.py','tio/arena_service.py',
    'server/mine_arena.py','server/mine_requests.py','tio/crystal_market.py','tio/mine_rounds.py')
EMPTY_TABLES=('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs',
              'wager_leases')
SETTLEMENT_TABLES=('battle_rewards','crystal_extractions','mine_crystal_extractions',
    'wager_matches','wager_members','wager_receipts','team_ranked_matches','wall_ranked_matches',
    'mine_round_missions')
POLICY='exact-two-native-lobby-files-stationary-city-idle-mine13-max-one-v1'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def durable_state(db):
    """Read only committed authoritative battle bindings and reservations."""
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required=set(EMPTY_TABLES)|{'wager_matches','character_locations','map_journeys'}
    if not required<=tables:
        raise RuntimeError('Required authoritative safety tables missing')
    counts={name:db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in EMPTY_TABLES}
    counts['active_wager_escrow']=db.execute("SELECT COUNT(*) FROM wager_matches WHERE status IN ('held','loading','active')").fetchone()[0]
    for name in ('team_ranked_matches','wall_ranked_matches'):
        counts['pending_'+name]=(db.execute('SELECT COUNT(*) FROM '+name+" WHERE state='pending'").fetchone()[0] if name in tables else 0)
    counts['mine_claim_leases']=(db.execute('SELECT COUNT(*) FROM mine_claim_leases').fetchone()[0] if 'mine_claim_leases' in tables else 0)
    return counts


def require_durable_idle(counts):
    expected=set(EMPTY_TABLES)|{'active_wager_escrow','pending_team_ranked_matches',
        'pending_wall_ranked_matches','mine_claim_leases'}
    if set(counts)!=expected or any(type(n)is not int or n<0 for n in counts.values()):
        raise RuntimeError('Malformed authoritative battle safety state')
    if any(counts.values()):
        raise RuntimeError('Battle, escrow or ranked reservation prevents this restart')


def settlement_boundary(db):
    """Detect a battle/extraction that began and settled in the stop gap."""
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result={}
    for name in SETTLEMENT_TABLES:
        if name not in tables:continue
        rows=sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM '+name))
        result[name]=dict(rows=len(rows),sha256=digest('\n'.join(rows).encode()))
    return result


def require_settlement_unchanged(before,after):
    if before!=after:
        raise RuntimeError('New battle or extraction settlement in stop gap; retain current DB and original code')


def require_city_safe(observed,owned_qa_closed):
    require_durable_idle(observed['durable'])
    if owned_qa_closed is not True:
        raise RuntimeError('Owned QA clients must already be closed')
    game,login=observed['game_connections'],observed['login_connections']
    if type(game)is not int or type(login)is not int or game<0 or login<0 or login or game>1:
        raise RuntimeError('Only zero or one game connection and no login connections allowed')
    if observed['owned_presence']:
        raise RuntimeError('An owned QA character is still present')
    if game==0:
        if observed['presence_count']:
            raise RuntimeError('Socket/presence state differs; inspect again')
        return
    web=observed['web_status']
    age=observed['web_status_age_seconds']
    if (not isinstance(web,dict) or web.get('status')!='online'
            or type(web.get('playersOnline'))is not int or web['playersOnline']!=1
            or type(age) not in (int,float) or not -2<=age<=15):
        raise RuntimeError('One fresh authenticated online account must match the socket')
    if (observed['presence_count']!=1 or observed['stationary_location_confirmed'] is not True
            or observed['online_account_journeys']!=0):
        raise RuntimeError('Remaining session is not a verified stationary city or idle Mine13 character')


def live_observation(run,dbpath,owned_hashes):
    """No process attachment or protocol traffic; usernames stay remote only."""
    service=dict(row.split('=',1) for row in run('systemctl','show','tio-server',
        '-p','MainPID','-p','ActiveState').splitlines() if '=' in row)
    if service.get('ActiveState')!='active' or not service.get('MainPID','0').isdigit() or service['MainPID']=='0':
        raise RuntimeError('Hosted game service must be active')
    sockets=run('ss','-Htn','state','established',
        '( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
    game=login=0
    for row in sockets.splitlines():
        fields=row.split()
        if len(fields)!=4:
            raise RuntimeError('Unknown established-socket layout')
        port=int(fields[-2].rsplit(':',1)[1])
        if port in (28513,29513):game+=1
        elif port in (28512,29512):login+=1
        else:raise RuntimeError('Unexpected gameplay socket port')
    # Require one current-process selected character. PID-scoped journal avoids
    # confusing a prior process's disconnected character with this live socket.
    journal=run('journalctl','-u','tio-server','_PID='+service['MainPID'],
                '--since','today','-n','20000','--no-pager','-o','json')
    presence={}
    for line in journal.splitlines():
        try:row=json.loads(line)
        except json.JSONDecodeError:continue
        if str(row.get('_PID',''))!=service['MainPID']:continue
        message=row.get('MESSAGE','')
        match=re.search(r'presence_join account=(\S+) town=(\S+)',message)
        if match:presence[match[1]]=match[2]
        match=re.search(r'presence_move account=(\S+) from=\S+ to=(\S+)',message)
        if match and match[1] in presence:presence[match[1]]=match[2]
        match=re.search(r'presence_leave account=(\S+) town=\S+',message)
        if match:presence.pop(match[1],None)
    webpath=dbpath.parent/'web-status.json'
    web=json.loads(webpath.read_bytes()) if webpath.is_file() else None
    age=time.time()-web['observedAt'] if web and type(web.get('observedAt'))in (int,float) else None
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        durable=durable_state(db)
        city=False;journeys=None;saved_town=None;presence_town=None;location_kind=None
        if len(presence)==1:
            account,town=next(iter(presence.items()))
            presence_town=int(town) if town.lstrip('-').isdigit() else None
            row=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
            saved_town=row[0] if row else 3
            journeys=db.execute('SELECT COUNT(*) FROM map_journeys WHERE account=?',(account,)).fetchone()[0]
            # Ordinary city IDs have stable policy. Other world locations,
            # prison and other mines are outside this maintenance exception.
            city_ids=(2,3,4,5,8,18)
            known=saved_town in (*city_ids,13)
            city=presence_town==saved_town and known and journeys==0
            location_kind='idle_mine13' if city and saved_town==13 else 'city' if city else None
        receipts=settlement_boundary(db)
    return dict(game_connections=game,login_connections=login,
        presence_count=len(presence),owned_presence=sum(digest(n.encode()) in owned_hashes for n in presence),
        stationary_location_confirmed=city,stationary_location_kind=location_kind,online_account_journeys=journeys,
        presence_town_id=presence_town,saved_town_id=saved_town,
        web_status=web,web_status_age_seconds=age,durable=durable,settlement_boundary=receipts,
        account_names_reported=False,peer_addresses_reported=False)


def helpers():
    return '\n'.join(inspect.getsource(f) for f in
        (digest,durable_state,require_durable_idle,settlement_boundary,require_settlement_unchanged,
         require_city_safe,live_observation))


def replace_once(code,before,after):
    if code.count(before)!=1:
        raise RuntimeError('Established deployment boundary changed')
    return code.replace(before,after)


def program():
    code=established.program(SOURCES)
    before=code[code.index('def idle_rows():'):code.index('def atomic(',code.index('def idle_rows():'))]
    code=replace_once(code,before,'EMPTY_TABLES='+repr(EMPTY_TABLES)+'\nSETTLEMENT_TABLES='+repr(SETTLEMENT_TABLES)+'\n'+helpers()+'''
city_observations=[]
def idle_rows():
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('BEGIN')
        require_durable_idle(durable_state(db))
        if city_observations:
            require_settlement_unchanged(city_observations[-1]['settlement_boundary'],settlement_boundary(db))

def idle():
    observed=live_observation(run,dbpath,p['owned_account_sha256'])
    require_city_safe(observed,p['owned_qa_closed'])
    city_observations.append(observed)

''')
    marker="if not p['files'] or not set(p['files'])<=allowed:raise ValueError('Unexpected economy files')\n"
    checks=("if set(p['files'])!=set("+repr(SOURCES)+"):raise ValueError('Only the frozen two-file lobby revision accepted')\n"
        +"if p.get('policy_review')!="+repr(POLICY)+":raise ValueError('Wrong deployment policy review')\n"
        +"if p.get('owned_qa_closed') is not True:raise ValueError('Owned QA clients must be closed')\n"
        +"for name,expected in "+repr(SOURCES)+".items():\n"
        +"    if (p['files'][name]['before'],p['files'][name]['after'])!=expected:raise ValueError('Unreviewed source revision')\n")
    code=replace_once(code,marker,marker+checks)
    code=replace_once(code,"prefix='tio-before-gameplay-completion-'","prefix='tio-before-legacy-lobby-city-projection-'")
    code=replace_once(code,"local_player_data_uploaded=False,database_restored=False)",
        "local_player_data_uploaded=False,database_restored=False,\n        connection_policy="+repr(POLICY)+",city_session_checks=city_observations,\n        maximum_pre_stop_game_connections=max((x['game_connections'] for x in city_observations),default=0))")
    code=replace_once(code,'import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,time',
        'import base64,fcntl,hashlib,json,os,re,shutil,sqlite3,subprocess,sys,tempfile,time')
    compile(code,'remote-city-only-lobby-projection','exec')
    return code


def inspector():
    from tools.inspect_gameplay_completion import INSPECT
    start=INSPECT.index('print(json.dumps(dict(')
    end=INSPECT.rindex(')))')
    code=INSPECT[:start]+'result=dict('+INSPECT[start+len('print(json.dumps(dict('):end]+')\n'
    code=code.replace('import hashlib,json,sqlite3,subprocess,sys,time','import hashlib,json,re,sqlite3,subprocess,sys,time')
    code+='\nEMPTY_TABLES='+repr(EMPTY_TABLES)+'\nSETTLEMENT_TABLES='+repr(SETTLEMENT_TABLES)+'\n'+helpers()+'''
result['city_restart_state']=live_observation(run,Path('/var/lib/tio-server/reservation.sqlite3'),p['owned_account_sha256'])
try:
 require_city_safe(result['city_restart_state'],p['owned_qa_closed'])
 result['city_restart_eligible']=True
except RuntimeError as error:
 result['city_restart_eligible']=False;result['city_restart_reason']=str(error)
result['remote_mutations']=0
print(json.dumps(result))
'''
    compile(code,'readonly-city-lobby-inspection','exec')
    return code


def owned_hashes():
    fixture=json.loads((ROOT/'reports/arena-surroundings/private/qs3110ad96.json').read_bytes())
    if fixture['host']!='185.184.42.88' or fixture['prefix']!='qs3110ad96' or len(fixture['names'])!=4:
        raise ValueError('Known owned QA fixture differs')
    return sorted(digest(name.encode()) for name in fixture['names'])


def validate_sources(entries):
    if set(entries)!=set(SOURCES):raise ValueError('Exactly two frozen lobby files required')
    for name,expected in SOURCES.items():
        entry=entries[name]
        raw=base64.b64decode(entry['content'],validate=True)
        if (entry['before'],entry['after'])!=expected or digest(raw)!=expected[1]:
            raise ValueError('Reviewed lobby source changed')
        established.validate(name,raw)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('inspect','prepare','deploy'))
    parser.add_argument('--folder',type=Path,default=DEPLOYMENT)
    parser.add_argument('--report',default='remote-baseline.json')
    parser.add_argument('--owned-clients-closed',action='store_true')
    args=parser.parse_args();folder=args.folder.resolve()
    if folder!=DEPLOYMENT or any(p.is_symlink() for p in (folder,*folder.parents)):
        raise ValueError('Use only the new scoped city-lobby deployment folder')
    if not args.owned_clients_closed:raise ValueError('Owned clients must already be closed')
    manifest=folder/'deployment-manifest.json'
    if args.action in ('inspect','prepare'):
        if Path(args.report).name!=args.report or not args.report.endswith('.json'):
            raise ValueError('Use a new plain inspection filename')
        path=folder/args.report
        if path.exists():raise ValueError('Preserve previous inspection evidence')
        observed=transaction.remote(inspector(),dict(files=sorted(SOURCES),
            owned_account_sha256=owned_hashes(),owned_qa_closed=True))
        folder.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8') as out:json.dump(observed,out,indent=2);out.write('\n')
        if args.action=='inspect':
            print(json.dumps({k:observed[k] for k in ('game_connections','city_restart_eligible','remote_mutations')}));return
        if manifest.exists():raise ValueError('Preserve previous prepared deployment manifest')
        if not observed['city_restart_eligible']:raise RuntimeError('Fresh city-only restart guard rejected current service state')
        if not QUALIFICATION_SHA:raise ValueError('Final departure qualification has not frozen yet')
        raw=(folder/'validation.json').read_bytes();validation=json.loads(raw)
        if (digest(raw)!=QUALIFICATION_SHA or validation.get('passed') is not True
                or validation.get('tests_run')!=111 or validation.get('native_original_slot_sequences')!=24
                or validation.get('candidate_sha256')!={name:values[1] for name,values in SOURCES.items()}
                or set(validation.get('changed_runtime_sources',()))!=set(SOURCES)):
            raise ValueError('Exact final hosted-source qualification required')
        entries={}
        for name,(before,after) in SOURCES.items():
            raw=established.source_path(folder,name).read_bytes()
            if observed['files'][name]['sha256']!=before or validation['candidate_sha256'].get(name)!=after:
                raise ValueError('Actual hosted or qualified source changed')
            entries[name]=dict(before=before,after=after,content=base64.b64encode(raw).decode('ascii'))
        validate_sources(entries)
        hashes=validation['unchanged_runtime_sha256']
        guards=dict(observed['guards'])
        for name in PROTECTED_RUNTIME:
            guards['/opt/tio-emulator/'+name]=hashes[name]
        actual=transaction.remote(transaction.INSPECT,dict(files=list(PROTECTED_RUNTIME)))
        if any(actual[n]['sha256']!=hashes[n] for n in PROTECTED_RUNTIME):raise ValueError('Battle/save/shutdown implementation changed since review')
        data=dict(files=entries,guards=guards,phase=folder.name,local_player_data_uploaded=False,
            owned_qa_closed=True,owned_account_sha256=owned_hashes(),policy_review=POLICY)
        with manifest.open('x',encoding='utf-8') as out:json.dump(data,out,indent=2);out.write('\n')
        print(json.dumps(dict(prepared_files=sorted(entries),game_connections=observed['game_connections'],remote_mutations=0)))
        return
    target=folder/'deployment.json'
    if not QUALIFICATION_SHA:raise ValueError('Final departure qualification has not frozen yet')
    if target.exists():raise ValueError('Preserve previous deployment report')
    data=json.loads(manifest.read_bytes());validate_sources(data['files'])
    if (data.get('policy_review')!=POLICY or data.get('owned_qa_closed') is not True
            or data.get('owned_account_sha256')!=owned_hashes()):
        raise ValueError('Prepared owned-session/policy guard changed')
    for name,entry in data['files'].items():
        if digest(established.source_path(folder,name).read_bytes())!=entry['after']:raise ValueError('Prepared candidate changed')
    report=transaction.remote(program(),data)
    with target.open('x',encoding='utf-8') as out:json.dump(report,out,indent=2);out.write('\n')
    if not report.get('source_parity'):raise RuntimeError('Deployment requires attention; current DB retained')
    print(json.dumps({k:report[k] for k in ('backup','service','accounts_preserved','wallets_preserved',
        'all_existing_tables_unchanged','source_parity','maximum_pre_stop_game_connections')}))


if __name__=='__main__':main()
