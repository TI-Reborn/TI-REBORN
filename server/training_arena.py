"""Noncapturable Assault4 training: native groups, eight real owners, three tours.

Uncharged waiting groups are process-local, like ordinary TeamLobbies. Active
fields and exact tour/score clocks use the existing shared battle journal. The
strategic mo/denver overview is separate from the five original combat maps.
"""
from copy import deepcopy
import random
import time
from uuid import uuid4

from tio.protocol.assault import (BATTLE_MODE,CREATE_ROOM,JOIN_ROOM,REQUEST_ROOMS,
    SELECT_PET,SET_READY,START_ROOM,DISBAND_ROOM,decode_request,RoomCell,RoomPet,
    RoomListItem,FlagPoints,PlayerResult,TeamResult,ZoneInfo,encode_room_info,
    encode_room_list,encode_room_deleted,encode_flag_status,encode_flag_points,
    encode_flag_increment,encode_battle_count,encode_battle_over,encode_zone_body)
from tio.world_completion import location,require_location

TRAINING_TOWNS=(19,20,21,22)


class AssaultMapLoader:
    """Bind original strategic asset; choose verified original combat scenes.

    mo.xml/denver.xml describe a16×16 strategic overview, not Ground tiles.
    All five Assault4 maps are shared by both backgrounds, as explicit server
    selection policy. No original per-background combat-map mapping is known.
    """
    OVERVIEWS={'assault\\mo.xml':'mo','assault\\denver.xml':'denver'}

    def __init__(self):
        from tio.territories import load_config,CONFIG
        policy,_=load_config(CONFIG)
        if policy['tours']!=3 or policy['players_per_group']!=4:raise ValueError('Training requires Assault4 three-tour policy')
        self.rules=deepcopy(policy)

    def overview(self,town):
        record=location(town)
        if record is None or record['profile']!='assault_training':raise ValueError('Not a training base')
        asset=record['assault_map']
        if asset not in self.OVERVIEWS:raise ValueError('Unsupported original strategic overview')
        return dict(asset=asset,background=self.OVERVIEWS[asset],kind='strategic_overview')

    def load(self,town,*,seed=None):
        overview=self.overview(town)
        from tio.assault_map import generate
        layout=generate(seed,deployment_size=12)
        if len(layout.flags)!=3:raise ValueError('Training requires three original Assault4 flags')
        return layout,overview


