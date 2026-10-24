"""Remove only the owned map-encounter checkpoint; audit the hosted release."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import remote
from tools.verify_game_operations_hosted import CLEANUP
OUT=ROOT/'reports/training-disband-20261018'

def main():
 gui=json.loads((OUT/'gui-verification.json').read_text());names=list(gui['own_locations'])
 # The native exit check can produce an ordinary map encounter. Its snapshot
 # is account-owned rather than reward_roster-owned; prove ownership first.
 setup='''
from tio.battle_snapshot import loads
request={'names':NAMES,'require_unchanged_players':True}
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as initial:
 request['protected_before']=protected(initial)
 request['matches']=[]
 for identity,payload in initial.execute('SELECT match_id,payload FROM battle_checkpoints'):
  if not any(n in payload for n in request['names']):continue
  state=loads(payload)[0]
  assert state['kind']=='private' and state['account'] in request['names']
  assert not initial.execute('SELECT 1 FROM battle_checkpoint_members WHERE match_id=? AND account NOT IN (?,?)',(identity,*request['names'])).fetchone()
  request['matches'].append(identity)
'''.replace('NAMES',repr(names))
 marker="from tio.rating_visibility import QA_LOGIN\nnames=request['names'];"
 code=CLEANUP.replace(marker,setup+"\nfrom tio.rating_visibility import QA_LOGIN\nnames=request['names'];")
 old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
 new="\n  if 'match_id' in columns and request['matches']:\n   parts.append(quote('match_id')+' IN ('+','.join('?' for _ in request['matches'])+')');args+=request['matches']\n  "+old
 assert marker in CLEANUP and old in code
 code=code.replace(old,new)
 cleanup=remote(code);(OUT/'encounter-cleanup.json').write_text(json.dumps(cleanup,indent=2))
 publication=json.loads((OUT/'client-publication.json').read_text())
 state=remote('''import json,sqlite3,subprocess
from pathlib import Path
names='''+repr(names)+'''
backup='''+repr(publication['backup'])+'''
with sqlite3.connect('file:'+backup+'/reservation.sqlite3?mode=ro',uri=True) as before,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as after:
 old={r[0] for r in before.execute('SELECT login FROM accounts')};new={r[0] for r in after.execute('SELECT login FROM accounts')}
 assert old-set(names)==new and not set(names)&new
 assert not any(any(n in p for n in names) for p, in after.execute('SELECT payload FROM battle_checkpoints'))
 assert after.execute('PRAGMA integrity_check').fetchone()==('ok',)
 result=dict(accounts=len(new),preexisting_accounts_preserved=True,own_accounts_removed=True,own_checkpoints_removed=True,integrity='ok',backup_database_valid=before.execute('PRAGMA integrity_check').fetchone()==('ok',))
 result['service']=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)
 assert 'MainPID=120170' in result['service'] and 'ActiveState=active' in result['service']
print(json.dumps(result))
''')
 assert not (ROOT/'.secrets/training-disband-20261018.json').exists()
 state['private_credentials_removed']=True
 (OUT/'final-state.json').write_text(json.dumps(state,indent=2));print(json.dumps(state))

if __name__=='__main__':main()
