"""Location membership shared by authenticated sessions; sockets remain thread-owned."""
from collections import deque
from dataclasses import replace
import logging
import threading
import time

from tio.protocol.presence import (Player,encode_players,encode_clear,
                                   encode_location_players,encode_location_clear)
from tio.protocol.transport import encode_initial_frame

LOG=logging.getLogger('tio.server')


class Presence:
    def __init__(self):
        self.lock=threading.RLock()
        self.players={};self.queues={};self.messages={};self.rate={};self.next_id=0x20000000
        self.online_clock={}

    def sync(self,session):
        now=time.monotonic()
        if now<getattr(session,'presence_next_sync',0):return
        session.presence_next_sync=now+.5
        from .world_runtime import heartbeat
        prison_replies=heartbeat(session)
        from .avatar_service import sync as sync_avatars
        sync_avatars(self,session)
        town=session.locations.current(session.account) if session.locations else 3
        from .public_profile import read_profile
        profile=read_profile(session.database,account=session.account,include_history=False)
        level=profile.level if profile else 0
        team=getattr(getattr(session,'router',None),'team_arena',None)
        status=int(bool(getattr(getattr(session,'arena',None),'_fields',{})) or bool(team and team.in_battle(session)))
        with self.lock:
            old=self.players.get(session)
            if old is None:
                self.online_clock[session]=now
                self.next_id+=1
                entry=(town,Player(self.next_id,session.probe_character_name,level,status=status))
                self.players[session]=entry;self.queues[session]=deque();self.messages[session]=deque()
                LOG.info('presence_join account=%s town=%s id=%d',session.account,town,self.next_id)
                self.refresh()
            elif old[0]!=town or old[1].level!=level or old[1].status!=status:
                self.players[session]=(town,replace(old[1],level=level,status=status));self.refresh()
                LOG.info('presence_move account=%s from=%s to=%s',session.account,old[0],town)
        started=self.online_clock.get(session)
        with self.lock:
            if session in self.messages:self.messages[session].extend(prison_replies[:max(0,128-len(self.messages[session]))])
        if session.database is not None and getattr(session,'owned_pet_probe',False):
            from .clan_service import sync as sync_clan
            from tio.clans import ClanRejected
            try:sync_clan(self,session)
            except ClanRejected:
                # Membership may change between the roster and warehouse reads.
                # Retry a fresh authorized snapshot on the next normal poll.
                session.clans_signature=None;session.clans_revision=None
                session.alliances_signature=None;session.alliances_invitation=None
        if started is not None and now-started>=30:
            from tio.player_statistics import save_online
            save_online(session.database,session.account,now-started)
            self.online_clock[session]=now

    def snapshot(self,session):
        town=self.players[session][0]
        records=[];local=[]
        for other,(location,p) in self.players.items():
            if other is session:p=replace(p,identity=session.probe_character_id)
            records.append(p)
            if town is not None and location==town:local.append(p)
        # Clear is also the native completion of the loading user-list spinner.
        # 4F fans out to Location (0), Trade (6), Help (8) in the original DLL.
        return (encode_clear(),encode_players(records),encode_location_clear(),encode_location_players(local))

    def refresh(self):
        # Global changes reach every town. Coalesce complete snapshots, preserving
        # pending local updates and keeping each connection's queue bounded.
        for session in self.players:
            self.queues[session].clear();self.queues[session].extend(self.snapshot(session))

    def handle(self,session,packet):
        if packet[:1]==b"\xac":
            from .avatar_service import handle as handle_avatars
            return handle_avatars(self,session,packet)
        if packet[:1]==b'\xa4':
            from .world_runtime import standings
            replies=standings(session,packet)
            with self.lock:
                if session in self.messages:self.messages[session].extend(replies[:max(0,128-len(self.messages[session]))])
            return True
        # Public standings remain a read-only query while TeamArena owns a
        # battle/result session; it otherwise consumes unrecognized packets.
        if packet[:1] in (b'\x82',b'\x59') or packet[:2] in (b'\xaf\x0e',b'\xaf\x06'):
            from .clan_service import handle as clan_handle
            return clan_handle(self,session,packet)
        if packet[:1]==b'\x68':
            self.profile(session,packet)
            return True
        if packet[:1]==b'\x21':
            self.chat(session,packet)
            return True
        if packet!=b'\xc7\x01':return False
        with self.lock:
            if session in self.players:
                self.queues[session].clear();self.queues[session].extend(self.snapshot(session))
        return True

    def profile(self,session,packet):
        from .public_profile import read_profile
        from tio.protocol.public_profile import decode_request,encode_profile
        from tio.protocol.system_message import encode_shop_error
        try:
            now=time.monotonic()
            if now<getattr(session,'profile_next_request',0):return
            session.profile_next_request=now+.5
            name=decode_request(packet)
            profile=read_profile(session.database,name=name)
            if profile is None:raise ValueError('Персонаж не найден')
            with self.lock:
                target=next((s for s,(_,p) in self.players.items() if p.name.lower()==name.lower()),None)
                entry=self.players[target][1] if target else None
                live=time.monotonic()-self.online_clock.get(target,time.monotonic()) if target else 0
            reply=encode_profile(entry.identity if entry else 0,profile.name,profile.level,profile.summary,
                                 rating=profile.rating,wins=profile.wins,losses=profile.losses,
                                 kills=profile.kills,deaths=profile.deaths,damage_dealt=profile.damage_dealt,
                                 damage_received=profile.damage_received,squad_rank=profile.squad_rank,
                                 squad_icon=profile.squad_icon,mercenaries=profile.mercenaries,
                                 skill=profile.skill,league=profile.league,place=profile.place,streak=profile.streak,
                                 clan_name=profile.clan_name,clan_crest_id=profile.clan_crest_id,
                                 alliance_name=profile.alliance_name,alliance_crest_id=profile.alliance_crest_id,
                                 online_hours=int((profile.online_seconds+live)//3600),
                                 online=entry is not None,in_battle=bool(entry and entry.status==1))
        except ValueError as exc:
            reply=encode_shop_error(str(exc))
        with self.lock:
            if session in self.messages and len(self.messages[session])<128:self.messages[session].append(reply)

    def chat(self,session,packet):
        from tio.protocol.chat import decode_send,encode_message
        from tio.protocol.system_message import encode_shop_error
        # Standings use ordinary private native chat replies, including in a
        # running battle. No unsupported selector is sent to the old client.
        try:
            channel,text,_=decode_send(packet)
            from .economy_runtime import private_command
            if private_command(packet):raise ValueError("Для операций банка и рынка вернитесь в город")
            contracts = getattr(getattr(session, 'router', None), 'contracts', None)
            if contracts is not None and contracts.command(session, text):
                return
            if text.strip().split()[:1] and text.strip().split()[0].lower() in ('!teamrating','!seasons'):
                if channel not in (0,1,2,3,4,6,7,8,12):
                    raise ValueError('Этот канал пока не поддерживается')
                now=time.monotonic()
                if now<getattr(session,'team_rating_next_query',0):return
                session.team_rating_next_query=now+.5
                from .team_ranked import command
                replies=command(session,text,channel=channel)
                with self.lock:
                    if session in self.messages:
                        self.messages[session].extend(replies[:max(0,128-len(self.messages[session]))])
                return
        except ValueError as exc:
            with self.lock:
                if session in self.messages and len(self.messages[session])<128:
                    self.messages[session].append(encode_shop_error(str(exc)))
            return
        clan_targets=None
        # Original chat tab m450=Alliance has Tag7 (a0757f); a50cb9 matches
        # incoming channel to that tag. Channel5 is a different native branch.
        if packet[1:2] in (b'\x02',b'\x07'):
            from contextlib import closing
            from tio.db_transaction import connect
            from tio.clans import membership
            with closing(connect(session.database)) as db:
                db.execute('BEGIN');clan=membership(db,session.account)
                ids=(clan['id'],) if clan else ()
                if packet[1:2]==b'\x07':
                    from tio.alliances import alliance_for_clan
                    alliance=alliance_for_clan(db,clan['id']) if clan else None
                    ids=alliance['clans'] if alliance else ()
                clan_targets={r[0] for r in db.execute('SELECT account FROM clan_members WHERE clan_id IN ('+
                    ','.join('?' for _ in ids)+')',ids)} if ids else set()
        # Never hold Presence.lock while entering TeamArena.lock.
        if packet[1:2] in (b'\x03',b'\x04'):
            hub=getattr(getattr(session,'router',None),'team_arena',None)
            try:
                channel,text,_=decode_send(packet)
                if hub is None:raise ValueError('Боевой чат доступен только в бою')
                hub.chat(session,channel,text)
            except ValueError as exc:
                with self.lock:
                    if session in self.messages and len(self.messages[session])<128:
                        self.messages[session].append(encode_shop_error(str(exc)))
            return
        with self.lock:
            if session not in self.players:return
            try:
                channel,text,recipient=decode_send(packet)
                if channel not in (0,1,2,6,7,8,12):raise ValueError('Этот канал пока не поддерживается')
                if channel==2 and not clan_targets:raise ValueError('Вы не состоите в клане')
                if channel==7 and not clan_targets:raise ValueError('Вы не состоите в действующем альянсе')
                if text.startswith('/'):raise ValueError('Команды чата пока не поддерживаются')
                now=time.monotonic();recent=self.rate.setdefault(session,deque())
                while recent and recent[0]<now-5:recent.popleft()
                if len(recent)>=5:raise ValueError('Подождите перед следующим сообщением')
                recent.append(now)
                town,player=self.players[session]
                if channel==1:
                    targets=[s for s,(_,p) in self.players.items() if p.name.lower()==recipient.lower()]
                    if not targets:raise ValueError('Игрок не в сети')
                    # The private sender already displays their outgoing text locally.
                elif channel in (2,7):
                    targets=[s for s in self.players if s.account in clan_targets]
                elif channel in (0,6,8):
                    targets=[s for s,(location,_) in self.players.items() if town is not None and town==location]
                else:targets=list(self.players)
                reply=encode_message(channel,player.name,text)
                delivered=0
                for target in targets:
                    # The native client already appends its own outgoing text.
                    # Echoing the server copy duplicates it in every shared
                    # channel (private chat has always followed this rule).
                    if target is session:continue
                    if len(self.messages[target])<128:
                        self.messages[target].append(reply);delivered+=1
                LOG.info('chat_message account=%s channel=%d recipients=%d',session.account,channel,delivered)
            except ValueError as exc:
                if len(self.messages[session])<128:self.messages[session].append(encode_shop_error(str(exc)))

    def drain(self,session,connection,cipher):
        with self.lock:
            packets=tuple(self.queues.get(session,()))+tuple(self.messages.get(session,()))
            if session in self.queues:self.queues[session].clear()
            if session in self.messages:self.messages[session].clear()
        for packet in packets:connection.sendall(encode_initial_frame(packet,cipher))

    def disconnect(self,session):
        from .world_runtime import heartbeat
        heartbeat(session,active=False)
        started=self.online_clock.pop(session,None)
        if started is not None:
            from tio.player_statistics import save_online
            save_online(session.database,session.account,max(0,time.monotonic()-started))
        with self.lock:
            old=self.players.pop(session,None);self.queues.pop(session,None)
            self.messages.pop(session,None);self.rate.pop(session,None)
            if old:
                self.refresh()
                LOG.info('presence_leave account=%s town=%s',session.account,old[0])
