"""Shared, journaled underground instances entered by native checkpoint roles.

Each instance admits one miner, one owner-clan escort and up to two raiders.
Departures retain their account-bound results; new admissions never regenerate
the map, drill, deposits, mutants or the round clock.
"""
from collections import deque
from contextlib import nullcontext
from copy import copy
from dataclasses import replace
import json
from pathlib import Path
import struct
from uuid import uuid4

from tio.protocol.system_message import encode_shop_error
from .mine_requests import MineRequests


def ability_catalog():
    from tio.abilities import AbilityCatalog, AbilityLevel
    rows = json.loads((Path(__file__).resolve().parents[1] / 'config/abilities.json').read_text())['records']
    return AbilityCatalog(AbilityLevel(r['id'], r['level'], r['fields']) for r in rows)


class MineArena(MineRequests):
    def mine_instances(self, town):
        return tuple(b for b in {id(b): b for b in self.battles.values()}.values()
                     if b.get('kind') == 'mine' and b['city_id'] == town and not b['finished'])

    def mine_unit(self, battle):
        journal = getattr(self, 'journal', None)
        return journal.unit(battle) if journal else nullcontext()

    def mine_menu(self, owner, town):
        from tio.protocol.mining import player_state
        from tio.mine_claims import MineClaimsStore
        session = self.players[owner]
        # Direct B014 entry must freeze the current round's tax too, even
        # when the client skipped the checkpoint-menu request.
        from tio.mine_rounds import MineRounds
        MineRounds(session.database).state()
        claim = MineClaimsStore(session.database).freeze(town)
        battles = self.mine_instances(town)
        counts = {role: sum(b['field'].mining.roles[o] == role for b in battles
                           for o in b['mine_active']) for role in (1, 2, 3)}
        can_defend = False
        try:
            MineClaimsStore(session.database).authorize_defender(session.account, claim)
            can_defend = True
        except ValueError:
            pass
        from tio.mine_rounds import MineRounds
        waiting={role:sum(r.town==town and r.role==role for r in self.mine_requests.values()) for role in (2,3)}
        return (player_state(can_raid=True,
                             can_defend=can_defend, miners=counts[1],
                             defenders=counts[3], raiders=counts[2],waiting_defenders=waiting[3],waiting_raiders=waiting[2]),
                *MineRounds(session.database).packets())

    def mine_seat(self, battle, role):
        mine = battle['field'].mining
        counts=sum(mine.roles.get(o)==role for o in battle['humans'])
        eligible=(counts==0 and battle.get('mine_help',{}).get(3,False)) if role==3 else counts<2 and (counts==0 or battle.get('mine_help',{}).get(2,False))
        return (len(battle['room'].members) < 8 and not battle.get('faulted')
                and not battle['finished'] and eligible
                and any(mine.roles[o] == 1 and battle['field'].living_actor_ids(o)
                        for o in battle['mine_active'])
                )

    def handle_mining(self, owner, packet):
        if packet[:1] != b'\xb0':
            return False
        session = self.players[owner]
        battle = self.battles.get(owner)
        if battle is not None and battle.get('kind') != 'mine':
            return False
        if len(packet) < 2:
            raise ValueError('Некорректный запрос шахты')
        sub = packet[1]
        if sub not in (0x14, 0x15, 0x19, 0x1c, 0x2c) and battle is None:
            return False  # Existing quote/rating readers keep their native ABI.
        from tio.locations import MINE_LOCATIONS
        town = session.locations.current(session.account) if session.locations else None
        if town not in MINE_LOCATIONS:
            raise ValueError('Сначала перейдите к блокпосту шахты')
        if sub in (0x1c, 0x2c) and len(packet) == 2:
            self.put(owner, *self.mine_menu(owner, town))
            if self.mine_waiting(owner):self.put(owner,*self.queue_packets(owner,town))
            return True
        if sub == 0x19 and len(packet) == 2:
            self.cancel_mine_request(owner)
            return True
        if battle is not None:
            if sub == 0x14 and packet == bytes((0xb0, 0x14, battle['field'].mining.roles[owner])):
                return True
            if sub == 0x15:
                from tio.protocol.mining import decode_pickup
                actor, x, y, amount = decode_pickup(packet)
                with self.mine_unit(battle):
                    arena = battle['arena']; turn = arena._turns.get(battle['room'].room_id)
                    if (turn is None or turn[0] != owner or actor not in turn[1]
                            or self.clock() >= turn[2] or owner in self.returning):
                        raise ValueError('Для снятия бура требуется ваш активный ход')
                    self.put(owner, *battle['field'].mining.pickup(owner, actor, x, y, amount))
                    self.snapshot(battle)
                    self.mine_after_action(battle, owner)
                return True
            if sub in (0x21, 0x24, 0x28):
                # Prices and role leaderboards are read-only during a battle.
                handled = session.mining.handle(session.account, session.probe_character_id,
                                                session.probe_character_name, packet)
                if handled is not None:
                    self.put(owner, *handled[1]); return True
            raise ValueError('Запрос недоступен в текущем бою шахты')
        if sub != 0x14 or len(packet) != 3 or packet[2] not in (1, 2, 3):
            raise ValueError('Некорректная роль шахты')
        if (self.busy(session) and not self.mine_waiting(owner) or session.survival.searching(session.probe_character_id)
                or any(session.probe_character_id in r.members for r in session.arena.rooms.snapshot())):
            raise ValueError('Сначала завершите текущий бой или поиск')
        from tio.owned_pets import OwnedPetStore
        from tio.matchmaking import SurvivalQueue
        from tio.mining import band
        from tio.crystal_market import POLICY
        ticket = SurvivalQueue(clock=self.clock).join(owner, OwnedPetStore(session.database).list(session.account))
        if band(ticket.levels) != tuple(POLICY['bands'][MINE_LOCATIONS[town]['band']]):
            raise ValueError('Отряд не соответствует диапазону уровней шахты')
        role = packet[2]
        if self.mine_waiting(owner) and self.mine_requests[owner].role!=role:raise ValueError('Сначала отмените предыдущую заявку шахты')
        if role == 1:
            journal = getattr(self, 'journal', None)
            if journal:
                journal.birth(self.build_mine, owner, town, ticket)
            else:
                self.build_mine(owner, town, ticket)
            self.try_mine_requests(self.battles[owner])
        else:
            self.enqueue_mine_request(owner,town,ticket,role)
            for chosen in sorted(self.mine_instances(town),key=lambda b:b['created_at']):self.try_mine_requests(chosen)
        return True

    def build_mine(self, owner, town, ticket):
        from tio.arena_service import ArenaService
        from tio.protocol.arena import ArenaCreateRequest
        from tio.mine_claims import MineClaimsStore
        from tools.mining_scene import prepare_shared_mining
        session = self.players[owner]
        claim = MineClaimsStore(session.database).freeze(town)
        prepared = prepare_shared_mining(session.database, ((session.account, ticket, 1),), ability_catalog())
        field = prepared.field
        field.return_town = town
        field.scene_metadata['town_id'] = town
        arena = ArenaService(clock=self.clock)
        room = arena.rooms.create(owner, ArenaCreateRequest(7, 0, 8, 2, 80, len(ticket.actors), len(ticket.actors), 0, 0))
        room = arena.rooms.join(room.room_id, prepared.bot_owner)
        arena._fields[room.room_id] = field
        arena._loading[room.room_id] = {prepared.bot_owner}
        from tio.visibility import VisibilityView
        # Preparation already refreshed its view to build packets. send_scene
        # sends the authoritative scene separately, so it needs an unsent view.
        view = VisibilityView(field, owner, prepared.visibility.templates)
        battle = dict(kind='mine', arena=arena, room=room, field=field, views={owner: view},
                      bots={prepared.bot_owner}, city_id=town, humans={owner}, mine_active={owner},
                      match_id=str(uuid4()), settled=set(), deadline=self.clock()+60, finished=False,
                      ground=prepared.packets[0], captain_name=session.probe_character_name,
                      names={owner: session.probe_character_name, prepared.bot_owner: b'Mutants'},
                      result_packets={}, reward_roster={owner: (session.account, tuple(ticket.levels), 0)},
                      reward_damage=set(), reward_support=set(), reward_started=False,
                      return_towns={owner: town}, mine_claim=claim, mine_pairs={owner: (session.account, None)},
                      mine_retired={}, mine_retired_state={}, mine_round_seen=set(),mine_help={2:False,3:False},
                      mine_raiders={},created_at=self.clock())
        from tio.mine_radio import configure
        configure(field,owner)
        self.tickets[owner] = ticket
        self.battles[owner] = battle
        self.account_owners[session.account] = owner
        self.send_scene(owner)
        return battle

    def join_mine(self, battle, owner, ticket, role):
        from tio.mine_claims import MineClaimsStore
        from tools.mining_scene import append_mining_owner
        session = self.players[owner]
        if not self.mine_seat(battle, role):
            raise ValueError('Место в шахте уже занято')
        if str(session.database) != str(next(iter(battle['field'].combat.persistence.values()))[0]):
            raise ValueError('Шахта должна использовать одну серверную базу')
        if session.account in {r[0] for r in battle['reward_roster'].values()}:
            raise ValueError('Повторный вход тем же аккаунтом в эту шахту запрещён')
        if role == 3:
            MineClaimsStore(session.database).authorize_defender(session.account, battle['mine_claim'])
        source = next(iter(battle['views'].values()))
        view, _ = append_mining_owner(battle['field'], session.database, session.account, ticket,
                                     ability_catalog(), role=role, templates=source.templates)
        for existing in battle['views'].values():
            existing.templates.update(view.templates)
        from tio.visibility import VisibilityView
        battle['views'][owner] = VisibilityView(battle['field'], owner, view.templates)
        room = battle['arena'].rooms.join(battle['room'].room_id, owner)
        # The mutant group runs once after all currently admitted squads.
        order = tuple(o for o in room.members if o not in battle['bots']) + tuple(battle['bots'])
        room = replace(room, members=order)
        battle['arena'].rooms._rooms[room.room_id] = room
        battle['room'] = room
        battle['names'][owner] = session.probe_character_name
        battle['humans'].add(owner); battle['mine_active'].add(owner)
        battle['reward_roster'][owner] = (session.account, tuple(ticket.levels), 1 if role == 2 else 0)
        battle['return_towns'][owner] = battle['city_id']
        if role == 3:
            miner = next(o for o in battle['mine_active'] if battle['field'].mining.roles[o] == 1)
            pair = (self.players[miner].account, session.account)
            battle['mine_pairs'][miner] = pair; battle['mine_pairs'][owner] = pair
        else:
            battle['mine_pairs'][owner] = (None, None)
            raiders=tuple(o for o in battle['room'].members if o in battle['humans'] and battle['field'].mining.roles.get(o)==2)
            pair=tuple(battle['reward_roster'][o][0] for o in raiders)
            battle.setdefault('mine_raiders',{}).update({o:pair for o in raiders})
        from tio.mine_radio import configure
        configure(battle['field'],owner)
        self.tickets[owner] = ticket
        self.battles[owner] = battle
        self.account_owners[session.account] = owner
        battle['deadline'] = self.clock()+60
        self.send_scene(owner)
        self.notify_online(battle, exclude=owner)
        self.snapshot(battle)

    def mine_call_help(self,battle,owner,packet):
        if packet[:1]!=b'\x81':return False
        from tio.protocol.ability_cast import decode_ability_cast
        cast=decode_ability_cast(packet)
        if cast.ability_id!=28:return False
        from tio.mine_radio import request
        role=request(battle['field'],owner,cast)
        mine=battle['field'].mining
        if role==2:
            first=next((o for o in battle['room'].members if o in battle['mine_active'] and mine.roles[o]==2),None)
            if first!=owner:raise ValueError('Второго рейдера вызывает первый рейдер')
        battle.setdefault('mine_help',{2:False,3:False})[role]=True
        from tio.protocol.chat import encode_system_message
        self.put(owner,encode_system_message(4,b'Server','Вызов помощи принят. Ожидаем подходящий отряд.'))
        return True

    def mine_exit_position(self, battle, owner):
        return battle['field'].mining.at_exit(owner)

    def mine_after_action(self, battle, owner, *, moved=False):
        """Refresh the menu flag; only an explicit quit request extracts a drill."""
        if owner not in battle['mine_active']:
            return
        self.mine_lift_refresh(battle)

    def mine_can_quit(self, battle, owner):
        return owner in battle['mine_active'] and battle['field'].mining.can_quit(owner)

    def mine_scene_flags(self, battle, owner):
        if battle.get('kind')!='mine':return ()
        from tio.protocol.mining import battle_state,can_quit
        enabled=self.mine_can_quit(battle,owner)
        battle.setdefault('mine_can_quit',{})[owner]=enabled
        return battle_state(True),can_quit(enabled)

    def mine_lift_refresh(self, battle):
        from tio.protocol.mining import can_quit
        cached=battle.setdefault('mine_can_quit',{})
        for owner in battle['mine_active']:
            enabled=self.mine_can_quit(battle,owner)
            if cached.get(owner) is not enabled:
                cached[owner]=enabled;self.put(owner,can_quit(enabled))

    def complete_mine_owner(self, battle, owner, result):
        if owner not in battle['mine_active']:
            return
        self.settle(battle, owner, result)
        field = battle['field']
        battle['mine_retired'][owner] = {i: field.actor(i) for i in field.actor_ids(owner)}
        identities=set(battle['mine_retired'][owner])
        battle['mine_retired_state'][owner]={
            name:{key:value for key,value in getattr(field,name).items()
                  if (key[0] if isinstance(key,tuple) else key) in identities}
            for name in ('_turn_points','_ability_turns','_cooldowns','_healing_rules','_slash_rules','_dog_rules')}
        self.players[owner]._battle_treatment_ids = {i: field.combat.storage_ids[i]
            for i in field.actor_ids(owner) if i in field.combat.storage_ids}
        self.battles.pop(owner, None); battle['mine_active'].discard(owner)
        self.results.add(owner); self.completed[owner] = battle
        field.remove_owner(owner)
        arena = battle['arena']; room = battle['room']
        arena._loading[room.room_id].add(owner)
        if arena._turns.get(room.room_id, (None,))[0] == owner:
            arena._turns.pop(room.room_id, None); arena._last_turn[room.room_id] = owner
        if not battle['mine_active']:
            battle['finished'] = True
        self.snapshot(battle)
        self.mine_asset_refresh(battle)

    def complete_mine_mission(self,battle,extractor):
        """The first positive lift/exit extraction ends the shared mission."""
        if battle['finished']:return
        field=battle['field'];mine=field.mining
        if not (mine.extracted_amounts.get(extractor) or 0):raise ValueError('Successful extraction required')
        from tio.mining import minimum_victory_crystals
        victory=mine.extracted_amounts[extractor]>=minimum_victory_crystals(field.scene_metadata['level_band'][0])
        side=1 if mine.roles[extractor]==2 else 0
        plans=tuple((o,int(victory and (1 if mine.roles[o]==2 else 0)==side),False) for o in sorted(battle['mine_active']))
        # Freeze every report before removing any actor. Database replay must
        # keep the earned partner shares even after scene membership changes.
        self.prepare_settlements(battle,plans)
        for owner,result,_ in plans:self.complete_mine_owner(battle,owner,result)
        battle['finished']=True

    def mine_asset_refresh(self, battle):
        from tio.crystal_market import CrystalMarket
        from tio.wallets import WalletStore
        from tio.protocol.asset_count import encode_asset_count
        recipients={row[0] for row in battle['reward_roster'].values()}
        # An escort may later extract a drill after its miner already returned
        # to town or entered another scene. Publish the frozen pair's payout
        # to the current online session without restoring battle membership.
        for session,owner in tuple(self.identities.items()):
            if session.account in recipients and owner not in self.offline:
                assets = CrystalMarket(session.database).project(session.account, WalletStore(session.database).ensure(session.account))
                self.put(owner, encode_asset_count(assets))

    def mine_result_field(self, battle, owner):
        field = battle['field']
        retired = battle.get('mine_retired', {}).get(owner)
        if retired is not None:
            field = copy(field)
            field._actors = {**field._actors, **retired}
            for name,values in battle['mine_retired_state'][owner].items():
                setattr(field,name,{**getattr(field,name),**values})
        return field

    def tick_mine(self, battle):
        arena = battle['arena']; room = battle['room']; field = battle['field']
        if battle['finished']:
            return
        for owner in tuple(battle['mine_active']):
            if not field.living_actor_ids(owner):
                self.complete_mine_owner(battle, owner, 0)
        if battle['finished']:
            return
        if arena._loading[room.room_id] != set(room.members):
            if self.clock() <= battle['deadline']:
                return
            # A late loader cannot roll back another player's existing mine.
            for owner in tuple(battle['mine_active'] - arena._loading[room.room_id]):
                self.settle(battle, owner, 0, escaped=True)
                self.remove_from_battle(battle, owner); self.to_city(owner)
        for owner, packet in arena.expire_turns():
            self.fence_finished_turn(battle, owner)
            self.put(owner, *arena.finished_turn_packets(owner, packet))
        self.finish_exhausted_turn(battle)
        if room.room_id in arena._turns or not battle['mine_active']:
            return
        battle['reward_started'] = True
        active = {o for o in room.members if field.living_actor_ids(o)}
        seen = battle['mine_round_seen']
        if seen and active <= seen:
            field.mining.advance(field.mining.last_tick+1)
            seen.clear()
            self.snapshot(battle)
        arena._last_turn.setdefault(room.room_id, room.members[-1])
        owner = arena.next_turn_owner(room.room_id)
        seen.add(owner)
        if owner in battle['bots']:
            from tio.training_bot import play_turn
            from .battle_events import BotEventArena
            self.announce_turn(battle, owner, 40)
            play_turn(BotEventArena(self, battle), room.room_id, owner)
        else:
            from tio.protocol.battle_turn import turn_seconds
            seconds = turn_seconds(len(field.living_actor_ids(owner)))
            battle['full_turn'] = (owner, self.clock()+seconds)
            if owner in self.offline:
                seconds //= 2
            self.announce_turn(battle, owner, seconds)
            self.begin_shared_turn(battle,owner,seconds)
