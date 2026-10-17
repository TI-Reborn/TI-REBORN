"""Aggregate offline proof provenance for the frozen 099 UI scale core.

Does not alter binaries, source transformers, upstream proof reports, gameplay,
processes, or hosted state. Purely reconstructs the core and verifies report
identities/counts before writing one independent provenance summary.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_ui_scale as core

BASE_SHA = '7a58e792614a179cfef1920e7f2d3b1775bc573ef0c39c8dc00eef3ccf23a8a8'
CORE_SHA = '0993172e8d25b1cbc671be8d1203d3be0ab607ef9949aa29ab50769f375b3061'


def require(value, message):
    if not value:
        raise ValueError(message)


def evidence(path):
    path = ROOT / path
    data = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'modified_utc': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def report(path):
    location = ROOT / path
    return json.loads(location.read_text(encoding='utf-8-sig')), evidence(path)


def aggregate():
    source_path = 'reports/screen-settings/client/silver.dll'
    candidate_path = 'reports/ui-scale/core/silver.dll'
    source = (ROOT / source_path).read_bytes()
    candidate = (ROOT / candidate_path).read_bytes()
    require(hashlib.sha256(source).hexdigest() == BASE_SHA, 'Published .11 baseline identity changed')
    require(hashlib.sha256(candidate).hexdigest() == CORE_SHA, 'Frozen 099 core identity changed')
    require(core.patch(source) == candidate, 'Current core source does not reconstruct the frozen candidate')
    native, native_ref = report('reports/ui-scale/core/native-proof.json')
    static, static_ref = report('reports/ui-scale/core/static-proof.json')
    inventory, inventory_ref = report('reports/ui-modernization/inventory-scrollbar-native-proof.json')
    build, build_ref = report('reports/ui-scale/core/build-proof.json')
    require(native['result'] == static['result'] == inventory['result'] == 'PASS', 'Upstream proof did not pass')
    require(native['candidate_sha256'] == static['candidate_sha256'] == inventory['core_candidate_sha256']
            == build['candidate_sha256'] == CORE_SHA, 'Proof candidate identities differ')
    require(build['base_sha256'] == inventory['source_sha256'] == BASE_SHA, 'Proof source baseline identities differ')
    require(native['cases'] == len(native['details']) == 534, 'Native proof case count differs')
    require(len(static['native_gui_callees']) == 19 and static['callee_stack_argument_bytes'] == 0,
            'Static ABI proof count/contract differs')
    require(inventory['cases'] == 468 and inventory['native_cases'] == len(inventory['rows']) == 256
            and inventory['product_helper_cases'] == len(inventory['product_rows']) == 212,
            'Independent native inventory case counts differ')
    require(inventory['stubs'] == [] and inventory['candidate_helper_verified'] is True,
            'Independent inventory proof must execute the actual native paths without stubs')
    native_bases = sorted({row['base'] for row in native['details']})
    inventory_bases = sorted({row['base'] for row in inventory['rows'] + inventory['product_rows']})
    require(native_bases == inventory_bases == ['0x10400000', '0x400000'], 'Expected preferred/relocated basis coverage')
    require(static['published_screen_payload_preserved'] is True and static['pe_sections'] == 13,
            'Published display payload or PE section layout changed')
    require(native['windows_apis_stubbed'] is True and native['native_manager_and_reflow_stubbed'] is True
            and native['actual_native_resize_and_rect_code_executed'] is True,
            'Native proof declared execution boundary differs')
    for item in (native, static, build):
        require(item['real_client_rendering_verified'] is False, 'Offline report should not claim graphical QA')
    require(inventory['graphical_validation'] is False and inventory['published'] is False,
            'Inventory report should not claim publication or graphical QA')
    return {
        'schema': 1, 'result': 'PASS', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'creator': 'tools/aggregate_ui_scale_core_proof.py', 'core_candidate_sha256': CORE_SHA,
        'baseline_sha256': BASE_SHA, 'candidate_bytes': len(candidate),
        'core_current_transformer_reconstructs_exact_candidate': True,
        'baseline': evidence(source_path), 'candidate': evidence(candidate_path),
        'core_transformer': evidence('deploy/client_ui_scale.py'), 'build_report': build_ref,
        'proofs': [
            {'kind': 'Unicorn UI-scale/input/rendering-boundary cases', 'cases': 534,
             'report': native_ref, 'verifier': evidence('tools/verify_client_ui_scale_native.py'),
             'bases': native_bases, 'case_kinds': dict(Counter(row['kind'] for row in native['details'])),
             'execution': 'Patched native x86 code in synthetic fixtures; Windows APIs and manager/reflow calls stubbed; actual native resize/rect code executes.'},
            {'kind': 'Static native callee ABI/flush/world-boundary proof', 'cases': 19,
             'report': static_ref, 'verifier': evidence('tools/verify_client_ui_scale_static.py'),
             'execution': 'Reachable native instructions, RET0/no positive EBP stack arguments; immutable screen payload and physical-world callsites checked.'},
            {'kind': 'Independent inventory native and direct product-helper cases', 'cases': 468,
             'native_cases': 256, 'direct_product_helper_cases': 212,
             'report': inventory_ref, 'verifier': evidence('tools/verify_inventory_layout_native.py'),
             'bases': inventory_bases, 'stubs': [],
             'execution': 'Actual native x86/X87 inventory and scrollbar methods plus patched helpers execute against synthetic guarded objects; inventory/selection/filter/cache/stack canaries checked.'}
        ],
        'preservation': {'published_screen_runtime_byte_identical': True, 'pe_sections': 13,
                         'physical_3d_backbuffer_and_world_picking_unchanged': True,
                         'requested_scale_retained': True, 'minimum_logical_canvas': [800, 768],
                         'inventory_gui_reconstruction': False, 'server_requests_from_helpers': False},
        'provenance_limit': 'Upstream reports embed candidate SHA identities. Current verifier source hashes are recorded here; original upstream reports do not embed their original verifier-source hashes.',
        'actual_game_clients_checked_by_this_aggregate': False,
        'hosted_gameplay_validated_by_this_aggregate': False,
        'graphical_qa_is_separate_evidence': True, 'published': False, 'remote_mutations': 0,
        'sources_or_binaries_modified': False,
        'aggregate_source': evidence('tools/aggregate_ui_scale_core_proof.py')
    }


if __name__ == '__main__':
    output = ROOT / 'reports/ui-modernization/core-099-proof-provenance.json'
    result = aggregate()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('PASS: frozen core099 provenance — native534, static19, independent inventory468')
