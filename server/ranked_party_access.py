"""Arena and database adapters used by the TrueSkill party coordinator."""
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from tio.character_identity import owner_for_name
from tio.db_transaction import connect
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info
from tio.ranked_party import Fighter, HUMAN_RESOURCES, RankedRejection
from tio.ranked_tokens import status

if TYPE_CHECKING:
    from .team_arena import TeamArena


@dataclass(frozen=True)
class Participant:
    owner: int
    database: Path
    account: str
    character_id: int
    name: bytes


class PartyAccess(Protocol):
    def member(self, owner: int) -> Participant: ...
    def ensure_not_fighting(self, owner: int) -> None: ...
    def eligible(self, owner: int, *, group: bool) -> Participant: ...
    def invitee(self, sender: Participant, name: bytes) -> int: ...
    def send(self, owner: int, *packets: bytes) -> None: ...
    def match(self, owner: int) -> None: ...


def load_roster(member: Participant) -> tuple[Fighter, ...]:
    fighters = []
    for identity, raw, _ in OwnedPetStore(member.database).list(member.account):
        resource = int.from_bytes(raw[5:9], 'little')
        fields = decode_pet_info(raw, human_equipment=resource in HUMAN_RESOURCES).fields
        fighters.append(Fighter(identity, fields['0x8c446f'], fields['0x8c4aef'],
                                fields['0x8c4ab1'], fields['0x8c4a07']))
    return tuple(fighters)


def load_tokens(member: Participant) -> int:
    with closing(connect(member.database)) as database, database:
        _, tokens = status(database, member.account)
    return min(tokens, 65535)


class ArenaPartyAccess:
    """Keep the existing arena's session and occupancy details at one boundary."""

    def __init__(self, hub: 'TeamArena') -> None:
        self.hub = hub

    def member(self, owner: int) -> Participant:
        session = self.hub.players[owner]
        return Participant(owner, session.database, session.account,
                           session.probe_character_id, session.probe_character_name)

    def ensure_not_fighting(self, owner: int) -> None:
        if owner in self.hub.battles or owner in self.hub.results:
            raise RankedRejection('Сначала завершите бой')

    def eligible(self, owner: int, *, group: bool) -> Participant:
        from .ranked_arena import RANKED_TOWNS
        from tio.world_completion import prison_state

        hub = self.hub
        session = hub.players.get(owner)
        if session is None or owner in hub.offline:
            raise RankedRejection('Игрок не в сети')
        if (owner in hub.battles or owner in hub.results or owner in hub.survival_waiting
                or hub.lobbies.room(owner) or hub.wager_busy(owner)
                or hub.assault_group(session) or hub.mine_waiting(owner)):
            raise RankedRejection('Игрок занят другим боем или группой')
        if (getattr(session.arena, '_fields', {})
                or any(session.probe_character_id in room.members
                       for room in session.arena.rooms.snapshot())):
            raise RankedRejection('Сначала завершите текущий бой')
        if not group and owner in hub.ranked_waiting:
            raise RankedRejection('Сначала отмените поиск TrueSkill')
        if not session.locations or session.locations.current(session.account) not in RANKED_TOWNS:
            raise RankedRejection('Группа TrueSkill доступна в городах с вносом вещей')
        with closing(connect(session.database)) as database:
            prison = prison_state(database, session.account)
        if prison and prison['remaining'] > 0:
            raise RankedRejection('Наказание отбывается онлайн в Prison')
        return self.member(owner)

    def invitee(self, sender: Participant, name: bytes) -> int:
        with closing(connect(sender.database)) as database:
            account = owner_for_name(database, name)
        for owner, session in self.hub.players.items():
            if (session.database == sender.database and session.account == account
                    and owner not in self.hub.offline):
                return owner
        raise RankedRejection('Игрок не в сети')

    def send(self, owner: int, *packets: bytes) -> None:
        self.hub.put(owner, *packets)

    def match(self, owner: int) -> None:
        self.hub.match_ranked(owner)
