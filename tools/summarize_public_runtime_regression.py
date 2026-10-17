"""Combine immutable bounded public runs without relabelling failures as PASS."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from tools.verify_public_runtime_regression import BASE_FOLDER, ROOT, sha


def classify(test,detail):
    if test.startswith('test_assault_arena.'):
        return 'runtime_defect','Ordinary arena gate rejected trusted assault maps outside town 7; scoped stage9 team_scene fix.'
    if "BattleField' object has no attribute 'combat'" in detail:
        return 'runtime_defect','Optional combat subsystem was dereferenced in AP cleanup/disconnect; scoped stage9 arena_service fix.'
    if test.startswith(('test_private_market.','test_trade_window_refresh.')):
        return 'runtime_defect','Passive city polling opens AE/F8 market UI without a user query; scoped stage9 revision2 private_market fix.'
    if test.startswith('test_login_economy_boundary.'):
        return 'undeployed_local_contract','Local-only helper initialize_character_economy and changed login expectations belong to another uninstalled source revision; installed public multi.py remains pinned.'
    if test.startswith('unittest.loader._FailedTest.test_assault_public'):
        return 'pending_stage9_test','New assault_public test was created during initial test freeze, before its runtime module was installed; retained initial error and explicitly excluded from .5 continuation.'
    if test.startswith('test_armor_models.'):
        return 'external_client_artifact','Requires original Windows meshes, unavailable in isolated Linux public runtime; retained initial failure and explicitly excluded on continuation.'
    if test.startswith('test_mail_protocol.'):
        return 'external_client_artifact','Original Silver DLL census cannot run on Linux; native verification remains separate.'
    if test.startswith('test_character_slots.'):
        return 'test_synchronization','The queued C8 bootstrap predates purchase processing. Original native ping barrier proves authoritative secondary SC2700, two purchased items, primary SC10000 preserved; see tcp-slot-sync-diagnosis.json.'
    if test in ('test_multi_account.MultiAccountTests.test_premium_purchase_and_personal_shop_prices','test_multi_account.MultiAccountTests.test_city_weapon_swap_tcp_persists_and_is_account_isolated'):
        return 'timing_sensitive_test','Unchanged .5 isolated focused rerun passed and SQL inventory/wallet matched expected final state; first-frame assertions can select queued city refreshes. Initial failures remain retained.'
    if test.startswith('test_starting_funds.'):
        return 'test_bundle_dependency','Readonly snapshot selected registration Python but omitted public HTML templates. Isolated diagnosis confirms jinja2.TemplateNotFound register.html; report remains ERROR.'
    if test.startswith('test_shared_special_items.'):
        return 'outdated_test_assertion','Rejected mine leaves every account/item/gameplay payload unchanged; only battle_checkpoints.revision increments 8 to 9 under the existing durable unit. Exact diagnosis in candidate9 failure-state-diagnosis.json.'
    if test.startswith('test_forest_encounters.'):
        return 'outdated_test_fixture','Fixture attempts a shop sale while saved character still travels; current sale requires a city. Complete the authoritative journey before testing city sale.'
    if test.startswith('test_appearance.'):
        return 'outdated_test_fixture','Starter onboarding now creates character_onboarding before fixture CREATE TABLE; do not duplicate schema creation.'
    if test.startswith(('test_battle_weapon_regressions.','test_survival_scene.')):
        return 'outdated_test_assertion','Exact packet census predates installed F7 battle-item projection; verify semantic packets plus the new projection.'
    if test.startswith(('test_miners.','test_weapon_damage_xml.','test_weapon_skill_damage.','test_weapons.','test_weight.')):
        return 'outdated_catalog_assertion','Original fixed catalog census predates added towns, smoke/flash nondamaging weapons, flare and item boosters; compare original entries and explicit extension semantics.'
    return 'unclassified','Requires investigation; never silently skip or relabel.'


def main():
    target=BASE_FOLDER/'baseline-combined.json'
    if target.exists():raise ValueError('Preserve earlier combined evidence')
    names=('hosted-isolated.json','hosted-isolated-batch-01.json','hosted-isolated-batch-02.json','hosted-isolated-batch-03.json')
    snapshot=json.loads((BASE_FOLDER/'snapshot.json').read_text())
    runs=[];all_records=[];by_test=defaultdict(list)
    for name in names:
        path=BASE_FOLDER/name;r=json.loads(path.read_text())
        if r['source_before']!=snapshot['source_sha256'] or r['source_after']!=snapshot['source_sha256']:
            raise ValueError('Actual runtime source pins changed')
        events=path.with_name(path.stem.replace('hosted-isolated','hosted-test-events')+'.jsonl')
        # Runner hashes text before Windows write_text normalizes LF to CRLF.
        event_text=events.read_text(encoding='utf-8')
        if sha(event_text.encode())!=r['events_sha256']:raise ValueError('Event evidence changed')
        rows=[json.loads(line) for line in event_text.splitlines()]
        for row in rows:
            record={**row,'events_file':events.relative_to(ROOT).as_posix()}
            all_records.append(record);by_test[row['test'].split(' (',1)[0]].append(record)
        runs.append(dict(report=path.relative_to(ROOT).as_posix(),sha256=sha(path.read_bytes()),
            bundle_sha256=r['test_bundle_sha256'],events_sha256=r['events_sha256'],
            seconds=r['seconds'],timed_out=r['timed_out'],passed=r['passed'],
            source_unchanged=r['source_unchanged'],outcome_records=dict(Counter(x['outcome'] for x in rows))))
    inventory=json.loads((BASE_FOLDER/names[-1]).read_text())['inventory'];unique=set(inventory)
    plan=json.loads((BASE_FOLDER/'plan-batch-03.json').read_text())
    failures=[]
    for record in all_records:
        if record['outcome']=='passed':continue
        category,reason=classify(record['test'],record.get('detail',''))
        failures.append({**record,'category':category,'classification':reason})
    unique_outcomes=Counter()
    for test in unique:
        outcomes={r['outcome'] for r in by_test[test]}
        outcome=next((x for x in ('error','failure','skipped','passed') if x in outcomes), 'missing')
        unique_outcomes[outcome]+=1
    duplicate_pass={test:len([r for r in rows if r['outcome']=='passed']) for test,rows in by_test.items()
                    if len([r for r in rows if r['outcome']=='passed'])>1}
    report=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
        installed_feature_version='2026.10.08.5',passed=False,
        coverage_complete=not(unique-by_test.keys()),selected_modules=plan['selected_modules'],
        selected_module_count=len(plan['selected_modules']),excluded_modules=plan['excluded_modules'],excluded_tests=plan['excluded_tests'],
        inventory_entries=len(inventory),unique_testcase_ids=len(unique),
        loader_duplicate_ids={k:v for k,v in Counter(inventory).items() if v>1},
        completed_unique_testcase_ids=len(unique&by_test.keys()),unique_testcase_outcomes=dict(unique_outcomes),
        missing_test_ids=sorted(unique-by_test.keys()),repeated_passed_test_ids=duplicate_pass,
        retained_initial_records_outside_corrected_inventory=sorted(by_test.keys()-unique),
        all_record_outcomes=dict(Counter(r['outcome'] for r in all_records)),
        nonpass_records=failures,classification_record_counts=dict(Counter(r['category'] for r in failures)),
        source_sha256=snapshot['source_sha256'],runtime_source_count=len(snapshot['source_sha256']),runs=runs,
        aggregate_seconds=round(sum(r['seconds'] for r in runs),3),
        resumed_only_unfinished=True,hosted_player_data_opened=False,hosted_player_data_copied=False,
        hosted_runtime_modified=False,graphical_client_acceptance=False,
        limitations=['A complete selected public suite finished across bounded processes, but it did not pass.',
            'One native Windows Silver builder testcase is explicitly skipped on Linux and requires separate client proof.',
            'Original failed records remain visible, including fixtures and undeployed local expectations.',
            'No graphical game-client acceptance was performed by this runner.'])
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('coverage_complete','passed','inventory_entries','unique_testcase_ids','completed_unique_testcase_ids','unique_testcase_outcomes','classification_record_counts')}))


if __name__=='__main__':main()
