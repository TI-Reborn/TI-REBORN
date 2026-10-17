"""Install the domain's game TLS credentials locally and request a safe reload.

Run on the hosting server as root. Private keys never leave this machine and
never enter output. Immutable generations plus an atomic symlink give the
backend a coherent certificate/key pair without interrupting existing games.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import stat
import subprocess
import tempfile
import time

DOMAIN = 'ti-reborn.com'
LINEAGE = Path('/etc/letsencrypt/live') / DOMAIN
DESTINATION = Path('/etc/tio-server/tls')


def validate(certificate: Path, private_key: Path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate), str(private_key))
    info = ssl._ssl._test_decode_cert(str(certificate))
    now = time.time()
    if not ssl.cert_time_to_seconds(info['notBefore']) <= now < ssl.cert_time_to_seconds(info['notAfter']):
        raise ValueError('Game TLS certificate is not currently valid')
    if ('DNS', DOMAIN) not in info.get('subjectAltName', ()):
        raise ValueError('Game TLS certificate lacks the required domain SAN')
    return {'certificate_sha256': hashlib.sha256(certificate.read_bytes()).hexdigest(),
            'not_after': info['notAfter'], 'domain': DOMAIN}


@contextmanager
def renewal_lock():
    import fcntl
    # /run/lock may be writable by other local users. Refuse symlinks and
    # foreign-owned objects before changing modes or taking the lock.
    descriptor = os.open('/run/lock/tio-game-tls-renew.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as handle:
        metadata = os.fstat(handle.fileno())
        if metadata.st_uid != 0 or not stat.S_ISREG(metadata.st_mode):
            raise PermissionError('Unexpected game TLS renewal lock ownership/type')
        os.fchmod(handle.fileno(), 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def install(*, reload_service=True):
    import grp
    if os.geteuid() != 0:
        raise PermissionError('Game TLS renewal must run as root')
    group = grp.getgrnam('tio').gr_gid
    with renewal_lock():
        # Resolve the certificate lineage's stable generation before copying.
        certificate, key = (LINEAGE / 'fullchain.pem').resolve(strict=True), (LINEAGE / 'privkey.pem').resolve(strict=True)
        metadata = validate(certificate, key)
        DESTINATION.mkdir(mode=0o750, parents=True, exist_ok=True)
        versions = DESTINATION / 'versions'
        versions.mkdir(mode=0o750, exist_ok=True)
        for directory in (DESTINATION, versions):
            os.chown(directory, 0, group)
            directory.chmod(0o750)
        generation = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=versions))
        os.chown(generation, 0, group)
        generation.chmod(0o750)
        try:
            for source, name in ((certificate, 'fullchain.pem'), (key, 'privkey.pem')):
                target = generation / name
                with target.open('xb') as output, source.open('rb') as input_file:
                    shutil.copyfileobj(input_file, output)
                    output.flush()
                    os.fsync(output.fileno())
                os.chown(target, 0, group)
                target.chmod(0o640)
            validate(generation / 'fullchain.pem', generation / 'privkey.pem')
            current = DESTINATION / 'current'
            previous = os.readlink(current) if current.is_symlink() else None
            if current.exists() and not current.is_symlink():
                raise RuntimeError('Unexpected non-symlink game TLS current path')
            temporary = DESTINATION / ('.current-' + generation.name)
            temporary.symlink_to(generation.relative_to(DESTINATION))
            temporary.replace(current)
            try:
                if reload_service:
                    subprocess.run(['systemctl', 'reload', 'tio-server'], check=True, capture_output=True, text=True, timeout=15)
            except BaseException:
                if previous is not None:
                    temporary.symlink_to(previous)
                    temporary.replace(current)
                else:
                    current.unlink(missing_ok=True)
                raise
            return dict(metadata, generation=generation.name, reload_requested=reload_service)
        except BaseException:
            # A failed candidate is kept private for diagnosis; the old live
            # symlink/context are preserved. Never remove a working generation.
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-reload', action='store_true', help='Initial installation before enabling the listeners')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    renewed = os.environ.get('RENEWED_LINEAGE')
    if renewed and Path(renewed).absolute() != LINEAGE:
        print(json.dumps({'ignored_other_lineage': True}))
        return 0
    if args.check_only:
        print(json.dumps(validate(LINEAGE / 'fullchain.pem', LINEAGE / 'privkey.pem')))
    else:
        print(json.dumps(install(reload_service=not args.no_reload)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
