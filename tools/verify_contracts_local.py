"""Run bounded local checks and save their actual results without any hosting I/O."""
import json
import argparse
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    'test_travel_party', 'test_pve_contracts', 'test_party_travel',
    'test_contract_scene', 'test_contracts_combat', 'test_contracts_service',
    'test_contracts_local_tcp', 'test_contracts_native_research',
    'test_shared_team_arena', 'test_presence', 'test_reward_policy',
    'test_map_generation', 'test_battle_crash_recovery',
    'test_shared_mine_arena', 'test_shared_mine_disconnect',
    'test_multi_account', 'test_prepare_contracts_local',
    'test_contracts_city_assets', 'test_contracts_city_native',
    'test_prepare_contracts_city_local', 'test_login_economy_boundary',
    'test_contracts_chat_native',
    'test_contracts_map_view_native',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', nargs='+', choices=CHECKS,
                        help='Repeat selected suites and merge their actual results into the complete report.')
    args = parser.parse_args()
    output = ROOT/'reports/contracts-local/verification'
    output.mkdir(parents=True, exist_ok=True)
    retained = {}
    if args.only:
        previous = json.loads((output/'checks.json').read_text(encoding='utf-8'))
        retained = {row['name']: row for row in previous['checks']}
        if set(retained)-set(CHECKS) or set(CHECKS)-set(retained)-set(args.only):
            parser.error('A complete report for all unselected suites is required before a selective repeat.')
    results = []
    for name in args.only or CHECKS:
        started = time.monotonic()
        command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', name+'.py']
        run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=90)
        log = run.stdout+run.stderr
        (output/(name+'.log')).write_text(log, encoding='utf-8')
        count = re.search(r'Ran (\d+) tests?', log)
        passed = run.returncode == 0 and count is not None
        row = dict(name=name, tests=int(count.group(1)) if count else 0,
                   passed=passed, exit_code=run.returncode, seconds=round(time.monotonic()-started, 2))
        results.append(row)
        print(f"{name}: {'PASS' if passed else 'FAIL'}, {row['tests']} tests", flush=True)
    if args.only:
        retained.update({row['name']: row for row in results})
        results = [retained[name] for name in CHECKS]
    report = dict(scope='Local temporary databases, real loopback TCP accounts, native x86 probes and city resource/install checks',
                  graphical_clients_tested=0, hosted_connections=0,
                  passed=all(row['passed'] for row in results), tests=sum(row['tests'] for row in results),
                  checks=results)
    if args.only:
        report['selectively_repeated'] = args.only
    (output/'checks.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
