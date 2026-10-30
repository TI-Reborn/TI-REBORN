"""Stage immutable map resources; publish the manifest while gameplay is stopped.

The server deployer owns SQLite/code/config backups. This tool never writes
player data and refuses publication without that cutover backup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

LIVE = Path('/var/www/tio-client/updates')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def transition(old: dict, new: dict) -> list[dict]:
    """Only replace Silver, add map PNGs, and update release metadata."""
    if old.get('version') != '2026.10.28.2' or new.get('version') != '2026.10.29.1':
        raise ValueError('Unexpected map release')
    rows = {}
    for manifest in (old,new):
        current = {}
        for row in manifest['files']:
            name = row['path']; path = PurePosixPath(name)
            if (not name or name != str(path) or path.is_absolute() or '..' in path.parts
                    or '\\' in name or ':' in name or any(ord(c)<32 for c in name)
                    or name in current or not re.fullmatch('[a-f0-9]{64}',row['sha256'])
                    or type(row['size']) is not int or not 0 <= row['size'] <= 64*1024*1024):
                raise ValueError('Unsafe client descriptor')
            current[name] = row
        rows[manifest['version']] = current
    before, after = rows[old['version']], rows[new['version']]
    added = set(after)-set(before)
    if (len(added) != 75 or set(before)-set(after)
            or any(not n.startswith('base/pda/global-map-v3/') or not n.endswith('.png') for n in added)
            or any(before[n] != after[n] for n in before if n != 'silver.dll')
            or after['silver.dll'].get('seed') is not False):
        raise ValueError('Unrelated client files changed')
    allowed = {'version','news','newsEn','files','archive'}
    if any(old.get(k) != new.get(k) for k in set(old)|set(new) if k not in allowed) or 'archive' in new:
        raise ValueError('Unrelated release metadata changed')
    return [after[n] for n in sorted(added|{'silver.dll'})]


def atomic(path: Path, raw: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix='.map-v3-',dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        pending.chmod(0o644); pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True,type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--previous-sha',required=True)
    parser.add_argument('--backup',type=Path)
    parser.add_argument('--publish',action='store_true')
    args = parser.parse_args()
    if digest(args.archive.read_bytes()) != args.sha256:
        raise ValueError('Map archive changed')
    previous = (LIVE/'manifest.json').read_bytes()
    if digest(previous) != args.previous_sha:
        raise ValueError('Published baseline changed')
    with tarfile.open(args.archive) as archive:
        members = archive.getmembers()
        if (len(members) != 77 or len({m.name for m in members}) != 77
                or any(not m.isfile() or m.size > 64*1024*1024 for m in members)
                or sum(m.size for m in members)>64*1024*1024):
            raise ValueError('Unexpected map package')
        candidate = archive.extractfile('manifest-candidate.json').read()
        changes = transition(json.loads(previous),json.loads(candidate))
        expected = {'manifest-candidate.json'}|{'blobs/'+r['sha256'] for r in changes}
        if {m.name for m in members} != expected:
            raise ValueError('Map payload differs from descriptors')
        for row in changes:
            raw = archive.extractfile('blobs/'+row['sha256']).read()
            if digest(raw) != row['sha256'] or len(raw) != row['size']:
                raise ValueError('Map blob changed')
            target = LIVE/'blobs'/row['sha256']
            if target.exists():
                if target.is_symlink() or target.read_bytes() != raw:
                    raise ValueError('Existing immutable blob differs')
            else:
                atomic(target,raw)
    if args.publish:
        if (args.backup is None or args.backup.parent != Path('/root')
                or not args.backup.name.startswith('tio-before-game-operations-')
                or not (args.backup/'at-cutover.sqlite3').is_file()):
            raise ValueError('Server cutover backup is required')
        status = subprocess.run(['systemctl','is-active','tio-server'],capture_output=True,text=True,timeout=10)
        if status.stdout.strip() != 'inactive':
            raise RuntimeError('Stop gameplay before changing the map manifest')
        with (args.backup/'previous-client-manifest.json').open('xb') as stream:
            stream.write(previous)
        if (LIVE/'manifest.json').read_bytes() != previous:
            raise RuntimeError('Client publication raced another update')
        atomic(LIVE/'manifest.json',candidate)
    print(json.dumps(dict(passed=True,published=args.publish,blobs=len(changes),
                          manifest_sha256=digest(candidate),player_data_written=False)))


if __name__ == '__main__':
    import fcntl
    with Path('/root/.tio-gameplay-client.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        main()
