"""Coordinate TrueSkill parties under the owning arena's existing lock."""
from collections.abc import Callable, Sequence
from typing import Protocol, cast

from tio.character_identity import auth_account
from tio.matchmaking import SearchTicket
from tio.rating_visibility import QA_LOGIN
from tio.ranked_party import (
    INVITATION_COOLDOWN, MINER_RESOURCE, Fighter, Party, PartyUnit,
    RankedRejection, allocation, can_join, closed_invitations, is_ranked_level,
    matchmaking_units, submission, validate_miner_count,
)
from tio.protocol.binary import PacketError
from tio.protocol.chat import encode_system_message
from tio.protocol.ranked import SEARCH_CANCELLED_PACKET, SEARCH_STARTED_PACKET
from tio.protocol.ranked_party import (
    PARTY_REQUEST_PREFIXES, MemberRow, Operation, decode, invite, snapshot,
)
from tio.protocol.system_message import encode_shop_error

from .ranked_party_access import Participant, PartyAccess, load_roster, load_tokens

PEER_WIRE_BASE = 0x4000
READY_STATE = 2


class PartyService:
    def __init__(
        self, access: PartyAccess, waiting: dict[int, SearchTicket],
        clock: Callable[[], float], *,
        roster: Callable[[Participant], tuple[Fighter, ...]] = load_roster,
        tokens: Callable[[Participant], int] = load_tokens,
    ) -> None:
        self.access = access
        self.waiting = waiting
        self.clock = clock
        self.read_roster = roster
        self.read_tokens = tokens
        self.groups: dict[int, Party] = {}
        self.invitations: dict[int, int] = {}
        self.invite_after: dict[int, float] = {}

    def wire(self, group: Party, owner: int, viewer: int) -> int:
        if owner == viewer:
            return self.access.member(viewer).character_id
        return PEER_WIRE_BASE + group.members.index(owner)

    def eligible(self, owner: int, *, group: bool = False) -> Participant:
        member = self.access.eligible(owner, group=group)
        if not any(is_ranked_level(fighter.level) for fighter in self.read_roster(member)):
            raise RankedRejection('Для TrueSkill нужен боец уровня 4–20')
        return member

    def notify(self, group: Party) -> None:
        members = {owner: self.access.member(owner) for owner in group.members}
        rosters = {owner: self.read_roster(member) for owner, member in members.items()}
        for viewer in group.members:
            rows: list[MemberRow] = []
            for owner in group.members:
                ticket = group.tickets.get(owner)
                owned = rosters[owner]
                shown = [(fighter.resource, 0, fighter.level, fighter.health,
                          fighter.max_health, 0, 0) for fighter in owned
                         if ticket and fighter.identity in ticket.actors]
                rows.append((
                    self.wire(group, owner, viewer), members[owner].name,
                    max((fighter.level for fighter in owned), default=1), 0, 0,
                    READY_STATE if ticket else 0, group.slots[owner], shown,
                ))
            self.access.send(viewer, snapshot(
                self.wire(group, group.leader, viewer), rows,
                self.read_tokens(members[viewer]),
            ))

    def cancel(self, group: Party) -> None:
        for owner in group.members:
            if self.waiting.pop(owner, None) is not None:
                self.access.send(owner, SEARCH_CANCELLED_PACKET)
        group.tickets.clear()

    def forget_invitations(self, owner: int) -> None:
        remaining = closed_invitations(self.invitations, owner)
        self.invitations.clear()
        self.invitations.update(remaining)

    def leave(self, owner: int) -> None:
        self.forget_invitations(owner)
        group = self.groups.get(owner)
        if group is None:
            return
        self.cancel(group)
        group.members.remove(owner)
        del self.groups[owner]
        del group.slots[owner]
        self.access.send(owner, snapshot(0, ()))
        if not group.members:
            return
        if group.leader == owner:
            group.leader = group.members[0]
        self.notify(group)

    def disconnect(self, owner: int) -> None:
        self.leave(owner)
        self.invite_after.pop(owner, None)

    def invite(self, owner: int, name: bytes, message: str) -> None:
        group = self.groups.get(owner)
        if group and group.leader != owner:
            raise RankedRejection('Приглашать может только лидер группы')
        if group:
            self.require_idle(group)
        sender = self.access.member(owner)
        target = self.access.invitee(sender, name)
        recipient = self.eligible(target)
        sender_root = auth_account(sender.database, sender.account)
        target_root = auth_account(recipient.database, recipient.account)
        if sender_root == target_root:
            raise RankedRejection('Нельзя пригласить персонажа своего аккаунта')
        if bool(QA_LOGIN.fullmatch(sender_root)) != bool(QA_LOGIN.fullmatch(target_root)):
            raise RankedRejection('Игрок недоступен для приглашения')
        if target in self.groups:
            raise RankedRejection('Игрок уже состоит в группе TrueSkill')
        if target in self.invitations:
            if self.invitations[target] == owner:
                return
            raise RankedRejection('Игрок уже отвечает на приглашение')
        if group:
            can_join(len(group.members), sum(group.slots.values()))
        now = self.clock()
        if now < self.invite_after.get(owner, 0):
            raise RankedRejection('Подождите перед следующим приглашением')
        if group is None:
            group = Party(owner, [owner], {owner: 1})
            self.groups[owner] = group
        self.invitations[target] = owner
        self.invite_after[owner] = now + INVITATION_COOLDOWN
        self.notify(group)
        self.access.send(target, invite(sender.name, message))
        self.access.send(owner, encode_system_message(
            1, b'Server', 'Приглашение в группу TrueSkill отправлено'))

    def answer(self, owner: int, accepted: bool) -> None:
        sender = self.invitations.pop(owner, None)
        group = self.groups.get(sender)
        if sender is None or group is None or group.leader != sender:
            raise RankedRejection('Приглашение уже закрыто')
        if not accepted:
            self.access.send(sender, encode_system_message(
                1, b'Server', 'Приглашение в группу TrueSkill отклонено'))
            return
        self.eligible(sender, group=True)
        if owner in self.groups:
            raise RankedRejection('Вы уже состоите в группе TrueSkill')
        can_join(len(group.members), sum(group.slots.values()))
        self.cancel(group)
        group.members.append(owner)
        group.slots[owner] = 1
        self.groups[owner] = group
        self.notify(group)

    def allocate(self, owner: int, wire_target: int, slots: int) -> None:
        group = self.groups.get(owner)
        if group is None:
            raise RankedRejection('Сначала создайте группу TrueSkill')
        target = next((member for member in group.members
                       if self.wire(group, member, owner) == wire_target), None)
        if target is None or owner not in (group.leader, target):
            raise RankedRejection('Нельзя изменять чужие места в группе')
        if slots == 0:
            self.leave(target)
            return
        proposed = allocation(group, owner, target, slots)
        self.cancel(group)
        group.slots = proposed
        self.notify(group)

    def require_idle(self, group: Party) -> None:
        if any(owner in self.waiting for owner in group.members):
            raise RankedRejection('Сначала отмените поиск группы')

    def submit(self, owner: int, ticket: SearchTicket) -> bool:
        group = self.groups.get(owner)
        if group is None:
            return False
        self.require_idle(group)
        proposed, start = submission(group, owner, ticket)
        if start:
            miners = 0
            for member in group.members:
                participant = self.eligible(member, group=True)
                miners += sum(fighter.resource == MINER_RESOURCE
                              for fighter in self.read_roster(participant)
                              if fighter.identity in proposed[member].actors)
            validate_miner_count(miners)
        # Commit only after every admission rule succeeds.
        group.tickets = proposed
        if start:
            self.waiting.update(proposed)
            for member in group.members:
                self.access.send(member, SEARCH_STARTED_PACKET)
            self.access.match(owner)
        else:
            self.notify(group)
        return True

    def consumed(self, tickets: Sequence[SearchTicket]) -> None:
        for ticket in tickets:
            owner = ticket.character_id
            self.waiting.pop(owner, None)
            if self.groups.pop(owner, None) is not None:
                self.access.send(owner, snapshot(0, ()))
            self.forget_invitations(owner)

    def handle(self, owner: int, packet: bytes) -> bool:
        if packet[:2] not in PARTY_REQUEST_PREFIXES:
            return False
        try:
            operation, value = decode(packet)
            if operation == Operation.LEAVE:
                # Leaving remains possible outside an eligible city.
                self.access.ensure_not_fighting(owner)
                self.leave(owner)
                return True
            self.eligible(owner, group=owner in self.groups)
            if operation == Operation.INVITE:
                name, message = cast(tuple[bytes, str], value)
                self.invite(owner, name, message)
            elif operation == Operation.ANSWER:
                self.answer(owner, bool(value))
            elif operation == Operation.ALLOCATE:
                target, slots = cast(tuple[int, int], value)
                self.allocate(owner, target, slots)
            elif operation == Operation.REFRESH:
                group = self.groups.get(owner)
                if group is None:
                    self.access.send(owner, snapshot(0, ()))
                else:
                    self.notify(group)
        except (PacketError, RankedRejection) as error:
            self.access.send(owner, encode_shop_error(str(error)))
        return True


