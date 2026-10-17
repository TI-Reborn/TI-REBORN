"""Read-only verification of every published language resource over trusted HTTPS."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.verify_published_launcher_update import fetch

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://185.184.42.88/updates/'


def main():
    _, raw = fetch(ORIGIN + 'manifest.json')
    manifest = json.loads(raw)
    if manifest['version'] != '2026.10.13.1':
        raise ValueError('Unexpected published language release')
    entries = [e for e in manifest['files']
               if e['path'] == 'base/english.lng' or e['path'].startswith('base/locales/')]
    if len(entries) != 11:
        raise ValueError('Incomplete language publication')

    def verify(entry):
        expected = ROOT / 'assets/english-localization/runtime' / entry['path']
        source = expected.read_bytes()
        downloaded, _ = fetch(ORIGIN + 'blobs/' + entry['sha256'], binary=True)
        passed = (hashlib.sha256(source).hexdigest() == entry['sha256'] == downloaded['sha256']
                  and len(source) == entry['size'] == downloaded['bytes'])
        if not passed:
            raise ValueError('Published resource mismatch: ' + entry['path'])
        return dict(path=entry['path'], sha256=entry['sha256'], size=entry['size'], passed=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(verify, entries))
    report = dict(passed=True, client_version=manifest['version'], trusted_https=True,
                  verified_utc=datetime.now(timezone.utc).isoformat(), files=results)
    output = ROOT / 'reports/english-localization/published-resource-verification.json'
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(dict(passed=True, files=len(results), report=str(output))))


if __name__ == '__main__':
    main()
