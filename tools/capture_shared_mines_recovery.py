"""Capture and independently verify deployed shared-mines recovery without local plaintext."""
from pathlib import Path
import argparse
import io
import json
import re
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import offsite_backup_windows as backup

REPORT=ROOT/'reports/shared-mines'


def public_report(path):
    path=Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(REPORT.resolve()):
        raise ValueError('Use a public report path within reports/shared-mines')
    return path


def expected_sources(path=None):
    """Reject a missing/empty/stale deployment record before remote capture."""
    deployment=json.loads(public_report(path or REPORT/'deployment.json').read_text(encoding='utf-8'))
    expected=deployment.get('source_sha256')
    if deployment.get('source_parity')is not True or not isinstance(expected,dict) or not expected:
        raise ValueError('Verified deployed source manifest required before recovery capture')
    for name,digest in expected.items():
        backup.safe_member(name)
        if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):
            raise ValueError('Invalid deployed source checksum')
    return expected


def write_report(name,value):
    # Preserve earlier evidence even if another operator raced the initial check.
    with (REPORT/name).open('x',encoding='utf-8') as out:
        out.write(json.dumps(value,indent=2)+'\n')


def main(argv=()):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment',type=Path,default=REPORT/'deployment.json')
    parser.add_argument('--output-prefix',default='offsite')
    args=parser.parse_args(argv)
    if not re.fullmatch('[a-z][a-z0-9-]{0,63}',args.output_prefix):
        raise ValueError('Use a simple lowercase report prefix')
    capture_name=args.output_prefix+'-capture.json';verified_name=args.output_prefix+'-verified.json'
    for name in (capture_name,verified_name):
        if (REPORT/name).exists():raise RuntimeError('Preserve the existing recovery evidence')
    expected=expected_sources(args.deployment)
    completed=subprocess.run([sys.executable,str(ROOT/'tools/offsite_backup_windows.py')],
        capture_output=True,text=True,encoding='utf-8',timeout=900)
    if completed.returncode:raise RuntimeError('Offsite capture failed; prior verified copies retained')
    captured=json.loads(completed.stdout)
    write_report(capture_name,captured)
    print(json.dumps(dict(status=captured['status'],path=captured['path'],
        accounts=captured['accounts'],encrypted_bytes=captured['encrypted_bytes'])),flush=True)
    raw=backup._read_encrypted(Path(captured['path']))
    payload=backup.crypt(raw[len(backup.MAGIC):],decrypt=True);del raw
    verified=backup.verify_payload(payload)
    with tarfile.open(fileobj=io.BytesIO(payload),mode='r:*') as archive:
        stream=archive.extractfile('manifest.json')
        if stream is None:raise RuntimeError('Recovery manifest missing')
        with stream:manifest=json.load(stream)
    members={entry['path']:entry['sha256'] for entry in manifest['files']}
    archived={name:members.get('game/'+name) for name in expected}
    verified.update(path=captured['path'],encrypted_bytes=captured['encrypted_bytes'],
        source_sha256=archived,deployed_source_parity=archived==expected,
        deployed_source_files=len(expected),
        capture_bundle_matches=verified['bundle_sha256']==captured['bundle_sha256'],
        local_plaintext_written=False)
    verified['passed']=(verified['integrity']=='ok' and verified['deployed_source_parity']
                        and verified['capture_bundle_matches'])
    write_report(verified_name,verified)
    print(json.dumps(dict(passed=verified['passed'],deployed_source_parity=verified['deployed_source_parity'],
        accounts=verified['accounts'],local_plaintext_written=False)),flush=True)
    if not verified['passed']:raise SystemExit(1)

if __name__=='__main__':main(sys.argv[1:])
