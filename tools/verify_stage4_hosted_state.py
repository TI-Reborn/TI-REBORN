"""Read-only post-acceptance health and source parity; never export player rows."""
from pathlib import Path
import hashlib
import json
import shlex
import subprocess

from inspect_stage4_economy import REMOTE

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/stage4-economy'


def main():
    deployment = json.loads((REPORT / 'deployment.json').read_text(encoding='utf-8'))
    baseline = json.loads((REPORT / 'remote-baseline.json').read_text(encoding='utf-8'))
    expected = deployment['source_sha256']
    command = ['ssh', '-i', str(Path.home() / '.ssh/tio_server'), '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=15', 'root@185.184.42.88', 'python3 -c ' + shlex.quote(REMOTE)]
    completed = subprocess.run(command, input=json.dumps({'files': list(expected)}),
                               text=True, encoding='utf-8', capture_output=True, timeout=90)
    if completed.returncode:
        raise RuntimeError('Read-only post-deployment health inspection failed')
    actual = json.loads(completed.stdout)
    for name, entry in actual['files'].items():
        entry.pop('source', None)
        entry['local_sha256'] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    actual['source_parity'] = all(entry['sha256'] == expected[name] == entry['local_sha256']
                                  for name, entry in actual['files'].items())
    actual['configuration_launcher_manifest_unchanged'] = actual['guards'] == baseline['guards']
    service_lines = {name: dict(line.split('=', 1) for line in value.splitlines())
                     for name, value in actual['services'].items()}
    actual['all_services_active_without_failure'] = all(
        value['ActiveState'] == 'active' and value['ExecMainStatus'] == '0'
        and value['NRestarts'] == '0' and int(value['MainPID']) > 0
        for value in service_lines.values())
    actual['retained_battle_members'] = actual['tables']['battle_checkpoint_members']['rows']
    actual['passed'] = (actual['integrity'] == 'ok' and actual['source_parity']
                        and actual['configuration_launcher_manifest_unchanged']
                        and actual['all_services_active_without_failure'])
    actual['scope'] = ('Read-only hosted health after QA. QA adds its own two accounts and '
                       'gameplay records; deployment.json proves all pre-update data was preserved.')
    (REPORT / 'hosted-final-state.json').write_text(json.dumps(actual, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: actual[key] for key in (
        'timestamp_utc', 'passed', 'source_parity', 'configuration_launcher_manifest_unchanged',
        'services', 'established_game_connections', 'retained_battle_members', 'unfinished_battle_rows')}))
    if not actual['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
