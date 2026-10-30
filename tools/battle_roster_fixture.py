"""Prepare one diagnostic scene actor from a consistent server DB snapshot.

The empty8x8 map, spawn2,2 and40 AP are local diagnostic settings.
No client-supplied learned ranks, health or healing amounts are accepted.
"""
from contextlib import closing
import sqlite3
from dataclasses import dataclass
from tools.battle_actor_fixture import actor_packet
from tio.battle_state import BattleActor,BattleField
from tio.owned_pets import OwnedPetStore
from tio.passive_stats import project_passives
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.abilities import decode_abilities,encode_abilities


@dataclass(frozen=True)
class PreparedActor:
    actor_id: int
    field: BattleField
    packets: tuple[bytes,...]


def prepare_actor(path,account,actor_id,character_id,catalog):
    from tio.dog_abilities import catalog_for_play
    from tio.restored_abilities import catalog_with_restored
    catalog=catalog_for_play(catalog_with_restored(catalog))
    with closing(sqlite3.connect(path)) as db,db:
        db.execute('BEGIN')
        row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                       (account,actor_id)).fetchone()
        if row is None:raise ValueError('Owned scene actor required')
        human,pet,inventory=bool(row[0]),bytes(row[1]),bytes(row[2])
        if OwnedPetStore.validate(pet,inventory,human)!=actor_id:raise ValueError('Saved actor ID mismatch')
        learned=()
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ability_states'").fetchone():
            saved=db.execute('SELECT packet FROM ability_states WHERE account=? AND pet_id=?',(account,actor_id)).fetchone()
            if saved:
                owner,learned,learning=decode_abilities(saved[0])
                if owner!=actor_id or learning:raise ValueError('Invalid saved skill snapshot')
        if len({e.ability_id for e in learned})!=len(learned):raise ValueError('Duplicate learned skill')
        if any((e.ability_id,e.level) not in catalog.by_key for e in learned):raise ValueError('Unknown learned rank')
        pet=project_passives(pet,human,learned,catalog,inventory=inventory)
    fields=decode_pet_info(pet,human_equipment=human).fields
    field=BattleField(8,8,[BattleActor(actor_id,character_id,2,2,40,
                                    fields['0x8c4ab1'],fields['0x8c4a07'],sight_radius=fields['0x8c4a1b'])],step_cost=1)
    if any(e.ability_id==23 for e in learned):
        field.configure_dog_healing(character_id,actor_id,fields['0x8c446f'],learned,catalog)
    packets=(actor_packet(pet,character_id,inventory,human=human),encode_abilities(actor_id,learned))
    return PreparedActor(actor_id,field,packets)
