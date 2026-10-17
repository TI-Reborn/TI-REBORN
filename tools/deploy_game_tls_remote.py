"""Guarded code-only game TLS rollout on the documented existing VPS.

The launcher is published separately after hosted acceptance. Never uploads or
restores player databases. Rollback restores old code/configuration while
retaining the current hosted saves.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

ROOT = Path('/opt/tio-emulator')
DATABASE = Path('/var/lib/tio-server/reservation.sqlite3')
CONFIG = Path('/etc/tio-server/server.toml')
LAUNCHER = Path('/var/www/tio-client/downloads/TIO-Launcher.exe')
CLIENT_MANIFEST = Path('/var/www/tio-client/updates/manifest.json')
DROPIN = Path('/etc/systemd/system/tio-server.service.d/game-tls.conf')
HOOK = Path('/etc/letsencrypt/renewal-hooks/deploy/tio-game-tls')
ALLOWED = {'server/config.py', 'server/runtime.py', 'server/multi.py', 'server/tls.py', 'deploy/renew_game_tls.py'}
TLS_PORTS = (29512, 29513)
LAUNCHER_CANDIDATE_ROOT = Path('/root')
MAX_LAUNCHER_BYTES = 200 * 1024 * 1024


def command(*args, timeout=45):
    return subprocess.run(args, check=True, capture_output=True, text=True, cwd=ROOT, timeout=timeout).stdout.strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def atomic_copy(source, destination, mode=0o644):
    destination.parent.mkdir(parents=True, exist_ok=True)
    previous = destination.stat() if destination.exists() else None
    temporary = destination.with_name(destination.name+'.game-tls-new')
    shutil.copy2(source, temporary)
    temporary.chmod(mode)
    if previous is not None and hasattr(os, 'chown'):
        os.chown(temporary, previous.st_uid, previous.st_gid)
    temporary.replace(destination)


def save_file(source, backup, name):
    target = backup/name
    if source.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return True
    return False


def table_digests(path):
    """Compare every hosted row without exposing any credentials or save data."""
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as database:
        if database.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Hosted database integrity check failed')
        result = {}
        for (name,) in database.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            records = sorted(repr(row) for row in database.execute('SELECT * FROM "'+name.replace('"','""')+'"'))
            result[name] = {'rows': len(records), 'sha256': hashlib.sha256('\n'.join(records).encode()).hexdigest()}
        return result


def unpack(archive):
    stage = Path(tempfile.mkdtemp(prefix='tio-game-tls-stage-', dir='/root'))
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        if len(set(names)) != len(names) or set(names) != ALLOWED | {'manifest.json', 'TIO-Launcher.exe'}:
            raise ValueError('Unexpected game TLS archive members')
        if any(not member.isfile() or not (stage/member.name).resolve().is_relative_to(stage) for member in members):
            raise ValueError('Unsafe game TLS archive member')
        bundle.extractall(stage, filter='data')
    manifest = json.loads((stage/'manifest.json').read_text())
    if manifest.get('schema') != 1 or set(manifest.get('files', {})) != ALLOWED:
        raise ValueError('Invalid game TLS manifest')
    for name, hashes in manifest['files'].items():
        if digest(stage/name) != hashes['after']:
            raise ValueError('TLS staged file hash mismatch: '+name)
    if digest(stage/'TIO-Launcher.exe') != manifest['launcher_after']:
        raise ValueError('TLS launcher hash mismatch')
    return stage, manifest


def verify_baseline(manifest):
    for name, hashes in manifest['files'].items():
        if digest(ROOT/name) != hashes['before']:
            raise RuntimeError('Actual remote baseline changed: '+name)
    for path, key in ((CONFIG, 'server_config_before'), (LAUNCHER, 'launcher_before'), (CLIENT_MANIFEST, 'client_manifest')):
        if digest(path) != manifest[key]:
            raise RuntimeError('Actual remote baseline changed: '+str(path))
    import tomllib
    config = tomllib.loads(CONFIG.read_text())
    if config.get('multi_account') is not True or config.get('game_port') != 28512 or config.get('session_port') != 28513:
        raise RuntimeError('Unexpected live gameplay configuration')
    if 'tls' in config:
        raise RuntimeError('Existing TLS configuration requires explicit reconciliation')
    if command('systemctl', 'is-active', 'tio-server') != 'active':
        raise RuntimeError('The live game service is not active')
    verify_idle()
    listeners = command('ss', '-Hltn')
    if any(line.split()[3].rsplit(':', 1)[-1] in {'29512', '29513'} for line in listeners.splitlines()):
        raise RuntimeError('Proposed TLS listener port is already occupied')


def verify_idle():
    connections = command('ss', '-Htn', 'state', 'established', '( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
    if connections:
        raise RuntimeError('Active gameplay connections; rollout postponed to preserve games')
    with closing(sqlite3.connect(f'file:{DATABASE}?mode=ro', uri=True)) as db:
        for table in ('battle_checkpoints', 'battle_settlement_jobs'):
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                continue
            if db.execute('SELECT count(*) FROM "'+table+'"').fetchone()[0]:
                raise RuntimeError('Durable gameplay state still active; rollout postponed: '+table)


def backup_host(manifest):
    backup = Path(tempfile.mkdtemp(prefix='tio-before-game-tls-', dir='/root'))
    backup.chmod(0o700)
    with closing(sqlite3.connect(f'file:{DATABASE}?mode=ro', uri=True)) as source, closing(sqlite3.connect(backup/'reservation.sqlite3')) as destination:
        source.backup(destination)
    (backup/'reservation.sqlite3').chmod(0o600)
    before = table_digests(backup/'reservation.sqlite3')
    (backup/'tables-before.json').write_text(json.dumps(before, indent=2)+'\n')
    state = {'files': {}, 'system_files': {}, 'firewall_added': [], 'launcher_published': False}
    for name in sorted(ALLOWED):
        state['files'][name] = save_file(ROOT/name, backup, 'files/'+name)
    for source, name in ((CONFIG, 'server.toml'), (LAUNCHER, 'TIO-Launcher.exe'),
                         (DROPIN, 'game-tls.conf'), (HOOK, 'renewal-hook')):
        state['system_files'][str(source)] = save_file(source, backup, name)
    with tarfile.open(backup/'previous-code-config.tar.gz', 'w:gz') as bundle:
        for name in ('tio', 'server', 'tools', 'deploy', 'config', 'evidence'):
            bundle.add(ROOT/name, arcname=name, filter=lambda item: None if '__pycache__' in Path(item.name).parts else item)
        bundle.add('/etc/systemd/system/tio-server.service', arcname='systemd/tio-server.service')
        bundle.add('/etc/systemd/system/tio-server.service.d', arcname='systemd/tio-server.service.d')
    shutil.copy2(CLIENT_MANIFEST, backup/'client-manifest.json')
    (backup/'firewall-before.txt').write_text(command('ufw', 'status', 'numbered')+'\n')
    (backup/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (backup/'state.json').write_text(json.dumps(state, indent=2)+'\n')
    return backup, state, before


def save_state(backup, state):
    (backup/'state.json').write_text(json.dumps(state, indent=2)+'\n')


def rollback(backup):
    backup = backup.resolve(strict=True)
    if backup.parent != Path('/root') or not backup.name.startswith('tio-before-game-tls-'):
        raise ValueError('Unexpected rollback directory')
    state = json.loads((backup/'state.json').read_text())
    command('systemctl', 'stop', 'tio-server', timeout=75)
    for name, existed in state['files'].items():
        if name not in ALLOWED:
            raise ValueError('Unexpected rollback file')
        if existed:
            atomic_copy(backup/'files'/name, ROOT/name)
        else:
            (ROOT/name).unlink(missing_ok=True)
    for source, name in ((CONFIG, 'server.toml'), (DROPIN, 'game-tls.conf'), (HOOK, 'renewal-hook')):
        if state['system_files'][str(source)]:
            atomic_copy(backup/name, source, 0o755 if source == HOOK else 0o640 if source == CONFIG else 0o644)
        else:
            source.unlink(missing_ok=True)
    if state['launcher_published']:
        atomic_copy(backup/'TIO-Launcher.exe', LAUNCHER)
    for port in state['firewall_added']:
        if port not in TLS_PORTS:
            raise ValueError('Unexpected firewall rollback port')
        command('ufw', '--force', 'delete', 'allow', str(port)+'/tcp')
    command('systemctl', 'daemon-reload')
    command('systemctl', 'start', 'tio-server')
    if command('systemctl', 'is-active', 'tio-server') != 'active':
        raise RuntimeError('Rolled-back game service is not healthy')
    return {'rollback': True, 'backup': str(backup), 'service': 'active', 'database_restored': False}


def deploy(stage, manifest):
    verify_baseline(manifest)
    verify_idle()
    command('systemctl', 'stop', 'tio-server', timeout=75)
    backup = None
    try:
        backup, state, before = backup_host(manifest)
        for name in sorted(ALLOWED):
            atomic_copy(stage/name, ROOT/name)
        certificate = json.loads(command(str(ROOT/'.venv/bin/python'), str(ROOT/'deploy/renew_game_tls.py'), '--no-reload'))
        config_text = CONFIG.read_text().rstrip()+'''\n\n[tls]\nenabled = true\nlogin_port = 29512\nsession_port = 29513\ncertificate = "/etc/tio-server/tls/current/fullchain.pem"\nprivate_key = "/etc/tio-server/tls/current/privkey.pem"\nhandshake_timeout_seconds = 5\nmax_handshakes = 4\n'''
        CONFIG.write_text(config_text)
        CONFIG.chmod(0o640)
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        DROPIN.write_text('[Service]\nExecReload=\nExecReload=/bin/kill -HUP $MAINPID\n')
        DROPIN.chmod(0o644)
        HOOK.parent.mkdir(parents=True, exist_ok=True)
        HOOK.write_text('#!/bin/sh\nset -eu\nexec /usr/bin/python3 /opt/tio-emulator/deploy/renew_game_tls.py\n')
        HOOK.chmod(0o755)
        preflight = command('runuser', '-u', 'tio', '--', str(ROOT/'.venv/bin/python'), '-m', 'server', '--config', str(CONFIG), '--check')
        command('systemctl', 'daemon-reload')
        command('systemctl', 'start', 'tio-server')
        if command('systemctl', 'is-active', 'tio-server') != 'active':
            raise RuntimeError('Updated game service failed to start')
        # UFW operations change only the two agreed TLS ports. Direct gameplay
        # and SSH rules remain available during the migration.
        firewall = command('ufw', 'status')
        for port in TLS_PORTS:
            if not any(line.split()[0] == str(port)+'/tcp' for line in firewall.splitlines() if line.split()):
                state['firewall_added'].append(port)
                save_state(backup, state)
                command('ufw', 'allow', str(port)+'/tcp')
        after = table_digests(DATABASE)
        if before != after:
            raise RuntimeError('Hosted player rows changed during code-only TLS rollout')
        if digest(CLIENT_MANIFEST) != manifest['client_manifest'] or digest(LAUNCHER) != manifest['launcher_before']:
            raise RuntimeError('Client publication changed unexpectedly')
        report = {'backup': str(backup), 'service': 'active', 'preflight': preflight,
                  'tls_ports': TLS_PORTS, 'certificate': certificate,
                  'existing_tables_unchanged': len(before), 'accounts_preserved': before['accounts']['rows'],
                  'database_uploaded': False, 'launcher_published': False,
                  'client_manifest_unchanged': True, 'files': {name: digest(ROOT/name) for name in sorted(ALLOWED)}}
        (backup/'deployment.json').write_text(json.dumps(report, indent=2)+'\n')
        return report
    except BaseException:
        if backup is not None:
            rollback(backup)
        else:
            command('systemctl', 'start', 'tio-server')
        raise


@contextmanager
def reviewed_launcher_source(stage, candidate, expected):
    if candidate is None and expected is None:
        yield stage/'TIO-Launcher.exe', None
        return
    if candidate is None or expected is None or re.fullmatch(r'[0-9a-fA-F]{64}', expected) is None:
        raise ValueError('A reviewed launcher requires both its candidate path and a 64-digit SHA256')
    candidate = Path(candidate)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise ValueError('Launcher candidate must be an absolute non-symlink regular file under /root')
    candidate = candidate.resolve(strict=True)
    if not candidate.is_relative_to(LAUNCHER_CANDIDATE_ROOT) or not candidate.is_file():
        raise ValueError('Launcher candidate must remain inside /root')
    metadata = candidate.stat()
    if metadata.st_uid != 0 or not 1024 * 1024 <= metadata.st_size <= MAX_LAUNCHER_BYTES:
        raise ValueError('Launcher candidate must be root-owned and between 1 and 200 MiB')
    # Snapshot first and verify its exact bytes before state or public files
    # change, preventing a source change between review and atomic publication.
    with tempfile.TemporaryDirectory(prefix='tio-reviewed-launcher-', dir=stage.parent) as folder:
        snapshot = Path(folder)/'TIO-Launcher.exe'
        shutil.copyfile(candidate, snapshot)
        size = snapshot.stat().st_size
        if not 1024 * 1024 <= size <= MAX_LAUNCHER_BYTES:
            raise ValueError('Reviewed launcher snapshot size is outside the allowed range')
        if digest(snapshot) != expected.lower():
            raise ValueError('Reviewed launcher candidate SHA256 mismatch')
        yield snapshot, {'path': str(candidate), 'sha256': expected.lower(), 'bytes': size}


def publish_launcher(stage, manifest, backup, *, launcher_candidate=None, launcher_sha256=None):
    backup = backup.resolve(strict=True)
    if backup.parent != Path('/root') or not backup.name.startswith('tio-before-game-tls-'):
        raise ValueError('Unexpected publication backup')
    if json.loads((backup/'manifest.json').read_text()) != manifest:
        raise RuntimeError('Publication archive differs from deployed TLS archive')
    for name, hashes in manifest['files'].items():
        if digest(stage/name) != hashes['after']:
            raise RuntimeError('Staged TLS source changed before publication')
        if digest(ROOT/name) != hashes['after']:
            raise RuntimeError('Deployed TLS source changed before publication')
    if digest(stage/'TIO-Launcher.exe') != manifest['launcher_after']:
        raise RuntimeError('Original staged launcher changed before publication')
    if digest(LAUNCHER) != manifest['launcher_before'] or digest(CLIENT_MANIFEST) != manifest['client_manifest']:
        raise RuntimeError('Published client baseline changed')
    if command('systemctl', 'is-active', 'tio-server') != 'active':
        raise RuntimeError('The live game service is not active')
    with reviewed_launcher_source(stage, launcher_candidate, launcher_sha256) as (source, reviewed):
        state = json.loads((backup/'state.json').read_text())
        state['launcher_published'] = True
        save_state(backup, state)
        atomic_copy(source, LAUNCHER)
        report = json.loads((backup/'deployment.json').read_text())
        report.update(launcher_published=True, launcher_sha256=digest(LAUNCHER), launcher_bytes=LAUNCHER.stat().st_size)
        if reviewed is not None:report['reviewed_launcher_candidate'] = reviewed
        (backup/'deployment.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path('/root/tio-game-tls-patch.tar.gz'))
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--publish-launcher', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--launcher-candidate', type=Path)
    parser.add_argument('--launcher-sha256')
    args = parser.parse_args(argv)
    if sum((args.check_only, args.publish_launcher, args.rollback)) > 1:
        parser.error('Choose one of --check-only, --publish-launcher or --rollback')
    if args.launcher_candidate is not None or args.launcher_sha256 is not None:
        if (not args.publish_launcher or args.launcher_candidate is None
                or args.launcher_sha256 is None or re.fullmatch(r'[0-9a-fA-F]{64}', args.launcher_sha256) is None):
            parser.error('A candidate path and SHA256 must be supplied together, only with --publish-launcher')
    if os.geteuid() != 0 or not ROOT.is_dir():
        raise RuntimeError('This tool runs only as root on the documented hosting server')
    if args.rollback:
        if args.backup is None:
            parser.error('--rollback requires --backup')
        result = rollback(args.backup)
    else:
        stage, manifest = unpack(args.archive)
        if args.check_only:
            verify_baseline(manifest)
            result = {'check_only': True, 'baseline_verified': True}
        elif args.publish_launcher:
            if args.backup is None:
                parser.error('--publish-launcher requires --backup')
            result = publish_launcher(stage, manifest, args.backup,
                launcher_candidate=args.launcher_candidate, launcher_sha256=args.launcher_sha256)
        else:
            result = deploy(stage, manifest)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
