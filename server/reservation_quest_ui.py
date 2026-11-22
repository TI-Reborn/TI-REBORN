"""Authorize Ruth's actions against the selected character and live city."""
from typing import TypedDict

from tio import reservation_quests
from tio.roster_progression import tutorial_incomplete


class QuestView(TypedDict, total=False):
    available: bool
    welcome: reservation_quests.Status
    survival: reservation_quests.Status
    purchases: list[int]
    weapon: bool
    outcome: int | None


def city_for_conversation(hub, session) -> int | None:
    if (session.locations is None or hub.busy(session) or session.arena._fields
            or session.survival.searching(session.probe_character_id)):
        return None
    return session.locations.current(session.account)


def ruth_available(session) -> bool:
    return not tutorial_incomplete(session.database, session.account)


def execute(hub, session, request: dict[str, object]) -> QuestView:
    action = request.get('value')
    if set(request) != {'action', 'value'} or not isinstance(action, str) or action not in (
        'state', 'accept_welcome', 'turn_in_welcome', 'accept_survival', 'turn_in_survival'
    ):
        raise ValueError('Некорректное действие окна Рут Восс')
    available = city_for_conversation(hub, session) == reservation_quests.TOWN and ruth_available(session)
    if not available:
        if action != 'state':
            raise ValueError('Поговорить с Рут можно в Резервации после вводного урока')
        return {'available': False}
    if action == 'state':
        state = reservation_quests.state(session.database, session.account)
    else:
        state = reservation_quests.act(session.database, session.account, action)
    return {'available': True, **state}
