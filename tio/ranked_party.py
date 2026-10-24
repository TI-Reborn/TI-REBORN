"""TrueSkill party values and rules; no storage, packets or session access."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .battle_modes import level_band
from .matchmaking import SearchTicket

MAX_FIGHTERS = 4
MIN_LEVEL = 4
MAX_LEVEL = 20
MAX_MINERS = 1
MINER_RESOURCE = 6
HUMAN_RESOURCES = (1, 2, MINER_RESOURCE)
DEPARTED_INVITER = 0
INVITATION_COOLDOWN = 2.0


class RankedRejection(ValueError):
    """An expected admission refusal that may be displayed to the player."""


@dataclass
class Party:
    leader: int
    members: list[int]
    slots: dict[int, int] = field(default_factory=dict)
    tickets: dict[int, SearchTicket] = field(default_factory=dict)


@dataclass(frozen=True)
class Fighter:
    identity: int
    resource: int
    level: int
    health: int
    max_health: int


@dataclass(frozen=True)
class PartyUnit:
    character_id: int
    actors: tuple[int, ...]
    levels: tuple[int, ...]
    joined_at: float
    members: tuple[SearchTicket, ...]


def is_ranked_level(level: int) -> bool:
    return MIN_LEVEL <= level <= MAX_LEVEL


def validate_miner_count(count: int) -> None:
    if count > MAX_MINERS:
        raise RankedRejection('В бой TrueSkill можно взять только одного шахтёра')


def can_join(member_count: int, allocated_slots: int) -> None:
    if member_count >= MAX_FIGHTERS or allocated_slots >= MAX_FIGHTERS:
        raise RankedRejection('В группе нет свободного места')


def allocation(group: Party, owner: int, target: int, slots: int) -> dict[int, int]:
    if target not in group.members or owner not in (group.leader, target):
        raise RankedRejection('Нельзя изменять чужие места в группе')
    if not 1 <= slots <= MAX_FIGHTERS:
        raise RankedRejection('Недопустимое число мест в группе')
    proposed = {**group.slots, target: slots}
    if sum(proposed.values()) > MAX_FIGHTERS:
        raise RankedRejection('В группе не может быть больше четырёх бойцов')
    return proposed


def submission(
    group: Party, owner: int, ticket: SearchTicket,
) -> tuple[dict[int, SearchTicket], bool]:
    if len(ticket.actors) != group.slots[owner]:
        raise RankedRejection('Выберите столько бойцов, сколько мест выделено вам в группе')
    start = all(member in group.tickets for member in group.members)
    proposed = {**group.tickets, owner: ticket}
    if start:
        if owner != group.leader:
            raise RankedRejection('Начать общий поиск может лидер группы')
        bands = {level_band(level) for row in proposed.values() for level in row.levels}
        if len(bands) != 1:
            raise RankedRejection('Бойцы группы должны быть одного уровневого диапазона')
    return proposed, start


def closed_invitations(invitations: Mapping[int, int], owner: int) -> dict[int, int]:
    # The native answer has no invitation ID. Keep a tombstone until its old
    # bool answer is consumed, so it cannot accept a different inviter.
    return {target: DEPARTED_INVITER if sender == owner else sender
            for target, sender in invitations.items() if target != owner}


def matchmaking_units(
    parties: Mapping[int, Party], candidates: Sequence[SearchTicket],
) -> list[SearchTicket | PartyUnit]:
    by_owner = {ticket.character_id: ticket for ticket in candidates}
    used: set[int] = set()
    result: list[SearchTicket | PartyUnit] = []
    for ticket in candidates:
        owner = ticket.character_id
        if owner in used:
            continue
        group = parties.get(owner)
        if group is None:
            result.append(ticket)
            continue
        used.update(group.members)
        if not all(member in by_owner for member in group.members):
            continue
        members = tuple(by_owner[member] for member in group.members)
        result.append(PartyUnit(
            group.leader,
            tuple(range(sum(len(member.actors) for member in members))),
            tuple(level for member in members for level in member.levels),
            min(member.joined_at for member in members),
            members,
        ))
    return result