class PartyHost(Protocol):
    ranked_party_service: PartyService


# Existing arena entry points stay in place; all state is initialized by its
# constructor and all calls run under the same arena lock.
def state(hub: PartyHost) -> tuple[dict[int, Party], dict[int, int]]:
    service = hub.ranked_party_service
    return service.groups, service.invitations


def party(hub: PartyHost, owner: int) -> Party | None:
    return hub.ranked_party_service.groups.get(owner)


def wire(hub: PartyHost, group: Party, owner: int, viewer: int) -> int:
    return hub.ranked_party_service.wire(group, owner, viewer)


def notify(hub: PartyHost, group: Party) -> None:
    hub.ranked_party_service.notify(group)


def cancel(hub: PartyHost, group: Party) -> None:
    hub.ranked_party_service.cancel(group)


def leave(hub: PartyHost, owner: int) -> None:
    hub.ranked_party_service.leave(owner)


def disconnect(hub: PartyHost, owner: int) -> None:
    hub.ranked_party_service.disconnect(owner)


def handle(hub: PartyHost, owner: int, packet: bytes) -> bool:
    return hub.ranked_party_service.handle(owner, packet)


def submit(hub: PartyHost, owner: int, ticket: SearchTicket) -> bool:
    return hub.ranked_party_service.submit(owner, ticket)


def units(hub: PartyHost, candidates: Sequence[SearchTicket]) -> list[SearchTicket | PartyUnit]:
    return matchmaking_units(hub.ranked_party_service.groups, candidates)


def consumed(hub: PartyHost, tickets: Sequence[SearchTicket]) -> None:
    hub.ranked_party_service.consumed(tickets)
