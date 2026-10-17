"""Prepare an isolated loopback test kit from an already verified local QA copy.

No network, installed-client access, SSH or process launch. Plaintext credentials
are written only to the isolated LOCAL_TEST_ACCOUNTS.txt and never returned.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.accounts import Accounts
from server.config import ServerConfig
from tio.onboarding import prepare as prepare_character


CREATOR = 'tools/prepare_contracts_local.py'
MARKER = '.tio-owned-contracts-local'
PROOF = 'contracts-client-provenance.json'
SOURCE_PROOF = 'qa-client-provenance.json'
SOURCE_CREATOR = 'tools/prepare_hosted_graphical_qa.py'
BINARIES = {'ti.exe', 'orange.dll', 'silver.dll', 'gold.dll', 'ode.dll', 'd3dx9_26.dll'}
IMMUTABLE_ART = {'.t', '.s', '.png', '.tga', '.jpg', '.jpeg', '.dds', '.bmp', '.wav', '.ogg', '.mp3', '.avi', '.fx', '.ttf'}
CONFIGS = {'base/config.cfg', 'base/autoexec.cfg', 'base/serverlist.cfg'}
SETTINGS = ('orange_addr 127.0.0.1\r\norange_port 28512\r\n'
            'g_language russian\r\nr_fullscreen 0\r\nr_width 1024\r\nr_height 768\r\n'
            'sound_enable 0\r\n').encode('ascii')
SERVERLIST = b'<Local Contracts> gameserver\r\n'
ACCOUNTS = {'contract_a': 'ContractA', 'contract_b': 'ContractB'}
LAUNCHER = r'''$ErrorActionPreference = 'Stop'
$clientRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$markerPath = Join-Path $clientRoot '.tio-owned-contracts-local'
$marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
if ($marker.creator -ne 'tools/prepare_contracts_local.py' -or $marker.root -ne $clientRoot) { throw 'Unowned local client copy' }
foreach ($relative in @('base/config.cfg', 'base/autoexec.cfg')) {
    $settings = Get-Content -LiteralPath (Join-Path $clientRoot $relative) -Raw
    $addresses = [regex]::Matches($settings, '(?m)^orange_addr\s+(\S+)\s*$')
    $ports = [regex]::Matches($settings, '(?m)^orange_port\s+(\d+)\s*$')
    if ($addresses.Count -ne 1 -or $addresses[0].Groups[1].Value -ne '127.0.0.1' -or $ports.Count -ne 1 -or $ports[0].Groups[1].Value -ne '28512') { throw 'Local client endpoint changed' }
}
Start-Process -FilePath (Join-Path $clientRoot 'ti.exe') -WorkingDirectory $clientRoot
'''


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def relative_path(value):
    path = PurePosixPath(value)
    if (not isinstance(value, str) or not value or path.is_absolute() or path.as_posix() != value
            or any(part in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_ .()\-]+', part)
                   or part.endswith(('.', ' '))
                   or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I) for part in path.parts)):
        raise ValueError('Unsafe client resource path')
    return path


def checked(root, relative):
    root = Path(root).absolute()
    target = root.joinpath(*relative_path(relative).parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Local test path escaped its designated directory')
    current = target
    while True:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('Local test path contains a filesystem link')
        if current == root:
            break
        if current.parent == current:
            raise ValueError('Local test path is outside its designated directory')
        current = current.parent
    return target


def atomic(target, *, data=None, source=None, hardlink=False):
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix='.contracts-stage-', dir=target.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        if hardlink:
            temporary.unlink()
            os.link(source, temporary)
        elif source is not None:
            shutil.copyfile(source, temporary)
        else:
            temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def excluded(relative):
    lower = relative.lower()
    name = PurePosixPath(lower).name
    return (lower.startswith('base/shared config/')
            or name in {'login.ini', 'skillbar.dat', 'log.txt', 'log_old.txt'}
            or name.startswith('notes-') or Path(name).suffix in {'.log', '.bak', '.dmp', '.sav'}
            or Path(name).suffix in {'.cfg', '.ini', '.dat', '.txt'}
            and any(word in name for word in ('credential', 'password', 'login')))


def safe_config(root, config_path):
    expected = checked(root, 'data/contracts-local')
    configuration = ServerConfig.load(config_path)
    if (configuration.bind_address != '127.0.0.1' or configuration.advertised_address != '127.0.0.1'
            or configuration.game_port != 28512 or configuration.session_port != 28513
            or configuration.data_directory != expected.resolve()
            or not configuration.multi_account or not configuration.contracts_enabled or configuration.tls.enabled):
        raise ValueError('Preparation requires loopback ports 28512/28513 and isolated data/contracts-local')
    return configuration


def source_records(root):
    source = checked(root, 'reports/arena-surroundings-implementation/client-qa/game-a')
    marker = json.loads(checked(source, '.tio-owned-qa').read_text(encoding='utf-8'))
    proof_path = checked(source, SOURCE_PROOF)
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    if (marker.get('schema') != 1 or marker.get('creator') != SOURCE_CREATOR or marker.get('root') != str(source)
            or proof.get('schema') != 1 or proof.get('creator') != SOURCE_CREATOR or proof.get('game_root') != str(source)):
        raise ValueError('Source is not the designated verified QA copy')
    records = proof.get('files')
    if not isinstance(records, list) or not records or proof.get('manifest_files') != len(records):
        raise ValueError('Source provenance has an invalid resource list')
    wanted, seen = [], set()
    for record in records:
        relative = record.get('path')
        path = relative_path(relative)
        lower = relative.lower()
        if lower in seen or not (lower in BINARIES or path.parts[0] == 'base' and len(path.parts) > 1):
            raise ValueError('Source provenance contains duplicate or unsupported resources')
        seen.add(lower)
        checksum, size = record.get('qa_sha256'), record.get('qa_size')
        if (not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum)
                or type(size) is not int or not 0 <= size <= 512 * 1024 * 1024):
            raise ValueError('Source resource size or hash is invalid')
        if excluded(relative):
            continue
        actual = checked(source, relative)
        if not actual.is_file() or actual.stat().st_size != size or digest(actual) != checksum:
            raise ValueError('Source QA resource no longer matches provenance: ' + relative)
        wanted.append(dict(path=relative, size=size, sha256=checksum))
    if not BINARIES.union(CONFIGS) <= seen:
        raise ValueError('Source QA copy lacks required executables/configuration')
    by_name = {record['path'].lower(): record for record in wanted}
    for name in ('ti.exe', 'orange.dll', 'silver.dll'):
        if proof.get('native_pins', {}).get(name) != by_name[name]['sha256']:
            raise ValueError('Source native pin changed: ' + name)
    return source, wanted, dict(path=str(proof_path), sha256=digest(proof_path),
                                manifest_version=proof.get('manifest_version'), source_files=len(records),
                                excluded_resources=len(records)-len(wanted))


def own_copy(root):
    root.mkdir(parents=True, exist_ok=True)
    marker_path = checked(root, MARKER)
    if marker_path.exists():
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
        if marker.get('schema') != 1 or marker.get('creator') != CREATOR or marker.get('root') != str(root):
            raise ValueError('Refuse a client directory owned by another preparation tool')
    else:
        if any(root.iterdir()):
            raise ValueError('Refuse to adopt a nonempty unmarked client directory')
        atomic(marker_path, data=(json.dumps(dict(schema=1, creator=CREATOR, root=str(root)), indent=2)+'\n').encode())


def prepare_copy(root, source, records, provenance, *, hardlinks=True):
    own_copy(root)
    managed = {record['path'] for record in records}
    allowed = managed | {MARKER, PROOF, 'launch-client.ps1'}
    for candidate in root.rglob('*'):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(root).as_posix()
        target = checked(root, relative)
        if excluded(relative):
            target.unlink()
        elif relative not in allowed:
            raise ValueError('Unexpected file in the owned local client: ' + relative)
    rows, counts = [], Counter()
    for record in records:
        relative = record['path']
        target, origin = checked(root, relative), checked(source, relative)
        if relative.lower() in CONFIGS:
            data = SERVERLIST if relative.lower().endswith('serverlist.cfg') else SETTINGS
            atomic(target, data=data)
            method = 'fresh_loopback_config'
            expected = hashlib.sha256(data).hexdigest()
        else:
            expected = record['sha256']
            immutable = hardlinks and target.suffix.lower() in IMMUTABLE_ART
            if (target.is_file() and target.stat().st_size == record['size'] and digest(target) == expected
                    and (immutable or target.stat().st_nlink == 1 and not os.path.samefile(target, origin))):
                method = 'existing_owned_verified'
            elif immutable:
                try:
                    atomic(target, source=origin, hardlink=True)
                    method = 'verified_immutable_hardlink'
                except OSError:
                    atomic(target, source=origin)
                    method = 'private_source_copy'
            else:
                atomic(target, source=origin)
                method = 'private_source_copy'
        if digest(target) != expected:
            raise ValueError('Prepared client hash verification failed: ' + relative)
        if target.suffix.lower() not in IMMUTABLE_ART and target.stat().st_nlink != 1:
            raise ValueError('Mutable/native client resource is not a private copy')
        counts[method] += 1
        rows.append(dict(path=relative, source_sha256=record['sha256'], sha256=expected,
                         size=target.stat().st_size, method=method))
    atomic(checked(root, 'launch-client.ps1'), data=LAUNCHER.encode('utf-8'))
    proof = dict(schema=1, creator=CREATOR, root=str(root), source=str(source), source_provenance=provenance,
                 prepared_utc=datetime.now(timezone.utc).isoformat(), resources=len(rows), methods=dict(counts),
                 files=rows, personal_files_copied=0, graphical_clients_started=0, endpoint='127.0.0.1:28512')
    atomic(checked(root, PROOF), data=(json.dumps(proof, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    return {name: proof[name] for name in ('root', 'resources', 'methods', 'graphical_clients_started', 'endpoint')}


def provision(config):
    data = config.data_directory
    data.mkdir(parents=True, exist_ok=True)
    database = checked(data, config.database.name)
    backup = None
    if database.exists():
        backup = checked(data, 'backups/reservation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8] + '.sqlite3')
        backup.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
    existing = set()
    if database.exists():
        with closing(sqlite3.connect(database)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone():
                existing = {row[0] for row in db.execute('SELECT login FROM accounts')}
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='characters'").fetchone():
                for login, name in ACCOUNTS.items():
                    row = db.execute('SELECT name FROM characters WHERE account=? AND slot=1', (login,)).fetchone()
                    if login in existing and (row is None or bytes(row[0]) != name.encode('ascii')):
                        raise ValueError('Existing local test character differs; preserved without reset')
    credentials_path = checked(data, 'LOCAL_TEST_ACCOUNTS.txt')
    saved = credentials_path.read_text(encoding='utf-8') if credentials_path.exists() else '# Isolated localhost contracts test accounts. Keep this file private.\n# login\tpassword\tcharacter\n'
    credentials = {}
    for line in saved.splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) != 3 or parts[0] not in ACCOUNTS or parts[2] != ACCOUNTS[parts[0]]:
            raise ValueError('Local credential file format changed; left untouched')
        if parts[0] in credentials:
            raise ValueError('Local credential file contains duplicate logins')
        credentials[parts[0]] = parts[1]
    new = [login for login in ACCOUNTS if login not in existing]
    for login in new:
        if login not in credentials:
            credentials[login] = secrets.token_urlsafe(24)
            saved = saved.rstrip('\n') + '\n' + login + '\t' + credentials[login] + '\t' + ACCOUNTS[login] + '\n'
    # Save new secrets before account creation so an interrupted run is resumable.
    if new or not credentials_path.exists():
        atomic(credentials_path, data=saved.encode('utf-8'))
        try:
            credentials_path.chmod(0o600)
        except OSError:
            pass
    accounts = Accounts(database)
    for login in new:
        accounts.create(login, credentials[login], character=ACCOUNTS[login])
        prepare_character(database, login)
    return dict(database=str(database), created_logins=new, preserved_logins=sorted(existing & ACCOUNTS.keys()),
                credentials_file=str(credentials_path), backup=str(backup) if backup else None)


def prepare(root=ROOT, *, config_path=None, hardlinks=True):
    root = Path(root).absolute()
    configuration = safe_config(root, config_path or checked(root, 'config/contracts-local.toml'))
    copies = [checked(root, 'reports/contracts-local/clients/game-' + suffix) for suffix in ('a', 'b')]
    for target in copies:
        marker = checked(target, MARKER)
        if target.exists() and any(target.iterdir()) and not marker.exists():
            raise ValueError('Refuse to adopt a nonempty unmarked client directory')
    source, records, provenance = source_records(root)
    results = [prepare_copy(target, source, records, provenance, hardlinks=hardlinks) for target in copies]
    accounts = provision(configuration)
    return dict(scope='isolated_local_contracts_test_kit', clients=results, accounts=accounts,
                source_provenance=provenance, graphical_validation=False, network_requests=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'config/contracts-local.toml')
    parser.add_argument('--no-hardlinks', action='store_true')
    args = parser.parse_args(argv)
    result = prepare(config_path=args.config, hardlinks=not args.no_hardlinks)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
