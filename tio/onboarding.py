"""Durable creation -> appearance -> character selection workflow."""

from .db_transaction import connect
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .characters import CharacterStore
from .owned_pets import OwnedPetStore
from .wallets import WalletStore
from .protocol.character_create import decode_character_create

OPEN_APPEARANCE = b'\x12\x05'  # Emulator extension; paired with client patch.


def pending(path, account):
    with closing(connect(path)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS character_onboarding (account TEXT PRIMARY KEY, completed INTEGER NOT NULL DEFAULT 0)')
        row=db.execute('SELECT completed FROM character_onboarding WHERE account=?',(account,)).fetchone()
        if row is not None:return not row[0]
        # Resume characters made by the previous build which never entered town.
        char=db.execute('SELECT request FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
        if not char:return False
        has_pets=db.execute("SELECT 1 FROM sqlite_master WHERE name='owned_pets'").fetchone()
        if has_pets and db.execute('SELECT 1 FROM owned_pets WHERE account=?',(account,)).fetchone():return False
        if decode_character_create(bytes(char[0])).options[0] not in (1,2):return False
        db.execute('INSERT INTO character_onboarding VALUES (?,0)',(account,))
        return True


def prepare(path,account):
    fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
    OwnedPetStore(path).ensure(account,bytes.fromhex(fixture['packet_hex']),
                              bytes.fromhex(fixture['inventory_packet_hex']),human=True)
    WalletStore(path).ensure(account)
    return CharacterStore(path).list(account)


def initialize_created(path,account):
    """Trusted NEW-create boundary; joins the enclosing creation transaction.

    This is never called by login, prepare, resume or save migration. Requiring
    the caller's transaction makes character/main/starter/wallet creation one
    rollback unit rather than a partially committed follow-up grant.
    """
    from .db_transaction import current,key
    from .roster_progression import grant_starters
    from .ability_progression import policy
    db=current()
    if db is None:raise ValueError('New character initialization requires creation transaction')
    if key(db.execute('PRAGMA database_list').fetchone()[2])!=key(path):raise ValueError('New creation belongs to another database')
    if policy()['extra_starter_mercenaries']!=2:raise ValueError('New characters require exactly two starter mercenaries')
    row=db.execute('SELECT request FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
    if row is None:raise ValueError('New character is missing')
    fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
    template=bytes.fromhex(fixture['packet_hex'])
    OwnedPetStore(path).ensure(account,template,bytes.fromhex(fixture['inventory_packet_hex']),human=True)
    WalletStore(path).ensure(account)
    starters=grant_starters(path,account,template,created=True)
    db.execute('CREATE TABLE IF NOT EXISTS character_onboarding(account TEXT PRIMARY KEY,completed INTEGER NOT NULL DEFAULT 0)')
    if decode_character_create(bytes(row[0])).options[0] in (1,2):
        db.execute('INSERT OR IGNORE INTO character_onboarding VALUES (?,0)',(account,))
    return starters


def pending_owner(path,login):
    """Resume unfinished creation without ever changing the authenticated login."""
    store=CharacterStore(path)
    for record in store.list(login):
        owner=store.owner(login,record.record_id)
        if pending(path,owner):return owner
    return None
