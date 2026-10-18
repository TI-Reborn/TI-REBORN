"""Shared team lobbies and one authoritative battlefield per paired teams.

All changes run under one lock; only each session's own thread writes its socket.
Account-local character and pet IDs are never used as shared identity keys.
"""
from collections import deque
from dataclasses import replace
import logging
import socket
import threading
import time
from tio.performance import timed,timed_lock
from uuid import uuid4

from tio.team_lobbies import TeamLobbies
from tio.matchmaking import SurvivalQueue
from tio.battle_modes import level_band
from tio.owned_pets import OwnedPetStore
from tio.protocol.arena import (decode_create_request, decode_room_ready, decode_room_start,
    decode_remove_request, BattleSettings, encode_battle_settings_body, ArenaRoom, encode_room_list, decode_room_list)
from tio.protocol.battle_members import BattleMemberRecord, encode_battle_members
from tio.protocol.system_message import (encode_shop_error, encode_leave_room,
    encode_finish_battle_view, encode_current_town, encode_open_town_view)
from tio.protocol.transport import encode_initial_frame
from tio.protocol.battle_turn import encode_turn_now, turn_seconds

LOG=logging.getLogger('tio.server')
# Native silver.dll's frame watchdog is reset by 9E, not TCP keepalive or
# ordinary turn packets. Quiet loading/turns must still service that watchdog.
TEAM_HEARTBEAT_SECONDS=10
TEAM_LEVEL_RANGES=((1,3),(4,6),(7,10),(11,15),(16,20))
from .battle_reconnect import BattleReconnect
from .battle_failures import BattleFailures,BattleSettlementError
from .failure_policy import storage_failure
from .ranked_arena import RankedArena
from .mine_arena import MineArena
from .assault_arena import AssaultArena
from .team_ranked import TeamRanked
from .wager_arena import WagerArena
from .tactical_marks import TacticalMarks
from .tutorial_arena import TutorialArena
from .training_arena import TrainingArena
from .contracts_combat import ContractsCombat


