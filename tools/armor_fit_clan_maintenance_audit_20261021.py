"""Explain pre-existing hourly maintenance separately from the visual update."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
OUT=ROOT/'reports/armor-fit-20261021'
CODE=r'''
import hashlib,json,sqlite3,sys
from pathlib import Path
from fractions import Fraction
from contextlib import closing
p=json.load(sys.stdin);states={};sha=lambda rows:hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest()
for label,path in {'baseline':'/root/tio-before-miner-model-jmmc4zg8/reservation.sqlite3','current':'/var/lib/tio-server/reservation.sqlite3'}.items():
 with closing(sqlite3.connect('file:'+path+'?mode=ro',uri=True)) as db:
  rows=db.execute('SELECT * FROM clans').fetchall();clocks={i:(h,r) for i,h,r in db.execute('SELECT clan_id,last_hour,remainder FROM clan_decay')};states[label]=dict(rows={r[0]:r for r in rows},sha=sha(rows),clocks=clocks)
assert states['baseline']['sha']==p['reference_sha256'];assert states['baseline']['rows'].keys()==states['current']['rows'].keys()
policy=json.loads(Path('/opt/tio-emulator/config/clan_benefits.json').read_text())['influence'];checks=[];timeline={0:[]}
for identity,row in states['baseline']['rows'].items():
 new=states['current']['rows'][identity];hour,remainder=states['baseline']['clocks'][identity];now,new_remainder=states['current']['clocks'][identity];hours=now-hour;assert 0<=hours<=policy['max_decay_hours_per_call']
 level,value,revision=row[4],row[5],row[8];units=int(Fraction(policy['daily_decay_ppm'])*Fraction(policy['level_decay_multipliers'][level])*2)
 timeline[0].append(row)
 for step in range(1,hours+1):
  charge,remainder=divmod(value*units+remainder,48000000);updated=max(0,value-charge);revision+=int(updated!=value);value=updated
  expected=list(row);expected[5]=value;expected[8]=revision;timeline.setdefault(step,[]).append(tuple(expected))
 assert value==new[5] and remainder==new_remainder and revision==new[8]
 assert all(a==b for i,(a,b) in enumerate(zip(row,new)) if i not in (5,8))
 checks.append(dict(clan_id=identity,elapsed_hours=hours,influence_before=row[5],influence_after=value,revision_before=row[8],revision_after=revision,exact_hourly_policy_match=True))
hashes={step:sha(rows) for step,rows in timeline.items()};matches=[step for step,value in hashes.items() if value==p['baseline_sha256']];assert matches,'Audit-start fingerprint is not on the exact maintenance trajectory'
assert hashes[max(hashes)]==states['current']['sha']
print(json.dumps(dict(passed=True,read_only=True,reference_sha256=states['baseline']['sha'],audit_start_sha256=p['baseline_sha256'],audit_start_reference_hour_offset=matches,current_sha256=states['current']['sha'],checks=checks,database_restored=False)))
'''
before=json.loads((OUT/'hosted-before.json').read_text())
if '--inspect' in sys.argv:
 code=CODE.split("assert states['baseline']['sha']")[0]+"\nprint(json.dumps({k:dict(sha=v['sha'],values=[(r[0],r[4],r[5],r[8]) for r in v['rows'].values()],clocks=v['clocks']) for k,v in states.items()}))"
 print(json.dumps(remote(code,{})));sys.exit(0)
reference=json.loads((ROOT/'reports/miner-model-20261021/publication.json').read_text())['protected_before']['clans']
result=remote(CODE,dict(baseline_sha256=before['protected']['clans'],reference_sha256=reference));(OUT/'clan-maintenance-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
