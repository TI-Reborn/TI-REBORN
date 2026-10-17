"""Read-only aggregate sockets/heartbeat and hashed account journal inspection.

Never exposes foreign account names or peer addresses, attaches to the process,
changes sessions, restarts services, or writes hosted data.
"""
from pathlib import Path
import argparse
import hashlib
import json

from tools.verify_public_runtime_regression import remote

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011'
CODE=r'''
import json,sys,subprocess,re,hashlib,pathlib,time
from datetime import datetime,timezone
p=json.load(sys.stdin);own=set(p['own_names'])
def identity(name):
 return dict(owned_qa=name in own,account_label=chr(65+p['own_names'].index(name)) if name in own else None,account_sha256=hashlib.sha256(name.encode()).hexdigest())
def stamp(value):
 return datetime.fromtimestamp(int(value)/1000000,timezone.utc).isoformat()
service=dict(line.split('=',1) for line in subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,ActiveState,ActiveEnterTimestampMonotonic'],text=True).splitlines() if '=' in line)
logs=subprocess.check_output(['journalctl','-u','tio-server','--since','today','-n','5000','--no-pager','-o','json'],text=True)
authorized=[];presence={};events=[];pid=str(service['MainPID'])
for line in logs.splitlines():
 try:row=json.loads(line)
 except json.JSONDecodeError:continue
 if str(row.get('_PID',''))!=pid:continue
 message=row.get('MESSAGE','');when=stamp(row.get('__REALTIME_TIMESTAMP',0))
 match=re.search(r'Login authorized requested_login=(\S+) transport=(\S+)',message)
 if match:
  name,transport=match.groups();authorized.append(dict(**identity(name),observed_utc=when,transport=transport))
 match=re.search(r'presence_(join|leave) account=(\S+) town=(\S+)',message)
 if match:
  action,name,town=match.groups();value=dict(**identity(name),observed_utc=when,action=action)
  events.append(value)
  if action=='join':presence[name]=value
  else:presence.pop(name,None)
connections=[]
lines=subprocess.check_output(['ss','-Htn','state','established','( sport = :29512 or sport = :29513 or sport = :28512 or sport = :28513 )'],text=True)
for line in lines.splitlines():
 fields=line.split()
 if len(fields)<4:continue
 local,peer=fields[-2:];port=int(local.rsplit(':',1)[1])
 connections.append(dict(local_port=port,peer_endpoint_sha256=hashlib.sha256(peer.encode()).hexdigest(),receive_queue=int(fields[0]),send_queue=int(fields[1])))
web=pathlib.Path('/var/lib/tio-server/web-status.json')
status=json.loads(web.read_bytes()) if web.exists() else None
print(json.dumps(dict(passed=True,remote_mutations=0,service=service,observed_utc=datetime.now(timezone.utc).isoformat(),web_status=status,web_status_age_seconds=round(time.time()-status['observedAt'],3) if status else None,connections=connections,established_tls_game_sockets=sum(x['local_port']==29513 for x in connections),established_direct_game_sockets=sum(x['local_port']==28513 for x in connections),established_login_sockets=sum(x['local_port'] in (29512,28512) for x in connections),authorized_events=authorized[-40:],presence_events=events[-40:],currently_joined_presence=list(presence.values()),foreign_names_or_addresses_reported=False,account_association_limit='Journal presence covers character selection; Auth2 before selection has no account-identifying success log. Socket counts alone do not prove authentication.')))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args();path=args.report.resolve()
    if path.exists() or not path.is_relative_to(FOLDER) or any(p.is_symlink() for p in [path,*path.parents]):
        raise ValueError('Use a new regular scoped read-only report')
    fixture=json.loads((ROOT/'reports/arena-surroundings/private/qs3110ad96.json').read_bytes())
    if fixture['host']!='185.184.42.88' or fixture['prefix']!='qs3110ad96':
        raise ValueError('Owned QA fixture target differs')
    result=remote(CODE,{'own_names':fixture['names']},timeout=45)
    result['inspector_code_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as out:json.dump(result,out,indent=2);out.write('\n')
    print(json.dumps({key:result.get(key) for key in ('passed','observed_utc','web_status','web_status_age_seconds','established_tls_game_sockets','established_login_sockets','currently_joined_presence','remote_mutations')},indent=2))


if __name__=='__main__':
    main()
