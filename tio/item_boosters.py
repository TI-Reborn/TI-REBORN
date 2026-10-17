"""Persistent saved-fighter boosters; native33 consumes owned instance once.

Gold offer prices, magnitudes, level gates and lifetimes are from manual80-82.
Per-fighter recipient/replace-family stacking are explicit server policy.
"""
from contextlib import closing
from dataclasses import replace
import math
import time

from .db_transaction import connect, transaction
from .protocol.item_list import decode_item_list, encode_item_list


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS item_boosters (
        account TEXT NOT NULL, pet_id INTEGER NOT NULL, family TEXT NOT NULL,
        template_id INTEGER NOT NULL, value INTEGER NOT NULL, expires_at REAL NOT NULL,
        PRIMARY KEY(account,pet_id,family),
        CHECK(family IN ('trainer','advisor','block_xp')),
        CHECK(value BETWEEN 1 AND 100))''')


def rule(template):
    from .battle_item_effects import rules
    row = rules()['items'].get(str(template))
    if row is None or row['kind'] != 'booster': raise ValueError('Unsupported booster')
    return row


def nontransferable(template):
    from .battle_item_effects import rules
    row = rules()['items'].get(str(template))
    return row is not None and row['kind'] == 'booster'


def _now(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid authoritative booster clock')
    return float(value)


def activate(db, account, identity, template, level, now):
    """Caller consumes the inventory in the same enclosing SQL transaction."""
    now = _now(now); row = rule(template)
    if not account or type(identity) is not int or identity <= 0: raise ValueError('Owned saved fighter required')
    if type(level) is not int or level < row['level']: raise ValueError('Booster level requirement not met')
    if db.execute('SELECT 1 FROM owned_pets WHERE account=? AND pet_id=?', (account, identity)).fetchone() is None:
        raise ValueError('Owned saved fighter required')
    schema(db)
    previous = db.execute('SELECT template_id,expires_at FROM item_boosters WHERE account=? AND pet_id=? AND family=?',
        (account, identity, row['family'])).fetchone()
    if previous is not None and previous[0] == template and previous[1] > now:
        raise ValueError('Identical booster is already active')
    expiry = now + row['seconds']
    db.execute('''INSERT INTO item_boosters VALUES (?,?,?,?,?,?)
        ON CONFLICT(account,pet_id,family) DO UPDATE SET
        template_id=excluded.template_id,value=excluded.value,expires_at=excluded.expires_at''',
        (account, identity, row['family'], template, row['value'], expiry))
    return expiry


def active(path, account, identity, now=None):
    now = _now(time.time() if now is None else now)
    with closing(connect(path)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='item_boosters'").fetchone() is None: return {}
        rows = db.execute('SELECT family,template_id,value,expires_at FROM item_boosters WHERE account=? AND pet_id=? AND expires_at>?',
                          (account, identity, now)).fetchall()
        return {family: dict(template=template, value=value, expires_at=expiry)
                for family, template, value, expiry in rows}


def use_saved(path, account, action, *, now=None):
    """City native33 route; stale/replayed IDs cannot renew a booster."""
    if action.option != 255: raise ValueError('Booster requires unspecified native33 target')
    from .protocol.pet_info import decode_pet_info
    with transaction(path) as db:
        row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                         (account, action.pet_id)).fetchone()
        if row is None: raise ValueError('Owned saved fighter required')
        human, profile, old = row
        owner, items, flag = decode_item_list(old)
        selected = next((i for i in items if i.instance_id == action.instance_id), None)
        if selected is None or selected.count < 1 or selected.equipped: raise ValueError('Owned unused booster required')
        level = decode_pet_info(profile, human_equipment=bool(human)).fields['0x8c4aef']
        activate(db, account, action.pet_id, selected.template_id, level, time.time() if now is None else now)
        inventory = encode_item_list(owner, tuple(replace(i, unknown_u32_01=i.count-1) if i == selected else i
            for i in items if i != selected or i.count > 1), flag)
        changed = db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=? AND inventory_packet=?',
                             (inventory, account, action.pet_id, old)).rowcount
        if changed != 1: raise ValueError('Booster inventory changed outside action')
    return inventory
