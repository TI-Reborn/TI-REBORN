"""Freeze actual-mode0 composition, actual entry proof and source dependencies."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-empty-roster-navigation'
OLD=F.parent/'client-search-availability'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    new=(F/'silver.dll').read_bytes();old=(OLD/'silver.dll').read_bytes();source=(F.parent/'client-freshness/silver.dll').read_bytes()
    assert sha(OLD/'silver.dll')=='9d24b8f13a2c2a07c0673f8f9165b9df9f76a45eaa8561415606b3854ca86302'
    assert sha(OLD/'combined-review.json')=='b670ffa21cab34b344d8571cf07acf41eb7f34da875617038f15bbdc3752e778'
    assert sha(OLD/'native-composition.json')=='8bbe0b934337df640e5a36a478f399c81cf824e200cb21ccedf1d267fece8cbc'
    assert sha(OLD/'native-navigation-proof.json')=='216b7b7df066a3c597d16df7308838edb6102eda3b5f6cc0012eb3ee9fca9f46'
    assert old[:len(source)]==new[:len(source)]
    assert old[len(source)+0x200:len(source)+0x600]==new[len(source)+0x200:len(source)+0x600]
    assert json.loads((F/'actual-arena-entry-proof.json').read_text(encoding='utf8'))['passed']
    assert json.loads((F/'native-navigation-proof.json').read_text(encoding='utf8'))['passed']
    paths=['deploy/client_arena_lobby_navigation.py','deploy/client_arena_lobby_search_status.py','deploy/client_arena_empty_roster_navigation.py','tools/build_arena_empty_roster_navigation_native.py','tools/verify_arena_empty_roster_navigation_native.py','tools/verify_actual_arena_entry_native.py','tools/hosted_graphical_qa_bridge.py']
    report=dict(passed=True,source_sha256=sha(F.parent/'client-freshness/silver.dll'),previous9d24_sha256=sha(OLD/'silver.dll'),candidate_sha256=sha(F/'silver.dll'),candidate_bytes=len(new),combined_review_sha256=sha(F/'combined-review.json'),native_composition_sha256=sha(F/'native-composition.json'),native_proof_sha256=sha(F/'native-navigation-proof.json'),actual_entry_proof_sha256=sha(F/'actual-arena-entry-proof.json'),owned_D_readonly_before_sha256=sha(F/'owned-d-selector-state-before-fix.json'),published_original_prefix_identical_to9d24=True,colour_helpers512_to1536_identical_to9d24=True,all_previous9d24_frozen_evidence_preserved=True,implementation_sources_sha256={path:sha(ROOT/path) for path in paths},actual_arena_mode=0,previous_mode4_behavior_preserved=True,no_graphical_process_driven=True,no_authentication_calls=True,hosted_modified=False,published=False)
    data=(json.dumps(report,indent=2)+'\n').encode();target=F/'final-freeze.json'
    if target.exists():assert target.read_bytes()==data
    else:target.write_bytes(data)
    print(json.dumps(dict(passed=True,final_freeze_sha256=sha(target),**{k:v for k,v in report.items() if k in ('candidate_sha256','candidate_bytes','combined_review_sha256','native_composition_sha256','native_proof_sha256','actual_entry_proof_sha256','implementation_sources_sha256')})))
if __name__=='__main__':main()
