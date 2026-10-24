"""Opt-in warehouse captions; all counts and lists share a read-only snapshot.

No request creates schema, wallets, services or item rows. The existing store
remains transfer authority, joined to the hub-owned gameplay transaction.
Legacy/overflow items remain accessible without consuming private city slots.
"""
from contextlib import closing, contextmanager
from contextvars import ContextVar
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import sqlite3
import time

from tio.db_transaction import current, transaction
from tio.character_identity import owner_for_slot, alias
from tio import warehouse_completion as completion
from tio.clans import ClansStore, require, VIEW_WAREHOUSE, VIEW_SAFE, MONEY_IDS
from tio.protocol.binary import PacketError
from tio.protocol.warehouse import (encode_private_warehouse_snapshot,
    encode_warehouse_list, warehouse_item_from_inventory, WarehouseItem,
    decode_warehouse_list)
from tio.protocol.warehouse_capacity import OPT_IN, Snapshot, encode_snapshot, encode_clear
from tio.protocol.transport import InitialCipher, encode_initial_frame


@dataclass
class State:
    enabled: bool = False
    negotiated: bool = False
    identity: tuple | None = None
    town: int | None = None
    clan: tuple | None = None
    kind: int | None = None
    signatures: dict = field(default_factory=dict)
    pending_segments: dict = field(default_factory=dict)
    next_poll: float = 0


def state(session):
    value = getattr(session, '_warehouse_capacity', None)
    if value is None:
        value = State(); session._warehouse_capacity = value
    return value


def reset(session):
    """A replaced game connection never inherits another connection's opt-in."""
    session._warehouse_capacity = State()


def _active(session):
    router = getattr(session, 'router', None)
    login = getattr(session, 'authenticated_account', None)
    if router is None or not isinstance(login, str) or not login:
        raise ValueError('Authenticated warehouse session required')
    with router.lock:
        if router.active_accounts.get(login) is not session:
            raise ValueError('Warehouse session is no longer active')
    return router, login


# Hot callbacks may open their own SQL readers. Capture them before BEGIN,
# then validate every persisted authority field on the single snapshot DB.
# ContextVar prevents cross-session/thread reuse; every exit resets its token.
_read_snapshot = ContextVar('tio_warehouse_read_snapshot', default=None)


def _preflight(session):
    from .economy_runtime import city_idle
    router, login = _active(session)
    owner = getattr(session, 'account', None)
    slot = getattr(session, 'selected_character_slot', 1)
    character = getattr(session, 'probe_character_id', None)
    if (not getattr(session, 'owned_pet_probe', False) or type(character) is not int
            or not 0 < character <= 0xffffffff or alias(login, slot) != owner):
        raise ValueError('Owned selected character required')
    # city_idle includes this owner's shared/private battle leases. The SQL
    # snapshot below rechecks persisted leases; unrelated sessions do not
    # participate in authorising this owner's personal or clan warehouse.
    if not city_idle(session):
        raise ValueError('Warehouse is available in an idle city only')
    return (login, owner, slot, character), session.locations.current(owner)


@contextmanager
def readonly(session):
    # Outward state must never describe a transaction that can still roll back.
    if current() is not None:
        raise ValueError('Warehouse snapshot requires a committed gameplay unit')
    router, _ = _active(session)
    with router.team_arena.lock:
        # Open mode=ro before callbacks: absence cannot create a new database.
        # The connection has executed no SQL and holds no snapshot lock yet.
        with closing(sqlite3.connect(Path(session.database).resolve().as_uri()+'?mode=ro', uri=True)) as db:
            hot = _preflight(session)
            db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
            token = _read_snapshot.set((session, db, hot))
            try:
                yield db
            finally:
                _read_snapshot.reset(token)


