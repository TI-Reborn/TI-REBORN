"""Single-player tournament entry and three rounds of shared PvP battles."""
from collections.abc import Callable
from dataclasses import replace
import logging
from pathlib import Path
from random import SystemRandom
import struct
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING

from tio import tournaments as rules
from tio.battle_modes import level_band
from tio.character_identity import auth_account
from tio.cities import CITIES
from tio.owned_pets import OwnedPetStore
from tio.protocol.mail import encode_notification
from tio.protocol import tournaments as wire
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.system_message import encode_shop_error
from tio.ranked_loadout import validate
from tio.ranked_party import MINER_RESOURCE, HUMAN_RESOURCES, is_ranked_level
from tio.rating_visibility import QA_LOGIN

from .ranked_arena import RANKED_TOWNS, RankedTicket

if TYPE_CHECKING:
    from .team_arena import TeamArena

LOG = logging.getLogger('tio.server')
REGISTRATION_SECONDS = 60
PREPARATION_SECONDS = 45
BATTLE_SECONDS = 600
MODE = 20
TOURNAMENT_RESOURCES = frozenset(HUMAN_RESOURCES) - {MINER_RESOURCE}


class TournamentArena:
    def __init__(self, hub: 'TeamArena', path: str | Path, *, wall: Callable[[], float] = time.time):
        self.hub = hub
        self.path = path
        self.wall = wall
        self.random = SystemRandom()
        self.events = {}
        self.registered = {}
        self.registration_deadline = {}
        self.ready = {}
        self.published = {}
        self.next_tick = 0.0
        rules.initialise(path)
        active = {battle['tournament'][:2] for battle in hub.battles.values() if battle.get('kind') == 'tournament'}
        for event in rules.active_events(path):
            event.bracket.winners.update(rules.results(path, event.identity))
            resume_until = self.wall() + PREPARATION_SECONDS
            if ((event.identity, event.stage) not in active and event.deadline < resume_until
                    and not any(stage == event.stage for stage, _ in event.bracket.winners)):
                event = rules.extend_preparation(path, event, resume_until)
            self.events[event.identity] = event

    def pool(self, owner: int) -> tuple[str, bool] | None:
        player = self.hub.players[owner]
        town = player.locations.current(player.account) if player.locations else None
        if town not in RANKED_TOWNS:
            return None
        return CITIES[town].pool, bool(QA_LOGIN.fullmatch(auth_account(self.path, player.account)))

    def event_for(self, account: str) -> rules.Tournament | None:
        return next((event for event in self.events.values() if account in event.bracket.slots), None)

    def rows(self, event: rules.Tournament) -> tuple[tuple[tuple[bytes, int], ...], ...]:
        rows = []
        for stage in range(min(event.stage + 1, rules.ROUNDS)):
            row = []
            for pair, slots in enumerate(event.bracket.pairs(stage)):
                winner = event.bracket.winners.get((stage, pair))
                row.extend((event.names[slot], 0 if winner is None else 1 if winner == slot else 2)
                           for slot in slots)
            rows.append(tuple(row))
        return tuple(rows)

    def status(self, owner: int, *, force: bool = False) -> None:
        player = self.hub.players[owner]
        event = self.event_for(player.account)
        now = self.wall()
        if event is None:
            pool = self.pool(owner)
            if pool is None:
                if self.published.pop(owner, None) is not None:
                    self.hub.put(owner, wire.encode_status(0, 0))
                return
            deadline = self.registration_deadline.setdefault(pool, now + REGISTRATION_SECONDS)
            queue = self.registered.get(pool, {})
            registered = player.account in queue
            signature = (1, deadline, registered, len(queue))
            packet = lambda: wire.encode_status(1, int((deadline - now) * 1000), registered=registered,
                                                 participants=len(queue))
        else:
            phase = 2 + 2 * event.stage + int(now >= event.deadline)
            signature = (phase, event.identity, event.deadline, len(event.bracket.winners))
            packet = lambda: wire.encode_status(phase, int((event.deadline - now) * 1000),
                                                 registered=True, participants=rules.SIZE, rounds=self.rows(event))
        if force or self.published.get(owner) != signature:
            self.published[owner] = signature
            self.hub.put(owner, packet())

    def choose(self, owner: int, packet: bytes) -> RankedTicket:
        player = self.hub.players[owner]
        selection = wire.decode_ready(packet)
        roster = {identity: (pet, inventory) for identity, pet, inventory in
                  OwnedPetStore(self.path).list(player.account)}
        levels = []
        for identity, equipment, _ in selection:
            if identity not in roster:
                raise ValueError('Выбранный наёмник не принадлежит вашему отряду')
            pet, inventory = roster[identity]
            if int.from_bytes(pet[5:9], 'little') not in TOURNAMENT_RESOURCES:
                raise ValueError('В турнире участвуют только люди')
            fields = decode_pet_info(pet, human_equipment=True).fields
            level = fields['0x8c4aef']
            if not is_ranked_level(level) or fields['0x8c4a07'] != fields['0x8c4ab1']:
                raise ValueError('Нужны полностью здоровые наёмники уровней 4–20')
            validate(pet, inventory, True, equipment)
            levels.append(level)
        return RankedTicket(owner, tuple(identity for identity, _, _ in selection), tuple(levels),
                            self.hub.clock(), selections=selection)

    def available(self, owner: int) -> bool:
        player = self.hub.players[owner]
        return (owner not in self.hub.offline and not self.hub.busy(player) and self.pool(owner) is not None
                and not any(player.probe_character_id in room.members for room in player.arena.rooms.snapshot()))

    def register(self, owner: int) -> None:
        from .world_runtime import require_unjailed
        player = self.hub.players[owner]
        pool = self.pool(owner)
        if pool is None or not self.available(owner) or self.event_for(player.account):
            raise ValueError('Вступить в турнир можно из города во время регистрации')
        require_unjailed(player)
        if not any(is_ranked_level(decode_pet_info(pet, human_equipment=True).fields['0x8c4aef'])
                   for _, pet, _ in OwnedPetStore(self.path).list(player.account)
                   if int.from_bytes(pet[5:9], 'little') in TOURNAMENT_RESOURCES):
            raise ValueError('Для участия в турнире нужен наёмник уровня 4–20')
        account = auth_account(self.path, player.account)
        if (any(auth_account(self.path, entrant) == account for queues in self.registered.values()
                for entrant in queues if entrant != player.account)
                or any(auth_account(self.path, entrant) == account for event in self.events.values()
                       for entrant in event.bracket.slots if entrant is not None)):
            raise ValueError('В турнире уже участвует персонаж этого аккаунта')
        self.registered.setdefault(pool, {})[player.account] = player.probe_character_name
        self.status(owner, force=True)

    def handle(self, owner: int, packet: bytes) -> bool:
        if packet[:1] != b'\xc6' or len(packet) < 2 or packet[1] not in range(0x39, 0x72):
            return False
        player = self.hub.players[owner]
        event = self.event_for(player.account)
        try:
            if packet == wire.OPEN:
                self.hub.put(owner, b'\xc6\x71' + bytes(4), b'\xc6\x48' + bytes(8))
                self.status(owner, force=True)
            elif packet == wire.REGISTER:
                self.register(owner)
            elif packet == wire.CANCEL:
                for queue in self.registered.values():
                    queue.pop(player.account, None)
                self.ready.pop(player.account, None)
                self.status(owner, force=True)
            elif packet[:2] in (wire.READY, wire.BRACKET) or packet == wire.UNREADY:
                if event is None:
                    raise ValueError('Вы не участвуете в турнире')
                if packet[:2] == wire.BRACKET:
                    if wire.bracket_request(packet) not in (0, event.identity):
                        raise ValueError('Сетка этого турнира недоступна')
                    self.hub.put(owner, wire.encode_bracket(event.identity, self.rows(event)))
                elif self.wall() >= event.deadline or not self.available(owner):
                    raise ValueError('Подготовка к текущему раунду завершена')
                elif packet == wire.UNREADY:
                    self.ready.pop(player.account, None)
                    self.hub.put(owner, b'\xc6\x43')
                else:
                    from .world_runtime import require_unjailed
                    require_unjailed(player)
                    self.ready[player.account] = self.choose(owner, packet)
                    self.hub.put(owner, b'\xc6\x42')
            else:
                return False
        except ValueError as error:
            self.hub.put(owner, encode_shop_error(str(error)[:180]))
        return True

    def start_event(self, queue: dict[str, bytes], accounts: tuple[str, ...], now: float) -> None:
        slots = list(rules.Bracket.create(accounts).slots)
        self.random.shuffle(slots)
        names = tuple(queue[owner] if owner is not None else f'AI bot {i + 1}'.encode('ascii')
                      for i, owner in enumerate(slots))
        event = rules.create_event(self.path, tuple(slots), names, now + PREPARATION_SECONDS)
        self.events[event.identity] = event
        for account in accounts:
            del queue[account]
        LOG.info('tournament_created id=%d humans=%d bots=%d', event.identity, len(accounts), rules.SIZE-len(accounts))

    def bot_ticket(self, source: RankedTicket, owner: int, slot: int) -> RankedTicket:
        weapons = (306, 330, 311)
        selections = tuple((identity, ((0, 242), (4, weapons[(slot + i) % len(weapons)])), 1)
                           for i, identity in enumerate(source.actors))
        return replace(source, character_id=owner, selections=selections)

    def start_pair(self, event: rules.Tournament, pair: int, slots: tuple[int, int],
                   online: dict[str, int]) -> None:
        tickets = {}
        for slot in slots:
            account = event.bracket.slots[slot]
            owner = online.get(account)
            ticket = self.ready.get(account)
            if owner is not None and ticket is not None and ticket.character_id == owner and self.available(owner):
                tickets[slot] = ticket
        active = tuple(slot for slot in slots if slot in tickets or event.bracket.slots[slot] is None)
        if not tickets or len(active) < 2:
            winner = self.random.choice(active or slots)
            rules.record_result(self.path, event.identity, event.stage, pair, winner)
            return
        source = next(iter(tickets.values()))
        source_player = self.hub.players[source.character_id]
        count = min(len(ticket.actors) for ticket in tickets.values())
        seats = []
        bots = set()
        used = set(self.hub.players)
        for battle in self.hub.battles.values():
            used.update(battle['room'].members)
        for side, slot in enumerate(slots):
            ticket = tickets.get(slot)
            if ticket is None:
                owner = next(identity for identity in range(0x64000000, 0x65000000) if identity not in used)
                bots.add(owner)
                ticket = self.bot_ticket(source, owner, slot)
                player = source_player
            else:
                owner = ticket.character_id
                player = self.hub.players[owner]
            ticket = replace(ticket, actors=ticket.actors[:count], levels=ticket.levels[:count],
                             selections=ticket.selections[:count])
            seats.append((owner, side, player.database, player.account, ticket, owner in bots))
        match = (event.identity, event.stage, pair, slots)
        first = SimpleNamespace(mode=MODE, soldiers=count, band=level_band(min(source.levels)),
                                captain=source.character_id, tournament=match,
                                tournament_ends=self.wall() + BATTLE_SECONDS,
                                tournament_names=tuple(event.names[slot] for slot in slots))
        self.hub.start_match(first, seats, [[seat[0]] for seat in seats], bots, lambda: None)

    def tick(self) -> None:
        now = self.wall()
        if now < self.next_tick:
            return
        self.next_tick = now + .5
        online = {player.account: owner for owner, player in self.hub.players.items()
                  if owner not in self.hub.offline}
        for pool, deadline in tuple(self.registration_deadline.items()):
            queue = self.registered.get(pool, {})
            for account in tuple(queue):
                owner = online.get(account)
                if owner is None or self.pool(owner) != pool:
                    del queue[account]
            if len(queue) >= rules.SIZE or now >= deadline:
                if queue:
                    self.start_event(queue, tuple(queue)[:rules.SIZE], now)
                self.registration_deadline[pool] = now + REGISTRATION_SECONDS
        fighting = {battle.get('tournament') for battle in self.hub.battles.values()}
        for event in tuple(self.events.values()):
            if now < event.deadline:
                continue
            event.bracket.winners.update(rules.results(self.path, event.identity))
            for pair, slots in enumerate(event.bracket.pairs(event.stage)):
                if (event.stage, pair) in event.bracket.winners or (event.identity, event.stage, pair, slots) in fighting:
                    continue
                try:
                    self.start_pair(event, pair, slots, online)
                except ValueError as error:
                    LOG.info('tournament_match_rejected id=%d pairing=%d reason=%s', event.identity, pair, error)
                    for slot in slots:
                        owner = online.get(event.bracket.slots[slot])
                        if owner is not None:
                            self.hub.put(owner, encode_shop_error(str(error)[:180]))
                    rules.record_result(self.path, event.identity, event.stage, pair, self.random.choice(slots))
            event.bracket.winners.update(rules.results(self.path, event.identity))
            if all((event.stage, pair) in event.bracket.winners for pair in range(rules.PAIRS)):
                self.advance(event, online, now)
        for owner in online.values():
            if owner not in self.hub.battles and owner not in self.hub.results:
                self.status(owner)

    def advance(self, event: rules.Tournament, online: dict[str, int], now: float) -> None:
        next_event = rules.advance(self.path, event, now + PREPARATION_SECONDS, now=now)
        finished = next_event.stage == rules.ROUNDS
        for slot, account in enumerate(event.bracket.slots):
            if account is None:
                continue
            self.ready.pop(account, None)
            owner = online.get(account)
            if owner is not None and finished:
                from tio.protocol.chat import encode_system_message
                place = event.bracket.placements().index(slot) + 1
                self.hub.put(owner, wire.encode_status(8, 0, registered=True, participants=rules.SIZE,
                                                       rounds=self.rows(event)), b'\xc6\x46',
                             encode_notification('TIO', rules.PRIZE_SUBJECT, True),
                             encode_system_message(0, b'TIO',
                                 f'Турнир завершён. Ваше место: {place} из {rules.SIZE}. Награда отправлена на почту.'))
        if finished:
            del self.events[event.identity]
        else:
            self.events[event.identity] = next_event

    def record_battle(self, battle: dict, side: int) -> None:
        identity, stage, pair, slots = battle['tournament']
        rules.record_result(self.path, identity, stage, pair, slots[side])

    def send_battle(self, battle: dict, owner: int) -> None:
        identity, stage, _, _ = battle['tournament']
        event = self.events.get(identity) or rules.read_event(self.path, identity)
        field = battle['field']
        teams = tuple((battle['names'][member], tuple(
            (field.combat.resources[actor], decode_pet_info(field.combat.proficiencies[actor],
                human_equipment=True).fields['0x8c4bbc']) for actor in field.actor_ids(member)))
                      for member in battle['room'].members)
        self.hub.put(owner, wire.encode_status(3 + stage * 2, 0, registered=True,
                                              participants=rules.SIZE, rounds=self.rows(event)),
                     wire.encode_battle(battle['room'].room_id, stage, teams),
                     wire.encode_countdown(int((battle['tournament_ends'] - self.wall()) * 1000)))

    def tiebreak(self, battle: dict) -> int:
        identity, stage, pair, _ = battle['tournament']
        return (identity + stage + pair) % 2

    def expired(self, battle: dict) -> bool:
        if self.wall() < battle['tournament_ends']:
            return False
        field = battle['field']
        live = {field.teams[actor.owner_id] for actor in field._actors.values() if actor.health}
        scores = battle['points'].scores
        battle['ranked_winner'] = (next(iter(live)) if len(live) == 1 else
                                   scores.index(max(scores)) if scores[0] != scores[1] else self.tiebreak(battle))
        return True

    def loading_timeout(self, battle: dict) -> None:
        room = battle['room']
        loaded = battle['arena']._loading[room.room_id]
        sides = {battle['field'].teams[owner] for owner in loaded}
        battle['ranked_winner'] = next(iter(sides)) if len(sides) == 1 else self.tiebreak(battle)

    def disconnect(self, owner: int) -> None:
        self.published.pop(owner, None)
        player = self.hub.players[owner]
        self.ready.pop(player.account, None)
