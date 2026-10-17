"""Bind completed hosted gameplay evidence and update the local progress record.

This reads existing reports only; it never connects to the server or a database.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/gameplay-completion'
WORLD = REPORTS / 'stage8-world'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def main():
    target = REPORTS / 'completion-verification.json'
    require(not target.exists(), 'Preserve existing completion evidence')
    names = ('validation.json', 'deployment.json', 'hosted-world.json',
             'client/publication.json', 'client/https-verification.json')
    evidence = {name: read(WORLD / name) for name in names}
    pins = evidence['deployment.json']['world_client_release']
    for name, report in evidence.items():
        require(report.get('passed') is True, name + ' did not pass')
        require(report.get('world_client_release') == pins,
                name + ' differs from the deployed world release')
    deployment = evidence['deployment.json']
    hosted = evidence['hosted-world.json']
    publication = evidence['client/publication.json']
    https = evidence['client/https-verification.json']
    final = read(WORLD / 'postpublication-state.json')
    runtime = deployment['runtime_files']
    require(len(runtime) == 27 and all(
        final['files'][name]['sha256'] == value for name, value in runtime.items()),
        'Final deployed source pins differ')
    require(final['integrity'] == 'ok' and final['game_connections'] == 0,
            'Final integrity or active game connections differ')
    require(final['service'] == deployment['service_state'],
            'Service changed after the verified deployment')
    require(final['tables']['accounts']['rows'] == 199
            and final['tables']['wallets']['rows'] == 198,
            'Hosted account or wallet counts differ')
    require(all(final['tables'][name]['rows'] == 0 for name in
                ('battle_checkpoints', 'battle_checkpoint_members', 'battle_settlement_jobs')),
            'Hosted scenes or settlement jobs remain')
    require(final['client']['version'] == publication['version']
            == https['version'] == '2026.10.08.5', 'Published version differs')
    require(final['guards']['/var/www/tio-client/updates/manifest.json']
            == publication['manifest_sha256'] == https['manifest_sha256'],
            'Published manifest differs from final host or HTTPS')
    require(https['trusted_https'] is True and publication['service_unchanged'] is True,
            'Publication service or HTTPS verification missing')
    require(final['client']['silver']['sha256']
            == '7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b'
            and final['client']['silver']['size'] == 7761408,
            'Previously published F8 client extension changed')
    for name in ('/etc/tio-server/server.toml', '/etc/systemd/system/tio-server.service'):
        require(final['guards'][name] == publication['guards']['configuration'][name]['sha256'],
                'Protected hosted configuration changed')
    require(all(publication[name] is False for name in
                ('server_restarted', 'database_opened', 'database_written', 'local_player_data_uploaded')),
            'Unexpected publication side effect')
    require(hosted['travel_completion']['completed'] is True
            and hosted['travel_completion']['actual_arrivals'] == 4,
            'Four actual native arrivals required')
    require(all(hosted[name] is True for name in (
        'wallets_inventory_ownership_preserved', 'foreign_state_preserved',
        'experience_and_levels_unchanged', 'awards_unchanged', 'payments_unchanged')),
        'Hosted preservation verification missing')
    progress_path = REPORTS / 'progress.json'
    progress = read(progress_path)
    require([p['order'] for p in progress['phases']] == list(range(1, 9))
            and all(p['status'] == 'complete' for p in progress['phases'][:7]),
            'Previous ordered phases are incomplete')
    stage = progress['phases'][7]
    stage.update(status='complete',
        hosted_verification='reports/gameplay-completion/stage8-world/hosted-world.json',
        hosted_scope='Two ordinary LV1 accounts: four real-clock native journeys, two legal road escapes, Outpost/Detroit level gates, shared22zones and nine Top100 selectors. Wallets/items/XP/foreign saves preserved; actual escape rank penalty20 each and exact existing legacy profile normalization recorded. Positive LV4 battles, eight-account training and Prison covered by isolated tests.',
        client_version='2026.10.08.5',
        client_publication='reports/gameplay-completion/stage8-world/client/publication.json',
        client_verification='reports/gameplay-completion/stage8-world/client/https-verification.json',
        final_host_state='reports/gameplay-completion/stage8-world/postpublication-state.json')
    progress['completion_verification'] = 'reports/gameplay-completion/completion-verification.json'
    result = dict(passed=True, observed_utc=datetime.now(timezone.utc).isoformat(),
        phases=list(range(1, 9)), client_version='2026.10.08.5', runtime_files=27,
        accounts=199, wallets=198, integrity='ok', game_connections=0,
        checkpoints=0, checkpoint_members=0, settlement_jobs=0,
        service=final['service'], world_client_release=pins,
        backup=deployment['backup'], client_backup=publication['backup'],
        graphical_client_acceptance=False,
        stripe='EUR0.01/Gold minimum50; live merchant keys absent, disabled',
        remaining_historical_prizes='36 existing temporary-credit reward policies retained',
        evidence_sha256={name: hashlib.sha256((WORLD/name).read_bytes()).hexdigest()
                         for name in (*names, 'postpublication-state.json')},
        local_player_data_uploaded=False, database_restored=False,
        verification_method='Existing automated/native TLS reports and final read-only host inspection')
    with target.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write('\n')
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, phases=8, client='2026.10.08.5',
                         evidence=str(target), network_actions=0)))


if __name__ == '__main__':
    main()