def _context(session, db):
    router, login = _active(session)
    captured = _read_snapshot.get()
    if captured is not None and captured[0] is session and captured[1] is db:
        identity, hot_town = captured[2]
    else:
        # Mutations already own the authoritative write transaction. Nested
        # stores join its Lease, so their callbacks do not open a second DB.
        if current() is not db:
            raise ValueError('Warehouse context requires its own committed snapshot or gameplay unit')
        identity, hot_town = _preflight(session)
    owner = getattr(session, 'account', None)
    slot = getattr(session, 'selected_character_slot', 1)
    character = getattr(session, 'probe_character_id', None)
    if (not getattr(session, 'owned_pet_probe', False) or type(character) is not int
            or not 0 < character <= 0xffffffff or owner_for_slot(db, login, slot) != owner):
        raise ValueError('Owned selected character required')
    if not db.execute('SELECT 1 FROM owned_pets WHERE account=? AND pet_id=1', (owner,)).fetchone():
        raise ValueError('Owned primary mercenary required')
    if identity != (login, owner, slot, character):
        raise ValueError('Warehouse selected identity changed')
    for table in ('battle_checkpoint_members', 'battle_settlement_jobs'):
        if completion.exists(db, table) and db.execute(
                'SELECT 1 FROM '+table+' WHERE account=?', (owner,)).fetchone():
            raise ValueError('Warehouse is available in an idle city only')
    town = completion.current_town(db, owner)
    if hot_town != town:
        raise ValueError('Warehouse town changed')
    if completion.exists(db, 'world_prison') and db.execute(
            'SELECT 1 FROM world_prison WHERE account=? AND remaining>0', (owner,)).fetchone():
        raise ValueError('Warehouse is unavailable in prison')
    from tio.clans import membership
    clan = membership(db, owner)
    return (login, owner, slot, character), town, (clan['id'], clan['permissions'], clan['leader']) if clan else None


def _data(session, db, kind, context):
    identity, town, clan = context
    owner, character = identity[1], identity[3]
    if type(kind) is not int or kind not in (0, 1, 2):
        raise PacketError('Unknown capacity warehouse kind')
    if kind == 0:
        status = completion.status(db, owner)
        from tio.warehouse import WarehouseStore
        items = tuple(completion.read_scope(db, owner).values())
        capacity, used, accessible = status['capacity'], status['used'], len(items)
        packets = encode_private_warehouse_snapshot(items)
    else:
        authorised = require(db, owner, VIEW_WAREHOUSE if kind == 1 else VIEW_SAFE)
        items = [warehouse_item_from_inventory(item) for item in ClansStore._items(db, authorised['id'], kind).values()]
        capacity = completion.clan_capacity(db, authorised['id'], kind)
        used = len(items)
        if kind == 2:
            items.extend(WarehouseItem(key, template, authorised[column], 0, 0, 0)
                         for key, (column, template, _) in MONEY_IDS.items() if authorised[column])
        accessible = len(items)
        packets = (encode_warehouse_list(kind, 1, 0, items),)
    from tio.bank_economy import project_marks
    packets = tuple(project_marks(db, owner, packet) for packet in packets)
    snapshot = encode_snapshot(Snapshot(character, town, kind, capacity, used, accessible))
    return snapshot, packets


def _bind(value, context):
    identity, town, clan = context
    if value.identity is not None and value.identity != identity:
        value.enabled = False; value.kind = None; value.signatures.clear()
        value.identity, value.town, value.clan = identity, town, clan
        return (encode_clear(),)
    town_changed = value.town is not None and value.town != town
    changed = value.town is not None and (town_changed or value.clan != clan)
    value.identity, value.town, value.clan = identity, town, clan
    if changed:
        value.signatures.clear()
        if town_changed: value.kind = None
        return (encode_clear(),)
    return ()


def opt_in(session, packet):
    """Consume only the agreed exact v1 opt-in; C2S supplies no owner or town."""
    if packet[:1] != b'\xfa': return None
    value = state(session)
    if packet != OPT_IN:
        replies = (encode_clear(),) if value.enabled else ()
        reset(session); return replies
    try:
        with readonly(session) as db: context = _context(session, db)
    except (ValueError, sqlite3.Error):
        replies = (encode_clear(),) if value.enabled else ()
        reset(session); return replies
    changed = _bind(value, context)
    value.enabled = True; value.negotiated = True
    return changed


def query(session, packet):
    """Replace only 69/0..2, without constructors that initialise SQL tables."""
    if packet[:1] != b'\x69': return None
    if len(packet) != 2: raise PacketError('Invalid warehouse query length')
    kind = packet[1]
    if kind not in (0, 1, 2): return None
    with readonly(session) as db:
        context = _context(session, db)
        snapshot, packets = _data(session, db, kind, context)
    value = state(session)
    prefix = _bind(value, context) if value.enabled else ()
    if value.enabled:
        value.kind = kind
        value.signatures[kind] = hashlib.sha256(snapshot+b''.join(packets)).digest()
        return prefix+(snapshot,)+packets
    return packets


