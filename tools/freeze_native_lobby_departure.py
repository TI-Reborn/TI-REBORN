"""Freeze isolated hosted-source departure candidate and exact bounded evidence."""
from pathlib import Path
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-departure'
BASE=F.parent/'runtime-native-lobby-list/isolated-runtime'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 candidate=json.loads((F/'candidate.json').read_text());native=json.loads((F/'native-tcp-sequence-proof.json').read_text())
 log=(F/'isolated-tests-final.log').read_text(encoding='utf8');assert re.search(r'Ran 111 tests.*?\bOK\b',log,re.S)
 tcp=(F/'tcp-tests-final.log').read_text(encoding='utf8');assert re.search(r'Ran 18 tests.*?\bOK\b',tcp,re.S)
 assert native['passed'] and len(native['cases'])==24
 changed=[];unchanged={}
 for path in BASE.rglob('*.py'):
  rel=path.relative_to(BASE);other=F/'isolated-runtime'/rel
  assert other.exists()
  if path.read_bytes()!=other.read_bytes():changed.append(str(rel).replace('\\','/'))
  else:unchanged[str(rel).replace('\\','/')]=sha(path)
 assert sorted(changed)==['server/team_arena.py','server/wager_arena.py'],changed
 for name,key in (('team_arena.py','candidate_sha256'),('wager_arena.py','wager_candidate_sha256')):
  assert sha(F/'runtime/server'/name)==candidate[key]==sha(F/'isolated-runtime/server'/name)
 artifacts=['candidate.json','team_arena.diff','wager_arena.diff','isolated-tests-final.log','tcp-tests-final.log','tcp-cases.json','native-tcp-sequence-proof.json']
 report=dict(passed=True,tests_run=111,prior_qualified_tests=93,new_departure_tcp_tests=18,native_original_slot_sequences=24,changed_runtime_sources=changed,unchanged_runtime_source_count=len(unchanged),unchanged_runtime_sha256=unchanged,source_sha256={'server/team_arena.py':candidate['source_sha256'],'server/wager_arena.py':candidate['wager_source_sha256']},candidate_sha256={'server/team_arena.py':candidate['candidate_sha256'],'server/wager_arena.py':candidate['wager_candidate_sha256']},artifacts_sha256={name:sha(F/name) for name in artifacts},native_original_25_27_proof_sha256=sha(F.parent/'member-leave-native/native-member-leave-proof.json'),owned_stale_A_proof_sha256=sha(F.parent/'member-leave-native/owned-a-stale-slots.json'),scope='Only Team/Wall room survivors receive native27/public owner ID before existing25 merge. Ordinary all Team/Wall; Wager modes1/4. Captain closure remains F0/24 for all. Other Wager modes, frozen roster/admission, transports unchanged.',hosted_modified=False,hosted_player_data_opened=False,real_gui_candidate_validation=False,published=False)
 target=F/'validation-final.json';data=(json.dumps(report,indent=2)+'\n').encode()
 if target.exists():assert target.read_bytes()==data,'Frozen validation differs'
 else:target.write_bytes(data)
 print(json.dumps(dict(passed=True,report_sha256=sha(target),candidate_sha256=report['candidate_sha256'],unchanged_runtime_sources=len(unchanged))))
if __name__=='__main__':main()
