"""Reuse the owned public two-account arena fixture for UI scale QA.

Pins the currently published .11 manifest. Only explicit start/cleanup use
public gameplay connections; --status reads the owned checkpoint through SSH.
No native UI input, client launch, account creation or deployment occurs here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import re
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import prepare_graphical_arena_match as matches
from tools import prepare_hosted_graphical_qa as assets
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, PRIVATE, require
from tools import ui_scale_battle_preservation as epochs
from tools import ui_scale_battle_assets as arena_assets

MANIFEST_SHA = 'b05f5ff717480e540dde4c13d152e2169861cc29d86801ee4ee591da8f079e6f'
FIXTURE = PRIVATE/'qsa1496217.json'
OUTPUT = ROOT/'reports/ui-modernization/graphical/battle'
EPOCH = OUTPUT/'current-epoch.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('status', 'prepare-epoch', 'preservation', 'validate-retained', 'start', 'cleanup'))
    parser.add_argument('--native-pids', type=int, nargs=2)
    parser.add_argument('--failed-report', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(dict(epoch=epochs.self_test(),assets=arena_assets.self_test())));return
    require(args.action is not None, 'An explicit action is required')
    fixture = FreshSurroundingsQA.load_private(FIXTURE)
    matches.validate_fixture(fixture, 0)
    require(len(fixture.names) == 2 and fixture.host == '185.184.42.88', 'Exact retained owned QA pair required')
    epochs.validate_fixture(fixture)
    matches.OUTPUT = OUTPUT
    matches.VERSION = '2026.10.09.11'
    path = matches.match_report_path(fixture, 'reservation', 0)
    if args.action == 'status':
        result = matches.own_state(fixture, 0)
    elif args.action == 'prepare-epoch':
        state=matches.own_state(fixture,0)
        require(state['established_connections']==0 and state['checkpoint'] is None and state['pending_settlements']==0,
                'Epoch backup requires no online player, checkpoint or pending settlement')
        result=epochs.prepare(fixture,EPOCH)
        result['action']='prepare-epoch'
    else:
        receipt=epochs.validate_receipt(json.loads(EPOCH.read_text(encoding='utf-8')))
        fixture=epochs.CurrentEpochFixture.wrap(fixture,receipt)
        if args.action=='preservation':
            result=fixture.preservation();result['action']='preservation'
        elif args.action=='validate-retained':
            require(args.failed_report is not None,'Retained validation requires the exact failed start report')
            result=validate_retained(fixture,path,args.failed_report,receipt)
        elif args.action=='start':
            result=start(fixture,path)
        else:
            require(args.native_pids is not None, 'Cleanup requires both observed owned native PIDs')
            saved=json.loads(path.read_text(encoding='utf-8'))
            require(saved['preservation_before']['epoch_backup']==receipt['backup'] and
                    saved['preservation_before']['epoch_metadata_sha256']==receipt['metadata_sha256'],
                    'Cleanup must retain the exact original QA start epoch')
            result=matches.cleanup(fixture,'reservation',path,args.native_pids,0)
    fields = ('action','passed','city','mode','match','ground_sha256','scene','participants','bots',
              'checkpoint_preserved','checkpoint_cleared','service','integrity','established_connections',
              'pending_settlements','checkpoint','backup','metadata_sha256','source_files','online',
              'archival_ownership_unchanged','existing_account_rows_preserved','epoch_backup',
              'excluded_owned_pair_on_both_sides','hosted_code_config_unchanged','match_started')
    print(json.dumps({k:result[k] for k in fields if k in result}, ensure_ascii=False))


def start(fixture,path):
    # Both generic before/after preservation calls now use the exact fresh
    # epoch. Every inherited mutation still runs archival OWNERSHIP.
    from tools.hosted_stage9_graphical_qa_revision3 import https
    raw = https(assets.ORIGIN+'manifest.json', 8*1024*1024)
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, 'Reviewed public .11 manifest moved')
    namespace=dict(matches.start.__globals__)
    namespace['published_scene']=arena_assets.published_scene
    scoped=types.FunctionType(matches.start.__code__,namespace,'start_ui_scale_owned_match',matches.start.__defaults__)
    scoped.__kwdefaults__=matches.start.__kwdefaults__
    return scoped(fixture,'reservation',path,0)


def validate_retained(fixture,path,failed_path,receipt):
    failed_path=failed_path.resolve()
    require(failed_path.parent==OUTPUT.resolve() and
            re.fullmatch(re.escape(fixture.prefix)+r'-reservation-start-failed-[0-9]+\.json',failed_path.name),
            'Only the dedicated failed owned UI match report may be completed')
    saved=json.loads(failed_path.read_text(encoding='utf-8'))
    require(saved.get('action')=='start' and saved.get('owned_roster_verified') is True and
            saved['city']=='reservation' and saved['host']==fixture.host and saved['accounts']==fixture.names and
            saved['mode']==0 and saved['participants']==2 and saved['bots']==0 and
            saved['fixture_private_path']==fixture.credential_path and saved['client_version']=='2026.10.09.11' and
            re.fullmatch('[0-9a-f]{64}',saved['ground_sha256']) is not None,
            'Failed start did not prove this exact owned real match')
    require(saved['preservation_before']['epoch_backup']==receipt['backup'] and
            saved['preservation_before']['epoch_metadata_sha256']==receipt['metadata_sha256'],
            'Retained validation must keep the exact original QA start epoch')
    state=matches.own_state(fixture,0)
    matches.validate_retained(state,fixture,'reservation',saved['match'],saved['ground_sha256'],complete=True,mode=0)
    snapshot=fixture.snapshot(fixture.names)
    matches.validate_start_snapshot(snapshot,fixture,'reservation',saved['ground_sha256'],0)
    manifest=matches.fetch_json('https://'+fixture.host+'/updates/manifest.json')
    resource=arena_assets.published_scene(fixture.host,manifest,saved['scene'],38)
    # All deferred asset guards must pass before evidence becomes a cleanup
    # record. This does not create a match, send packets or change a checkpoint.
    state=matches.own_state(fixture,0)
    checkpoint=matches.validate_retained(state,fixture,'reservation',saved['match'],saved['ground_sha256'],complete=True,mode=0)
    protected=fixture.preservation_during_owned_match(saved['match'])
    result=dict(saved)
    result.update(passed=True,checkpoint_preserved=True,report=str(path),
                  original_failed_report=str(failed_path),original_start_asset_checker_rejected=True,
                  deferred_asset_validation_passed=True,match_restarted=False,
                  preservation_during_retained=protected,
                  final_checkpoint_status=checkpoint['status'],
                  published_resource=dict(path=resource['path'],sha256=resource['sha256'],
                    models=resource['native']['model_count'],sides=sorted(resource['alpha_proof']['four_sides']),
                    corners=sorted(resource['alpha_proof']['four_corners']),
                    model_dependencies=len(resource['model_dependencies']),
                    actual_client_version=resource['actual_client_version'],
                    actual_manifest_sha256=resource['actual_manifest_sha256'],
                    all_inherited_arena_records_exact=resource['all_inherited_arena_records_exact']))
    result.pop('error_type',None)
    proof_path=path.with_name(path.stem+'-retained-assets.json')
    matches.write_report(proof_path,resource)
    if path.exists():
        stamp=hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        path.with_name(path.stem+'-previous-'+stamp+'.json').write_bytes(path.read_bytes())
    matches.write_report(path,result)
    return result


if __name__ == '__main__':
    main()