def transfer(session, packet, *, capacity):
    """Canonical 6B mutation commits before any matching outward snapshot."""
    from tio.warehouse_service import transfer_private_items
    from tio.protocol.warehouse_transfer import decode_warehouse_transfer
    request = decode_warehouse_transfer(packet)
    router, _ = _active(session)
    if current() is not None: raise ValueError('Outward transfer must own its gameplay unit')
    with router.team_arena.lock:
        with transaction(session.database) as db:
            _context(session, db)
            packets = transfer_private_items(session.database, session.account, packet, capacity=capacity)
        # Store scopes cannot commit the outer unit. Re-read only after commit.
        fresh = query(session, bytes((0x69, request.warehouse_type)))
        if fresh is None: raise PacketError('Unknown transfer warehouse kind')
        from .economy_runtime import note_warehouse_transfer
        note_warehouse_transfer(session, packets)
        result = []
        inserted = False
        for packet in packets:
            if packet[:1] == b'\x6a':
                if not inserted: result.extend(fresh); inserted = True
            else: result.append(packet)
        return tuple(result)


def encode_transfer_replies(
        database: str | Path, replies: tuple[bytes, ...], cipher: InitialCipher,
        encode_reply: Callable[[bytes, InitialCipher], bytes]) -> bytes:
    """Project a committed transfer's replies on one short SQL unit.

    City weight, armor, marks and counters otherwise reopen the same database
    many times. Nested projectors join this unit; no frames leave until commit.
    The item transfer itself has already committed independently.
    """
    with transaction(database):
        return b''.join(encode_initial_frame(reply, cipher)
                        if reply[:1] in (b'\xfa', b'\x6a') else encode_reply(reply, cipher)
                        for reply in replies)


def _invalidate(value, *, disable=True):
    had = value.enabled
    value.signatures.clear(); value.kind = None
    if disable: value.enabled = False
    return (encode_clear(),) if had else ()


def poll(session, *, now=None):
    """At most one selected kind per two seconds, only for opted-in sessions."""
    value = state(session)
    if not value.enabled: return ()
    now = time.monotonic() if now is None else now
    if now < value.next_poll: return ()
    value.next_poll = now+2
    try:
        with readonly(session) as db:
            context = _context(session, db)
            prefix = _bind(value, context)
            if not value.enabled or value.kind is None: return prefix
            snapshot, packets = _data(session, db, value.kind, context)
            signature = hashlib.sha256(snapshot+b''.join(packets)).digest()
            if signature == value.signatures.get(value.kind): return prefix
            value.signatures[value.kind] = signature
            return prefix+(snapshot,)+packets
    except (ValueError, sqlite3.Error):
        return _invalidate(value)


def frames(session, packet, cipher):
    """Replace passive 6A with one complete authorised FA+6A snapshot.

    A queued list may predate a clan/rights change. Re-read its whole kind at
    delivery, rather than attaching new counts to old or foreign item rows.
    Subsequent segments of the replaced old list are consumed without output.
    None leaves the original transport path byte-for-byte unchanged.
    """
    value = state(session)
    if packet[:1] == b'\x6a' and len(packet) >= 9:
        pending_kind = int.from_bytes(packet[1:5], 'little')
        pending_segment = int.from_bytes(packet[7:9], 'little')
        pending_total = value.pending_segments.get(pending_kind)
        if pending_segment and pending_total is not None:
            if pending_segment >= pending_total-1: value.pending_segments.pop(pending_kind, None)
            return b''
    if not value.enabled and not (value.negotiated and packet[:1] == b'\x6a'): return None
    if packet[:5] == b'\xf0\x61\0\0\0':
        return b''.join(encode_initial_frame(p, cipher) for p in _invalidate(value)+(packet,))
    if packet[:1] != b'\x6a': return None
    try:
        kind, total, segment, _ = decode_warehouse_list(packet)
        if kind not in (0, 1, 2): raise PacketError('Unknown capacity warehouse kind')
        if segment: return b''
        if total > 1: value.pending_segments[kind] = total
        with readonly(session) as db:
            context = _context(session, db)
            prefix = _bind(value, context) if value.enabled else ()
            snapshot, packets = _data(session, db, kind, context)
        value.signatures[kind] = hashlib.sha256(snapshot+b''.join(packets)).digest()
        return b''.join(encode_initial_frame(p, cipher) for p in prefix+((snapshot,) if value.enabled else ())+packets)
    except (ValueError, sqlite3.Error):
        kind = int.from_bytes(packet[1:5], 'little') if len(packet) >= 5 else 0
        packets = _invalidate(value)
        if kind in (0, 1, 2): packets += (encode_warehouse_list(kind, 1, 0, ()),)
        return b''.join(encode_initial_frame(p, cipher) for p in packets)
