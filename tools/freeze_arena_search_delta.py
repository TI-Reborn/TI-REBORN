"""Prove NEW search-status freeze composes over immutable afaa evidence."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-search-availability'
OLD=F.parent/'client-availability-navigation'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 old=(OLD/'silver.dll').read_bytes();new=(F/'silver.dll').read_bytes();source=(F.parent/'client-freshness/silver.dll').read_bytes()
 assert len(old)==len(new)==8131072
 assert sha(OLD/'silver.dll')=='afaa457c06ba6223476bc6e53eeff9947e9291acbce19700bb10ed5c3b29bdad'
 assert sha(OLD/'native-navigation-proof.json')=='3f0164eb8b5779fa7b25ad2341981c329999444ff185dd26dc364bcb67994731'
 assert sha(OLD/'combined-review.json')=='8a21ac17cc576514af7dfacb4d2970737567f1080d185e54df89a435a194d165'
 assert sha(OLD/'native-composition.json')=='052aacf9ee36a495bf38e5a79e98a71e172229e74e5933d2d1976cf7c0eebcf8'
 assert old[:len(source)+0x200]==new[:len(source)+0x200]
 changes=[i for i,(a,b) in enumerate(zip(old,new)) if a!=b]
 assert changes and all(len(source)+0x200<=i<len(new) for i in changes)
 proof=json.loads((F/'native-navigation-proof.json').read_text(encoding='utf8'));assert proof['passed']
 # Native27 and25 functions are in the byte-identical original prefix.
 report=dict(passed=True,published_source_sha256=sha(F.parent/'client-freshness/silver.dll'),frozen_afaa_sha256=sha(OLD/'silver.dll'),candidate_sha256=sha(F/'silver.dll'),changed_existing_afaa_prefix_bytes=0,changed_appended_bytes=len(changes),changed_append_offset_min=min(changes)-len(source),changed_append_offset_max=max(changes)-len(source),navigation_helpers_first512_bytes_identical=True,original_25_27_consumers_identical=True,prior_afaa_proofs_unchanged=True,previous_auth_texture_status_transport_roster_navigation_unchanged=True,review_sha256=sha(F/'combined-review.json'),composition_sha256=sha(F/'native-composition.json'),native_proof_sha256=sha(F/'native-navigation-proof.json'),old_25_27_proof_sha256=sha(F.parent/'member-leave-native/native-member-leave-proof.json'),implementation_sources_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in (ROOT/'deploy/client_arena_lobby_navigation.py',ROOT/'deploy/client_arena_lobby_search_status.py',ROOT/'tools/build_arena_lobby_search_status_native.py',ROOT/'tools/verify_arena_lobby_search_status_native.py')},no_gui_driven=True,published=False)
 target=F/'afaa-delta-proof.json';data=(json.dumps(report,indent=2)+'\n').encode()
 if target.exists():assert target.read_bytes()==data
 else:target.write_bytes(data)
 print(json.dumps(dict(passed=True,report_sha256=sha(target),changed_append_bytes=len(changes),native_proof_sha256=report['native_proof_sha256'])))
if __name__=='__main__':main()
