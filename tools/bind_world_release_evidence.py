"""Join successful runtime evidence to the exact executed native XML release.

Adds publication metadata only after checking every frozen runtime hash.
It makes no network calls and never opens a player database.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from tools.deploy_gameplay_completion import ROOT, source_path
from tools.publish_world_completion_client import FOLDER, reviewed


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bind(kind):
    folder = FOLDER.resolve()
    release, _, _, _ = reviewed(folder)
    pins = release['world_client_release']
    names = json.loads((folder/'runtime-files.json').read_text())
    frozen = json.loads((folder/'frozen-sources.json').read_text())
    actual = {name: digest(source_path(folder, name).read_bytes()) for name in names}
    if len(names) != 27 or actual != frozen:
        raise ValueError('Reviewed frozen world runtime changed')
    if (actual['config/world_completion.json'] != pins['policy_sha256']
            or actual['evidence/zones_diagnostic.xml'] != pins['runtime_sha256']):
        raise ValueError('Runtime XML/policy differs from the native release')
    path = folder/(kind+'.json')
    original = path.read_bytes()
    value = json.loads(original)
    if value.get('source_sha256') != actual:
        raise ValueError('Evidence does not cover all exact frozen runtime files')
    additions = {'world_client_release': pins}
    if kind == 'validation':
        if not value.get('passed') or not value.get('source_unchanged'):
            raise ValueError('Successful frozen runtime validation required')
        native = next((n for n in value['native']
                       if n['tool'] == 'verify_world_completion_native.py'), None)
        if not native or not native['passed']:
            raise ValueError('Executed original world/client proof required')
        result = json.loads(native['output'])
        if (not result['passed'] or result['world_client_release'] != pins
                or result['world_towns'] != 22 or result['visibility_cases'] != 44
                or result['standings_requests'] != 9 or result['standings_cases'] != 13):
            raise ValueError('Native reader/standings evidence differs')
    else:
        before, after = value['tables_before'], value['tables_after']
        if (value.get('source_parity') is not True or value.get('service') != 'active'
                or value.get('local_player_data_uploaded') is not False
                or value.get('database_restored') is not False
                or value['all_existing_tables_unchanged'] != len(before)
                or any(after.get(n) != row for n, row in before.items())
                or any(row['rows'] for n, row in after.items() if n not in before)):
            raise ValueError('Actual deployment/preservation proof required')
        manifest = json.loads((folder/'deployment-manifest.json').read_text())
        if {n: row['after'] for n, row in manifest['files'].items()} != actual:
            raise ValueError('Actual deployment scope differs')
        additions.update(passed=True, runtime_files=actual)
    if any(k in value and value[k] != v for k, v in additions.items()):
        raise ValueError('Preserve conflicting release evidence')
    evidence = folder/('chain-binding-'+kind+'.json')
    if evidence.exists():
        if all(value.get(k) == v for k, v in additions.items()):
            return
        raise ValueError('Preserve previous evidence binding')
    value.update(additions)
    final = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf8')
    proof = dict(passed=True, kind=kind, original_sha256=digest(original),
                 bound_sha256=digest(final), world_client_release=pins,
                 runtime_files=actual, database_opened=False, network_accessed=False,
                 utc=datetime.now(timezone.utc).isoformat())
    evidence.write_text(json.dumps(proof, indent=2)+'\n', encoding='utf8')
    path.write_bytes(final)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('validation', 'deployment'))
    args = parser.parse_args()
    bind(args.kind)
    print(json.dumps(dict(passed=True, kind=args.kind, runtime_files=27,
                         database_opened=False, network_accessed=False)))


if __name__ == '__main__':
    main()
