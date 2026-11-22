"""NPCs the selected character can talk to in the current location."""
from typing import TypedDict

from tio import reservation_quests
from .reservation_quest_ui import city_for_conversation, ruth_available


class Npc(TypedDict):
    id: str
    name: str
    has_available_quest: bool


class LocationNpcs(TypedDict):
    town: int | None
    npcs: list[Npc]


def ruth(session) -> Npc | None:
    if not ruth_available(session):
        return None
    state = reservation_quests.state(session.database, session.account)
    return dict(id='ruth', name='Рут Восс',
                has_available_quest='available' in (state['welcome'], state['survival']))


LOCATION_NPCS = {reservation_quests.TOWN: (ruth,)}


def snapshot(hub, session, request: dict[str, object]) -> LocationNpcs:
    if set(request) != {'action'}:
        raise ValueError('Некорректный запрос списка NPC')
    town = city_for_conversation(hub, session)
    npcs = [npc for describe in LOCATION_NPCS.get(town, ()) if (npc := describe(session)) is not None]
    return dict(town=town, npcs=npcs)
