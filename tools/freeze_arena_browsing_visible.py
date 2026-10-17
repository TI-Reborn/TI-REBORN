"""Freeze the scoped real-Show correction and all byte/source evidence."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-main-list-visibility'
OLD=F.parent/'client-empty-roster-navigation'
from deploy import client_arena_browsing_visible as patcher
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    source=(F.parent/'client-freshness/silver.dll').read_bytes();candidate=(F/'silver.dll').read_bytes()
    assert patcher.patch(source)==candidate and sha(F/'silver.dll')=='e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80'
    assert sha(OLD/'silver.dll')=='8735e66a1495b124f935432bebaa413f94dbcc9d4f4f00cb502911656e3bbb0b'
    assert sha(OLD/'combined-review.json')=='b0d48ee0a678c5bd77c3a1306ff5e7972efb8cecd51eba5e5c91a5a0071ff963'
    assert sha(OLD/'native-composition.json')=='a83e5c0358e60924f0f33aab0dbec143a522828e31326d765b5822279eac2369'
    assert sha(OLD/'native-navigation-proof.json')=='8e23fe551f59e3c0c2c5e6810a5672e49266d3843fcfcae0ef04feb32bdf5822'
    assert sha(OLD/'final-freeze.json')=='d6a54491fa22c30cd7c9c175de7d40cb0d3a4326ce2dc96e7779df64ea93e0c3'
    old=(OLD/'silver.dll').read_bytes();assert candidate[len(source):len(source)+0x600]==old[len(source):len(source)+0x600]
    reports={}
    for name in ('combined-review.json','native-composition.json','native-navigation-proof.json','actual-native-window-flow-proof.json','bridge-static-guards.json'):
        value=json.loads((F/name).read_text(encoding='utf8'))
        if name!='combined-review.json':assert value['passed'] and value['candidate_sha256']==sha(F/'silver.dll')
        reports[name]=sha(F/name)
    flow=json.loads((F/'actual-native-window-flow-proof.json').read_text(encoding='utf8'))
    assert flow['no_window_lookup_bypass'] and flow['no_show_or_OnShow_or_event_dispatch_stubs']
    paths=['deploy/client_arena_lobby_navigation.py','deploy/client_arena_lobby_search_status.py',
           'deploy/client_arena_empty_roster_navigation.py','deploy/client_arena_browsing_visible.py',
           'deploy/client_equipment_batch.py','deploy/client_server_list_status.py',
           'tools/build_arena_browsing_visible_native.py','tools/verify_arena_browsing_visible_native.py',
           'tools/verify_arena_browsing_window_flow_native.py','tools/hosted_graphical_qa_bridge.py',
           'tools/verify_hosted_graphical_bridge_browsing_visible.py','tools/freeze_arena_browsing_visible.py']
    pins={path:sha(ROOT/path) for path in paths}
    for path in paths:
        target=F/'source'/path;target.parent.mkdir(parents=True,exist_ok=True);data=(ROOT/path).read_bytes()
        if target.exists():assert target.read_bytes()==data
        else:target.write_bytes(data)
    composition=json.loads((F/'native-composition.json').read_text(encoding='utf8'))
    report=dict(passed=True,source_sha256=sha(F.parent/'client-freshness/silver.dll'),source_bytes=len(source),
                previous8735_sha256=sha(OLD/'silver.dll'),candidate_sha256=sha(F/'silver.dll'),candidate_bytes=len(candidate),
                report_sha256=reports,implementation_sources_sha256=pins,
                original_selected_scan_preserved=True,selector_and_colour_helpers_first1536_bytes_unchanged=True,
                all_prior_frozen_evidence_preserved=True,declared_original_ranges=14,
                native_preservation=composition['preservation'],native_authentication_guard_count=16,
                actual_Arena_first_entry_mode=0,actual_category_callbacks=['875630','8755bc'],
                complete_registry_Show_OnShow_event_dispatch_executed=True,
                first_entry_and_subsequent_OnShow_cases=len(flow['first_entry_and_subsequent_OnShow_cases']),
                original_empty_selected_regression_cases=len(flow['original_empty_squad_hide_regressions']),
                jail_and_other_category_guards=len(flow['other_categories_and_jail_guards']),
                actual_owned_gui_before_sha256=sha(F/'owned-d-main-transition-before-fix.json'),
                real_graphical_candidate_clients=0,authentication_calls=0,hosted_modified=False,published=False)
    data=(json.dumps(report,indent=2)+'\n').encode();target=F/'final-freeze.json'
    if target.exists():assert target.read_bytes()==data
    else:target.write_bytes(data)
    print(json.dumps(dict(passed=True,final_freeze_sha256=sha(target),**{key:report[key] for key in ('candidate_sha256','candidate_bytes','report_sha256','implementation_sources_sha256')})))
if __name__=='__main__':main()
