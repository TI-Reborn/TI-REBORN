"""Check a bounded lobby candidate against actual hosted code and catalogs."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

from tools import verify_public_runtime_regression as public
from tools import deploy_gameplay_completion as deployment

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot','check'))
    parser.add_argument('--files', nargs='+')
    parser.add_argument('--tests', nargs='+')
    args = parser.parse_args()
    stage = FOLDER / 'isolated-runtime'
    if args.action == 'snapshot':
        if stage.exists():
            raise ValueError('Preserve prior isolated snapshot')
        snapshot = public.remote(public.SNAPSHOT, {}, timeout=90)
        archive = base64.b64decode(snapshot.pop('archive'), validate=True)
        stage.mkdir()
        public.extract(archive, stage)
        baseline = json.loads((FOLDER/'remote-baseline.json').read_text(encoding='utf-8'))
        for name, entry in baseline['files'].items():
            if snapshot['source_sha256'].get(name) != entry['sha256']:
                raise ValueError('Actual runtime changed since inspected baseline: '+name)
        with (FOLDER/'isolated-snapshot.json').open('x', encoding='utf-8') as out:
            json.dump(snapshot, out, indent=2)
        print(json.dumps({'source_files':len(snapshot['source_sha256']),
                          'hosted_player_data_opened':False}))
        return
    if not args.files or not args.tests:
        raise ValueError('Explicit bounded runtime and test selections required')
    snapshot = json.loads((FOLDER/'isolated-snapshot.json').read_text(encoding='utf-8'))
    # Each verification keeps its own candidate tree and diagnostics, including
    # failed attempts. A fresh remote snapshot cannot silently change a baseline.
    current = public.remote(public.SNAPSHOT, {}, timeout=90)
    if current['source_sha256'] != snapshot['source_sha256']:
        raise ValueError('Hosted source changed since the reviewed snapshot')
    stage = Path(tempfile.mkdtemp(prefix='candidate-runtime-', dir=FOLDER))
    public.extract(base64.b64decode(current.pop('archive'),validate=True), stage)
    source_hashes = {}
    for name in args.files:
        if not deployment.valid_path(name):
            raise ValueError('Unsafe candidate source')
        source = deployment.source_path(FOLDER, name)
        raw = source.read_bytes()
        deployment.validate(name, raw)
        target = stage/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        source_hashes[name] = sha(source)
    tests = stage/'tests'
    tests.mkdir(exist_ok=True)
    # Copy test helpers without importing local gameplay code into the process.
    for source in (ROOT/'tests').glob('*.py'):
        shutil.copy2(source, tests/source.name)
    fixtures = {}
    if 'test_arena' in args.tests:
        for name in ('arena_room_native.json','arena_members_native.json',
                     'arena_create_request_native.json','room_actions_native.json',
                     'battle_settings_native.json'):
            source = ROOT/'evidence'/name
            shutil.copy2(source,stage/'evidence'/name)
            fixtures[name] = sha(source)
    command = [sys.executable, '-m', 'unittest', '-v', *args.tests]
    bootstrap = ('import sys,runpy;sys.path[:0]=[".","tests"];'
                 'sys.argv='+repr(command[2:])+';runpy.run_module("unittest",run_name="__main__")')
    with (stage/'isolated-tests.log').open('x', encoding='utf-8') as output:
        result = subprocess.run([sys.executable,'-c',bootstrap], cwd=stage,
                                text=True,stdout=output,stderr=subprocess.STDOUT,timeout=180)
    unchanged = all(sha(deployment.source_path(FOLDER,n)) == digest for n,digest in source_hashes.items())
    evidence = {'passed':result.returncode==0,'source_unchanged':unchanged,
                'source_sha256':source_hashes,'test_modules':args.tests,
                'runtime':'fresh hosted snapshot plus bounded candidate',
                'hosted_runtime_modified':False,'hosted_player_data_opened':False,
                'candidate_directory':str(stage),'log':str(stage/'isolated-tests.log'),
                'local_test_fixture_sha256':fixtures}
    with (stage/'validation.json').open('x',encoding='utf-8') as out:
        json.dump(evidence,out,indent=2)
    with (FOLDER/'validation.json').open('x',encoding='utf-8') as out:
        json.dump(evidence,out,indent=2)
    print(json.dumps(evidence,indent=2))
    if not evidence['passed'] or not unchanged:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
