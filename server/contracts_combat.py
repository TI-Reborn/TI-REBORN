"""One journaled PvE field for a frozen party of real account owners.

The native battle and reconnect paths retain their normal ownership checks.
Contract templates determine NPCs and quoted rewards; this mixin never creates
mirror player accounts, PvP opponents, ranked reports or a team rating match.
"""
from copy import deepcopy
import time
from uuid import uuid4

from tio.db_transaction import key, transaction
from tio.locations import LocationStore, center
from tio.matchmaking import SearchTicket
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.system_message import encode_shop_error
from tio.pve_contracts import ContractStore
from tio.travel_party import PartyStore


class ContractsCombat:
    def start_contract(self, session, service):
        """Validate and publish the complete scene and checkpoint atomically."""
        with self.lock:
            journal = getattr(self, 'journal', None)
            if journal is None or key(journal.path) != key(service.path):
                raise ValueError('Для контрактов требуется журнал боёв той же серверной базы')
            return journal.birth(self.build_contract, session, service)

    def build_contract(self, session, service):
        from tio.arena_service import ArenaService
        from tio.contract_scene import prepare
        from tio.protocol.arena import ArenaCreateRequest
        from tio.protocol.battle_turn import turn_seconds
        from tio.character_identity import auth_account

        party = service.parties.info(session.account)
        if not party or party['leader'] != session.account:
            raise ValueError('Бой контракта запускает лидер группы')
        contract = service.contracts.active(party['id'])
        if not contract or contract['state'] != 'arrived' or party['state'] != 'at_target':
            raise ValueError('Сначала доберитесь всей группой до цели контракта')
        if not 2 <= len(party['members']) <= 4 or not all(m['online'] and m['ready'] for m in party['members']):
            raise ValueError('Все участники группы должны быть в сети и готовы')
        bounds = contract['target']['bounds']
        seats, sessions = [], {}
        frozen = {member['owner']: member for member in contract['roster']}
        for member in party['members']:
            account = member['owner']
            candidates = [(owner, player) for owner, player in self.players.items()
                          if player.account == account and owner not in self.offline
                          and not (getattr(player, 'stopping', None) and player.stopping.is_set())]
            if len(candidates) != 1:
                raise ValueError('Каждый участник должен подключиться своим персонажем')
            owner, player = candidates[0]
            if key(player.database) != key(service.path):
                raise ValueError('Группа должна использовать одну серверную базу')
            login = getattr(player, 'authenticated_account', None) or auth_account(service.path, account)
            if login != member['login'] or account not in frozen:
                raise ValueError('Учётная запись участника изменилась')
            if tuple(member['selected']) != tuple(frozen[account]['selected']):
                raise ValueError('Состав бойцов контракта изменился')
            if self.busy(player) or player.survival.searching(player.probe_character_id) or player.arena._fields:
                raise ValueError('Участник занят другим боем или поиском')
            point, route = service.travel.point(account)
            if route is not None or not (bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]):
                raise ValueError('Все участники должны находиться у цели контракта')
            rows = {identity: (raw, inventory) for identity, raw, inventory in OwnedPetStore(service.path).list(account)}
            levels = []
            for identity in member['selected']:
                if identity not in rows:
                    raise ValueError('Выбранный боец больше не принадлежит персонажу')
                packet = rows[identity][0]
                resource = int.from_bytes(packet[5:9], 'little')
                pet = decode_pet_info(packet, human_equipment=resource in (1, 2, 6)).fields
                if pet['0x8c43eb'] != identity or pet['0x8c4ab1'] <= 0 or pet['0x8c44a6'] == 4:
                    raise ValueError('Для контракта нужны живые пригодные бойцы')
                level = pet['0x8c4aef']
                if not contract['template']['levels'][0] <= level <= contract['template']['levels'][1]:
                    raise ValueError('Уровень бойца не подходит для контракта')
                levels.append(level)
            ticket = SearchTicket(owner, tuple(member['selected']), tuple(levels), self.clock(), 7)
            seats.append((owner, 0, service.path, account, ticket, False))
            sessions[owner] = player
        if sum(len(seat[4].actors) for seat in seats) > 8:
            raise ValueError('В контракт допускается не более восьми бойцов')
        field, views, ground, skills, bot_owner = prepare(seats, contract)
        if set(views) != set(sessions) or bot_owner in sessions or any(field.teams[owner] != 0 for owner in sessions) or field.teams[bot_owner] != 1:
            raise ValueError('Некорректное владение общей сценой контракта')
        if set(field.combat.persistence) != {identity for owner in sessions for identity in field.actor_ids(owner)}:
            raise ValueError('NPC контракта не должны сохраняться как бойцы игроков')
        match_id = str(uuid4())
        contract = service.contracts.start(contract['id'], party, session.account, match_id)
        service.parties.change_state(party['id'], 'battle', 'at_target')
        arena = ArenaService(clock=self.clock)
        captain = self.identities[session]
        humans = (captain, *sorted(owner for owner in sessions if owner != captain))
        order = (*humans, bot_owner)
        soldiers = max(len(seat[4].actors) for seat in seats)
        room = arena.rooms.create(captain, ArenaCreateRequest(7, 0, len(order), 2,
                                  turn_seconds(soldiers), soldiers, soldiers, 0, 0))
        for member in order[1:]:
            room = arena.rooms.join(room.room_id, member)
        arena._fields[room.room_id] = field
        arena._loading[room.room_id] = {bot_owner}
        arena._match_ids[room.room_id] = match_id
        field.scene_metadata['town_id'] = contract['town_id']
        battle = dict(kind='contract', arena=arena, room=room, field=field, views=views,
                      bots={bot_owner}, humans=set(humans), city_id=contract['town_id'],
                      match_id=match_id, settled=set(), deadline=self.clock()+60,
                      finished=False, ground=ground, captain_name=session.probe_character_name,
                      names={**{owner: sessions[owner].probe_character_name for owner in humans}, bot_owner: b'Marauders'},
                      result_packets={}, reward_roster={seat[0]: (seat[3], tuple(seat[4].levels), 0) for seat in seats},
                      reward_damage=set(), reward_support=set(), reward_started=False,
                      return_towns={owner: contract['town_id'] for owner in humans},
                      contract_id=contract['id'], contract_party_id=contract['party_id'],
                      contract_path=service.path, contract_roster=deepcopy(contract['roster']),
                      contract_quotes=deepcopy(contract['rewards']), contract_returned=False)
        for owner, _, _, account, ticket, _ in seats:
            self.tickets[owner] = ticket
            self.battles[owner] = battle
            self.account_owners[account] = owner
            sessions[owner]._battle_treatment_ids = None
        for owner in humans:
            self.send_scene(owner)
        return battle

    def _contract_unit(self, battle):
        journal = getattr(self, 'journal', None)
        if journal is None:
            raise ValueError('Для завершения контракта требуется журнал боёв')
        return journal.unit(battle)

    def finish_contract(self, battle):
        if battle.get('kind') != 'contract':
            raise ValueError('Ожидался бой контракта')
        if battle['finished']:
            return
        with self._contract_unit(battle):
            field = battle['field']
            bots_alive = any(field.living_actor_ids(owner) for owner in battle['bots'])
            humans_alive = any(field.living_actor_ids(owner) for owner in battle['reward_roster'])
            if bots_alive and humans_alive:
                raise ValueError('Зачистка ещё не завершена')
            victory = bool(humans_alive and not bots_alive)
            store = ContractStore(battle['contract_path'])
            receipt = store.transition(battle['contract_id'], 'active', 'completed' if victory else 'failed',
                                       match_id=battle['match_id'], outcome='victory' if victory else 'defeat')
            battle['contract_result'] = int(victory)
            battle['contract_receipt'] = receipt
            requests = tuple((owner, int(victory), False) for owner in sorted(battle['humans']))
            self.prepare_settlements(battle, requests)
            for owner, result, _ in requests:
                self.settle(battle, owner, result)
            battle['finished'] = True
            self._return_contract_party(battle)
            for owner in battle['humans']:
                self.battles.pop(owner, None)
                self.results.add(owner)
                self.completed[owner] = battle

    def abort_contract(self, battle, reason):
        """One departure aborts the entire mission; no partial winning payout."""
        if battle.get('kind') != 'contract':
            return
        if battle['finished']:
            return
        if not isinstance(reason, str) or not reason:
            raise ValueError('Нужна причина отмены боя контракта')
        with self._contract_unit(battle):
            store = ContractStore(battle['contract_path'])
            battle['contract_receipt'] = store.transition(battle['contract_id'], 'active', 'failed',
                                                         match_id=battle['match_id'], outcome='aborted')
            battle['contract_result'] = 0
            battle['contract_abort_reason'] = reason
            requests = tuple((owner, 0, True) for owner in sorted(battle['humans']))
            self.prepare_settlements(battle, requests)
            for owner, result, _ in requests:
                self.settle(battle, owner, result, escaped=True)
            battle['finished'] = True
            self._return_contract_party(battle)
            for owner in tuple(battle['humans']):
                self.battles.pop(owner, None)
                self.completed[owner] = battle
                self.put(owner, encode_shop_error('Контракт прекращён. Группа возвращена в город.'))
                self.to_city(owner)

    def contract_settlement_inputs(self, battle, owner, *, escaped=False):
        if owner not in battle['reward_roster']:
            raise ValueError('Награда контракта принадлежит зафиксированному участнику')
        field, combat = battle['field'], battle['field'].combat
        identities = field.actor_ids(owner)
        account = battle['reward_roster'][owner][0]
        health = {combat.storage_ids[identity]: field.actor(identity).health for identity in identities}
        earned = {} if escaped else {combat.storage_ids[identity]: value
                                     for identity, value in combat.experience.report(combat, owner).items()}
        values = dict(escaped=escaped, now=time.time(), health=health, experience_report=earned,
                      rental_units=tuple(combat.rental_tax_units.get(identity, 0) for identity in identities))
        if not escaped and battle.get('contract_result') == 1:
            frozen = next((member for member in battle['contract_roster'] if member['owner'] == account), None)
            quote = next((member for member in battle['contract_quotes'] if member['owner'] == account), None)
            if frozen is None or quote is None or frozen['login'] != quote['login']:
                raise ValueError('Не найдена зафиксированная награда контракта')
            selected = tuple(frozen['selected'])
            quotient, remainder = divmod(quote['experience'], len(selected))
            bonus = {}
            for index, identity in enumerate(selected):
                bonus[identity] = quotient + int(index < remainder)
                earned[identity] = earned.get(identity, 0) + bonus[identity]
            values['contract_report'] = dict(version=1, instance_id=battle['contract_id'], match_id=battle['match_id'],
                                            owner=account, login=frozen['login'], credits=quote['credits'], experience=quote['experience'],
                                            bonus_experience=bonus)
        return values

    def _return_contract_party(self, battle):
        if battle.get('contract_returned'):
            return
        path = battle['contract_path']
        with transaction(path) as db:
            parties = PartyStore(path)
            party = parties.snapshot(battle['contract_party_id'], connection=db)
            if party is None:
                raise ValueError('Группа активного контракта исчезла')
            expected = {(member['owner'], member['login']) for member in battle['contract_roster']}
            if {(member['owner'], member['login']) for member in party['members']} != expected:
                raise ValueError('Состав группы активного контракта изменился')
            town = battle['city_id']
            point = center(town)
            for member in battle['contract_roster']:
                LocationStore._save(db, member['owner'], town, *point)
                db.execute('DELETE FROM map_journeys WHERE account=?', (member['owner'],))
            db.execute('DELETE FROM travel_party_journeys WHERE party_id=?', (battle['contract_party_id'],))
            db.execute('UPDATE travel_party_groups SET town_id=? WHERE id=?',
                       (town, battle['contract_party_id']))
            if party['state'] != 'city':
                parties.change_state(party['id'], 'city', party['state'], connection=db)
            battle['contract_returned'] = True

    def contract_to_city(self, battle, owner):
        """Restore authoritative city positions before the standard native exit."""
        if battle.get('kind') != 'contract':
            return False
        if not battle['finished'] or owner not in battle['reward_roster']:
            raise ValueError('Сначала завершите всю миссию контракта')
        self._return_contract_party(battle)
        return True
