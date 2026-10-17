"""Install only the reviewed map release into the existing selected client.

No launch, login, settings changes or remote writes. Publication must already
be verified over trusted HTTPS. Every changed file has an exact backup and the
existing updater's exclusive lock protects the local transaction.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGET = Path('C:/Users/jundu/AppData/Local/TIO-Online')
OUT = ROOT / 'reports/global-map-integration-20261010/local-install'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def no_links(path):
    return not any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
                   for p in (path, *path.parents))


def safe_target(name):
    from tools.publish_global_map_remote import safe_target as validate
    validate(name)
    path = TARGET.joinpath(*name.split('/'))
    if not path.resolve().is_relative_to(TARGET.resolve()) or not no_links(path):
        raise ValueError('Local resource escaped the selected regular client')
    return path


def running_guard():
    # Read-only process inventory; never close somebody else's client.
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                             "@(Get-Process -Name ti -ErrorAction SilentlyContinue).Count"],
                            capture_output=True, text=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or result.stdout.strip() != '0':
        raise RuntimeError('Close running game clients before installing the map')


@contextmanager
def update_lock():
    from ctypes import wintypes
    work = TARGET / '.tio-update'
    if not no_links(work):
        raise ValueError('Updater lock contains a filesystem link')
    work.mkdir(exist_ok=True)
    lock_path = work / 'lock'
    if not no_links(lock_path) or (lock_path.exists() and not lock_path.is_file()):
        raise ValueError('Updater lock must be a regular file')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL
    handle = create(str(lock_path), 0xC0000000, 0, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'The selected client updater is busy')
    try:
        if (work / 'journal.json').exists():
            raise RuntimeError('Existing updater recovery must finish first')
        yield
    finally:
        close(handle)


def atomic(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.global-map-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def install(package_path, package_sha, *, check_only=False):
    from tools import publish_global_map_remote as publication
    package, payloads = publication.load_package(package_path, package_sha)
    payload = publication.make_payload(package_path, package_sha, 'inspect')
    public = publication.verify_https(payload)
    if public.get('passed') is not True or len(payloads) != 24:
        raise ValueError('Exact published map package is required')
    if not TARGET.is_dir() or not no_links(TARGET):
        raise ValueError('Observed selected client folder is unavailable')
    baseline = json.loads(publication.BASELINE.read_bytes())
    source = {r['path']: r for r in baseline['files']}
    if sha((TARGET/'ti.exe').read_bytes()) != publication.TI_SHA:
        raise ValueError('Selected native game executable differs')
    running_guard()
    personal = [TARGET/n for n in ('base/config.cfg', 'base/autoexec.cfg', 'login.ini', 'base/login.ini')]
    if any(not no_links(p) for p in personal):
        raise ValueError('Personal settings pathname is linked')
    private_hashes = {str(p): sha(p.read_bytes()) if p.exists() else None for p in personal}
    originals = {}
    for name, raw in payloads.items():
        path = safe_target(name)
        previous = path.read_bytes() if path.exists() else None
        expected = source.get(name)
        if previous is not None and previous != raw and (expected is None or
                (len(previous), sha(previous)) != (expected['size'], expected['sha256'])):
            raise ValueError('Existing selected resource differs from the baseline: '+name)
        if name == 'silver.dll' and previous is None:
            raise ValueError('Selected client lacks its native library')
        originals[name] = previous
    changed = {name: raw for name, raw in payloads.items() if originals[name] != raw}
    if check_only:
        return dict(passed=True, check_only=True, target=str(TARGET), version=publication.VERSION,
                    resources=len(payloads), pending=len(changed), files_written=0, personal_files_changed=0)
    folder = OUT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    with update_lock():
        running_guard()
        # Recheck exactly the reviewed state after acquiring the updater lock.
        for name, previous in originals.items():
            path = safe_target(name)
            if (path.read_bytes() if path.exists() else None) != previous:
                raise RuntimeError('Selected resource changed before local installation')
        folder.mkdir(parents=True)
        for name in changed:
            if originals[name] is not None:
                backup = folder / 'previous' / name
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(originals[name])
        journal = dict(package_sha256=package_sha, target=str(TARGET), version=publication.VERSION,
                       changed=[dict(path=n, existed=originals[n] is not None,
                                     before_sha256=sha(originals[n]) if originals[n] is not None else None,
                                     after_sha256=sha(changed[n])) for n in changed])
        (folder/'journal.json').write_text(json.dumps(journal, indent=2)+'\n', encoding='utf-8')
        applied = []
        try:
            # All visual resources precede the native module that references them.
            for name in sorted(changed, key=lambda n: (n == 'silver.dll', n)):
                running_guard()
                atomic(safe_target(name), changed[name])
                applied.append(name)
            for name, raw in payloads.items():
                if safe_target(name).read_bytes() != raw:
                    raise RuntimeError('Installed resource verification failed')
            after = {str(p): sha(p.read_bytes()) if p.exists() else None for p in personal}
            if after != private_hashes:
                raise RuntimeError('Personal settings changed during installation')
        except BaseException:
            for name in reversed(applied):
                path = safe_target(name)
                if path.read_bytes() != changed[name]:
                    raise RuntimeError('Concurrent resource change prevents automatic rollback')
                if originals[name] is None:
                    path.unlink()
                else:
                    atomic(path, originals[name])
            raise
    report = dict(passed=True, target=str(TARGET), version=publication.VERSION,
                  package_sha256=package_sha, resources_verified=len(payloads), files_written=len(changed),
                  personal_files_preserved=True, client_started=False, backup=str(folder))
    (folder/'receipt.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--package-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.package, args.package_sha256, check_only=args.check_only), indent=2))