class _SharedTeamArena(ContractsCombat,TacticalMarks,WagerArena,AssaultArena,MineArena,RankedArena,TeamRanked,BattleReconnect,BattleFailures):
    def __init__(self, *, clock=time.monotonic):
        self.lock=threading.RLock();self.clock=clock
        self.lobbies=TeamLobbies(clock)
        self.players={};self.identities={};self.queues={};self.tickets={};self.battles={};self.results=set()
        self.next_id=0x10000000
        self.survival_queue=SurvivalQueue(clock=clock)
        self.survival_waiting=set()
        self.ranked_waiting={}
        self.init_wagers()
        self.init_mine_requests()
        self.wager_listing_cache={}
        self.arena_listing_cache={}
        self.lobby_auto_rosters={}
        self._init_reconnect()

    def identity(self, session):
        if session not in self.identities:
            self.next_id+=1
            self.identities[session]=self.next_id
            self.players[self.next_id]=session
            self.queues[self.next_id]=deque()
        return self.identities[session]

    def busy(self, session):
        with self.lock:
            owner=self.identities.get(session)
            return self.mine_waiting(owner) or owner in self.ranked_waiting or owner in self.survival_waiting or owner in self.battles or owner in self.results or self.lobbies.room(owner) is not None or self.wager_busy(owner) or self.assault_group(session) is not None

    def in_battle(self, session):
        with self.lock:
            return self.identities.get(session) in self.battles

    def chat(self,session,channel,text):
        from tio.protocol.chat import encode_message
        with self.lock:
            owner=self.identities.get(session);battle=self.battles.get(owner)
            if channel not in (3,4) or battle is None or battle['finished']:
                raise ValueError('Боевой чат доступен только в бою')
            if text.startswith('/'):raise ValueError('Команды чата пока не поддерживаются')
            now=self.clock();rate=battle.setdefault('chat_rate',{}).setdefault(owner,deque())
            while rate and rate[0]<now-5:rate.popleft()
            if len(rate)>=5:raise ValueError('Подождите перед следующим сообщением')
            rate.append(now)
            reply=encode_message(channel,session.probe_character_name,text)
            # Native 9FF60D already appends the sender's battle text locally.
            for target in battle['humans']:
                if target!=owner and (channel==3 or battle['field'].allied(owner,target)):
                    self.put(target,reply)
            LOG.info('battle_chat match=%s owner=%d channel=%d',battle['match_id'],owner,channel)

    def put(self, owner, *packets):
        if owner in self.offline:return
        q=self.queues.get(owner)
        if q is None:return
        if len(q)+len(packets)>2048:
            self.players[owner].stop()
            return
        q.extend(packets)

    def city(self, owner, levels=None):
        from tio.cities import CITIES,require_arena
        s=self.players[owner]
        if s.database is not None:
            from .world_runtime import require_unjailed
            require_unjailed(s)
        town=s.locations.current(s.account) if s.locations else 3
        if levels is None:
            city=CITIES.get(town)
            if city is None:raise ValueError('В этой локации обычные бои не проводятся')
            return city
        return require_arena(town,levels if s.locations else ())

    def roster(self, owner, mode, *, rows=None):
        session=self.players[owner]
        if rows is None:rows=OwnedPetStore(session.database).list(session.account)
        if mode==4:
            # Manual: only the first selected fighter is admitted to Wall.
            from tio.protocol.pet_info import decode_pet_info, encode_pet_info
            selected=[]
            for i,p,inv in rows:
                human=int.from_bytes(p[5:9],'little') in (1,2,6)
                pet=decode_pet_info(p,human_equipment=human)
                if pet.fields['0x8c44a6'] in (1,2,3):selected.append((pet.fields['0x8c44a6'],i,p,inv,human,pet))
            if not selected:raise ValueError('Выберите бойца в отряд')
            _,i,p,inv,human,pet=min(selected)
            rows=((i,encode_pet_info(replace(pet,fields={**pet.fields,'0x8c44a6':1})),inv),)
        ticket=SurvivalQueue(clock=self.clock).join(owner,rows,mode=mode)
        from tio.protocol.pet_info import decode_pet_info
        chosen={i:decode_pet_info(p,human_equipment=int.from_bytes(p[5:9],'little') in (1,2,6)).fields for i,p,_ in rows}
        for i in ticket.actors:
            pet=chosen[i];hp,maximum=pet['0x8c4ab1'],pet['0x8c4a07']
            if hp!=maximum:
                name=pet['0x8c4489'].decode('cp1251')[:40]
                raise ValueError(f'{name}: здоровье {hp}/{maximum}. Для команды нужен полностью здоровый боец. Вылечите его в казарме или дождитесь восстановления.')
        bands={level_band(l) for l in ticket.levels}
        if len(bands)!=1:raise ValueError('Бойцы должны быть одного уровневого диапазона')
        city=self.city(owner,ticket.levels)
        return replace(ticket,pool=city.pool),next(iter(bands)),rows

    def lobby_roster(self, owner, room, *, frozen=False):
        """Admit owned reserves without changing the account's saved selection."""
        from tio.protocol.pet_info import decode_pet_info,encode_pet_info
        if frozen and owner not in self.lobby_auto_rosters:
            return self.roster(owner,room.mode)
        rows=OwnedPetStore(self.players[owner].database).list(self.players[owner].account)
        admitted=self.lobby_auto_rosters.get(owner) if frozen else None
        if admitted is None:
            try:
                current=self.roster(owner,room.mode,rows=rows)
                if (current[1],len(current[0].actors))==(room.band,room.soldiers):return current
            except ValueError:
                pass
        candidates=[]
        low,high=TEAM_LEVEL_RANGES[room.band]
        for identity,packet,inventory in rows:
            human=int.from_bytes(packet[5:9],'little') in (1,2,6)
            pet=decode_pet_info(packet,human_equipment=human);fields=pet.fields
            if admitted is not None:
                if identity not in admitted:continue
                order=admitted.index(identity)
            else:
                if not low<=fields['0x8c4aef']<=high or fields['0x8c4ab1']!=fields['0x8c4a07']:continue
                slot=fields['0x8c44a6'];order=(slot if slot in (1,2,3) else 4,identity)
            candidates.append((order,identity,packet,inventory,human,pet))
        candidates.sort(key=lambda row:row[0])
        if len(candidates)<room.soldiers:
            raise ValueError(f'Для команды нужны {room.soldiers} полностью здоровых бойцов уровней {low}–{high}')
        projected=tuple((identity,encode_pet_info(replace(pet,fields={**pet.fields,'0x8c44a6':slot})),inventory)
            for slot,(_,identity,packet,inventory,human,pet) in enumerate(candidates[:room.soldiers],1))
        ticket,band,projected=self.roster(owner,room.mode,rows=projected)
        if band!=room.band:raise ValueError(f'Для команды нужны бойцы уровней {low}–{high}')
        return ticket,band,projected

    def member_records(self, room):
        """Common immutable projection, scoped to one notification under hub.lock."""
        from tio.arena_roster import room_soldiers
        records=[]
        for index,owner in enumerate(room.members):
            session=self.players[owner];ticket=self.tickets[owner]
            if owner in self.lobby_auto_rosters:
                rows=self.lobby_roster(owner,room,frozen=True)[2]
            else:
                rows=OwnedPetStore(session.database).list(session.account)
                rows=tuple(r for r in rows if r[0] in ticket.actors)
            records.append(BattleMemberRecord(owner,session.probe_character_name,0,
                bytes((max(ticket.levels),max(ticket.levels),index,0,int(owner in room.ready),1)),
                room_soldiers(rows,room.soldiers,path=session.database,account=session.account)))
        for index in range(room.bots):
            records.append(BattleMemberRecord(0x70000000+room.identity*4+index,b'AI bot '+str(index+1).encode(),0,
                bytes((1,1,len(records),0,1,1))))
        return tuple(records)

    def members(self, room, viewer, *, update=False, records=None):
        if records is None:records=self.member_records(room)
        own_id=self.players[viewer].probe_character_id
        return encode_battle_members(room.mode,int(update),
            (replace(record,character_id=own_id) if record.character_id==viewer else record
             for record in records))

    @timed('lobby.notify')
    def notify(self, room, *, entering=()):
        captain=self.players[room.captain]
        settings=BattleSettings(1,room.capacity,room.mode,turn_seconds(room.soldiers),2,
            captain.probe_character_name,bytes((*TEAM_LEVEL_RANGES[room.band],room.soldiers,0,0)),0,0)
        records=self.member_records(room)
        for owner in room.members:
            if owner in entering:self.put(owner,b'\x6c'+encode_battle_settings_body(settings))
            self.put(owner,self.members(room,owner,update=owner not in entering,records=records))

    def list_packet(self, owner, *, pool=None):
        # A supplied pool is an already checked city projection for this tick;
        # mutation/admission paths continue to resolve the owner's current city.
        if pool is None:pool=self.city(owner).pool
        records=[]
        for r in self.lobbies.rooms.values():
            if r.pool!=pool:continue
            name=self.players[r.captain].probe_character_name
            records.append(ArenaRoom(r.identity,0,r.mode,2 if r.searching else 0,0,
                len(r.members),r.capacity,name,0,*TEAM_LEVEL_RANGES[r.band],r.soldiers,0))
        records.extend(self.wager_rooms(owner,pool=pool))
        return encode_room_list(records)

    def remember_arena_listing(self, owner, packet):
        """BA02 is a merge; retain IDs to send native BA06 deletions."""
        snapshot=(packet,frozenset(r.unknown_u32_00 for r in decode_room_list(packet)))
        self.arena_listing_cache[owner]=snapshot
        return snapshot

    def battle_list_packet(self, owner, *, pool=None):
        """The main native table receives typed C8/2C, separate from BA/02."""
        from tio.protocol.wagers import WagerRoomRecord
        if pool is None:pool=self.city(owner).pool
        records=[]
        for room in self.lobbies.rooms.values():
            if room.pool!=pool:continue
            low,high=TEAM_LEVEL_RANGES[room.band]
            middle=(low+high)//2
            name=self.players[room.captain].probe_character_name
            records.append(WagerRoomRecord(room.identity,name,
                middle,room.mode,room.capacity,len(room.members),
                2 if room.searching else 0,room.soldiers,0,high-middle,0,0))
        return self.wager_list_packet(owner,extra=records,pool=pool)

    @timed('hub.handle')
    def handle(self, session, packet):
        with timed_lock(self.lock,'hub.handle_lock'):
            owner=self.identity(session)
            # A TCP read may contain exit-to-city followed by a keepalive.
            # Answer it even when the preceding packet just cleared busy().
            if packet==b'\x70':self.put(owner,b'\x9e');return True
            contracts = getattr(self, 'contracts_service', None)
            if contracts and owner not in self.battles and owner not in self.results and contracts.guard(session, packet):
                return True
            if self.handle_wager(owner,packet):
                if packet==b'\xba\x01':
                    try:self.remember_arena_listing(owner,self.list_packet(owner))
                    except ValueError:pass
                return True
            try:
                if self.handle_assault(owner,packet):return True
            except ValueError as error:
                self.put(owner,encode_shop_error(str(error)));return True
            if packet[:1]==b'\xb0' and session.database is not None:
                try:
                    if self.handle_mining(owner,packet):return True
                except ValueError as error:
                    self.put(owner,encode_shop_error(str(error)));return True
            if packet in (b'\xc6\x02',b'\xc6\x20') or packet[:1]==b'\xc6' and owner not in self.battles and owner not in self.results:
                return self.handle_ranked(owner,packet)
            if owner in self.ranked_waiting:
                self.put(owner,encode_shop_error('Отмените поиск рейтингового боя'));return True
            if (owner in self.survival_waiting or packet[:3]==b'\xba\x03\0') and owner not in self.battles and owner not in self.results:
                return self.handle_survival(owner,packet)
            active=self.busy(session)
            is_create=packet[:2]==b'\xc8\x2b' and len(packet)>=6 and int.from_bytes(packet[2:6],'little') in (1,4)
            is_ba_create=packet[:2]==b'\xba\x03' and len(packet)==4 and packet[2] in (1,4)
            is_join=packet[:1]==b'\x29' or packet[:2]==b'\xba\x04'
            treatment=packet[:1]==b'\x7c' and (owner in self.results or
                owner not in self.battles and (not active or self.assault_group(session) is not None)
                and getattr(session,'_battle_treatment_ids',None) is not None)
            if not active and not (treatment or is_create or is_ba_create or is_join or packet==b'\xba\x01'):return False
            try:
                if treatment:
                    self.treat_result(owner,packet)
                    return True
                if owner in self.results:
                    if packet==b'\x2a\x01':self.to_city(owner)
                    elif packet==b'\x36' and owner in self.returning:
                        self.returning.pop(owner,None)
                        self.put(owner,*self.completed[owner]['result_packets'][owner])
                    return True
                if owner in self.battles:
                    if self.battles[owner].get('faulted'):
                        self.put(owner,encode_shop_error('Бой остановлен. Сохраняется результат.'))
                        return True
                    self.battle_action(owner,packet)
                    return True
                if packet==b'\xba\x01':
                    listing=self.list_packet(owner)
                    self.put(owner,listing,self.battle_list_packet(owner))
                    self.remember_arena_listing(owner,listing)
                    return True
                if is_create or is_ba_create or is_join:
                    self.city(owner)
                    if session.survival.searching(session.probe_character_id) or any(session.probe_character_id in r.members for r in session.arena.rooms.snapshot()):
                        raise ValueError('Сначала выйдите из текущего боя или поиска')
                    if is_create:
                        req=decode_create_request(packet)
                        if req.stake:raise ValueError('Бои со ставками пока недоступны')
                        mode=req.mode
                    elif is_ba_create:mode=packet[2]
                    else:
                        if packet[:1]==b'\x29':
                            from tio.protocol.wagers import decode_join
                            identity=decode_join(packet)
                        else:
                            if len(packet)!=6:raise ValueError('Некорректный вход в команду')
                            identity=int.from_bytes(packet[2:6],'little')
                        target=self.lobbies.rooms.get(identity)
                        if target is None:raise ValueError('Команда закрыта')
                        if target.searching:raise ValueError('Команда занята: уже ищет бой')
                        if len(target.members)>=target.capacity and owner not in target.members:raise ValueError('Команда заполнена')
                        mode=target.mode
                    ticket,band,rows=self.lobby_roster(owner,target) if is_join else self.roster(owner,mode)
                    if is_create and mode==1 and req.soldiers_count_01!=len(ticket.actors):raise ValueError('Число бойцов не совпадает с отрядом')
                    room=self.lobbies.create(owner,mode,band,len(ticket.actors),pool=ticket.pool) if is_create or is_ba_create else self.lobbies.join(target.identity,owner,band,len(ticket.actors),pool=ticket.pool)
                    self.tickets[owner]=ticket
                    if is_join:
                        self.lobby_auto_rosters[owner]=ticket.actors
                    self.notify(room,entering=(owner,))
                    LOG.info('team_lobby_joined account=%s room=%d mode=%d',session.account,room.identity,mode)
                elif packet[:1]==b'\x2c' or packet[:2]==b'\xba\x07':
                    ready=decode_room_ready(packet if packet[:1]==b'\x2c' else b'\x2c'+packet[2:])
                    room=self.lobbies.set_ready(owner,ready);self.notify(room)
                elif packet[:1]==b'\x2e':
                    room=self.lobbies.room(owner)
                    if room is None or room.captain!=owner:raise ValueError('Начать поиск может только капитан')
                    decode_room_start(packet,mode=room.mode)
                    # Revalidate frozen squads before admission to the queue.
                    for member in room.members:
                        current,band,_=self.lobby_roster(member,room,frozen=True)
                        old=self.tickets[member]
                        if (current.actors,current.levels)!=(old.actors,old.levels):raise ValueError('Состав отряда изменился; пересоздайте команду')
                    # Native captain has Start instead of a separate Ready button.
                    self.lobbies.set_ready(owner,True)
                    room=self.lobbies.start(owner);self.notify(room)
                    LOG.info('team_search_started room=%d humans=%d bots=%d mode=%d band=%d soldiers=%d',
                             room.identity,len(room.members),room.bots,room.mode,room.band,room.soldiers)
                    self.match()
                elif packet==b'\x2a\x01':self.leave(owner)
                elif packet[:1]==b'\x2b':
                    from tio.protocol.wagers import decode_kick
                    target=decode_kick(packet)
                    self.leave(owner,owner if target==session.probe_character_id else target)
                elif packet[:2]==b'\xba\x05':
                    removal=decode_remove_request(packet)
                    target=owner if removal.character_id==session.probe_character_id else removal.character_id
                    if not removal.kick and target!=owner:raise ValueError('Можно выйти только из своей команды')
                    self.leave(owner,target)
                else:raise ValueError('Сначала покиньте команду, чтобы изменять отряд или снаряжение')
            except ValueError as exc:
                if owner in self.battles:
                    failed=self.battles[owner]
                    manager=getattr(self,'journal',None)
                    if manager is None:
                        self.put(owner,*failed['field'].combat.cancel_equipment_batch(owner))
                    else:
                        with manager.unit(failed):
                            self.put(owner,*failed['field'].combat.cancel_equipment_batch(owner))
                self.put(owner,encode_shop_error(str(exc)[:180]))
                if owner in self.battles:
                    battle=self.battles[owner]
                    if packet[:2]==b'\xc8\x3d':
                        self.put(owner,*battle['arena'].rejected_mine_packets(owner,packet))
                    if packet[:1]==b'\x6e':
                        from tio.battle_exchange import refresh
                        battle['field'].combat.exchange_sessions.pop(owner,None)
                        ids=tuple(int.from_bytes(packet[i:i+4],'little') for i in (1,5) if len(packet)>=i+4)
                        self.put(owner,*refresh(battle['field'].combat,owner,ids))
                    if packet[:1] in (b'\x3c',b'\x3e',b'\x81'):
                        from tio.battle_rejection import restore_actor
                        self.put(owner,*restore_actor(battle['field'],owner,packet))
                    if packet[:1]==b'\x3e' and len(packet)==8 and packet[5] in (0,1):
                        from tio.protocol.battle_door import decode_door_request,encode_door_state
                        request=decode_door_request(packet)
                        doors=getattr(battle['field'],'doors',None)
                        if doors is not None and (request.x,request.y) in doors.states:
                            actor=battle['field']._actors.get(request.actor_id)
                            if actor is not None and actor.owner_id==owner:
                                self.put(owner,encode_door_state(replace(request,opened=doors.states[request.x,request.y])))
                    turn=battle['arena']._turns.get(battle['room'].room_id)
                    if turn is not None and turn[0]!=owner:
                        self.put(owner,b'\x39',encode_turn_now(turn[0],max(0,int(turn[2]-self.clock()))))
                LOG.info('team_request_rejected account=%s opcode=%s reason=%s',session.account,packet[:1].hex(),exc)
            except Exception as error:
                if storage_failure(error):raise
                battle=self.battles.get(owner)
                if battle is not None:self.quarantine(battle,error)
                else:
                    LOG.error('team_session_failed account=%s error_type=%s',session.account,type(error).__name__,
                              exc_info=(type(error),error,error.__traceback__))
                    session.stop()
            return True

    def handle_survival(self, owner, packet):
        session=self.players[owner];character=session.probe_character_id
        service=session.survival
        try:
            if packet==b'\x70':self.put(owner,b'\x9e');return True
            if packet[:2]==b'\xba\x03':
                if packet[:3]!=b'\xba\x03\0':raise ValueError('Cancel the existing search first')
                if self.lobbies.room(owner) is not None or any(character in r.members for r in session.arena.rooms.snapshot()):
                    raise ValueError('Leave the current room first')
                self.city(owner)
                ticket,band,rows=self.roster(owner,0)
                reply=service.join(character,session.probe_character_name,packet,rows)
                self.survival_queue.join(owner,rows,pool=ticket.pool)
                self.survival_waiting.add(owner);self.put(owner,reply)
            elif packet[:2]==b'\xba\x07':
                if packet==b'\xba\x07\1':ticket,_,rows=self.roster(owner,0)
                reply=service.set_ready(character,packet)
                if packet[2]:self.survival_queue.join(owner,rows,pool=ticket.pool)
                else:self.survival_queue.cancel(owner)
                self.put(owner,reply)
            elif packet[:2]==b'\xba\x05':
                reply=service.cancel(character,packet)
                self.survival_queue.cancel(owner);self.survival_waiting.discard(owner)
                self.put(owner,reply)
            else:raise ValueError('Cancel the search before changing squad or equipment')
            self.match_survival(owner)
        except ValueError as exc:
            self.put(owner,encode_shop_error(str(exc)[:180]))
            LOG.info('survival_request_rejected account=%s reason=%s',session.account,exc)
        return True

    def match_survival(self, owner):
        from types import SimpleNamespace
        proposal=self.survival_queue.propose(owner)
        if proposal is None:return
        tickets=proposal.members
        from tio.character_identity import auth_account
        accounts={(str(self.players[t.character_id].database),
                   auth_account(self.players[t.character_id].database,self.players[t.character_id].account))
                  for t in tickets}
        if len(accounts)!=len(tickets):raise ValueError('Для Выживания нужны разные аккаунты')
        count=min(len(t.actors) for t in tickets)
        seats=[];teams=[]
        for side,ticket in enumerate(tickets):
            member=ticket.character_id;session=self.players[member]
            chosen=replace(ticket,actors=ticket.actors[:count],levels=ticket.levels[:count])
            seats.append((member,side,session.database,session.account,chosen,False))
            teams.append([member])
        first=SimpleNamespace(mode=0,soldiers=count,band=level_band(tickets[0].levels[0]),captain=tickets[0].character_id)
        def consume():
            self.survival_queue.consume(proposal)
            for ticket in tickets:
                member=ticket.character_id;session=self.players[member]
                self.survival_waiting.discard(member)
                session.survival.disconnected(session.probe_character_id)
        bots=set()
        if proposal.uses_bot:
            # Native owner-eliminated compares a sign-extended member ID with
            # an unsigned actor owner. IDs >= 2**31 always look eliminated.
            bot=0x60000000+(owner & 0x0fffffff)
            if bot in self.players or any(bot in b['room'].members for b in self.battles.values()):
                raise ValueError('Reserved bot owner collision')
            session=self.players[owner]
            seats.append((bot,1,session.database,session.account,tickets[0],True))
            teams.append([bot]);bots.add(bot)
        self.start_match(first,seats,teams,bots,consume)

    def leave(self, owner, target=None):
        affected=self.lobbies.leave(owner,target)
        for member in affected:
            room=self.lobbies.room(member)
            if room is None:
                self.lobby_auto_rosters.pop(member,None)
                self.tickets.pop(member,None);self.put(member,encode_leave_room())
        remaining={r.identity:r for member in affected if (r:=self.lobbies.room(member)) is not None}
        # Native25 merges slots even with flag0; absent members are not erased.
        # Native27 removes the public member ID already shown to each survivor.
        departed=tuple(member for member in affected if self.lobbies.room(member) is None)
        for room in remaining.values():
            for member in room.members:
                for removed in departed:self.put(member,b'\x27'+removed.to_bytes(4,'little'))
            self.notify(room)

    def match(self):
        for first,second in self.lobbies.pairs():
            count=min(first.soldiers,second.soldiers)
            teams=[];bots=set();seats=[]
            for side,room in enumerate((first,second)):
                for member in room.members:
                    current,band,_=self.lobby_roster(member,room,frozen=True)
                    old=self.tickets[member]
                    if (current.actors,current.levels,current.pool)!=(old.actors,old.levels,old.pool):
                        raise ValueError('Состав отряда изменился; пересоздайте команду')
                owners=list(room.members)
                for index in range(room.bots):
                    bot=0x70000000+room.identity*4+index;owners.append(bot);bots.add(bot)
                teams.append(owners)
                for owner in owners:
                    source=self.players[room.captain if owner in bots else owner]
                    ticket=self.tickets[room.captain if owner in bots else owner]
                    ticket=replace(ticket,actors=ticket.actors[:count],levels=ticket.levels[:count])
                    seats.append((owner,side,source.database,source.account,ticket,owner in bots))
            def consume():
                self.lobbies.consume(first,second)
                for room in (first,second):
                    for member in room.members:self.lobby_auto_rosters.pop(member,None)
            self.start_match(replace(first,soldiers=count),seats,teams,bots,consume)
            LOG.info('team_pair_admitted rooms=%s mode=%d band=%d selected=%s admitted=%d',
                     (first.identity,second.identity),first.mode,first.band,(first.soldiers,second.soldiers),count)

    def start_match(self, first, seats, teams, bots, consume):
        from tio.team_scene import prepare
        from tio.arena_service import ArenaService
        from tio.protocol.arena import ArenaCreateRequest
        from tio.protocol.known_mines import encode_known_mines
        from tio.cities import require_arena
        cities=[]
        for owner,side,path,account,ticket,bot in seats:
            if bot:continue
            s=self.players[owner];town=s.locations.current(s.account) if s.locations else 3
            cities.append((ticket.joined_at,owner,town,require_arena(town,ticket.levels if s.locations else ())))
        if len({city.pool for _,_,_,city in cities})!=1:raise ValueError('Города несовместимы для боя')
        _,_,town,city=min(cities,key=lambda row:row[:2])
        wagering=getattr(first,'wager',False)
        wager_request=first.request if wagering else None
        field,views,ground,skills=prepare(seats,0 if first.mode==21 else first.mode,ranked=first.mode==21,profile=city.profile,
            wager=wagering,selected_ids=wagering or any(owner in self.lobby_auto_rosters for owner,side,path,account,ticket,bot in seats),
            map_size=wager_request.map_size if wagering else None,town_id=town)
        field.combat.wager=wagering
        field.scene_metadata['town_id']=town
        field.combat.city_kill_bonus=city.kill_bonus
        order=tuple(v for pair in zip(*teams) for v in pair)
        arena=ArenaService(clock=self.clock)
        from tio.rating_completion import ranked_turn_seconds
        duration=ranked_turn_seconds(first.soldiers) if first.mode==21 else turn_seconds(first.soldiers)
        request=ArenaCreateRequest(first.mode,0,len(order),2,wager_request.unknown_u32_01 if wagering else duration,first.soldiers,first.soldiers,first.band,0)
        room=arena.rooms.create(order[0],request)
        for member in order[1:]:room=arena.rooms.join(room.room_id,member)
        arena._fields[room.room_id]=field;arena._loading[room.room_id]=set(bots)
        battle=dict(arena=arena,room=room,field=field,views=views,bots=bots,city_id=town,
                    humans=set(views),match_id=first.match_id if wagering else str(uuid4()),settled=set(),deadline=self.clock()+60,finished=False)
        if wagering:
            from tio.db_transaction import transaction
            from tio.wagers import transition
            with transaction(seats[0][2]) as db:transition(db,battle['match_id'],'loading')
            battle.update(kind='wager',wager_request=wager_request,wager_active=False)
        battle.update(ground=ground,captain_name=self.players[first.captain].probe_character_name,
            names={m:b'AI bot' if m in bots else self.players[m].probe_character_name for m in order},result_packets={})
        # Frozen real-account participants survive disconnects and actor removal.
        battle['reward_roster']={owner:(account,tuple(ticket.levels),side)
                                for owner,side,path,account,ticket,bot in seats if not bot}
        # Freeze bot strength/side separately: bots have no persistent account
        # and must never enter human repeat-pair or ranking rosters.
        battle['reward_bot_roster']={owner:(tuple(ticket.levels),side)
                                    for owner,side,path,account,ticket,bot in seats
                                    if bot and first.mode in (0,1,4) and not wagering}
        battle['reward_damage']=set()
        battle['reward_support']=set()
        battle['reward_started']=False
        if not wagering:self.freeze_team_rating(battle,seats,teams,first)
        if first.mode==21:
            if bots or len(seats)!=2:raise ValueError('Ranked matches require two real accounts')
            from tio.control_points import ControlPoints
            # Find open cells in the same connected component as both spawns.
            free={(x,y) for x in range(field.width) for y in range(field.height) if (x,y) not in field.blocked}
            from collections import deque
            pending=deque([(field.actor(field.actor_ids(order[0])[0]).x,field.actor(field.actor_ids(order[0])[0]).y)])
            reached=set(pending)
            while pending:
                x,y=pending.popleft()
                for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if p in free and p not in reached:reached.add(p);pending.append(p)
            positions=[]
            spawns={(a.x,a.y) for a in field._actors.values()}
            broad={p for p in reached-spawns if all(q in reached for q in ((p[0]-1,p[1]),(p[0]+1,p[1]),(p[0],p[1]-1),(p[0],p[1]+1)))}
            for team in teams:
                a=field.actor(field.actor_ids(team[0])[0])
                positions.append(min(broad-set(positions),key=lambda p:(abs(p[0]-a.x)+abs(p[1]-a.y),p)))
            middle=min(broad-set(positions),key=lambda p:((p[0]-field.width//2)**2+(p[1]-field.height//2)**2,p))
            authored=field.scene_metadata.get('control_points')
            battle['points']=ControlPoints(tuple(map(tuple,authored)) if authored else tuple((*positions,middle)),[0,1,None],[0,0])
            # Original flag fragments contain a class2 occupied cell. Keep
            # movement collision and transparent sight in sync with the client.
            field.blocked|=frozenset(battle['points'].positions)
            if field.transparent_obstacles is not None:field.transparent_obstacles|=frozenset(battle['points'].positions)
            from tio.protocol.battle_ground import decode_battle_ground,encode_battle_ground,GroundEntry
            mapped=decode_battle_ground(ground)
            if not authored:
                ground=encode_battle_ground(replace(mapped,entries=(*mapped.entries,
                    *(GroundEntry(b'trueskill_checkpoint_base',x,y) for x,y in battle['points'].positions))))
            battle['ground']=ground
            field.battle_mode=21
            from tio import ranked
            battle['ranked_teams']=tuple(tuple((self.players[o].account,*ranked.snapshot(self.players[o].database,self.players[o].account)) for o in team) for team in teams)
        battle['return_towns']={o:(self.players[o].locations.current(self.players[o].account) if self.players[o].locations else 3) for o in views}
        consume()
        for owner in views:
            self.battles[owner]=battle
            self.account_owners[self.players[owner].account]=owner
            s=self.players[owner];view=views[owner]
            s._battle_treatment_ids=None
            settings=BattleSettings(1,len(order),first.mode,request.unknown_u32_01,2,
                self.players[first.captain].probe_character_name,
                bytes((max(1,first.creator_level-wager_request.level_range_index),min(20,first.creator_level+wager_request.level_range_index),first.soldiers,wager_request.map_size,0)) if wagering else bytes((0,0,first.soldiers,0,0)),
                wager_request.stake if wagering else 0,0)
            records=tuple(BattleMemberRecord(s.probe_character_id if m==owner else m,
                b'AI bot' if m in bots else self.players[m].probe_character_name,0,
                bytes((1,1,i,field.teams[m],1,1))) for i,m in enumerate(order))
            if first.mode==21:
                from tio.protocol.ranked import encode_accepted
                from tio.protocol.pet_info import decode_pet_info
                from tio.ranked import skill
                lineup=[[(o,tuple((int.from_bytes(field.combat.proficiencies[i][5:9],'little'),decode_pet_info(field.combat.proficiencies[i],human_equipment=field.combat.human[i]).fields['0x8c4bbc']) for i in field.actor_ids(o))) for o in team] for team in teams]
                ratings={o:skill(*ranked.snapshot(self.players[o].database,self.players[o].account)) for o in order}
                self.put(owner,encode_accepted(room.room_id,lineup,battle['names'],ratings),b'\xc6\x05')
            self.put(owner,b'\x6c'+encode_battle_settings_body(settings),encode_battle_members(first.mode,0,records),
                self.battle_order_packet(battle,owner),ground)
            self.put(owner,*view.refresh(),*(skills[i] for i in field.actor_ids(owner) if i in skills),
                     *(field.combat.inventory_packet(i) for i in field.actor_ids(owner)),*field.combat.hazard_packets(owner),*self.ranked_packets(battle,owner,scene=True),b'\x41')
            self.put(owner,*self.team_rating_announcements(battle,owner))
        LOG.info('team_match_created id=%s humans=%d bots=%d',battle['match_id'],len(views),len(bots))

    def snapshot(self, battle):
        # Membership changes only; ordinary actions use native event packets.
        for owner in battle['humans']:
            if self.battles.get(owner) is not battle:continue
            view=battle['views'][owner]
            self.put(owner,*view.refresh())
            if getattr(battle['field'].combat,'mines',None):self.put(owner,*battle['field'].combat.hazard_packets(owner))
        if 'points' in battle:self.ranked_refresh(battle)
        if battle.get('kind')=='mine':self.mine_lift_refresh(battle)
        if battle.get('kind')=='assault':self.assault_refresh(battle)

    def announce_turn(self,battle,owner,seconds):
        if 'points' in battle:
            from tio.protocol.ranked import encode_turn
            actor=battle['field'].living_actor_ids(owner)[0]
            for target in battle['humans']:
                identity=self.players[target].probe_character_id if target==owner else owner
                self.put(target,encode_turn(battle['field'].teams[owner],identity,actor))
        for target in battle['humans']:
            if target!=owner and self.battles.get(target) is battle:self.put(target,encode_turn_now(owner,seconds))

    def perform_action(self,battle,owner,packet):
        from tio.visibility import VisibilityView,visible_actors
        from .battle_events import project_action
        arena=battle['arena'];field=battle['field']
        methods={0x3a:arena.end_turn,0x3c:arena.move,0x3e:arena.door_action,0x49:arena.attack,
                 0x81:arena.cast_ability,0x6d:arena.swap_weapons,0x46:arena.loot_action,
                 0x40:arena.loot_action,0x6e:arena.exchange_action,0x33:arena.equip,0x7e:arena.repair,0xc2:arena.repair,
                 0xf6:arena.equipment_batch}
        method=arena.mine_action if packet[:2]==b'\xc8\x3d' else methods.get(packet[0])
        if method is None:raise ValueError('Действие недоступно в командном бою')
        before=dict(field._actors)
        hazard_damage=dict(field.combat.hazard_damage)
        mines=dict(getattr(field.combat,'mines',{}))
        known={target:view.visible for target,view in battle['views'].items()}
        # Service methods may refresh their view. Keep all recipient views intact
        # until projection; use an action-local view for templates and skill UI.
        source=battle['views'].get(owner) or next(iter(battle['views'].values()))
        action_view=VisibilityView(field,owner,dict(source.templates))
        action_view.visible=visible_actors(field,owner)
        result=method(owner,packet) if packet[0] in (0x3a,0x3c) else method(owner,packet,view=action_view)
        if packet[0]==0xf6 and (len(packet)<3 or packet[2]!=1):
            # Stage/cancel replies carry private previews, never authoritative
            # templates, actor equipment, fog or another account's inventory.
            self.put(owner,*result)
            return result
        eligible=battle['reward_roster'].keys() | battle.get('reward_bot_roster',{}).keys()
        if owner in eligible:
            for identity,previous in before.items():
                current=field._actors.get(identity)
                if current is None or previous.health is None or previous.owner_id not in eligible:continue
                if packet[0] in (0x49,0x81) and current.health<previous.health and not field.allied(owner,previous.owner_id):
                    battle['reward_damage'].add(owner)
                if current.health>previous.health and owner!=previous.owner_id and field.allied(owner,previous.owner_id):
                    battle['reward_support'].add((owner,previous.owner_id))
        packets=(result,) if isinstance(result,bytes) else tuple(result or ())
        if packet[0]==0x3a:packets=arena.finished_turn_packets(owner,result)
        from tio.durability import refresh_template
        for reply in packets:
            identity=int.from_bytes(reply[1:5],'little')
            if reply[0]==0x30 and identity in field.combat.inventories:
                refresh_template(field.combat,action_view,identity)
        described={int.from_bytes(p[1:5],'little') for p in packets if p[0]==0x3b}
        changed=tuple(i for i in field._actors if i in action_view.visible and action_view.templates[i]!=source.templates[i] and i not in described)
        packets+=tuple(p for i in changed for p in action_view.snapshot_packets(i))
        for view in battle['views'].values():
            for i in field._actors:view.templates[i]=action_view.templates[i]
        for target in battle['humans']:
            if self.battles.get(target) is battle:
                self.put(target,*project_action(battle['views'][target],owner,before,known[target],packets))
                if mines!=field.combat.mines:self.put(target,*field.combat.hazard_packets(target))
        self.hazard_activity(battle,hazard_damage)
        if 'points' in battle and packet[0]!=0x3a:
            if packet[0]==0x3c:
                from dataclasses import replace
                from tio.protocol.battle_move import decode_battle_move
                for reply in packets:
                    if reply[:1]!=b'\x3d':continue
                    move=decode_battle_move(reply);actor=field.actor(move.actor_id)
                    for x,y in move.path:
                        field._actors[actor.actor_id]=replace(actor,x=x,y=y)
                        battle['points'].capture(field)
                    field._actors[actor.actor_id]=actor
            battle['points'].capture(field);self.ranked_refresh(battle)
        if packet[0]==0x3a:
            LOG.info('team_turn_skipped match=%s owner=%d actor=%d',battle['match_id'],owner,int.from_bytes(packet[1:5],'little'))
        elif packet[0]==0x6e:
            LOG.info('battle_exchange match=%s owner=%d actor=%d target=%d confirmation=%s',battle['match_id'],owner,
                     int.from_bytes(packet[1:5],'little'),int.from_bytes(packet[5:9],'little'),len(packet)>17)
        if battle.get('kind')=='assault' and packet[0]!=0x3a:
            battle['assault_points'].capture(field);self.assault_refresh(battle)
        return result

    def hazard_activity(self,battle,before_damage):
        # A trap explodes in the opponent's turn, and a burn ticks in its
        # victim's turn. Attribute activity to the authoritative source owner.
        field=battle['field'];roster=battle['reward_roster'].keys() | battle.get('reward_bot_roster',{}).keys()
        for (owner,victim),damage in field.combat.hazard_damage.items():
            if (owner in roster and victim in roster and not field.allied(owner,victim)
                    and damage>before_damage.get((owner,victim),0)):
                battle['reward_damage'].add(owner)

    def begin_shared_turn(self,battle,owner,seconds,*,actor_ids=None):
        from .battle_events import project_action
        arena=battle['arena'];field=battle['field']
        before=dict(field._actors)
        known={target:view.visible for target,view in battle['views'].items()}
        hazard_damage=dict(field.combat.hazard_damage)
        actors=field.living_actor_ids(owner) if actor_ids is None else actor_ids
        packets=arena.begin_turn_packets(owner,actors,seconds)
        from tio.durability import refresh_template
        changed={int.from_bytes(p[1:5],'little') for p in packets if p[0]==0x30}
        snapshots=[]
        for identity in sorted(changed):
            described=False
            for view in battle['views'].values():
                previous=view.templates[identity]
                refresh_template(field.combat,view,identity)
                if view.templates[identity]!=previous and not described:
                    snapshots.extend(view.snapshot_packets(identity))
                    described=True
        packets+=tuple(snapshots)
        self.hazard_activity(battle,hazard_damage)
        for target in battle['humans']:
            if self.battles.get(target) is battle:
                self.put(target,*project_action(battle['views'][target],owner,before,known[target],packets))
        self.finish_exhausted_turn(battle)
        return packets

    def finish_exhausted_turn(self,battle):
        arena=battle['arena'];field=battle['field'];room=battle['room']
        turn=arena._turns.get(room.room_id)
        if turn is not None and not any(field.actor(i).action_points>0 for i in field.living_actor_ids(turn[0])):
            self.fence_finished_turn(battle,turn[0])
            del arena._turns[room.room_id];arena._last_turn[room.room_id]=turn[0]
            self.put(turn[0],*arena.finished_turn_packets(turn[0]))
            LOG.info('team_turn_exhausted match=%s owner=%d',battle['match_id'],turn[0])

    @timed('hub.tick_core')
    def tick(self):
        with self.lock:
            self.expire_reconnects()
            self.tick_assault_events()
            self.tick_wagers()
            # Original main-room window expects server-pushed C82C data.
            # Publish only changed lists to idle city sessions, never to a
            # battle HUD or another city's matchmaking pool.
            listings={}
            for owner,s in tuple(self.players.items()):
                if owner in self.offline or self.busy(s):continue
                try:pool=self.city(owner).pool
                except ValueError:continue
                if pool not in listings:
                    try:listing=self.battle_list_packet(owner,pool=pool)
                    except ValueError:continue
                    try:arena_listing=self.list_packet(owner,pool=pool)
                    except ValueError:arena_listing=None
                    listings[pool]=(listing,arena_listing)
                listing,arena_listing=listings[pool]
                previous=self.arena_listing_cache.get(owner)
                if arena_listing is not None and (previous is None or previous[0]!=arena_listing):
                    current_ids=frozenset(r.unknown_u32_00 for r in decode_room_list(arena_listing))
                    deleted=() if previous is None else sorted(previous[1]-current_ids)
                    self.put(owner,*(b'\xba\x06'+identity.to_bytes(4,'little') for identity in deleted),arena_listing)
                    self.remember_arena_listing(owner,arena_listing)
                if self.wager_listing_cache.get(owner)!=listing:
                    self.put(owner,listing);self.wager_listing_cache[owner]=listing
            for owner in tuple(self.survival_queue.tickets):
                if owner not in self.survival_queue.tickets:continue
                try:self.match_survival(owner)
                except ValueError as error:
                    self.put(owner,encode_shop_error(str(error)[:180]))
            for battle in {id(b):b for b in self.battles.values()}.values():
                try:
                    if battle.get('faulted'):self.retry_quarantined(battle)
                    else:
                        self.tick_battle(battle)
                        if battle.get('kind')=='mine' and not battle['finished']:self.try_mine_requests(battle)
                except Exception as error:
                    if storage_failure(error):raise
                    self.quarantine(battle,error)

    def tick_battle(self,battle):
        self.expire_tactical_marks(battle)
        if battle.get('kind')=='mine':return self.tick_mine(battle)
        if battle.get('kind')=='assault':return self.tick_assault(battle)
        arena=battle['arena'];room=battle['room'];field=battle['field']
        if battle['finished']:return
        if battle.get('kind')=='wager' and battle.get('wager_report',{}).get('refund_reason'):
            self.abort_wager(battle,battle['wager_report']['refund_reason']);return
        if len(field.living_sides())<=1:
            self.finish(battle);return
        points=battle.get('points')
        if points is not None and points.outcome(field) is not None:
            self.finish(battle);return
        if arena._loading[room.room_id]!=set(room.members):
            if self.clock()>battle['deadline']:
                if battle.get('kind') == 'contract':
                    self.abort_contract(battle, 'loading_timeout'); return
                if battle.get('kind')=='wager':
                    self.abort_wager(battle,'loading_timeout');return
                self.cancel_team_rating(battle,'loading_timeout')
                for owner in tuple(battle['humans']):
                    self.battles.pop(owner,None);self.to_city(owner)
                LOG.warning('team_match_loading_timeout id=%s',battle['match_id'])
            return
        for owner,packet in arena.expire_turns():
            self.fence_finished_turn(battle,owner)
            self.put(owner,*arena.finished_turn_packets(owner,packet))
            LOG.info('team_turn_expired match=%s owner=%d',battle['match_id'],owner)
        battle['reward_started']=True
        if battle.get('kind')=='wager' and not battle.get('wager_active'):
            from tio.db_transaction import transaction
            from tio.wagers import transition
            with transaction(next(self.players[o].database for o in battle['humans'])) as db:
                transition(db,battle['match_id'],'active')
            battle['wager_active']=True
        self.finish_exhausted_turn(battle)
        if room.room_id in arena._turns:return
        if points is not None and battle.pop('point_turn_pending',False):
            points.advance(field);self.ranked_refresh(battle)
            if points.outcome(field) is not None:self.finish(battle);return
        arena._last_turn.setdefault(room.room_id,room.members[-1])
        owner=arena.next_turn_owner(room.room_id)
        if owner in battle['bots']:
            from tio.training_bot import play_turn
            from .battle_events import BotEventArena
            self.announce_turn(battle,owner,40)
            play_turn(BotEventArena(self,battle),room.room_id,owner)
        else:
            from tio.rating_completion import ranked_turn_seconds
            seconds=(battle['wager_request'].unknown_u32_01 if battle.get('kind')=='wager'
                     else ranked_turn_seconds(len(field.living_actor_ids(owner))) if points is not None
                     else turn_seconds(len(field.living_actor_ids(owner))))
            battle['full_turn']=(owner,self.clock()+seconds)
            if owner in self.offline:seconds//=2
            self.announce_turn(battle,owner,seconds)
            self.begin_shared_turn(battle,owner,seconds)
            if points is not None:battle['point_turn_pending']=True
            LOG.info('team_turn_started match=%s account=%s owner=%d actors=%s',
                     battle['match_id'],self.players[owner].account,owner,field.living_actor_ids(owner))

    def battle_action(self, owner, packet):
        from tio.protocol.item_list import decode_item_list_request
        battle=self.battles[owner];arena=battle['arena'];room=battle['room'];view=battle['views'][owner]
        if packet==b'\x36':
            arena.member_loaded(owner,packet)
            from tio.protocol.battle_loaded import encode_member_loaded
            for target in battle['humans']:
                self.put(target,*(encode_member_loaded(self.players[target].probe_character_id if m==target else m)
                                  for m in arena._loading[room.room_id]))
            if owner in self.returning:
                self.returning.pop(owner,None);self.restore_turn(battle,owner)
            return
        if packet==b'\x2a\x01':
            if battle.get('kind') == 'contract':
                self.abort_contract(battle, 'participant_left'); return
            if battle.get('kind')=='wager' and not battle.get('wager_active'):
                self.abort_wager(battle,'participant_left_loading');return
            if battle.get('kind')=='mine' and self.mine_exit_position(battle,owner):
                mine=battle['field'].mining;amount=mine.exit(owner)
                if amount>0:self.complete_mine_mission(battle,owner);return
                successful=amount>0
                if mine.roles[owner]==3:
                    miner_name=battle['mine_pairs'][owner][0]
                    successful=successful or any(r[0]==miner_name and (mine.extracted_amounts.get(o) or 0)>0
                                                 for o,r in battle['reward_roster'].items())
                self.complete_mine_owner(battle,owner,int(successful));return
            if 'points' in battle:battle['ranked_winner']=1-battle['field'].teams[owner]
            self.settle(battle,owner,0,escaped=True)
            self.remove_from_battle(battle,owner);self.to_city(owner);return
        # Read-only skill bar request; the client also sends it while reloading.
        if packet[:2]==b'\xc8\x12':
            self.put(owner,*(arena.skill_list_packets(owner,packet) or ()));return
        if owner in self.returning:raise ValueError('Дождитесь загрузки боя')
        if battle.get('kind')=='mine' and self.mine_call_help(battle,owner,packet):return
        if self.handle_tactical_mark(owner,packet):return
        # The old waiting widget can emit this during scene transition.
        if packet[:2]==b'\xba\x05':return
        if packet[:1]==b'\x2f':
            self.put(owner,*arena.inventory_packets(owner,decode_item_list_request(packet)));return
        if packet[:1]==b'\x3a':
            from tio.protocol.battle_turn import decode_end_turn
            decode_end_turn(packet)
            # Legacy EndTurn has no turn sequence. A second UI/transport send
            # can arrive after a fast bot turn and otherwise finish the NEXT
            # human turn. Ignore only the bounded tail of a completed turn;
            # never echo TurnFinished into the newly active turn.
            if 0<battle.get('end_turn_fences',{}).get(owner,0)-self.clock()<=1.0:
                LOG.info('team_turn_repeat_ignored match=%s owner=%d',battle['match_id'],owner)
                return
        self.perform_action(battle,owner,packet)
        if packet[:1]==b'\x3a':self.fence_finished_turn(battle,owner)
        self.finish_exhausted_turn(battle)
        if battle.get('kind')=='mine':self.mine_after_action(battle,owner)

    def fence_finished_turn(self,battle,owner):
        if owner in battle['humans']:
            battle.setdefault('end_turn_fences',{})[owner]=self.clock()+1.0

    def settlement_inputs(self,battle,owner,*,escaped=False):
        if battle.get('kind') == 'contract':
            return self.contract_settlement_inputs(battle, owner, escaped=escaped)
        from tio.ranks import battle_report
        from tio.combat_completion import settlement_health
        field=battle['field'];combat=field.combat
        ids=field.actor_ids(owner)
        from tio.reward_policy import RewardContext
        account,levels,side=battle['reward_roster'][owner]
        if battle.get('kind')=='wager':
            return dict(escaped=escaped,now=time.time(),wager=True,
                wager_report=battle.get('wager_report'),
                health={combat.storage_ids.get(i,i):settlement_health(combat,i) for i in ids})
        opponents=tuple((name,ls) for other,(name,ls,team) in battle['reward_roster'].items() if team!=side)
        opponents+=tuple((bot,ls) for bot,(ls,team) in battle.get('reward_bot_roster',{}).items() if team!=side)
        active=owner in battle['reward_damage'] or any(
            healer==owner and target in battle['reward_damage'] for healer,target in battle['reward_support'])
        context=RewardContext(levels,opponents,active,battle.get('city_id')) if opponents and battle['reward_started'] else None
        remap=lambda values:{combat.storage_ids.get(i,i):v for i,v in values.items()}
        from tio.player_statistics import battle_report as statistics_report
        values=dict(escaped=escaped,now=time.time(),
            ranked_report=self.ranked_report(battle),
            team_ranked_report=self.team_rating_report(battle),
            statistics_report=statistics_report(combat,owner),
            reward_context=context,
            health=remap({i:settlement_health(combat,i) for i in ids}),
            rank_report={} if battle.get('city_coefficients',{}).get('town_id')==4 else remap(battle_report(combat,owner,weekly_rank_by_victim=
                getattr(combat,'item_effects',{}).get('weekly_rank',{}))),
            experience_report=remap(combat.experience.report(combat,owner)),
            achievement_report=combat.achievements.report(field,owner,battle['room'].request.mode),
            rental_units=tuple(combat.rental_tax_units.get(i,0) for i in ids))
        if battle.get('kind')=='mine':
            mine=field.mining;amount=0 if escaped else (mine.extracted_amounts.get(owner) or 0)
            miner,defender=battle['mine_pairs'][owner]
            if mine.roles[owner]==1 and defender is not None:
                escort=next((o for o,r in battle['reward_roster'].items() if r[0]==defender),None)
                if escort not in battle['mine_active'] or not field.living_actor_ids(escort):defender=None
            values.update(mined_crystals=0,mine_extraction=dict(gross=amount,role=mine.roles[owner],
                extractor=account,claim=battle['mine_claim'],miner=miner,defender=defender))
            if mine.roles[owner]==2:
                values['mine_extraction']['raiders']=list(battle.get('mine_raiders',{}).get(owner,(account,)))
        return values

    def settle(self, battle, owner, result, *, escaped=False):
        if owner in battle['settled']:return
        from tio import battle_settlement
        from tio.battle_rewards import receipt
        from tio.protocol.asset_count import encode_asset_count
        from tio.protocol.battle_over import encode_battle_over
        s=self.players[owner];combat=battle['field'].combat
        if battle.get('kind')=='wager' and escaped and 'wager_report' not in battle:
            from tio.db_transaction import transaction
            from tio.wagers import forfeit
            if battle.get('wager_active'):
                with transaction(s.database) as db:forfeit(db,battle['match_id'],s.account)
            else:
                battle['wager_report']=dict(version=1,winner_side=None,refund_reason='participant_left_loading')
        try:
            self.prepare_settlements(battle,((owner,result,escaped),))
            assets=battle_settlement.apply(s.database,battle['match_id'],s.account)
        except Exception as error:
            if storage_failure(error):raise
            raise BattleSettlementError(type(error).__name__) from error
        gross,tax=receipt(s.database,s.account,battle['match_id'])
        if not escaped:
            from tio.level_progression import result_packets
            updates,experience=result_packets(s.database,s.account,battle['match_id'],combat,battle['views'][owner])
            replies=(b'\x39',encode_asset_count(assets),*self.ranked_packets(battle,owner),*updates,
                     encode_battle_over(result,credits=gross,rental_tax=tax,soldiers=experience,**combat.statistics.get(owner,{})))
            battle['result_packets'][owner]=replies
            if owner not in self.returning:self.put(owner,*replies)
        battle['settled'].add(owner)
        LOG.info('team_match_settled id=%s account=%s result=%d escaped=%s',battle['match_id'],s.account,result,escaped)

    def finish(self,battle):
        if battle.get('kind') == 'contract':return self.finish_contract(battle)
        if battle.get('kind')=='assault':return self.finish_assault(battle)
        alive=battle['field'].living_sides()
        if battle.get('kind')=='wager':
            if len(alive)>1:raise ValueError('Wager battle is still in progress')
            battle['wager_report']=dict(version=1,winner_side=next(iter(alive))[1] if alive else None,
                refund_reason=None if alive and battle.get('wager_active') else 'draw' if not alive else 'ended_before_loading')
            if not battle.get('wager_active'):battle['wager_report']['winner_side']=None
        if 'points' in battle:
            winner=battle['points'].outcome(battle['field'])
            if winner is None:raise ValueError('Ranked battle is still in progress')
            battle['ranked_winner']=winner
        else:winner=None
        requests=tuple((owner,(2 if winner==2 else int(battle['field'].teams[owner]==winner)) if 'points' in battle else (2 if not alive else int(battle['field'].side(owner) in alive)),False)
                       for owner in battle['humans'])
        self.finish_team_rating(battle)
        self.prepare_settlements(battle,requests)
        for owner,result,_ in requests:
            self.settle(battle,owner,result)
        battle['finished']=True
        for owner in battle['humans']:
            self.battles.pop(owner,None);self.results.add(owner);self.completed[owner]=battle

    def abort_wager(self,battle,reason):
        from tio.db_transaction import transaction
        from tio.wagers import settle
        from tio.wallets import WalletStore
        from tio.protocol.asset_count import encode_asset_count
        report=battle.setdefault('wager_report',dict(version=1,winner_side=None,refund_reason=reason))
        path=next(self.players[o].database for o in battle['humans'])
        with transaction(path) as db:settle(db,battle['match_id'],report)
        battle['finished']=True
        for owner in tuple(battle['humans']):
            self.battles.pop(owner,None)
            s=self.players[owner]
            self.put(owner,encode_asset_count(WalletStore(path).ensure(s.account)),encode_shop_error('Бой со ставкой отменён; ставки возвращены'))
            self.to_city(owner)
        battle['humans'].clear()

    def remove_from_battle(self,battle,owner):
        battle['field'].combat.cancel_equipment_batch(owner,forget_receipts=True)
        self.battles.pop(owner,None);battle['humans'].discard(owner)
        arena=battle['arena'];room=battle['room']
        # Keep turn ordering/room owner stable; disconnected actors are removed.
        arena._loading[room.room_id].add(owner)
        if arena._turns.get(room.room_id,(None,))[0]==owner:
            arena._turns.pop(room.room_id,None);arena._last_turn[room.room_id]=owner
        battle['field'].remove_owner(owner)
        if battle.get('kind')=='mine':
            battle['mine_active'].discard(owner)
            if not battle['mine_active']:battle['finished']=True
        if battle.get('kind')=='assault' and not battle['humans']:
            self.abort_assault(battle,'no_active_humans');battle['finished']=True
        if not battle['humans']:
            self.cancel_team_rating(battle,'no_active_humans')
        self.snapshot(battle)

    def to_city(self,owner):
        completed=self.completed.get(owner)
        if completed is not None and completed.get('kind') == 'contract':
            self.contract_to_city(completed, owner)
        if completed is not None:
            # Native Finish sends2A01 before7C, while7C still contains shared
            # battlefield actor IDs. Retain only this account's ID mapping.
            field=self.mine_result_field(completed,owner)
            self.players[owner]._battle_treatment_ids={i:field.combat.storage_ids[i]
                for i in field.actor_ids(owner) if i in field.combat.storage_ids}
        self.completed.pop(owner,None);self.returning.pop(owner,None)
        s=self.players[owner]
        if self.account_owners.get(s.account)==owner:self.account_owners.pop(s.account,None)
        self.results.discard(owner);self.tickets.pop(owner,None)
        town=s.locations.current(s.account) if s.locations else 3
        self.put(owner,encode_finish_battle_view(),encode_current_town(town or 3),encode_open_town_view())
        s=self.players[owner]
        # Existing city refresh path handles asynchronous native scene teardown.
        s.arena._completed.add(s.probe_character_id)
        s.arena._return_towns[s.probe_character_id]=town or 3

    def treat_result(self,owner,packet):
        from tio.battle_recovery import decode_treatment,treat
        from tio.protocol.asset_count import encode_asset_count
        from tio.protocol.pet_info import decode_pet_info
        session=self.players[owner];battle=self.completed.get(owner)
        mapping=getattr(session,'_battle_treatment_ids',None) or {}
        if battle is not None:
            field=self.mine_result_field(battle,owner)
            mapping={i:field.combat.storage_ids[i] for i in field.actor_ids(owner)
                if i in field.combat.storage_ids}
        ids=decode_treatment(packet)
        if any(i in mapping for i in ids):
            if not all(i in mapping for i in ids):raise ValueError('Некорректный отряд для лечения')
            ids=tuple(mapping[i] for i in ids)
        blocked=(session.survival.searching(session.probe_character_id) or
            any(session.probe_character_id in r.members for r in session.arena.rooms.snapshot()))
        owner=self.identities.get(session)
        blocked=blocked or self.lobbies.room(owner) is not None or owner in self.ranked_waiting or owner in self.survival_waiting
        group=self.assault_group(session)
        blocked=blocked or bool(group and group['status'] in ('paired','running'))
        try:assets,cost=treat(session.database,session.account,ids,blocked=blocked)
        except ValueError as error:
            if str(error)=='Insufficient treatment credits':
                raise ValueError('Недостаточно кредитов для лечения бойцов') from error
            raise
        roster=OwnedPetStore(session.database).list(session.account)
        asset_packet=encode_asset_count(assets)
        self.put(owner,asset_packet,*(pet for _,pet,_ in roster))
        if battle is not None:
            # A repeated/reconnected result must show the current balance and HP.
            battle['result_packets'][owner]=tuple(asset_packet if p[:2]==b'\xc8\x39' else p
                for p in battle['result_packets'][owner])
            saved={i:pet for i,pet,_ in roster}
            for identity,local in mapping.items():
                if local in ids:
                    actor=field.actor(identity)
                    pet=decode_pet_info(saved[local],human_equipment=field.combat.human[identity])
                    field._actors[identity]=replace(actor,health=pet.fields['0x8c4ab1'],max_health=pet.fields['0x8c4a07'])
                    if identity in battle.get('mine_retired',{}).get(owner,{}):
                        battle['mine_retired'][owner][identity]=field._actors[identity]
        LOG.info('post_battle_treatment account=%s credits=%d',session.account,cost)

    def disconnect(self,session):
        with self.lock:
            owner=self.identities.get(session)
            if owner is not None:self.arena_listing_cache.pop(owner,None)
            if owner is not None and self.detach(session,owner):return True
            if getattr(self,'assault_store',None) and getattr(session,'account',None):
                group=self.assault_group(session)
                if group:
                    self.assault_store.disconnect(session.account)
                    self.assault_notify(self.assault_store.group(group['id']))
            retained=self.retain_private(session)
            if owner is None:return retained
            self.leave_wager(owner)
            if owner in self.battles:
                battle=self.battles[owner]
                self.settle(battle,owner,0,escaped=True)
                self.remove_from_battle(battle,owner)
            self.survival_queue.cancel(owner)
            self.cancel_mine_request(owner)
            self.ranked_waiting.pop(owner,None)
            self.survival_waiting.discard(owner)
            session.survival.disconnected(session.probe_character_id)
            self.leave(owner)
            self.results.discard(owner);self.tickets.pop(owner,None)
            self.wager_listing_cache.pop(owner,None);self.lobby_auto_rosters.pop(owner,None)
            self.queues.pop(owner,None);self.players.pop(owner,None);self.identities.pop(session,None)
            return retained

    def drain(self,session,game,cipher):
        with self.lock:
            owner=self.identities.get(session)
            packets=tuple(self.queues.get(owner,()))
            if owner in self.queues:self.queues[owner].clear()
        now=self.clock()
        last=getattr(session,'_team_heartbeat_at',None)
        if last is None:
            session._team_heartbeat_at=now
        if last is not None and now-last>=TEAM_HEARTBEAT_SECONDS:
            packets+=(b'\x9e',)
        for packet in packets:
            if packet[:2]==b'\xc8\x39' and session.database is not None:
                from tio.crystal_market import CrystalMarket
                from tio.protocol.asset_count import decode_asset_count,encode_asset_count
                packet=encode_asset_count(CrystalMarket(session.database).project(session.account,decode_asset_count(packet)))
                from tio.premium import project_packet
                packet=project_packet(session.database,session.account,packet)
            # Only owner character IDs are projected; globally unique battle actors
            # remain stable throughout a scene and map to saved IDs at persistence.
            if packet[:1]==b'\x3b':
                # The owner dword has the same header offset for every
                # species; equipment tails differ (mine resource100 is human).
                if int.from_bytes(packet[5:9],'little')==owner:
                    packet=packet[:5]+session.probe_character_id.to_bytes(4,'little')+packet[9:]
            if session.database is not None:
                from server.economy_runtime import project_packet
                packet=project_packet(session.database,session.account,packet)
            from .warehouse_capacity import frames as capacity_frames
            frame=capacity_frames(session,packet,cipher)
            game.sendall(encode_initial_frame(packet,cipher) if frame is None else frame)
            if packet==b'\x9e':session._team_heartbeat_at=self.clock()

    def pump(self,session,game,reader,cipher):
        self.tick();self.drain(session,game,cipher)
        game.settimeout(.1)
        try:data=game.recv(65535)
        except socket.timeout:return
        if not data:raise EOFError('Team session disconnected')
        for packet in reader.feed(data):
            if not session.router.presence.handle(session,packet):self.handle(session,packet)
        self.drain(session,game,cipher)


from .battle_journal import shared_method
for _name in ('start_match','perform_action','tick_battle','battle_action','settle','finish',
              'remove_from_battle','to_city','send_scene','retry_quarantined','forget'):
    setattr(_SharedTeamArena,_name,shared_method(getattr(_SharedTeamArena,_name)))


class TeamArena(TrainingArena,TutorialArena,_SharedTeamArena):
    """Training and tutorial hooks precede the ordinary shared hub."""
    pass
