"""Native Assault4 groups and a journaled, exclusively real-account field."""
import logging
import time
from uuid import uuid4

from tio.protocol.system_message import encode_shop_error

LOG=logging.getLogger('tio.server')


class AssaultArena:
    def init_assault(self,path,*,config_path=None,wall=time.time):
        from tio.territories import TerritoriesStore
        self.assault_store=TerritoriesStore(path,config_path,clock=wall)
        self.assault_wall=wall
        self.assault_update_at=0

    def assault_group(self,session):
        store=getattr(self,'assault_store',None)
        return store.own_group(session.account) if store and getattr(session,'account',None) else None

    def assault_owner(self,account):
        return next((o for o,s in self.players.items() if s.account==account and o not in self.offline),None)

    def recover_assault_bindings(self):
        """Run once after journal recovery, preserving quarantined saves."""
        from contextlib import closing
        from tio.db_transaction import connect
        live={b['match_id'] for b in (*self.battles.values(),*self.completed.values())}
        with closing(connect(self.assault_store.path)) as db:
            rows=db.execute("SELECT event_id,match_id FROM warfare_matches WHERE status='running'").fetchall()
        for event,match in rows:
            if match not in live:
                self.assault_store.abort_match(event,match,'recovery_missing')
                LOG.error('assault_binding_aborted_after_recovery event=%s match=%s',event,match)

    def assault_town(self,session):
        town=session.locations.current(session.account) if session.locations else None
        store=getattr(self,'assault_store',None)
        if store is None or town not in store.locations or not store.locations[town]['enabled']:
            raise ValueError('Сначала перейдите на территорию штурма')
        if session.locations.travelling(session.account):raise ValueError('Дождитесь прибытия на территорию')
        return town

    def assault_selection(self,session):
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info
        chosen=[]
        for identity,packet,_ in OwnedPetStore(session.database).list(session.account):
            fields=decode_pet_info(packet,human_equipment=int.from_bytes(packet[5:9],'little') in (1,2,6)).fields
            if fields['0x8c44a6'] in (1,2,3):chosen.append((fields['0x8c44a6'],identity))
        if not chosen:raise ValueError('Выберите бойцов в казарме')
        return tuple(i for _,i in sorted(chosen)[:3])

    def assault_room_packet(self,group,viewer):
        from tio.protocol.assault import RoomCell,RoomPet,encode_room_info
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info
        cells=[]
        for member in group['members']:
            owner=self.assault_owner(member['account'])
            identity=self.players[viewer].probe_character_id if member['account']==self.players[viewer].account else (owner or 0)
            pets=[]
            for i,p,_ in OwnedPetStore(self.assault_store.path).list(member['account']):
                if i not in member['pet_ids']:continue
                f=decode_pet_info(p,human_equipment=int.from_bytes(p[5:9],'little') in (1,2,6)).fields
                pets.append(RoomPet(f['0x8c4aef'],f['0x8c446f'],0,f['0x8c4489'],f['0x8c4a07'],0,max(1,f['0x8c4bbc']),f['0x8c4bd0'],1))
            cells.append(RoomCell(identity,member['name'],max(member['levels']),0,int(member['account']==group['leader']),tuple(pets),int(member['ready'] and owner is not None)))
        return encode_room_info(group['id'],cells,int(group['status'] in ('ready','paired','running')))

    def assault_list_packet(self,owner,town):
        from tio.protocol.assault import RoomListItem,encode_room_list
        session=self.players[owner]
        try:coalition=self.assault_store.participant(session.account,town,self.assault_selection(session))['coalition']
        except ValueError:return encode_room_list(())
        groups=self.assault_store.groups(town,coalition)
        rows=[]
        for group in groups:
            if group['status'] in ('paired','running','closed'):continue
            leader=next((m['name'] for m in group['members'] if m['account']==group['leader']),b'')
            rows.append(RoomListItem(group['id'],leader,0,0 if group['alliance_id'] else None,4,len(group['members']),int(group['status']=='ready')))
        return encode_room_list(rows)

    def assault_notify(self,group):
        for member in group['members']:
            owner=self.assault_owner(member['account'])
            if owner is not None and owner not in self.battles and owner not in self.results:
                self.put(owner,self.assault_room_packet(group,owner))

    def handle_assault(self,owner,packet):
        if len(packet)<2 or packet[0]!=0xc8 or not 0x1d<=packet[1]<=0x23:return False
        from tio.protocol.assault import decode_request,CREATE_ROOM,JOIN_ROOM,REQUEST_ROOMS,SELECT_PET,SET_READY,START_ROOM,DISBAND_ROOM,encode_room_deleted
        op,value=decode_request(packet);session=self.players[owner];town=self.assault_town(session)
        if owner in self.battles or owner in self.results:raise ValueError('Завершите текущий бой')
        group=self.assault_group(session)
        if op==REQUEST_ROOMS:
            self.put(owner,self.assault_list_packet(owner,town))
            if group:self.put(owner,self.assault_room_packet(group,owner))
            return True
        if group is None and self.busy(session):raise ValueError('Завершите текущую очередь или комнату')
        if op==CREATE_ROOM:
            group=self.assault_store.create_group(session.account,town,self.assault_selection(session))
        elif op==JOIN_ROOM:
            candidate=self.assault_store.group(value)
            if candidate['town']!=town:raise ValueError('Группа находится на другой территории')
            group=self.assault_store.join_group(session.account,value,self.assault_selection(session))
        else:
            if group is None or group['town']!=town:raise ValueError('Нет вашей группы на этой территории')
            if op==SELECT_PET:
                # This native command chooses a fighter by private owned ID.
                selected=list(next(m['pet_ids'] for m in group['members'] if m['account']==session.account))
                if value in selected:
                    if len(selected)>1:selected.remove(value)
                elif len(selected)<3:selected.append(value)
                else:raise ValueError('В группе допускается не больше трёх бойцов')
                group=self.assault_store.select(session.account,tuple(selected))
            elif op==SET_READY:group=self.assault_store.ready(session.account,bool(value))
            elif op==START_ROOM:
                if any(self.assault_owner(m['account']) is None for m in group['members']):raise ValueError('Все четыре игрока должны быть подключены')
                group=self.assault_store.start_group(session.account)
            elif op==DISBAND_ROOM:
                key=group['id'];group=self.assault_store.leave_group(session.account)
                self.put(owner,encode_room_deleted(key))
        self.assault_notify(group)
        self.put(owner,self.assault_list_packet(owner,town))
        self.tick_assault_events(force=True)
        return True

    def tick_assault_events(self,*,force=False):
        store=getattr(self,'assault_store',None)
        if store is None or not force and self.clock()<self.assault_update_at:return
        self.assault_update_at=self.clock()+1
        for event in store.sync():
            from tio.locations import town_packets
            signature=(event['id'],event['phase'],event['phase_ends'],event['claim']['revision'])
            for owner,session in tuple(self.players.items()):
                if owner in self.offline or owner in self.battles or owner in self.results:continue
                if session.locations and session.locations.current(session.account)==event['town']:
                    if getattr(session,'assault_zone_signature',None)!=signature:
                        self.put(owner,town_packets(event['town'],store.path,clock=self.assault_wall)[0])
                        session.assault_zone_signature=signature
            for group in store.groups(event['town']):
                if group['status']=='ready':
                    for member in group['members']:
                        owner=self.assault_owner(member['account'])
                        if owner is None or owner in self.battles or owner in self.results:
                            store.disconnect(member['account']);break
            while event['phase'] in ('TOUR1','TOUR2','TOUR3'):
                pair=store.pair_ready(event['id'])
                if pair is None:break
                try:
                    journal=getattr(self,'journal',None)
                    if journal:journal.birth(self.build_assault,pair)
                    else:self.build_assault(pair)
                except Exception as error:
                    from .failure_policy import storage_failure
                    store.cancel_pair(pair['id'])
                    if storage_failure(error):raise
                    for group in pair['groups']:
                        for member in group['members']:
                            store.disconnect(member['account'])
                            owner=self.assault_owner(member['account'])
                            if owner is not None:self.put(owner,encode_shop_error('Штурм не запущен: '+str(error)[:150]))
                    LOG.warning('assault_birth_rejected event=%s error=%s',event['id'],type(error).__name__)
            if event['phase']=='FINISHED' and not any(m['status']=='running' for m in store.matches(event['id'])):store.finalize(event['id'])

    def build_assault(self,pair):
        if getattr(self,'journal',None) is None:raise ValueError('Штурмы требуют серверного журнала сохранений')
        from tio.assault_map import generate
        from tio.assault_battle import AssaultPoints
        from tio.team_scene import prepare
        from tio.matchmaking import SearchTicket
        from tio.arena_service import ArenaService
        from tio.protocol.arena import ArenaCreateRequest
        from tio.protocol.assault import BATTLE_MODE
        groups=pair['groups'];town=groups[0]['town'];seats=[];teams=[]
        for side,group in enumerate(groups):
            team=[]
            for member in group['members']:
                owner=self.assault_owner(member['account'])
                if owner is None or owner in self.battles or owner in self.results:raise ValueError('Участник уже недоступен')
                session=self.players[owner]
                if str(session.database)!=str(self.assault_store.path) or self.assault_town(session)!=town:raise ValueError('Участник покинул территорию')
                checked=self.assault_store.participant(session.account,town,member['pet_ids'])
                if checked['clan_id']!=member['clan_id'] or checked['coalition']!=group['coalition'] or checked['levels']!=member['levels']:raise ValueError('Состав отряда изменился')
                ticket=SearchTicket(owner,tuple(member['pet_ids']),tuple(member['levels']),self.clock())
                seats.append((owner,side,session.database,session.account,ticket,False));team.append(owner)
            teams.append(tuple(team))
        if len(seats)!=8 or len({s[3] for s in seats})!=8:raise ValueError('Нужны восемь отдельных игровых аккаунтов')
        layout=generate(deployment_size=12)
        field,views,ground,_=prepare(seats,0,arena_map=layout.arena,selected_ids=True,profile='assault',town_id=town)
        field.battle_mode=BATTLE_MODE;field.scene_metadata.update(town_id=town,original_scene=layout.resource)
        # Account health/gear is read again by prepare; territory enhancement
        # limits are applied authoritatively to every admitted fighter.
        cap=min(self.assault_store.participant(s[3],town,s[4].actors)['max_upgrade'] for s in seats)
        for identity in field._actors:field.combat.enhancement_caps[identity]=min(field.combat.enhancement_caps[identity],cap)
        order=tuple(o for pair_owners in zip(*teams) for o in pair_owners)
        arena=ArenaService(clock=self.clock)
        request=ArenaCreateRequest(BATTLE_MODE,0,8,2,80,3,3,0,0)
        room=arena.rooms.create(order[0],request)
        for owner in order[1:]:room=arena.rooms.join(room.room_id,owner)
        arena._fields[room.room_id]=field;arena._loading[room.room_id]=set()
        match=str(uuid4());self.assault_store.bind_match(match,pair)
        event=self.assault_store.current_event(town)
        battle=dict(kind='assault',arena=arena,room=room,field=field,views=views,bots=set(),city_id=town,
            humans=set(views),match_id=match,settled=set(),deadline=self.clock()+60,finished=False,ground=ground,
            captain_name=self.players[order[0]].probe_character_name,names={o:self.players[o].probe_character_name for o in order},result_packets={},
            reward_roster={o:(a,tuple(t.levels),side) for o,side,p,a,t,b in seats},reward_damage=set(),reward_support=set(),reward_started=False,
            return_towns={o:town for o in views},assault_points=AssaultPoints(layout.flags,[None]*3,[0,0]),
            assault_event=event['id'],assault_groups=tuple(g['id'] for g in groups),assault_owners=tuple(order),
            assault_round_seen=set(),assault_ends=min(self.assault_wall()+900,event['phase_ends']))
        for owner in views:
            self.battles[owner]=battle;self.account_owners[self.players[owner].account]=owner
            self.players[owner]._battle_treatment_ids=None
            self.send_scene(owner)
        LOG.info('assault_created event=%s match=%s accounts=8 scene=%s',event['id'],match,layout.resource)
        return battle

    def assault_packets(self,battle,owner):
        if battle.get('kind')!='assault':return ()
        from tio.protocol.assault import FlagPoints,encode_flag_status,encode_flag_points,encode_flag_increment,encode_battle_count
        points=battle['assault_points']
        increments=points.increments()
        return (*[encode_flag_status(x,y,0 if points.owners[i] is None else points.owners[i]+1) for i,(x,y) in enumerate(points.positions)],
                encode_flag_points(tuple(FlagPoints(side+1,points.scores[side],increments[side]) for side in (0,1))),
                encode_battle_count(1,0))

    def assault_refresh(self,battle):
        for owner in battle['humans']:
            if self.battles.get(owner) is battle:self.put(owner,*self.assault_packets(battle,owner))

    def tick_assault(self,battle):
        if battle['finished']:return
        arena=battle['arena'];room=battle['room'];field=battle['field']
        if not battle['humans']:
            self.abort_assault(battle,'no_active_humans');battle['finished']=True;return
        if self.assault_wall()>=battle['assault_ends'] or len(field.living_sides())<=1:
            self.finish_assault(battle);return
        if arena._loading[room.room_id]!=set(room.members):
            if self.clock()>battle['deadline']:
                self.abort_assault(battle,'loading_timeout')
                for owner in tuple(battle['humans']):
                    self.settle(battle,owner,0,escaped=True);self.remove_from_battle(battle,owner);self.to_city(owner)
                battle['finished']=True
            return
        for owner,packet in arena.expire_turns():self.put(owner,*arena.finished_turn_packets(owner,packet))
        battle['reward_started']=True;self.finish_exhausted_turn(battle)
        if room.room_id in arena._turns:return
        seen=battle['assault_round_seen'];living={o for o in room.members if field.living_actor_ids(o)}
        if living and living<=seen:
            points=battle['assault_points'];points.advance(field);seen.clear()
            from tio.protocol.assault import encode_flag_increment
            gains=points.increments()
            for index,(x,y) in enumerate(points.positions):
                side=points.owners[index]
                if side is None:continue
                packet=encode_flag_increment(x,y,gains[side]//points.owners.count(side),side+1)
                for target in battle['humans']:self.put(target,packet)
            self.assault_refresh(battle)
        arena._last_turn.setdefault(room.room_id,room.members[-1]);owner=arena.next_turn_owner(room.room_id)
        from tio.protocol.battle_turn import turn_seconds
        seconds=turn_seconds(len(field.living_actor_ids(owner)));battle['full_turn']=(owner,self.clock()+seconds)
        if owner in self.offline:seconds//=2
        self.announce_turn(battle,owner,seconds)
        self.begin_shared_turn(battle,owner,seconds);seen.add(owner)

    def abort_assault(self,battle,reason):
        if battle.get('kind')!='assault' or battle.get('assault_receipt'):return
        battle['assault_receipt']=self.assault_store.abort_match(battle['assault_event'],battle['match_id'],reason)

    def finish_assault(self,battle):
        if battle['finished']:return
        points=battle['assault_points'];field=battle['field'];winner=points.outcome(field)
        decisive=battle['assault_groups'][winner] if winner in (0,1) else None
        statistics={}
        for owner,(account,levels,side) in battle['reward_roster'].items():
            values=field.combat.statistics.get(owner,{})
            statistics[account]=dict(kills=values.get('kills',0),deaths=values.get('losses',0),damage_dealt=values.get('damage_dealt',0),damage_taken=values.get('damage_received',0))
        if not battle.get('assault_receipt'):
            battle['assault_receipt']=self.assault_store.settle_match(battle['assault_event'],battle['match_id'],statistics,tuple(points.scores),decisive)
        if winner is None:winner=2 if points.scores[0]==points.scores[1] else int(points.scores[1]>points.scores[0])
        from tio.protocol.assault import TeamResult,PlayerResult,ClanResult,encode_battle_over
        from contextlib import closing
        from tio.db_transaction import connect
        rows=[]
        receipt=battle['assault_receipt']
        for side in (0,1):
            players=[];clan_points={}
            for owner,(account,levels,team) in battle['reward_roster'].items():
                if team!=side:continue
                score=receipt.get('accounts',{}).get(account,{})
                units=score.get('ov_units',0);values=statistics[account]
                players.append(PlayerResult(battle['names'][owner],values['kills'],values['deaths'],units/2))
                clan=score.get('clan_id')
                if clan is not None:clan_points[clan]=clan_points.get(clan,0)+units
            clans=[]
            with closing(connect(self.assault_store.path)) as db:
                for clan,units in clan_points.items():
                    row=db.execute('SELECT name FROM clans WHERE id=?',(clan,)).fetchone()
                    if row:clans.append(ClanResult(bytes(row[0]),0,0,units/2))
            result=0 if winner==2 else (1 if side==winner else 2)
            rows.append(TeamResult(result,points.scores[side],sum(c.assault_points for c in clans),tuple(players),tuple(clans)))
        requests=tuple((o,2 if winner==2 else int(field.teams[o]==winner),False) for o in battle['humans'])
        self.prepare_settlements(battle,requests)
        for owner,result,_ in requests:
            self.settle(battle,owner,result)
            side=field.teams[owner]
            final=encode_battle_over(battle['city_id'],rows[side],rows[1-side])
            battle['result_packets'][owner]=(*battle['result_packets'][owner],final)
            self.put(owner,final)
        battle['finished']=True
        for owner in battle['humans']:
            self.battles.pop(owner,None);self.results.add(owner);self.completed[owner]=battle