class TrainingArena:
    def init_training(self,path,*,wall=time.time):
        self.training_path=path;self.training_wall=wall
        self.training_loader=AssaultMapLoader()
        self.training_groups={};self.training_members={};self.training_next_group=0x30000000
        self.training_events={};self.training_update_at=0

    def training_group(self,session):
        owner=self.identities.get(session)
        identity=getattr(self,'training_members',{}).get(owner)
        return getattr(self,'training_groups',{}).get(identity)

    def busy(self,session):
        return self.training_group(session) is not None or super().busy(session)

    def _training_town(self,session):
        if str(session.database)!=str(self.training_path) or session.locations is None:raise ValueError('Нужен общий сохранённый персонаж на тренировочной базе')
        town=session.locations.current(session.account)
        if town not in TRAINING_TOWNS or session.locations.travelling(session.account):raise ValueError('Дождитесь прибытия на тренировочную базу')
        return town

    def _training_selection(self,owner,ids=None):
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info
        from tio.protocol.item_list import decode_item_list
        session=self.players[owner];town=self._training_town(session)
        roster=OwnedPetStore(session.database).list(session.account)
        pets={i:(p,inv) for i,p,inv in roster}
        if ids is None:
            selected=sorted((decode_pet_info(p,human_equipment=int.from_bytes(p[5:9],'little') in (1,2,6)).fields['0x8c44a6'],i)
                            for i,p,_ in roster)
            ids=tuple(i for slot,i in selected if slot in (1,2,3))
        ids=tuple(ids)
        if not 1<=len(ids)<=3 or len(set(ids))!=len(ids):raise ValueError('Выберите от одного до трёх бойцов')
        levels=[];cap=location(town)['max_upgrade'];room_pets=[]
        for identity in ids:
            if type(identity) is not int or identity not in pets:raise ValueError('Боец не принадлежит персонажу')
            packet,inventory=pets[identity];human=int.from_bytes(packet[5:9],'little') in (1,2,6)
            f=decode_pet_info(packet,human_equipment=human).fields
            if f['0x8c4ab1']<=0 or f['0x8c4ab1']!=f['0x8c4a07']:raise ValueError('Нужны полностью здоровые бойцы')
            inv_owner,items,_=decode_item_list(inventory)
            if inv_owner!=identity or any(i.equipped and i.unknown_bytes_03[0]>cap for i in items):raise ValueError('Улучшение экипировки превышает предел базы')
            levels.append(f['0x8c4aef'])
            room_pets.append(RoomPet(f['0x8c4aef'],f['0x8c446f'],0,f['0x8c4489'],f['0x8c4a07'],0,max(1,f['0x8c4bbc']),f['0x8c4bd0'],1))
        require_location(town,levels,training=True)
        return dict(owner=owner,account=session.account,pet_ids=ids,levels=tuple(levels),
            name=session.probe_character_name,pets=tuple(room_pets),ready=False,town=town)

    def _training_event(self,town):
        from tio.territories import TerritoriesStore
        now=self.training_wall();event=self.training_events.get(town)
        if event is None or now>=event['ends']:
            rules=deepcopy(self.training_loader.rules)
            start=int(now);end=start+rules['registration_seconds']+3*rules['tour_seconds']+2*rules['pause_seconds']
            event=dict(id=str(uuid4()),town=town,starts=start,ends=end,rules=rules)
            self.training_events[town]=event
        phase,tour,end=TerritoriesStore._phase(event['starts'],event['rules'],now)
        return {**event,'phase':phase,'tour':tour,'phase_ends':end}

    def training_town_packet(self,town):
        from tio.locations import town_packets
        from server.territory_service import PHASES
        event=self._training_event(town);record=location(town);lo,hi=record['levels']
        raw=town_packets(town,clock=self.training_wall)[0]
        zone=ZoneInfo(PHASES[event['phase']],int(self.training_wall()),event['starts'],int(event['phase_ends']),lo,hi,lo,hi,record['max_upgrade'])
        return raw[:-2]+b'\x01'+encode_zone_body(zone)+raw[-1:]

    def training_room_packet(self,group,viewer):
        cells=tuple(RoomCell(self.players[viewer].probe_character_id if owner==viewer else owner,
            member['name'],max(member['levels']),0,int(owner==group['leader']),member['pets'],int(member['ready']))
            for owner,member in group['members'].items())
        return encode_room_info(group['id'],cells,int(group['status']=='ready'))

    def _training_notify(self,group):
        for owner in group['members']:
            if owner in self.players and owner not in self.offline:self.put(owner,self.training_room_packet(group,owner))

    def _training_list(self,town):
        return encode_room_list(RoomListItem(g['id'],g['members'][g['leader']]['name'],None,None,4,len(g['members']),int(g['status']=='ready'))
            for g in self.training_groups.values() if g['town']==town)

    def _training_leave(self,owner):
        identity=self.training_members.pop(owner,None)
        if identity is None:return
        group=self.training_groups[identity]
        if owner==group['leader']:
            self.training_groups.pop(identity)
            for member in group['members']:
                self.training_members.pop(member,None);self.put(member,encode_room_deleted(identity))
        else:
            group['members'].pop(owner);group['status']='forming'
            for member in group['members'].values():member['ready']=False
            self.put(owner,encode_room_deleted(identity));self._training_notify(group)

    def handle_assault(self,owner,packet):
        session=self.players[owner]
        town=session.locations.current(session.account) if session.locations else None
        if town not in TRAINING_TOWNS or not hasattr(self,'training_path'):return super().handle_assault(owner,packet)
        if len(packet)<2 or packet[0]!=0xc8 or not CREATE_ROOM<=packet[1]<=DISBAND_ROOM:return False
        operation,value=decode_request(packet);town=self._training_town(session)
        if owner in self.battles or owner in self.results:raise ValueError('Завершите текущий бой')
        group=self.training_group(session)
        if operation==REQUEST_ROOMS:
            self.put(owner,self.training_town_packet(town),self._training_list(town))
            if group:self.put(owner,self.training_room_packet(group,owner))
            return True
        if group is None and super().busy(session):raise ValueError('Завершите текущую очередь')
        if operation==CREATE_ROOM:
            if group is None:
                if len(self.training_groups)>=64:raise ValueError('Подождите освобождения тренировочных групп')
                member=self._training_selection(owner);self.training_next_group+=1
                group=dict(id=self.training_next_group,town=town,leader=owner,status='forming',members={owner:member})
                self.training_groups[group['id']]=group;self.training_members[owner]=group['id']
                self._training_event(town)
        elif operation==JOIN_ROOM:
            if group is not None:raise ValueError('Сначала покиньте текущую группу')
            candidate=self.training_groups.get(value)
            if candidate is None or candidate['town']!=town or candidate['status']!='forming' or len(candidate['members'])>=4:raise ValueError('Группа недоступна')
            member=self._training_selection(owner);candidate['members'][owner]=member
            self.training_members[owner]=value;group=candidate
            for m in group['members'].values():m['ready']=False
        else:
            if group is None or group['town']!=town:raise ValueError('Нет вашей тренировочной группы')
            if operation==DISBAND_ROOM:self._training_leave(owner);self.put(owner,self._training_list(town));return True
            if operation==SELECT_PET:
                ids=list(group['members'][owner]['pet_ids'])
                if value in ids:ids.remove(value)
                else:ids.append(value)
                member=self._training_selection(owner,ids);group['members'][owner]=member;group['status']='forming'
                for m in group['members'].values():m['ready']=False
            elif operation==SET_READY:
                member=self._training_selection(owner,group['members'][owner]['pet_ids'])
                member['ready']=bool(value);group['members'][owner]=member;group['status']='forming'
            elif operation==START_ROOM:
                if owner!=group['leader'] or len(group['members'])!=4 or not all(m['ready'] for m in group['members'].values()):raise ValueError('Нужны четыре готовых реальных игрока')
                for o,m in group['members'].items():
                    if o in self.offline or self._training_selection(o,m['pet_ids'])['levels']!=m['levels']:raise ValueError('Состав группы изменился')
                group['status']='ready'
        self._training_notify(group);self.put(owner,self._training_list(town));self.tick_training_events(force=True)
        return True

    def tick_training_events(self,*,force=False):
        if not hasattr(self,'training_path') or not force and self.clock()<self.training_update_at:return
        self.training_update_at=self.clock()+1
        self.recover_training_events()
        for town in TRAINING_TOWNS:
            event=self._training_event(town)
            signature=(event['id'],event['phase'],event['phase_ends'])
            for owner,session in tuple(self.players.items()):
                if owner in self.offline or owner in self.battles or owner in self.results:continue
                if session.locations and session.locations.current(session.account)==town:
                    if getattr(session,'training_zone_signature',None)!=signature:
                        self.put(owner,self.training_town_packet(town));session.training_zone_signature=signature
            if event['phase'] not in ('TOUR1','TOUR2','TOUR3'):continue
            ready=[g for g in self.training_groups.values() if g['town']==town and g['status']=='ready']
            while len(ready)>=2:
                groups=ready[:2];ready=ready[2:]
                journal=getattr(self,'journal',None)
                if journal is None:raise ValueError('Тренировка требует серверного журнала боёв')
                try:journal.birth(self.build_training,deepcopy(groups),event)
                except Exception as error:
                    from .failure_policy import storage_failure
                    if storage_failure(error):raise
                    from tio.protocol.system_message import encode_shop_error
                    for group in groups:
                        group['status']='forming'
                        for owner,member in group['members'].items():
                            member['ready']=False;self.put(owner,encode_shop_error('Тренировка не запущена: '+str(error)[:150]))
                        self._training_notify(group)
                    continue
                for group in groups:
                    self.training_groups.pop(group['id'])
                    for owner in group['members']:self.training_members.pop(owner,None)

    def build_training(self,groups,event):
        if getattr(self,'journal',None) is None:raise ValueError('Тренировка требует серверного журнала боёв')
        if len(groups)!=2 or any(len(g['members'])!=4 for g in groups):raise ValueError('Нужны две группы по четыре реальных игрока')
        town=groups[0]['town'];current=self._training_event(town)
        if event['id']!=current['id'] or event['tour']!=current['tour'] or current['phase'] not in ('TOUR1','TOUR2','TOUR3'):raise ValueError('Тур тренировки изменился')
        from tio.matchmaking import SearchTicket
        from tio.team_scene import prepare
        from tio.arena_service import ArenaService
        from tio.protocol.arena import ArenaCreateRequest
        from tio.assault_battle import AssaultPoints
        seats=[];teams=[]
        for side,group in enumerate(groups):
            if group['town']!=town or group['status']!='ready':raise ValueError('Группа находится на другой базе')
            team=[]
            for owner,member in group['members'].items():
                session=self.players.get(owner)
                if session is None or owner in self.offline or owner in self.battles or owner in self.results or self.retained(session.account):raise ValueError('Игрок недоступен')
                checked=self._training_selection(owner,member['pet_ids'])
                if checked['account']!=member['account'] or checked['town']!=town or checked['levels']!=member['levels'] or not member['ready']:raise ValueError('Состав группы изменился')
                ticket=SearchTicket(owner,checked['pet_ids'],checked['levels'],self.clock())
                seats.append((owner,side,session.database,session.account,ticket,False));team.append(owner)
            teams.append(tuple(team))
        if len({s[3] for s in seats})!=8 or len({s[0] for s in seats})!=8:raise ValueError('Нужны восемь отдельных реальных персонажей')
        seed=random.SystemRandom().getrandbits(64);layout,overview=self.training_loader.load(town,seed=seed)
        field,views,ground,_=prepare(seats,0,seed=seed,arena_map=layout.arena,selected_ids=True,profile='assault',town_id=town)
        field.battle_mode=BATTLE_MODE;record=location(town)
        field.scene_metadata.update(town_id=town,original_scene=layout.resource,
            training_policy=dict(version=1,capture=False,weekly_awards=False,tour=event['tour'],tours=3,
                max_upgrade=record['max_upgrade'],overview=overview,seed=seed))
        for identity in field._actors:field.combat.enhancement_caps[identity]=min(field.combat.enhancement_caps[identity],record['max_upgrade'])
        order=tuple(o for pair in zip(*teams) for o in pair)
        arena=ArenaService(clock=self.clock);request=ArenaCreateRequest(BATTLE_MODE,0,8,2,80,3,3,0,0)
        room=arena.rooms.create(order[0],request)
        for owner in order[1:]:room=arena.rooms.join(room.room_id,owner)
        arena._fields[room.room_id]=field;arena._loading[room.room_id]=set()
        match=str(uuid4());arena._match_ids[room.room_id]=match
        battle=dict(kind='training',arena=arena,room=room,field=field,views=views,bots=set(),humans=set(views),
            city_id=town,match_id=match,settled=set(),deadline=self.clock()+60,finished=False,ground=ground,
            captain_name=self.players[order[0]].probe_character_name,names={o:self.players[o].probe_character_name for o in order},
            result_packets={},reward_roster={o:(a,tuple(t.levels),side) for o,side,p,a,t,b in seats},
            reward_damage=set(),reward_support=set(),reward_started=False,return_towns={o:town for o in views},
            assault_points=AssaultPoints(layout.flags,[None]*3,[0,0]),assault_round_seen=set(),
            training_event=deepcopy(event),training_ends=min(self.training_wall()+event['rules']['emulator_policy']['battle_max_seconds'],event['phase_ends']))
        for owner in views:
            self.battles[owner]=battle;self.account_owners[self.players[owner].account]=owner
            self.players[owner]._battle_treatment_ids=None;self.send_scene(owner)
        return battle

    def recover_training_events(self):
        """Recover active event windows from existing primitive checkpoints."""
        seen=set()
        for battle in (*self.battles.values(),*self.completed.values()):
            if id(battle) in seen or battle.get('kind')!='training':continue
            seen.add(id(battle));event=battle['training_event'];town=event['town']
            if self.training_wall()>=event['ends']:continue
            existing=self.training_events.get(town)
            if existing is None or existing['starts']<event['starts']:
                self.training_events[town]={k:deepcopy(event[k]) for k in ('id','town','starts','ends','rules')}

    def assault_packets(self,battle,owner):
        if battle.get('kind')!='training':return super().assault_packets(battle,owner)
        points=battle['assault_points'];gains=points.increments()
        return (*[encode_flag_status(x,y,0 if points.owners[i] is None else points.owners[i]+1) for i,(x,y) in enumerate(points.positions)],
            encode_flag_points(tuple(FlagPoints(side+1,points.scores[side],gains[side]) for side in (0,1))),encode_battle_count(1,0))

    def training_refresh(self,battle):
        for owner in battle['humans']:
            if self.battles.get(owner) is battle:self.put(owner,*self.assault_packets(battle,owner))

    def perform_action(self,battle,owner,packet):
        if battle.get('kind')!='training':return super().perform_action(battle,owner,packet)
        with self.journal.unit(battle):
            result=super().perform_action(battle,owner,packet)
            if packet[0]!=0x3a:
                battle['assault_points'].capture(battle['field']);self.training_refresh(battle)
            return result

    def tick_battle(self,battle):
        if battle.get('kind')!='training':return super().tick_battle(battle)
        if battle['finished']:return
        arena=battle['arena'];room=battle['room'];field=battle['field']
        turn=arena._turns.get(room.room_id)
        marks_due=any(self.tactical_wall()>mark['expires_at_wall'] or not self._mark_member(battle,author)
            for author,mark in battle.get('tactical_marks',{}).items())
        # Match the ordinary journal's idle shortcut, while respecting the
        # training tour's absolute UTC cutoff even during a live player turn.
        if not marks_due and self.training_wall()<battle['training_ends'] and len(field.living_sides())>1:
            if arena._loading[room.room_id]!=set(room.members) and self.clock()<=battle['deadline']:return
            if turn is not None and self.clock()<turn[2] and any(field.actor(i).action_points>0 for i in field.living_actor_ids(turn[0])):return
        with self.journal.unit(battle):return self._tick_training(battle)

    def _tick_training(self,battle):
        if battle['finished']:return
        self.expire_tactical_marks(battle)
        arena=battle['arena'];room=battle['room'];field=battle['field']
        if self.training_wall()>=battle['training_ends'] or len(field.living_sides())<=1:return self.finish_training(battle)
        if arena._loading[room.room_id]!=set(room.members):
            if self.clock()>battle['deadline']:
                battle['finished']=True
                for owner in tuple(battle['humans']):self.battles.pop(owner,None);self.to_city(owner)
                battle['humans'].clear()
            return
        for owner,packet in arena.expire_turns():self.put(owner,*arena.finished_turn_packets(owner,packet))
        battle['reward_started']=True;self.finish_exhausted_turn(battle)
        if room.room_id in arena._turns:return
        seen=battle['assault_round_seen'];living={o for o in room.members if field.living_actor_ids(o)}
        if living and living<=seen:
            points=battle['assault_points'];points.advance(field);seen.clear();gains=points.increments()
            for i,(x,y) in enumerate(points.positions):
                side=points.owners[i]
                if side is None:continue
                packet=encode_flag_increment(x,y,gains[side]//points.owners.count(side),side+1)
                for target in battle['humans']:self.put(target,packet)
            self.training_refresh(battle)
        arena._last_turn.setdefault(room.room_id,room.members[-1]);owner=arena.next_turn_owner(room.room_id)
        from tio.protocol.battle_turn import turn_seconds
        seconds=turn_seconds(len(field.living_actor_ids(owner)));battle['full_turn']=(owner,self.clock()+seconds)
        if owner in self.offline:seconds//=2
        self.announce_turn(battle,owner,seconds);self.begin_shared_turn(battle,owner,seconds);seen.add(owner)

    def finish_training(self,battle):
        if battle['finished']:return
        with self.journal.unit(battle):return self._finish_training(battle)

    def _finish_training(self,battle):
        field=battle['field'];points=battle['assault_points'];winner=points.outcome(field)
        if winner is None:winner=2 if points.scores[0]==points.scores[1] else int(points.scores[1]>points.scores[0])
        rows=[]
        for side in (0,1):
            players=[]
            for owner,(_,_,team) in battle['reward_roster'].items():
                if team!=side:continue
                values=field.combat.statistics.get(owner,{})
                players.append(PlayerResult(battle['names'][owner],values.get('kills',0),values.get('losses',0),0))
            rows.append(TeamResult(0 if winner==2 else 1 if side==winner else 2,points.scores[side],0,tuple(players),()))
        requests=tuple((o,2 if winner==2 else int(field.teams[o]==winner),False) for o in battle['humans'])
        self.prepare_settlements(battle,requests)
        for owner,result,_ in requests:
            self.settle(battle,owner,result)
            side=field.teams[owner];final=encode_battle_over(battle['city_id'],rows[side],rows[1-side])
            battle['result_packets'][owner]=(*battle['result_packets'][owner],final);self.put(owner,final)
        battle['finished']=True;arena=battle['arena'];arena._turns.pop(battle['room'].room_id,None)
        for owner in battle['humans']:self.battles.pop(owner,None);self.results.add(owner);self.completed[owner]=battle

    def finish(self,battle):
        if battle.get('kind')=='training':return self.finish_training(battle)
        return super().finish(battle)

    def tick(self):
        with self.lock:self.tick_training_events();return super().tick()

    def disconnect(self,session):
        with self.lock:
            owner=self.identities.get(session)
            if hasattr(self,'training_path') and owner not in self.battles:self._training_leave(owner)
            return super().disconnect(session)
