"""Publish the bounded native lobby and texture fix using the reviewed transaction.

Keeps Launcher 0.1.6 and all other client records. The established transaction
backs up hosted SQLite, code/config and previous publication before commit.
"""
from pathlib import Path
import argparse
import hashlib
import json

from tools import publish_mine_drill_ui_remote as established

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011'
BASELINE = FOLDER / 'client/source/manifest.json'
PREVIOUS_VERSION = '2026.10.10.5'
VERSION = '2026.10.11.1'
MANIFEST_SHA = '61a1deaca13fb2472f295c574995b65e8344b39cd477da2a765db8c8444c6814'
SILVER_SHA = '5afcac81549ac2ca5e6ceb9a015a075c3a986f6fbda24d0a90a4ad407f066d17'
SILVER_BYTES = 8106496
BASELINE_RECORDS = 6567
FIX = 'legacy-team-lobbies-and-texture-filtering'


def replace_once(raw, before, after):
    if raw.count(before) != 1:
        raise ValueError('Established publisher guard changed: ' + before[:80])
    return raw.replace(before, after)


def configure():
    remote = established.REMOTE
    for key, value in dict(MANIFEST_SHA=MANIFEST_SHA, PREVIOUS_VERSION=PREVIOUS_VERSION,
                           VERSION=VERSION, SILVER_SHA=SILVER_SHA,
                           SILVER_BYTES=SILVER_BYTES, BASELINE_RECORDS=BASELINE_RECORDS).items():
        remote = replace_once(remote, f'{key}={getattr(established,key)!r}\n', f'{key}={value!r}\n')
        setattr(established, key, value)
    previous = "if p['selection']!={'fix':'battle-ui-quality-and-mine-hover'}:"
    replacement = "if p['selection']!={'fix':" + repr(FIX) + "}:"
    remote = replace_once(remote, previous, replacement)
    validation = replace_once(established.VALIDATION, previous, replacement)
    previous = "if not isinstance(p['files'],list) or not 1<=len(p['files'])<=256:"
    replacement = "if not isinstance(p['files'],list) or len(p['files'])!=1 or p['files'][0].get('kind')!='native' or p['files'][0].get('path')!='silver.dll':"
    remote = replace_once(remote, previous, replacement)
    validation = replace_once(validation, previous, replacement)
    remote = replace_once(remote, "prefix='tio-before-mine-drill-ui-fix-'", "prefix='tio-before-legacy-lobbies-client-'")
    compile(remote, 'legacy-client-publication', 'exec')
    established.REMOTE = remote
    established.VALIDATION = validation
    established.REPORT_ROOT = FOLDER
    established.BASELINE = BASELINE
    exec(validation, established.__dict__)
    return established


PUBLISHER = configure()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot','inspect','publish','verify'))
    parser.add_argument('--package', type=Path, default=FOLDER/'client/package.json')
    parser.add_argument('--package-sha256')
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--inspect-report', type=Path)
    args = parser.parse_args()
    report = args.report.resolve()
    if report.exists() or not report.is_relative_to(FOLDER) or not PUBLISHER.no_symlinks(report.parent):
        raise ValueError('Use a new regular scoped report path')
    if args.action == 'snapshot':
        result = PUBLISHER.baseline_snapshot()
    else:
        if not args.package_sha256:
            raise ValueError('Pin the exact reviewed package SHA256')
        payload = PUBLISHER.make_payload(args.package, args.package_sha256,
                    'apply' if args.action=='publish' else 'inspect', baseline=BASELINE,
                    before_inspect=args.inspect_report)
        result = PUBLISHER.verify_https(payload) if args.action=='verify' else PUBLISHER.invoke(payload)
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('x', encoding='utf-8') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    if args.action == 'publish':
        https = PUBLISHER.verify_https(payload)
        with report.with_name(report.stem+'-https.json').open('x', encoding='utf-8') as out:
            json.dump(https, out, indent=2)
            out.write('\n')
    print(json.dumps({k:result.get(k) for k in ('passed','operation','version','backup','manifest_sha256','services_unchanged')}, indent=2))


if __name__ == '__main__':
    main()
