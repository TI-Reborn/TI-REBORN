"""Aggregate immutable automated evidence for the deployed 0.1.6 release."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011'
SILVER_SHA = '4897eb6d6af6beb587fc9b303dc6911519d90b3414ae8cca8fd1ffb698c1f082'


def main():
    evidence = {}

    def read(name):
        raw = (FOLDER / name).read_bytes()
        evidence[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    server = read('overall-validation.json')
    deployment = read('deployment.json')
    publication = read('client/deployment/publication.json')
    https = read('client/deployment/publication-https.json')
    native = read('native-proof-final.json')
    texture = read('textures/candidate-final/native-sampler-proof.json')
    gpu = read('textures/gpu-sampler-proof.json')
    runtime = read('textures/runtime-qa-revision2/cleanup-verified-native-runtime-proof.json')
    health = read('release-health.json')
    hosted = read('hosted-lobbies-tls-verified.json')
    assert all(item['passed'] is True for item in (server, publication, https, texture, gpu, runtime, health, hosted))
    assert native['status'] == 'PASS' and native['cases'] == 118 and len(native['join_cases']) == 6
    assert server['checks']['unique_tests'] == 106 and server['checks']['remaining_failures'] == 0
    assert texture['cases'] == 138 and gpu['cases'] == 32
    assert native['candidate_sha256'] == texture['candidate_sha256'] == runtime['candidate_sha256'] == SILVER_SHA
    assert publication['candidates']['silver.dll']['sha256'] == https['candidates']['silver.dll']['sha256'] == SILVER_SHA
    assert deployment['source_sha256'] == health['code_sha256'] == server['source_sha256']
    assert deployment['accounts_preserved'] == 204 and deployment['all_existing_tables_unchanged'] == 163
    assert publication['account_identities_and_credentials_preserved'] and publication['services_unchanged']
    assert not deployment['local_player_data_uploaded'] and not publication['local_player_data_uploaded']
    assert health['database']['integrity'] == 'ok' and health['database']['checkpoints'] == health['database']['settlement_jobs'] == 0
    shared = hosted['shared_battle']
    assert shared['humans'] == 4 and shared['bots'] == 0 and shared['scene_received_by_all']
    assert health['local_launcher']['ready_to_play_observed'] and health['local_launcher']['installed_silver_sha256'] == SILVER_SHA
    report = {
        'passed': True,
        'scope': 'Deployed release and automated/native/TLS verification; graphical battle acceptance remains unverified',
        'verified_utc': datetime.now(timezone.utc).isoformat(),
        'launcher_version': '0.1.6', 'client_release': '2026.10.11.1',
        'silver_sha256': SILVER_SHA,
        'features': {
            'team_wall_main_list': True, 'free_full_search_and_human_occupancy': True,
            'native_join': True, 'levels_1_to_3_authoritative_validation': True,
            'any_owned_eligible_fighter_including_reserves_controls_colour': True,
            'available_colour': 'green/mint', 'no_eligible_owned_fighter_colour': 'red',
            'saved_squad_preserved_for_reserve_join': True,
            'linear_texture_filtering_active_in_actual_native_startup': True,
            'raster_assets_modified': False,
        },
        'checks': {'server_tests': 106, 'native_list_colour_cases': 118,
                   'native_join_writers': 6, 'native_texture_cases': 138,
                   'actual_d3d9_hal_cases': 32, 'real_hidden_launcher_startup': True,
                   'visible_launcher_updated_ready': True},
        'hosted_tls': shared,
        'preservation': {'original_accounts': 204, 'original_tables': 163,
                         'all_original_account_save_rows_verified': True,
                         'own_qa_and_normal_timer_changes_audited': True,
                         'local_player_data_uploaded': False,
                         'details': 'hosted-lobbies-tls-verified.json'},
        'backups': {'server': deployment['backup'], 'client': publication['backup']},
        'health': {'service': health['service'], 'database': health['database']},
        'limitations': ['Graphical multiplayer battle has not been visually verified in game windows.',
                        'Filtering reduces sampling aliasing; grain drawn into source images is preserved.',
                        'All-texture visual clarity and complete grain removal are not established.'],
        'evidence_sha256': evidence,
    }
    target = FOLDER / 'acceptance.json'
    with target.open('x', encoding='utf-8') as out:
        json.dump(report, out, indent=2)
        out.write('\n')
    print(json.dumps({'passed': True, 'release': report['client_release'], 'report': str(target)}, indent=2))


if __name__ == '__main__':
    main()
