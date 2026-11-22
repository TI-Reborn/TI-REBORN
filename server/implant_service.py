"""Private city workshop routing and bounded native recipe catalogues."""
from contextlib import closing
from functools import lru_cache
import zlib

from tio.db_transaction import connect
from tio.implant_crafting import craft
from tio.implant_equipment import discard, destroy
from tio.implant_recipes import available_pairs, items_xml
from tio.item_presentation import items_xml as presented_items
from tio.owned_pets import OwnedPetStore
from tio.protocol.shared_config import MAX_COMPRESSED_SIZE, SharedConfigData, encode_shared_config_data
from tio.protocol.system_message import encode_shop_error
from .clan_service import enqueue
from .economy_runtime import city_idle


def recipe_pairs(session) -> tuple[tuple[int, int], ...]:
    inventories = ()
    if session.database is not None and session.account:
        with closing(connect(session.database)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='owned_pets'").fetchone():
                inventories = tuple(r[0] for r in db.execute(
                    'SELECT inventory_packet FROM owned_pets WHERE account=? AND human=1', (session.account,)))
    return available_pairs(inventories)


@lru_cache(maxsize=8)
def _pack_catalogue(source: bytes, pairs: tuple[tuple[int, int], ...]) -> tuple[bytes, SharedConfigData]:
    while True:
        xml = items_xml(source, pairs)
        compressor = zlib.compressobj(level=9, memLevel=6)
        compressed = compressor.compress(xml) + compressor.flush()
        if len(compressed) <= MAX_COMPRESSED_SIZE:
            return xml, SharedConfigData(b'items', len(xml), compressed)
        if not pairs:
            raise ValueError('Базовый каталог предметов превышает буфер клиента')
        # shortcut: omit surplus previews when the full catalogue exceeds the native buffer, until the client can carry it.
        pairs = pairs[:len(pairs) * MAX_COMPRESSED_SIZE // len(compressed)]


def _session_catalogue(session, pairs: tuple[tuple[int, int], ...] | None) -> tuple[bytes, SharedConfigData]:
    pairs = recipe_pairs(session) if pairs is None else pairs
    packed = _pack_catalogue(presented_items(getattr(session, 'interface', 'new')), pairs)
    session._implant_recipe_pairs = pairs
    return packed


def catalogue_xml(session, pairs: tuple[tuple[int, int], ...] | None = None) -> bytes:
    return _session_catalogue(session, pairs)[0]


def catalogue_data(session, pairs: tuple[tuple[int, int], ...] | None = None) -> SharedConfigData:
    return _session_catalogue(session, pairs)[1]


def catalogue_updates(session) -> tuple[bytes, ...]:
    previous = getattr(session, '_implant_recipe_pairs', ())
    pairs = recipe_pairs(session)
    if pairs == previous:
        return ()
    data = catalogue_data(session, pairs)
    # B9/03 is the original data response; a city refresh replaces the same file.
    session._implant_catalogue_ack = True
    return (encode_shared_config_data(data),)


def handle(presence, session, packet: bytes) -> bool:
    if packet == b'\xb9\x04' and getattr(session, '_implant_catalogue_ack', False):
        session._implant_catalogue_ack = False
        return True
    extracting = packet[:2] == b'\xc8\x49'
    discarding = packet[:1] == b'\x32'
    if not extracting and not discarding and packet[:2] != b'\xc1\x10':
        return False
    with session.router.team_arena.lock:
        try:
            if not city_idle(session):
                raise ValueError('Операции с имплантами доступны только в городе вне боя и поиска')
            if extracting or discarding:
                remove = discard if discarding else destroy
                inventory = remove(session.database, session.account, packet)
                owner = int.from_bytes(inventory[1:5], 'little')
                pet = next(p for i, p, _ in OwnedPetStore(session.database).list(session.account) if i == owner)
                replies = (inventory, pet)
            else:
                replies = craft(session.database, session.account, packet, allow_mutation=True)
        except ValueError as error:
            replies = (encode_shop_error(str(error)),)
        enqueue(presence, session, *replies)
    return True
