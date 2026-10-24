"""Explain elapsed-time clan maintenance without modifying hosted state."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
OUT=ROOT/'reports/dog-models-20261021'
CODE=r'''
from contextlib import closing
from fractions import Fraction
from pathlib import Path
import hashlib,json,sqlite3,sys
p=json.load(sys.stdin)
sha=lambda rows:hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest()
paths={'baseline':'/root/tio-before-female-fighter-s07u80p7/reservation.sqlite3','publication':'/root/tio-before-dog-models-a94awnhn/reservation.sqlite3','current':'/var/lib/tio-server/reservation.sqlite3'}
states={}
for label,path in paths.items():
 with closing(sqlite3.connect('file:'+path+'?mode=ro',uri=True)) as db:
  rows=db.execute('SELECT * FROM clans').fetchall();decay={c:(h,r) for c,h,r in db.execute('SELECT clan_id,last_hour,remainder FROM clan_decay')}
  states[label]=dict(rows=rows,decay=decay,sha256=sha(rows))
assert states['baseline']['sha256']==p['baseline_clans_sha256']
assert states['publication']['sha256']==states['current']['sha256'],'Unexpected clan activity after publication'
policy=json.loads(Path('/opt/tio-emulator/config/clan_benefits.json').read_text())['influence']
old={r[0]:r for r in states['baseline']['rows']};new={r[0]:r for r in states['current']['rows']};assert set(old)==set(new)
checks=[]
for identity,row in old.items():
 level,value,revision=row[4],row[5],row[8];last,remainder=states['baseline']['decay'][identity];current_hour,current_remainder=states['current']['decay'][identity]
 hours=current_hour-last;assert 0<=hours<=policy['max_decay_hours_per_call']
 units=int(Fraction(policy['daily_decay_ppm'])*Fraction(policy['level_decay_multipliers'][level])*2)
 for _ in range(hours):
  charge,remainder=divmod(value*units+remainder,24*1000000*2);value=max(0,value-charge)
 assert new[identity][5]==value and current_remainder==remainder
 assert new[identity][8]==revision+int(value!=row[5])
 assert all(a==b for i,(a,b) in enumerate(zip(row,new[identity])) if i not in (5,8))
 checks.append(dict(clan_id=identity,elapsed_hours=hours,influence_before=row[5],influence_after=value,revision_before=revision,revision_after=new[identity][8],exact_policy_match=True))
print(json.dumps(dict(passed=True,read_only=True,reason='Existing automatic hourly clan-influence decay, exactly reproduced from prior database clock and configured policy',
 baseline_clans_sha256=states['baseline']['sha256'],current_clans_sha256=states['current']['sha256'],publication_matches_current=True,checks=checks,database_restored=False)))
'''
before=json.loads((OUT/'hosted-before.json').read_text())
result=remote(CODE,dict(baseline_clans_sha256=before['protected']['clans']))
(OUT/'clan-maintenance-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
