"""Native wager lobbies; the common arena owns battlefield and settlement.

Integration contract: init_wagers(), wager_busy(owner), handle_wager(owner,p),
wager_rooms(owner), leave_wager(owner,target), tick_wagers(), stop_wagers().
The common start_match must honor first.request and first.match_id, mark
kind='wager', and transition escrow to loading before journaling the new scene.
All ordinary accepted battle actions retain existing journal/settlement rules.
"""
from dataclasses import replace
from uuid import uuid4
import logging

from tio.db_transaction import transaction, key
from tio.character_identity import auth_account
from tio.matchmaking import SearchTicket
from tio.owned_pets import OwnedPetStore
from tio.protocol.arena import (decode_create_request, decode_room_ready,
    decode_room_start, decode_remove_request, BattleSettings,
    encode_battle_settings_body, ArenaRoom)
from tio.protocol.battle_members import BattleMemberRecord, encode_battle_members
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.system_message import encode_shop_error, encode_leave_room
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.wagers import decode_join, decode_kick, decode_transfer, WagerRoomRecord, encode_room_list
from tio import wagers

LOG = logging.getLogger('tio.server')


class WagerArena:
    def init_wagers(self):
        self.wager_lobbies = wagers.WagerLobbies(clock=self.clock)

    def wager_busy(self, owner):
        return self.wager_lobbies.room(owner) is not None

    def wager_roster(self, owner, request):
        session = self.players[owner]
        if session.database is None: raise ValueError('Для ставки нужен постоянный аккаунт')
        if session.locations and session.locations.current(session.account)==18:
            from tio.world_completion import detroit_wager_dimensions
            detroit_wager_dimensions(request.mode,request.map_size)
        selected = []
        rows = OwnedPetStore(session.database).list(session.account)
        for identity, packet, inventory in rows:
            human = int.from_bytes(packet[5:9], 'little') in (1, 2, 6)
            fields = decode_pet_info(packet, human_equipment=human).fields
            if fields['0x8c44a6'] in (1, 2, 3):
                selected.append((fields['0x8c44a6'], identity, fields))
        selected.sort(key=lambda r: r[0])
        if request.mode == 4: selected = selected[:1]
        if not selected or len(selected) > request.soldiers_count_01 or len({r[0] for r in selected}) != len(selected):
            raise ValueError('Выберите отряд не больше указанного в заявке')
        if any(p['0x8c4ab1'] != p['0x8c4a07'] for _, _, p in selected):
            raise ValueError('Перед ставкой полностью вылечите бойцов')
        ids = tuple(i for _, i, _ in selected); levels = tuple(p['0x8c4aef'] for _, _, p in selected)
        pool = self.city(owner, levels).pool
        ticket = SearchTicket(owner, ids, levels, self.clock(), request.mode, pool)
        return ticket

    def wager_notify(self, room, *, entering=()):
        from tio.arena_roster import room_soldiers
        captain = self.players[room.captain]
        request = room.request
        settings = BattleSettings(1, request.players_count, request.mode,
            request.unknown_u32_01, 2, captain.probe_character_name,
            bytes((max(1,room.creator_level-request.level_range_index),
                   min(20,room.creator_level+request.level_range_index),
                   request.soldiers_count_01,request.map_size,0)), request.stake, 0)
        for viewer in room.members:
            records = []
            for color, owner in enumerate(room.members):
                s = self.players[owner]; ticket = self.tickets[owner]
                rows = tuple(r for r in OwnedPetStore(s.database).list(s.account) if r[0] in ticket.actors)
                # Wall uses the first selected pet even if it occupied slot2/3.
                if request.mode == 4:
                    rows = tuple((i, encode_pet_info(replace(
                        decode_pet_info(p, human_equipment=int.from_bytes(p[5:9],'little') in (1,2,6)),
                        fields={**decode_pet_info(p,human_equipment=int.from_bytes(p[5:9],'little') in (1,2,6)).fields,
                                '0x8c44a6':1})),inv) for i,p,inv in rows)
                records.append(BattleMemberRecord(s.probe_character_id if viewer == owner else owner,
                    s.probe_character_name,0,bytes((max(ticket.levels),max(ticket.levels),color,
                    room.sides[owner],int(owner in room.ready),1)),room_soldiers(rows,room.soldiers,path=s.database,account=s.account)))
            if viewer in entering: self.put(viewer,b'\x6c'+encode_battle_settings_body(settings))
            self.put(viewer,encode_battle_members(request.mode,int(viewer not in entering),records))

    def wager_rooms(self, owner, *, pool=None):
        if pool is None:pool=self.city(owner).pool
        records=[]
        for r in self.wager_lobbies.rooms.values():
            if r.pool != pool or r.starts_at is not None and r.mode not in (1,4):
                continue
            name=self.players[r.captain].probe_character_name
            # Retain the existing projection for other arena modes.
            current,capacity,soldiers,status=0,r.soldiers,len(r.members),0
            if r.mode in (1,4):
                current,capacity,soldiers=len(r.members),r.capacity,r.soldiers
                status=2 if r.starts_at is not None else 0
            records.append(ArenaRoom(r.identity,0,r.mode,status,0,current,capacity,name,0,
                max(1,r.creator_level-r.request.level_range_index),min(20,r.creator_level+r.request.level_range_index),
                soldiers,r.request.map_size))
        return tuple(records)

    def wager_list_packet(self, owner, *, extra=(), pool=None):
        if pool is None:pool=self.city(owner).pool
        records=[]
        for r in self.wager_lobbies.rooms.values():
            if r.pool != pool or r.starts_at is not None and r.mode not in (1,4):
                continue
            name=self.players[r.captain].probe_character_name
            status=0
            if r.mode in (1,4):
                status=2 if r.starts_at is not None else 0
            records.append(WagerRoomRecord(r.identity,name,r.creator_level,r.mode,
                r.capacity,len(r.members),status,r.soldiers,r.request.map_size,
                r.request.level_range_index,0,r.request.stake))
        return encode_room_list((*extra,*records))

    def wager_assets(self, owners):
        for owner in owners:
            s = self.players.get(owner)
            if s is not None:
                from tio.wallets import WalletStore
                self.put(owner,encode_asset_count(WalletStore(s.database).ensure(s.account)))

    def push_battle_listing(self, owner, packet, *, reset=False):
        """C82C merges rows; remove vanished IDs before sending current rows."""
        from tio.protocol.wagers import decode_room_list,encode_room_removed,encode_room_list_clear
        previous=self.wager_listing_cache.get(owner)
        if reset or previous is None:
            self.put(owner,encode_room_list_clear(),packet)
        elif previous!=packet:
            current={r.identity for r in decode_room_list(packet)}
            deleted=sorted({r.identity for r in decode_room_list(previous)}-current)
            self.put(owner,*(encode_room_removed(identity) for identity in deleted),packet)
        self.wager_listing_cache[owner]=packet

    def cancel_wager_start(self, room, reason):
        if room.match_id is None: return
        path = self.players[room.captain].database
        with transaction(path) as db: wagers.refund(db,room.match_id,reason)
        LOG.info('wager_start_cancelled match=%s room=%d reason=%s humans=%d',room.match_id,room.identity,reason,len(room.members))
        room.match_id = None; room.starts_at = None
        self.wager_assets(room.members)

    def leave_wager(self, owner, target=None):
        room = self.wager_lobbies.room(owner)
        if room is None: return False
        chosen = owner if target is None else target
        if chosen not in room.members or chosen != owner and room.captain != owner:
            raise ValueError('Исключать участников может только создатель')
        self.cancel_wager_start(room,'participant_cancelled_start')
        affected = self.wager_lobbies.leave(owner,target)
        for member in affected:
            remaining = self.wager_lobbies.room(member)
            if remaining is None:
                self.tickets.pop(member,None); self.put(member,encode_leave_room())
        if self.wager_lobbies.rooms.get(room.identity) is room:
            if room.mode in (1,4):
                # Native Team/Wall25 merges; explicitly clear departed slots first.
                for member in room.members:self.put(member,b'\x27'+chosen.to_bytes(4,'little'))
            self.wager_notify(room)
        return True

    def handle_wager(self, owner, packet):
        room = self.wager_lobbies.room(owner)
        creating = packet[:2] == b'\xc8\x2b' and len(packet) == 20 and int.from_bytes(packet[-4:],'little') > 0
        joining = (packet[:1] == b'\x29' and (room is not None or len(packet)==5 and int.from_bytes(packet[1:],'little') in self.wager_lobbies.rooms)
                   or packet[:2] == b'\xba\x04' and len(packet) == 6 and int.from_bytes(packet[2:],'little') in self.wager_lobbies.rooms)
        if room is None and not creating and not joining: return False
        try:
            session = self.players[owner]
            if owner in self.battles or owner in self.results:
                return False
            if creating or joining:
                if room is None and self.busy(session): raise ValueError('Сначала завершите бой или отмените поиск')
                if any(session.probe_character_id in r.members for r in session.arena.rooms.snapshot()) or session.survival.searching(session.probe_character_id):
                    raise ValueError('Сначала завершите текущий бой или поиск')
                if creating:
                    request = wagers.validate_request(decode_create_request(packet))
                    ticket = self.wager_roster(owner,request)
                    room = self.wager_lobbies.create(owner,auth_account(session.database,session.account),request,max(ticket.levels),ticket.pool)
                else:
                    identity = decode_join(packet) if packet[:1] == b'\x29' else int.from_bytes(packet[2:],'little')
                    target = self.wager_lobbies.rooms.get(identity)
                    if target is None: raise ValueError('Заявка со ставкой закрыта')
                    ticket = self.wager_roster(owner,target.request)
                    if key(session.database) != key(self.players[target.captain].database):
                        raise ValueError('Ставка должна проходить на одном игровом сервере')
                    room = self.wager_lobbies.join(identity,owner,auth_account(session.database,session.account),ticket.levels,len(ticket.actors),ticket.pool)
                self.tickets[owner] = ticket; self.wager_notify(room,entering=(owner,))
            elif packet[:1] == b'\x2c' or packet[:2] == b'\xba\x07':
                ready = decode_room_ready(packet if packet[:1] == b'\x2c' else b'\x2c'+packet[2:])
                if not ready: self.cancel_wager_start(room,'ready_cancelled_start')
                self.wager_lobbies.ready(owner,ready); self.wager_notify(room)
            elif packet[:1] == b'\x2e':
                decode_room_start(packet,mode=room.mode)
                room = self.wager_lobbies.validate_start(owner)
                if room.starts_at is not None: return True
                members = []
                humans = set()
                for member in room.members:
                    current = self.wager_roster(member,room.request); frozen = self.tickets[member]
                    if (current.actors,current.levels,current.pool) != (frozen.actors,frozen.levels,frozen.pool):
                        raise ValueError('Отряд изменился; пересоздайте заявку')
                    actor_session = self.players[member]
                    canonical = auth_account(actor_session.database,actor_session.account)
                    if canonical in humans or room.accounts[member] != canonical:
                        raise ValueError('Для ставки нужны разные настоящие аккаунты')
                    humans.add(canonical)
                    members.append((actor_session.account,room.sides[member],current.actors,current.levels))
                match = str(uuid4())
                with transaction(session.database) as db:
                    wagers.reserve(db,match,room.request,members,creator_level=room.creator_level,pool=room.pool)
                room.match_id = match; room.starts_at = self.clock()+wagers.COUNTDOWN_SECONDS
                room.ready.add(owner); self.wager_assets(room.members); self.wager_notify(room)
                from tio.protocol.chat import encode_system_message
                for participant in room.members:
                    self.put(participant,encode_system_message(3,b'TIO','Бой со ставкой начнётся через 5 секунд. Отмена готовности вернёт ставку.'))
                LOG.info('wager_countdown_started match=%s room=%d humans=%d stake=%d mode=%d',
                         match,room.identity,len(room.members),room.request.stake,room.mode)
            elif packet == b'\x2a\x01': self.leave_wager(owner)
            elif packet[:1] == b'\x2b' or packet[:2] == b'\xba\x05':
                if packet[:1] == b'\x2b': target = decode_kick(packet)
                else:
                    request = decode_remove_request(packet)
                    target = request.character_id if request.kick else owner
                    if not request.kick and request.character_id != session.probe_character_id:
                        raise ValueError('Некорректный выход из заявки')
                if target == session.probe_character_id: target = owner
                self.leave_wager(owner,target)
            elif packet[:1] == b'\x2d':
                target, side = decode_transfer(packet)
                if target == session.probe_character_id: target = owner
                self.wager_lobbies.transfer(owner,target,side); self.wager_notify(room)
            elif packet == b'\xba\x01':
                self.put(owner,self.list_packet(owner))
                self.push_battle_listing(owner,self.battle_list_packet(owner),reset=True)
            else: raise ValueError('Действие недоступно в заявке со ставкой')
        except ValueError as error:
            self.put(owner,encode_shop_error(str(error)))
        return True

    def tick_wagers(self):
        for room in tuple(self.wager_lobbies.rooms.values()):
            if room.starts_at is None or self.clock() < room.starts_at: continue
            try:
                seats = []; teams = [[] for _ in range(room.capacity if room.mode == 0 else 2)]
                for owner in room.members:
                    current = self.wager_roster(owner,room.request); frozen = self.tickets[owner]
                    if (current.actors,current.levels,current.pool) != (frozen.actors,frozen.levels,frozen.pool):
                        raise ValueError('Отряд изменился во время запуска')
                    s = self.players[owner]; side = room.sides[owner]; teams[side].append(owner)
                    seats.append((owner,side,s.database,s.account,frozen,False))
                self.start_match(room,seats,teams,set(),lambda:self.wager_lobbies.consume(room))
                LOG.info('wager_battle_started match=%s room=%d humans=%d mode=%d',
                         room.match_id,room.identity,len(room.members),room.mode)
            except Exception as error:
                from .failure_policy import storage_failure
                if storage_failure(error): raise
                LOG.warning('wager_battle_start_failed match=%s room=%d error_type=%s',
                            room.match_id,room.identity,type(error).__name__)
                self.cancel_wager_start(room,'battle_start_failed')
                room.ready.clear()
                for owner in room.members: self.put(owner,encode_shop_error('Не удалось загрузить бой со ставкой'))
                self.wager_notify(room)

    def stop_wagers(self):
        for room in tuple(self.wager_lobbies.rooms.values()):
            self.cancel_wager_start(room,'server_stop_before_start')
