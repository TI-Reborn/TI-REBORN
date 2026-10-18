"""Opt-in cooperative contracts through private commands in native game chat."""
from contextlib import closing
from collections import deque
from dataclasses import replace
from pathlib import Path
import time
from uuid import uuid4
from xml.etree import ElementTree as ET

from tio.db_transaction import connect, transaction
from tio.travel_party import PartyStore
from tio.pve_contracts import ContractStore
from tio.party_travel import PartyTravel, PartyLocations
from tio.protocol.chat import encode_system_message
from tio.protocol.town_info import diagnostic_town_info, encode_town_info

ROOT = Path(__file__).resolve().parents[1]
PARTY_STATES = {'city': 'в городе', 'travelling': 'в пути', 'at_target': 'у цели',
                'loading': 'загрузка боя', 'battle': 'в бою'}
CONTRACT_STATES = {'accepted': 'принят', 'travelling': 'переход к цели',
                   'arrived': 'можно начать зачистку', 'active': 'бой'}


class ContractsService:
    def __init__(self, hub, path, *, clock=time.time):
        self.hub, self.path, self.clock = hub, Path(path), clock
        self.parties = PartyStore(path, clock=clock)
        self.contracts = ContractStore(path, clock=clock, party_store=self.parties)
        self.travel = PartyTravel(path, self.parties, self.contracts, clock=clock)
        self.parties.reset_online()

    def locations(self, base):
        return PartyLocations(base, self.travel)

    def map_query(self, session, packet):
        """Answer native79 tooltip polling without admitting a city or battle.

        The native map polls a visible town at most every ten seconds. These
        reads must precede the city-service gate, and private contract slots23..25
        must resolve in this session's private scene rather than public IDs.
        """
        if packet[:1] != b'\x79':
            return None
        if len(packet) != 2:
            return ()
        town = packet[1]
        with self.hub.lock:
            template = next((row for row in self.contracts.catalog() if row['zone_id'] == town), None)
            if template is not None:
                target = self.contracts.target_for(session.account)
                enabled = bool(target and target['zone_id'] == town)
                levels = target['levels'] if enabled else template['levels']
                return (encode_town_info(replace(diagnostic_town_info(), town_id=town,
                    unknown_bytes=(*levels, 0, 0), final_bool=int(enabled))),)
            # Preserve every actual public slot and its enabled flags.
            # Tooltip reads cannot enable a hidden town or another party target.
            root = ET.fromstring((ROOT/'evidence/zones_diagnostic.xml').read_bytes())
            zone = next((node for node in root if int(node.get('id')) == town), None)
            if zone is None:
                return ()
            values = {value.get('key'): value.get('val') for value in zone}
            from tio.locations import TOWNS, town_packets
            raw = (town_packets(town, self.path, clock=self.clock)[0] if town in TOWNS else
                   encode_town_info(replace(diagnostic_town_info(), town_id=town,
                       unknown_bytes=(int(values.get('minlevel', 1)), int(values.get('maxlevel', 20)), 0, 0))))
            # Enabled is the final native bool, after any territory extension.
            # Keep those public claim/schedule branches intact.
            return (raw[:-1] + bytes((int(values.get('enabled') == '1'),)),)

    def zones_xml(self):
        root = ET.fromstring((ROOT/'evidence/zones_diagnostic.xml').read_bytes())
        ids = [int(t.get('id')) for t in root]
        if ids != list(range(1, len(ids)+1)):
            raise ValueError('Contract zones require contiguous public slots')
        backgrounds = {'camp': 'loc_forest', 'depot': 'loc_ny', 'checkpoint': 'loc_outpost'}
        for template in sorted(self.contracts.catalog(), key=lambda t: t['zone_id']):
            if template['zone_id'] != len(root)+1:
                raise ValueError('Hidden contract slots must be contiguous')
            town = ET.SubElement(root, 'town', id=str(template['zone_id']), name=template['name'])
            bounds = template['bounds']
            values = dict(enabled='0', background=backgrounds[template['id']],
                          x1=bounds[0], y1=bounds[1], x2=bounds[2], y2=bounds[3],
                          size=bounds[2]-bounds[0], minlevel=template['levels'][0],
                          maxlevel=template['levels'][1], drop='false')
            for key, value in values.items():
                ET.SubElement(town, 'value', key=key, val=str(value))
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)

    def member(self, session):
        try:
            return self.parties.info(session.account)
        except ValueError:
            return None

    def selected_owner(self, login):
        with closing(connect(self.path)) as db:
            row = db.execute('SELECT owner FROM travel_party_members WHERE login=?', (login,)).fetchone()
            return row[0] if row else None

    def sync(self, session):
        with self.hub.lock:
            owner = self.hub.identity(session)
            party = self.member(session)
            if party:
                self.parties.set_online(session.account, True)
                party = self.parties.recover_leader(party['id'])
            target = self.contracts.target_for(session.account)
            signature = (party['id'], party['revision']) if party else None
            marker = target['instance_id'] if target else None
            if getattr(session, '_contract_markers', object()) != marker:
                for template in self.contracts.catalog():
                    enabled = bool(target and target['zone_id'] == template['zone_id'])
                    self.hub.put(owner, encode_town_info(replace(diagnostic_town_info(),
                        town_id=template['zone_id'], unknown_bytes=(template['levels'][0], template['levels'][1], 0, 0),
                        final_bool=int(enabled))))
                session._contract_markers = marker
            if getattr(session, '_travel_party_revision', None) != signature:
                session._travel_party_revision = signature
                if party:
                    self.reply(session, f"Группа: {len(party['members'])}/4; лидер {self.name(party['leader'])}; {PARTY_STATES[party['state']]}.")
                    if party['state'] == 'at_target' and target:
                        point, route = self.travel.point(session.account)
                        bounds = target['bounds']
                        if route is None and bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]:
                            self.reply(session, 'Цель контракта достигнута. Лидер: !contracts start — начать зачистку.')

    def disconnect(self, session):
        with self.hub.lock:
            if self.member(session):
                self.parties.set_online(session.account, False)

    def reply(self, session, *texts):
        owner = self.hub.identity(session)
        for text in texts:
            # Native channel0 requires an open Location tab. Channel5 appends
            # a system notice to the first enabled tab of this client; routing
            # remains private through the owner's queue. It omits the sender,
            # so keep the localized label in the UTF16 message body.
            self.hub.put(owner, encode_system_message(5, 'Контракты'.encode('cp1251'), f'[Контракты] {text}'))

    def name(self, owner):
        with closing(connect(self.path)) as db:
            row = db.execute('SELECT name FROM characters WHERE account=? AND slot=1', (owner,)).fetchone()
            return bytes(row[0]).decode('cp1251') if row else owner

    def named_owner(self, name):
        from tio.character_identity import owner_for_name
        with closing(connect(self.path)) as db:
            owner = owner_for_name(db, name.encode('cp1251'))
        if owner is None:
            raise ValueError('Персонаж не найден')
        sessions = [s for s in self.hub.players.values()
                    if s.account == owner and not s.stopping.is_set()]
        if not sessions:
            raise ValueError('Приглашаемый игрок должен быть в сети')
        return owner, sessions[0]

    def command(self, session, text):
        args = text.strip().split(); command = args[0].lower() if args else ''
        if command not in ('!party', '!contracts'):
            return False
        with self.hub.lock:
            before = {owner: deque(queue) for owner, queue in self.hub.queues.items()}
            try:
                with transaction(self.path):
                    self._command(session, command, args[1:])
            except (ValueError, UnicodeError) as error:
                self.hub.queues = before
                self.reply(session, str(error))
        return True

    def guard(self, session, packet):
        """Grouped players cannot independently enter another gameplay queue."""
        if not self.member(session):
            return False
        forbidden = (packet[:1] in (b'\xb0', b'\x1f', b'\x2e', b'\x29') or
                     packet[:2] in (b'\xba\x03', b'\xba\x04', b'\xc8\x2b') or
                     packet[:1] == b'\xc6')
        if forbidden:
            self.reply(session, 'Сначала выйдите из группы, чтобы войти в другой бой или поиск.')
        return forbidden

    def travel_map(self, session, packet, *, busy=False):
        with self.hub.lock:
            party = self.member(session)
            if party:
                for member in party['members']:
                    live = [player for owner, player in self.hub.players.items()
                            if player.account == member['owner'] and owner not in self.hub.offline
                            and not player.stopping.is_set()]
                    if party['state'] == 'city' and len(live) != 1:
                        raise ValueError('Для выхода все участники должны подключиться к игре')
                    busy = busy or any(self.hub.busy(player) or player.arena._fields
                                       or player.survival.searching(player.probe_character_id) for player in live)
            return session.locations.travel(session.account, packet, session.probe_character_id, busy=busy)

    def _command(self, session, command, args):
        owner = session.account; party = self.member(session)
        action = args[0].lower() if args else 'help'
        if command == '!contracts' and action == 'help':
            self.reply(session, '!contracts list | take camp/depot/checkpoint | status | start | cancel')
            return
        if command == '!party' and action == 'help':
            self.reply(session, '!party create | invite Ник | accept ID | decline ID | ready | unready | status',
                       '!party select ID [ID] | leader Ник | kick Ник | leave | disband')
            return
        if action == 'status':
            if not party:
                self.reply(session, 'Вы не состоите в группе. !party create')
                for invite in self.parties.invitations(owner):
                    self.reply(session, f"Приглашение {invite['id']} от {self.name(invite['leader'])}: !party accept {invite['id']}")
                return
            if command == '!contracts':
                contract = self.contracts.active(party['id'])
                target = self.contracts.target_for(owner) if contract else None
                self.reply(session, f"{contract['template']['name']}: {CONTRACT_STATES[contract['state']]}" if contract else 'Активного контракта нет.')
                if target is not None:
                    self.reply(session, f"Цель контракта: {target['name']}. Координаты ({target['x']}, {target['y']}).")
            else:
                self.reply(session, f"Группа — {PARTY_STATES[party['state']]}; лидер {self.name(party['leader'])}.")
                for member in party['members']:
                    self.reply(session, f"{self.name(member['owner'])}: {'лидер; ' if member['owner']==party['leader'] else ''}"
                               f"{'готов' if member['ready'] else 'не готов'}, {'в сети' if member['online'] else 'не в сети'}, бойцы {list(member['selected'])}")
                if party['state'] == 'city' and not self.contracts.active(party['id']):
                    self.reply(session, '!party invite Ник — пригласить; !party select ID [ID] — выбрать бойцов; !party ready — готовность.')
                elif party['state'] in ('city', 'at_target'):
                    self.reply(session, '!party ready — подтвердить готовность; !contracts status — посмотреть задание.')
            return
        if command == '!contracts' and action == 'list':
            self.reply(session, 'Доска контрактов — зачистки для группы из 2–4 игроков.')
            for template in self.contracts.catalog():
                reward = template['reward']
                self.reply(session, f"{template['id']}: {template['name']}; {reward['credits']} кредитов, {reward['experience']} опыта за победу.")
            self.reply(session, '!contracts take camp/depot/checkpoint — выбор лидера; !contracts status — текущее задание.'
                       if party else 'Сначала соберите группу в городе — !party create, затем !party invite Ник.')
            return
        if self.hub.busy(session) or session.survival.searching(session.probe_character_id) or session.arena._fields:
            raise ValueError('Сначала завершите текущий бой или поиск')
        if command == '!contracts':
            if not party:
                raise ValueError('Сначала соберите группу в городе: !party create')
            if action == 'take' and len(args) == 2:
                if any(self.hub.busy(s) or s.survival.searching(s.probe_character_id) or s.arena._fields
                       for s in self.hub.players.values() if any(m['owner']==s.account for m in party['members'])):
                    raise ValueError('Участники должны выйти из боёв и поиска')
                contract = self.contracts.accept(party, owner, args[1], str(uuid4()))
                # Accepting changes the mission; each member consents again.
                for member in party['members']:
                    self.parties.ready(member['owner'], False)
                target = contract['target']
                self.reply(session, f"Контракт принят: {target['name']}. Цель ({target['x']}, {target['y']}). Все: !party ready; лидер выбирает маршрут на карте.")
            elif action == 'cancel' and len(args) == 1:
                self.contracts.cancel(party, owner)
                self.reply(session, 'Контракт отменён. Группу можно вернуть в город общим маршрутом.')
            elif action == 'start' and len(args) == 1:
                self.start(session)
            else:
                raise ValueError('Неизвестная команда. !contracts')
            return
        # A frozen contract must be cancelled before roster edits.
        if party and action in ('invite', 'select', 'leader', 'kick', 'leave', 'disband') and self.contracts.active(party['id']):
            raise ValueError('Сначала отмените контракт, чтобы изменить состав или бойцов')
        if action == 'create' and len(args) == 1:
            self.parties.create(owner)
        elif action == 'invite' and len(args) == 2:
            target, target_session = self.named_owner(args[1])
            if self.hub.busy(target_session) or target_session.arena._fields or target_session.survival.searching(target_session.probe_character_id):
                raise ValueError('Приглашаемый игрок занят боем')
            invite = self.parties.invite(owner, target)
            self.reply(target_session, f"{self.name(owner)} приглашает в группу. !party accept {invite['id']} или !party decline {invite['id']} (120 секунд).")
            self.reply(session, f"Приглашение {invite['id']} отправлено {self.name(target)}. Действует 120 секунд.")
            return
        elif action in ('accept', 'decline') and len(args) == 2:
            getattr(self.parties, action)(owner, int(args[1]))
        elif action in ('ready', 'unready') and len(args) == 1:
            self.parties.ready(owner, action == 'ready')
        elif action == 'select' and 2 <= len(args) <= 3:
            self.parties.select(owner, tuple(int(i) for i in args[1:]))
        elif action in ('leader', 'kick') and len(args) == 2:
            target, _ = self.named_owner(args[1])
            getattr(self.parties, 'transfer' if action == 'leader' else 'kick')(owner, target)
        elif action in ('leave', 'disband') and len(args) == 1:
            getattr(self.parties, action)(owner)
        else:
            raise ValueError('Неизвестная команда. !party')
        self.reply(session, 'Группа обновлена. !party status')

    def start(self, session):
        # The shared battle builder is installed by the local combat stage.
        builder = getattr(self.hub, 'start_contract', None)
        if builder is None:
            raise ValueError('Общий бой контрактов ещё не подключён')
        return builder(session, self)
