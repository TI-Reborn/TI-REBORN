"""Capture and independently verify Stage4 recovery without local plaintext."""
from pathlib import Path
import io
import json
import subprocess
import sys
import tarfile

import offsite_backup_windows as backup

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/stage4-economy'


def main():
    completed = subprocess.run([sys.executable, str(ROOT / 'tools/offsite_backup_windows.py')],
                               capture_output=True, text=True, encoding='utf-8', timeout=900)
    if completed.returncode:
        raise RuntimeError('Stage4 offsite capture failed; previous verified copies retained')
    captured = json.loads(completed.stdout)
    (REPORT / 'offsite-capture.json').write_text(json.dumps(captured, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=captured['status'], path=captured['path'],
                         accounts=captured['accounts'], encrypted_bytes=captured['encrypted_bytes'])), flush=True)
    # Reopen the committed encrypted file. Verify every archived checksum and
    # restore SQLite in memory; plaintext exists only in this process memory.
    raw = backup._read_encrypted(Path(captured['path']))
    payload = backup.crypt(raw[len(backup.MAGIC):], decrypt=True)
    del raw
    verified = backup.verify_payload(payload)
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:*') as archive:
        stream = archive.extractfile('manifest.json')
        if stream is None:
            raise RuntimeError('Recovery manifest missing')
        with stream:
            manifest = json.load(stream)
    expected = json.loads((REPORT / 'deployment.json').read_text(encoding='utf-8'))['source_sha256']
    members = {entry['path']: entry['sha256'] for entry in manifest['files']}
    archived = {name: members.get('game/' + name) for name in expected}
    verified.update(path=captured['path'], encrypted_bytes=captured['encrypted_bytes'],
                    source_sha256=archived, deployed_source_parity=archived == expected,
                    capture_bundle_matches=verified['bundle_sha256'] == captured['bundle_sha256'],
                    local_plaintext_written=False)
    verified['passed'] = verified['integrity'] == 'ok' and verified['deployed_source_parity'] and verified['capture_bundle_matches']
    (REPORT / 'offsite-verified.json').write_text(json.dumps(verified, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(passed=verified['passed'], deployed_source_parity=verified['deployed_source_parity'],
                         accounts=verified['accounts'], local_plaintext_written=False)), flush=True)
    if not verified['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
