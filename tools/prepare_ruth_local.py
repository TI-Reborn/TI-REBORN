"""Prepare two disposable game copies and an authenticated loopback server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket

from server.accounts import Accounts
from server.config import ServerConfig
from tio.rating_visibility import QA_LOGIN
from tio.wallets import WalletStore, NEW_CHARACTER_CREDITS
from tio.db_transaction import transaction
from tools.build_launcher_silver_regions import require_compatible

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / 'work/launcher-adapters-0159-20261120/launcher'
SOURCE = ROOT / 'work/implant-workshop-qa-20261121/game-a'
OUTPUT = ROOT / 'work/ruth-local-20261121'
CERTS = ROOT / 'tests/fixtures/game_tls'
ARTWORK = ROOT / 'assets/onboarding-quests-v1'


def free_ports() -> tuple[int, int, int, int]:
    with socket.socket() as first, socket.socket() as second, socket.socket() as third, socket.socket() as fourth:
        for connection in (first, second, third, fourth):
            connection.bind(('127.0.0.1', 0))
        return tuple(connection.getsockname()[1] for connection in (first, second, third, fourth))


def copy_asset(source: str, destination: str) -> None:
    # The local launcher has no updater. Share only large read-only media.
    if Path(source).suffix.lower() in ('.hd', '.png', '.jpg', '.tga'):
        os.link(source, destination)
    else:
        shutil.copy2(source, destination)


def create_accounts(config: Path) -> None:
    database = ServerConfig.load(config).database
    credentials_file = config.parent / 'local-accounts.json'
    if database.exists() or credentials_file.exists():
        raise FileExistsError('Refusing to overwrite local accounts or game data')
    accounts = Accounts(database)
    prefix = 'qr' + secrets.token_hex(4)
    credentials = {}
    for suffix, character in (('a', 'RuthScout'), ('b', 'RuthRival'), ('c', None)):
        owner = prefix + suffix
        assert QA_LOGIN.fullmatch(owner)
        password = secrets.token_urlsafe(21)
        accounts.create(owner, password, character=character)
        if character is not None:
            WalletStore(database).ensure(owner)
            with transaction(database) as db:
                db.execute('UPDATE wallets SET credits=? WHERE account=?', (NEW_CHARACTER_CREDITS, owner))
        credentials[suffix] = dict(login=owner, password=password, character=character)
    credentials_file.write_text(json.dumps(credentials, indent=2), encoding='utf-8')


def prepare(source: Path) -> Path:
    source = source.resolve(strict=True)
    if not (source / '.tio-owned-qa').is_file():
        raise ValueError('Provide a known, dedicated .tio-owned-qa client')
    silver = (source / 'silver.dll').read_bytes()
    require_compatible(silver, LAUNCHER / 'Assets/native-silver-regions.json')
    tls_key = CERTS / 'valid-key.pem'
    for prerequisite in (tls_key, CERTS / 'valid-chain.pem', CERTS / 'ca.pem'):
        if not prerequisite.is_file():
            raise ValueError('Generate the local test TLS fixtures before preparation')
    OUTPUT.mkdir()
    (OUTPUT / '.ruth-local').write_text('loopback-only fixture\n', encoding='utf-8')
    (OUTPUT / 'artwork').mkdir()
    for name in ('ruth-voss.png', 'ruth-dialogue.png'):
        shutil.copy2(ARTWORK / name, OUTPUT / 'artwork' / name)

    for name in ('ca.pem', 'valid-chain.pem', 'valid-key.pem'):
        shutil.copy2(CERTS / name, OUTPUT / name)
    login, session, tls_login, tls_session = free_ports()
    (OUTPUT / 'admission/updates').mkdir(parents=True)
    (OUTPUT / 'admission/downloads').mkdir()
    (OUTPUT / 'admission/updates/manifest.json').write_text(json.dumps(dict(
        silver=hashlib.sha256(silver).hexdigest(), tls_login=tls_login, tls_session=tls_session)), encoding='utf-8')
    (OUTPUT / 'admission/downloads/launcher-manifest.json').write_text('{"version":"0.1.59"}', encoding='utf-8')
    config = OUTPUT / 'server.toml'
    config.write_text(f'''bind_address = "127.0.0.1"
advertised_address = "127.0.0.1"
game_port = {login}
session_port = {session}
data_directory = "data"
log_level = "INFO"
multi_account = true
contracts_enabled = true
sqlite_wal = true
[tls]
enabled = true
login_port = {tls_login}
session_port = {tls_session}
certificate = "valid-chain.pem"
private_key = "valid-key.pem"
launch_manifests = "admission"
max_handshakes = 8
''', encoding='utf-8')
    create_accounts(config)

    for suffix in ('a', 'b'):
        copy = OUTPUT / ('game-' + suffix)
        copy.mkdir()
        shutil.copytree(source / 'base', copy / 'base', copy_function=copy_asset,
                        ignore=shutil.ignore_patterns('login.ini', 'notes-*.cfg', 'log*.txt'))
        for entry in source.iterdir():
            if entry.name == '.tio-owned-qa' or entry.suffix.lower() in ('.dll', '.exe'):
                shutil.copy2(entry, copy / entry.name)
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    args = parser.parse_args()
    print(prepare(args.source))
