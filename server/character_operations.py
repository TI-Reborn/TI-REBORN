"""Native selection-screen deletion under the authoritative gameplay lock."""
from collections.abc import Callable
import time

from tio.characters import CharacterStore
from tio.character_deletion import CharacterDeletionRejected
from tio.db_transaction import transaction
from tio.protocol.binary import PacketError
from tio.protocol.character_delete import decode_delete_request, encode_delete_result
from tio.protocol.character_select import encode_character_list


def delete_character(session: object, packet: bytes, *, clock: Callable[[], float] = time.time) -> tuple[bytes, ...]:
    router = getattr(session, 'router')
    login = getattr(session, 'authenticated_account')
    path = getattr(session, 'database')
    store = CharacterStore(path)
    with router.team_arena.lock:
        try:
            slot = decode_delete_request(packet)
            with transaction(path):
                if slot not in {record.record_id for record in store.list(login)}:
                    raise CharacterDeletionRejected('Character slot is not owned by this account')
                owner = store.owner(login, slot)
                if router.team_arena.retained(owner):
                    raise CharacterDeletionRejected('Finish the retained battle before deleting the character')
                store.delete(login, slot, now=clock())
        except (PacketError, CharacterDeletionRejected):
            # The original result handler supports ordinary rejection statuses
            # and re-enables selection controls. Malformed choices stay local.
            status = 1
        else:
            status = 0
        return encode_delete_result(status), encode_character_list(store.list(login))
