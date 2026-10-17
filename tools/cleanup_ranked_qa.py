"""Remove rating-only QA entries from this stage's recorded fresh accounts."""
from prepare_ranked_deploy import ROOT,SSH
import json,shlex,subprocess

def main():
    pairs=[json.loads(p.read_text())['accounts'] for p in (ROOT/'reports/ranked').glob('hosted-qt*.json')]
    code='''import json,sys,sqlite3,time,tempfile,pathlib,subprocess
sys.path.insert(0,'/opt/tio-emulator')
from tio.battle_snapshot import loads
from tio.battle_checkpoints import delete
pairs=json.load(sys.stdin);names=set(n for pair in pairs for n in pair)
assert names and all(n.startswith('qt') and len(n)==11 for n in names)
old=sqlite3.connect('file:/root/tio-before-ranked-hlua4zet/reservation.sqlite3?mode=ro',uri=True)
assert not names.intersection(n for n, in old.execute('SELECT login FROM accounts'))
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).strip()
 backup=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-ranked-qa-cleanup-',dir='/root'))/'reservation.sqlite3'
 with sqlite3.connect(backup) as saved:db.backup(saved)
 db.execute('BEGIN IMMEDIATE')
 checkpoints=[]
 for m,payload,status,updated in db.execute('SELECT match_id,payload,status,updated_at FROM battle_checkpoints').fetchall():
  state=loads(payload)[0];participants=set(data['account'] for data in state.get('sessions',{}).values())
  if participants.intersection(names):
   assert status=='finished' and state['battle']['finished'] and updated<time.time()-180
   assert any(participants==set(pair) for pair in pairs)
   assert not db.execute('SELECT 1 FROM battle_settlement_jobs WHERE match_id=?',(m,)).fetchone()
   for n in participants:assert db.execute('SELECT 1 FROM battle_rewards WHERE match_id=? AND account=?',(m,n)).fetchone()
   delete(db,m);checkpoints.append(m)
 for n in names:
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(n,)).fetchone(),n
  assert not db.execute('SELECT 1 FROM battle_settlement_jobs WHERE account=?',(n,)).fetchone(),n
 matches=[]
 for match,payload in db.execute('SELECT match_id,report FROM ranked_matches').fetchall():
  accounts=set(p[0] for team in json.loads(payload)['teams'] for p in team)
  if accounts.intersection(names):
   assert any(accounts==set(pair) for pair in pairs)
   db.execute('DELETE FROM ranked_matches WHERE match_id=?',(match,));matches.append(match)
 removed=sum(db.execute('DELETE FROM ranked_players WHERE account=?',(n,)).rowcount for n in names)
print(json.dumps(dict(accounts=sorted(names),backup=str(backup),expired_qa_checkpoints_removed=checkpoints,ranked_players_removed=removed,ranked_matches_removed=matches)))
'''
    p=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(pairs),capture_output=True,text=True,encoding='utf-8')
    if p.returncode:raise RuntimeError(p.stderr)
    (ROOT/'reports/ranked/qa-cleanup.json').write_text(p.stdout)
    print(p.stdout.strip())

if __name__=='__main__':main()
