"""Run focused tests in a copy of hosted code; no live database/service writes."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path('/opt/tio-emulator')
PATCH = Path('/root/tio-arena-surroundings-patch.tar.gz')
TESTS = Path('/root/tio-arena-surroundings-tests.tar.gz')
REPORT = Path('/root/tio-arena-surroundings-candidate.json')
SERVER_FILES = {'tio/arena_map.py', 'tio/map_generation.py', 'tio/arena_surroundings.py',
                'config/battle_map_profiles.json', 'config/arena_surroundings.json'}
BASELINE_FILES = SERVER_FILES | {'config/arena_fragments.json', 'config/reservation_visuals.json', 'tio/protocol/battle_ground.py'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def extract(archive, destination):
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        if len({member.name for member in members}) != len(members):
            raise RuntimeError('Duplicate archive path')
        if not all(member.isfile() and (destination / member.name).resolve().is_relative_to(destination)
                   for member in members):
            raise RuntimeError('Unsafe archive path or type')
        stream.extractall(destination, filter='data')


def main():
    candidate = Path(tempfile.mkdtemp(prefix='tio-arena-surroundings-candidate-', dir='/root')).resolve()
    report = dict(passed=False, candidate=str(candidate), patch_sha256=digest(PATCH),
                  tests_archive_sha256=digest(TESTS), kind='isolated hosted code overlay and temporary SQLite fixtures; no graphical clients',
                  checks=[])
    try:
        shutil.copytree(ROOT, candidate, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.pyc', '.git'))
        extract(PATCH, candidate)
        guard = json.loads((candidate / 'guard.json').read_text())
        if set(guard['server_files']) != SERVER_FILES or set(guard['baseline_files']) != BASELINE_FILES or digest(TESTS) != guard['tests_archive_sha256']:
            raise RuntimeError('Unexpected candidate scope or test archive')
        for name, expected in guard['baseline_files'].items():
            if digest(ROOT / name) != expected:
                raise RuntimeError('Hosted baseline changed: ' + name)
        for name, entry in guard['server_files'].items():
            if digest(candidate / name) != entry['after']:
                raise RuntimeError('Candidate source differs from packaged guard: ' + name)
        if digest(Path('/var/www/tio-client/updates/manifest.json')) != guard['baseline_client_manifest_sha256']:
            raise RuntimeError('Published baseline changed')
        extract(TESTS, candidate)
        for name, expected in guard['candidate_only_fixture_files'].items():
            if not (candidate / name).resolve().is_relative_to(candidate) or digest(candidate / name) != expected:
                raise RuntimeError('Candidate-only fixture differs from the prepared release')
        environment = dict(os.environ, PYTHONPATH=str(candidate) + os.pathsep + str(candidate / 'tests'),
                           PYTHONDONTWRITEBYTECODE='1')
        for pattern in guard['test_patterns']:
            if not re.fullmatch(r'test_[a-z_]+\.py', pattern) or not (candidate / 'tests' / pattern).is_file():
                raise RuntimeError('Required candidate test is missing or unsafe')
            result = subprocess.run([str(ROOT / '.venv/bin/python'), '-m', 'unittest', 'discover',
                                     '-s', 'tests', '-p', pattern, '-v'], cwd=candidate,
                                    env=environment, capture_output=True, text=True, timeout=300)
            log = result.stdout + result.stderr
            (candidate / (pattern + '.log')).write_text(log)
            counts = re.findall(r'Ran (\d+) tests?', log)
            count = int(counts[-1]) if counts else 0
            check = dict(pattern=pattern, tests=count, passed=result.returncode == 0 and count > 0)
            report['checks'].append(check)
            print(json.dumps(check), flush=True)
            if not check['passed']:
                print(log, flush=True)
                raise RuntimeError('Candidate checks failed: ' + pattern)
        report.update(passed=True, guard_sha256=digest(candidate / 'guard.json'),
                      total_tests=sum(check['tests'] for check in report['checks']))
    finally:
        REPORT.write_text(json.dumps(report, indent=2) + '\n')
        REPORT.chmod(0o600)
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
