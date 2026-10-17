"""Publish a validated UI-only archive without restarting the hosted game service.

The module is safe to import for local validation. Only main() writes anything.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile


ROOT = Path('/opt/tio-emulator')
DATABASE = Path('/var/lib/tio-server/reservation.sqlite3')
CONFIGURATION = Path('/etc/tio-server/server.toml')
LIVE = Path('/var/www/tio-client/updates')
STAGING_ROOT = Path('/root')
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.dds', '.ajpg'}
ADDITIONAL_UI_PATHS = {'base/fonts/menu.xml', 'base/fonts/menu.png'}
NEW_UI_PATHS = {'base/pda/menubutton.png', 'base/pda/menuframe.png',
                'base/fonts/menu.xml', 'base/fonts/menu.png'}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_ui_path(name: str) -> None:
    require(isinstance(name, str), 'UI path must be a string')
    path = PurePosixPath(name)
    require(not path.is_absolute() and path.as_posix() == name and '..' not in path.parts
            and '\\' not in name and ':' not in name, 'Unsafe UI path: ' + name)
    require((name.startswith(('base/pda/', 'base/gui/', 'base/gui2/'))
             and path.suffix.lower() in IMAGE_SUFFIXES) or name in ADDITIONAL_UI_PATHS,
            'Not an allowed UI resource: ' + name)
    require(all(re.fullmatch(r'[A-Za-z0-9_ .()\-]+', part)
                and not part.endswith(('.', ' ')) for part in path.parts),
            'Unsupported UI path: ' + name)


def validate_manifest(manifest):
    require(isinstance(manifest, dict) and manifest.get('schema') == 1,
            'Unexpected manifest schema')
    require(isinstance(manifest.get('version'), str)
            and re.fullmatch(r'\d{4}\.\d{2}\.\d{2}\.\d+', manifest['version']),
            'Invalid client version')
    require(isinstance(manifest.get('files'), list) and manifest['files'],
            'Manifest has no file records')
    records = {}
    for record in manifest['files']:
        require(isinstance(record, dict) and isinstance(record.get('path'), str),
                'Invalid file record')
        name = record['path']
        require(name not in records, 'Duplicate manifest path: ' + name)
        require(type(record.get('size')) is int and record['size'] >= 0,
                'Invalid file size: ' + name)
        require(isinstance(record.get('sha256'), str)
                and re.fullmatch(r'[0-9a-f]{64}', record['sha256']),
                'Invalid file checksum: ' + name)
        require('seed' not in record or type(record['seed']) is bool,
                'Invalid seed flag: ' + name)
        records[name] = record
    return records


def validate_manifests(previous, updated, allowed_paths, patch_plan=None, added_paths=None):
    """Preserve original records and permit only explicitly scoped UI changes."""
    before = validate_manifest(previous)
    after = validate_manifest(updated)
    require(isinstance(allowed_paths, list) and allowed_paths
            and all(isinstance(path, str) for path in allowed_paths)
            and len(set(allowed_paths)) == len(allowed_paths), 'Invalid UI allowlist')
    allowed = set(allowed_paths)
    for path in allowed:
        if path != 'silver.dll':
            validate_ui_path(path)
    require(('silver.dll' in allowed) == (patch_plan is not None),
            'silver.dll requires an explicit patch plan; other binaries are refused')
    added_paths = [] if added_paths is None else added_paths
    require(isinstance(added_paths, list) and all(isinstance(path, str) for path in added_paths)
            and len(set(added_paths)) == len(added_paths), 'Invalid explicit addition allowlist')
    additions = set(added_paths)
    require(additions <= NEW_UI_PATHS, 'Unapproved UI resource addition')
    require(additions == set(after) - set(before), 'Manifest paths or ordering changed')
    require(list(after) == list(before) + sorted(additions), 'Manifest paths or ordering changed')
    require(allowed <= set(after), 'UI allowlist contains an unpublished path')
    old_version = tuple(map(int, previous['version'].split('.')))
    new_version = tuple(map(int, updated['version'].split('.')))
    require(new_version > old_version, 'Client version must increase')
    require({key: value for key, value in previous.items()
             if key not in ('version', 'news', 'files')}
            == {key: value for key, value in updated.items()
                if key not in ('version', 'news', 'files')},
            'Non-release manifest metadata changed')
    if 'news' in updated:
        require(isinstance(updated['news'], str), 'Invalid release news')
    changed = {name for name in before if before[name] != after[name]} | additions
    require(changed == allowed, 'Changed records differ from the UI allowlist')
    for name in allowed:
        if name in additions:
            require(set(after[name]) == {'path', 'size', 'sha256', 'seed'}
                    and after[name]['seed'] is False and after[name]['size'] > 0,
                    'New UI resource metadata is invalid: ' + name)
            continue
        require(not before[name].get('seed', False) and not after[name].get('seed', False),
                'Seed settings cannot be replaced: ' + name)
        require({key: value for key, value in before[name].items()
                 if key not in ('size', 'sha256')}
                == {key: value for key, value in after[name].items()
                    if key not in ('size', 'sha256')},
                'Non-content file metadata changed: ' + name)
    if patch_plan is not None:
        validate_patch_plan(patch_plan, before['silver.dll'], after['silver.dll'])
    return before, after, allowed


def validate_patch_plan(plan, previous_record, updated_record):
    require(isinstance(plan, dict) and plan.get('path') == 'silver.dll',
            'Binary patch plan must target silver.dll')
    require(plan.get('previous_sha256') == previous_record['sha256']
            and plan.get('updated_sha256') == updated_record['sha256'],
            'Binary patch plan hashes differ from manifest records')
    require(previous_record['size'] == updated_record['size'],
            'Binary layout patch cannot change the file size')
    require(isinstance(plan.get('changes'), list) and plan['changes'],
            'Binary patch plan has no changed ranges')
    previous_end = 0
    total_bytes = 0
    for change in plan['changes']:
        require(isinstance(change, dict) and type(change.get('offset')) is int
                and change['offset'] >= previous_end, 'Binary patch ranges overlap or are unordered')
        old_hex, new_hex = change.get('previous_hex'), change.get('updated_hex')
        require(isinstance(old_hex, str) and isinstance(new_hex, str)
                and re.fullmatch(r'(?:[0-9a-fA-F]{2})+', old_hex) is not None
                and re.fullmatch(r'(?:[0-9a-fA-F]{2})+', new_hex) is not None
                and len(old_hex) == len(new_hex) and old_hex.lower() != new_hex.lower(),
                'Invalid old/new bytes in binary patch plan')
        size = len(old_hex) // 2
        previous_end = change['offset'] + size
        total_bytes += size
        require(previous_end <= previous_record['size'], 'Binary patch range exceeds file size')
    require(total_bytes <= 4096, 'Binary patch exceeds the scoped UI layout byte limit')


def validate_binary_patch(previous_raw, updated_raw, plan, previous_record, updated_record):
    validate_patch_plan(plan, previous_record, updated_record)
    validate_blob(previous_raw, previous_record)
    validate_blob(updated_raw, updated_record)
    cursor = 0
    for change in plan['changes']:
        offset = change['offset']
        old_bytes = bytes.fromhex(change['previous_hex'])
        new_bytes = bytes.fromhex(change['updated_hex'])
        end = offset + len(old_bytes)
        require(previous_raw[cursor:offset] == updated_raw[cursor:offset],
                'Binary change exists outside the explicit UI patch ranges')
        require(previous_raw[offset:end] == old_bytes and updated_raw[offset:end] == new_bytes,
                'Binary bytes differ from the explicit patch plan')
        cursor = end
    require(previous_raw[cursor:] == updated_raw[cursor:],
            'Binary change exists outside the explicit UI patch ranges')


def validate_blob(raw, record):
    require(len(raw) == record['size'] and sha(raw) == record['sha256'],
            'UI blob size/checksum mismatch: ' + record['path'])


def read_release(stage):
    previous_raw = (stage / 'previous-manifest.json').read_bytes()
    updated_raw = (stage / 'manifest.json').read_bytes()
    plan_path = stage / 'patch-plan.json'
    plan = json.loads(plan_path.read_bytes()) if plan_path.exists() else None
    addition_path = stage / 'added-paths.json'
    additions = json.loads(addition_path.read_bytes()) if addition_path.exists() else []
    before, after, allowed = validate_manifests(
        json.loads(previous_raw), json.loads(updated_raw),
        json.loads((stage / 'allowed-paths.json').read_bytes()), plan, additions)
    expected = {'previous-manifest.json', 'manifest.json', 'allowed-paths.json'}
    expected.update('blobs/' + after[name]['sha256'] for name in allowed)
    if plan is not None:
        expected.update({'patch-plan.json', 'previous-blobs/' + before['silver.dll']['sha256']})
    if additions:
        expected.add('added-paths.json')
    actual = {path.relative_to(stage).as_posix() for path in stage.rglob('*') if path.is_file()}
    require(actual == expected, 'Unexpected or missing release archive files')
    for name in allowed:
        validate_blob((stage / 'blobs' / after[name]['sha256']).read_bytes(), after[name])
    if plan is not None:
        validate_binary_patch(
            (stage / 'previous-blobs' / before['silver.dll']['sha256']).read_bytes(),
            (stage / 'blobs' / after['silver.dll']['sha256']).read_bytes(), plan,
            before['silver.dll'], after['silver.dll'])
    return previous_raw, updated_raw, before, after, allowed


def unpack_release(archive, archive_sha256, stage):
    require(re.fullmatch('[0-9a-f]{64}', archive_sha256) is not None,
            'Invalid expected archive checksum')
    require(sha(archive.read_bytes()) == archive_sha256, 'Release archive checksum mismatch')
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        names = [member.name for member in members]
        require(len(set(names)) == len(names), 'Duplicate release archive member')
        for member in members:
            require(member.isfile() and (member.name in
                    {'previous-manifest.json', 'manifest.json', 'allowed-paths.json',
                     'patch-plan.json', 'added-paths.json'}
                    or re.fullmatch(r'(?:blobs|previous-blobs)/[0-9a-f]{64}', member.name) is not None),
                    'Unsafe release archive member: ' + member.name)
        bundle.extractall(stage, filter='data')
    return read_release(stage)


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def service_state():
    return (command('systemctl', 'is-active', 'tio-server'),
            command('systemctl', 'show', 'tio-server', '--property=MainPID', '--value'))


def code_hashes():
    paths = list(ROOT.glob('*.py')) + list(ROOT.glob('*.toml'))
    for folder in ('tio', 'server', 'config', 'tools', 'deploy'):
        if (ROOT / folder).exists():
            paths.extend((ROOT / folder).rglob('*'))
    return {path.relative_to(ROOT).as_posix(): sha(path.read_bytes())
            for path in sorted(paths) if path.is_file() and '__pycache__' not in path.parts}


def copy_code_backup(backup):
    def filter_member(member):
        parts = PurePosixPath(member.name).parts
        return None if any(part in {'.git', '.venv', '__pycache__', 'data'}
                           for part in parts) else member
    with tarfile.open(backup / 'previous-code-config.tar.gz', 'w:gz') as bundle:
        for path in sorted(ROOT.iterdir()):
            bundle.add(path, arcname=path.name, filter=filter_member)


def atomic_manifest(raw, prefix):
    with tempfile.NamedTemporaryFile(dir=LIVE, prefix=prefix, delete=False) as output:
        output.write(raw)
        output.flush()
        import os
        os.fsync(output.fileno())
    pending = Path(output.name)
    try:
        pending.chmod(0o644)
        pending.replace(LIVE / 'manifest.json')
    finally:
        pending.unlink(missing_ok=True)


@contextmanager
def publication_lock():
    import fcntl
    with (LIVE / '.client-release.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def publish(archive, archive_sha256):
    stage = Path(tempfile.mkdtemp(prefix='tio-menu-interface-stage-', dir=STAGING_ROOT))
    old, new, before, after, allowed = unpack_release(archive, archive_sha256, stage)
    with publication_lock():
        require((LIVE / 'manifest.json').read_bytes() == old,
                'Published baseline changed; refusing a stale client release')
        original_state = service_state()
        require(original_state[0] == 'active' and int(original_state[1]) > 0,
                'Hosted game service is not healthy')
        original_code = code_hashes()
        backup = Path(tempfile.mkdtemp(prefix='tio-before-menu-interface-', dir=STAGING_ROOT))
        with closing(sqlite3.connect(f'file:{DATABASE}?mode=ro', uri=True)) as source, \
                closing(sqlite3.connect(backup / 'reservation.sqlite3')) as target:
            require(source.execute('PRAGMA integrity_check').fetchone()[0] == 'ok',
                    'Hosted database integrity check failed')
            source.backup(target)
            require(target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok',
                    'Hosted database backup integrity check failed')
            accounts = target.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
        (backup / 'reservation.sqlite3').chmod(0o600)
        fragment = Path(command('systemctl', 'show', 'tio-server',
                                '--property=FragmentPath', '--value'))
        shutil.copy2(CONFIGURATION, backup / 'server.toml')
        shutil.copy2(fragment, backup / 'tio-server.service')
        dropins = [Path(name) for name in shlex.split(command(
            'systemctl', 'show', 'tio-server', '--property=DropInPaths', '--value'))]
        if dropins:
            (backup / 'service-dropins').mkdir()
            require(len({path.name for path in dropins}) == len(dropins),
                    'Ambiguous service drop-in backup filenames')
            for dropin in dropins:
                shutil.copy2(dropin, backup / 'service-dropins' / dropin.name)
        (backup / 'effective-tio-server.service').write_text(
            command('systemctl', 'cat', 'tio-server') + '\n')
        copy_code_backup(backup)
        (backup / 'client-manifest.json').write_bytes(old)
        (backup / 'blobs').mkdir()
        for name in sorted(allowed):
            if name not in before:
                continue
            old_blob = LIVE / 'blobs' / before[name]['sha256']
            validate_blob(old_blob.read_bytes(), before[name])
            if name == 'silver.dll':
                validate_binary_patch(old_blob.read_bytes(),
                    (stage / 'blobs' / after[name]['sha256']).read_bytes(),
                    json.loads((stage / 'patch-plan.json').read_bytes()), before[name], after[name])
            shutil.copy2(old_blob, backup / 'blobs' / old_blob.name)
        require((LIVE / 'manifest.json').read_bytes() == old
                and code_hashes() == original_code and service_state() == original_state,
                'Hosted baseline changed while backing up')
        published = False
        try:
            for name in sorted(allowed):
                record = after[name]
                source = stage / 'blobs' / record['sha256']
                target = LIVE / 'blobs' / record['sha256']
                if target.exists():
                    validate_blob(target.read_bytes(), record)
                else:
                    with tempfile.NamedTemporaryFile(dir=LIVE / 'blobs', prefix='.ui-',
                                                     delete=False) as output:
                        output.write(source.read_bytes())
                    pending = Path(output.name)
                    try:
                        pending.chmod(0o644)
                        pending.replace(target)
                    finally:
                        pending.unlink(missing_ok=True)
                validate_blob(target.read_bytes(), record)
            require((LIVE / 'manifest.json').read_bytes() == old,
                    'Published baseline changed before manifest commit')
            atomic_manifest(new, '.menu-interface-')
            published = True
            require(service_state() == original_state and code_hashes() == original_code,
                    'Game service or server code changed during UI publication')
            with closing(sqlite3.connect(f'file:{DATABASE}?mode=ro', uri=True)) as source:
                require(source.execute('PRAGMA integrity_check').fetchone()[0] == 'ok',
                        'Hosted database integrity check failed after publication')
                current_accounts = source.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
            require(current_accounts >= accounts, 'Hosted account count decreased')
            report = dict(backup=str(backup), client_version=json.loads(new)['version'],
                          changed_files=len(allowed), service='active', service_restarted=False,
                          main_pid=original_state[1], server_code_unchanged=True,
                          accounts_in_backup=accounts, accounts_after=current_accounts,
                          database_uploaded=False, integrity='ok', manifest_sha256=sha(new),
                          previous_manifest_sha256=sha(old), archive_sha256=archive_sha256,
                          changed_paths=sorted(allowed),
                          added_paths=sorted(set(after) - set(before)),
                          validated_binary_patch='silver.dll' in allowed)
            report['service_dropins_backed_up'] = len(dropins)
            (backup / 'deployment.json').write_text(json.dumps(report, indent=2) + '\n')
        except BaseException:
            if published and (LIVE / 'manifest.json').read_bytes() == new:
                atomic_manifest(old, '.menu-interface-rollback-')
            raise
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--expected-archive-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.archive, args.expected_archive_sha256)))


if __name__ == '__main__':
    main()
