"""Place a saved squad at the native exit for settlement-focused tests."""
from dataclasses import replace

from tio.battle_state import BattleField


def place_squad_at_edge(field: BattleField, owner: int) -> None:
    for index, identity in enumerate(field.living_actor_ids(owner)):
        field._actors[identity] = replace(field.actor(identity), x=1, y=index + 2)
