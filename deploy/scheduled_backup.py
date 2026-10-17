"""Verified SQLite snapshots; expire only this job's dated automatic backups."""
import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.backup import backup

AUTOMATIC = re.compile(r'auto-(\d{8}T\d{12}Z)\.sqlite3')


def snapshot(source, directory, *, days=14, tag='auto', now=None):
    if type(days) is not int or days < 1:
        raise ValueError('Retention must be at least one day')
    if tag not in ('auto', 'pre-update'):
        raise ValueError('Unsupported backup tag')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware backup time required')
    now = now.astimezone(timezone.utc)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (tag + '-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
    if destination.exists():
        raise FileExistsError(destination)
    temporary = directory / ('.pending-' + uuid4().hex + '.sqlite3')
    try:
        backup(source, temporary)
        temporary.chmod(0o600)
        # Atomically publish without overwriting an existing backup (same FS).
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print('Verified snapshot:', destination, flush=True)
    # Only after a successful backup. Manual/pre-update/unknown files survive.
    cutoff = now - timedelta(days=days)
    for candidate in directory.iterdir():
        match = AUTOMATIC.fullmatch(candidate.name)
        if not match or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            stamp = datetime.strptime(match[1], '%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if candidate != destination and stamp < cutoff:
            candidate.unlink()
            print('Expired automatic backup:', candidate.name, flush=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--tag', choices=('auto', 'pre-update'), default='auto')
    args = parser.parse_args()
    snapshot(args.source, args.directory, days=args.days, tag=args.tag)
