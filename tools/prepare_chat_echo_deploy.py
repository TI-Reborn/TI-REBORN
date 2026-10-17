"""Build a one-file patch against the inspected live chat-presence source."""
from pathlib import Path
import hashlib
import io
import json
import tarfile


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/chat-echo-20261012'
BASE = ROOT / 'reports/travel-trade-followup/remote-presence-before-chat-fix.py'
CANDIDATE = REPORT / 'server-presence-candidate.py'
ARCHIVE = REPORT / 'tio-chat-presence-patch.tar.gz'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    before = BASE.read_bytes()
    candidate = CANDIDATE.read_bytes()
    if b'if target is session:continue' not in candidate:
        raise SystemExit('Candidate does not exclude the sending session')
    if b'from .warehouse_capacity import frames as capacity_frames' not in candidate:
        raise SystemExit('Candidate does not preserve the live warehouse frame handling')
    manifest = {'server/presence.py': {'before': sha(before), 'after': sha(candidate)}}
    with tarfile.open(ARCHIVE, 'w:gz') as tar:
        for name, payload in (
                ('manifest.json', json.dumps(manifest, indent=2).encode() + b'\n'),
                ('server/presence.py', candidate)):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(payload))
    print(json.dumps({'archive': str(ARCHIVE), 'manifest': manifest}, indent=2))


if __name__ == '__main__':
    main()
