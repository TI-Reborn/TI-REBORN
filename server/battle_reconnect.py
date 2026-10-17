"""Bounded, account-bound reconnection to the existing authoritative PvP battle.

No replay of actions and no regeneration of maps, inventories or turns. An
offline player remains targetable. Deadlines use the hub's monotonic clock.
Graceful shutdown settles battles; the battle journal restores process crashes.
"""
from collections import deque
from dataclasses import replace
import logging
from .failure_policy import storage_failure

from tio.protocol.arena import BattleSettings,encode_battle_settings_body
from tio.protocol.battle_members import BattleMemberRecord,encode_battle_members
from tio.protocol.battle_turn import encode_turn_now,encode_your_turn,encode_members_arranged
from tio.protocol.known_mines import encode_known_mines
from tio.visibility import VisibilityView

LOG=logging.getLogger('tio.server')
RECONNECT_SECONDS=180
RELOAD_SECONDS=30


class BattleReconnect:
    def _init_reconnect(self):
        self.offline={};self.returning={};self.account_owners={};self.completed={}
        self.private={}

    def retained(self,account):
        with self.lock:
            owner=self.account_owners.get(account)
            return owner in self.battles or owner in self.completed or account in self.private

    def resume(self,session):
        with self.lock:
            self.expire_reconnects()
            if session.account in self.private:
                if getattr(self.private[session.account][0].arena,'_faulted',False):
                    raise ValueError('Результат предыдущего боя ещё сохраняется')
                self.resume_private(session)
                return True
            owner=self.account_owners.get(session.account)
            if owner is None or owner not in self.offline:return False
            if owner not in self.battles and owner not in self.completed:return False
            if self.battles.get(owner,{}).get('faulted'):
                raise ValueError('Результат предыдущего боя ещё сохраняется')
            self.players[owner]=session;self.identities[session]=owner
            self.offline.pop(owner);self.queues[owner]=deque()
            self.returning[owner]=self.clock()+RELOAD_SECONDS
            self.send_scene(owner,reconnect=True)
            self.notify_online(self.battles.get(owner) or self.completed[owner],exclude=owner)
            LOG.info('battle_reconnected account=%s owner=%d',session.account,owner)
            return True

    def send_scene(self,owner,*,reconnect=False):
        battle=self.battles.get(owner) or self.completed[owner]
        s=self.players[owner];field=self.mine_result_field(battle,owner);room=battle['room']
        if reconnect:
            field.combat.cancel_equipment_batch(owner,forget_receipts=True)
            old=battle['views'][owner]
            view=VisibilityView(field,owner,dict(old.templates))
            # Send current visible door/loot states, not merely changes since
            # the disconnected client's old scene.
            view.door_states={}
            battle['views'][owner]=view
            for identity in field.actor_ids(owner):field.loot.sessions.pop(identity,None)
            field.combat.repair_selections.pop(owner,None)
        view=battle['views'][owner]
        if view.field is not field:
            view=VisibilityView(field,owner,dict(view.templates));battle['views'][owner]=view
        if hasattr(field,'mining'):field.mining.sent_deposits.pop(owner,None)
        settings=BattleSettings(1,len(room.members),room.request.mode,room.request.unknown_u32_01,2,
            battle['captain_name'],bytes((0,0,room.request.soldiers_count_01,0,0)),0,0)
        if battle.get('kind')=='wager':
            r=battle['wager_request']
            settings=BattleSettings(1,len(room.members),r.mode,r.unknown_u32_01,2,
                battle['captain_name'],bytes((0,0,r.soldiers_count_01,r.map_size,0)),r.stake,0)
        from tio.protocol.abilities import encode_abilities
        from tio.weapon_effects import battle_skills
        skills=tuple(encode_abilities(i,battle_skills(field.combat.learned.get(i,()),field.combat.inventories[i],field.combat.human[i]))
                     for i in field.actor_ids(owner))
        self.put(owner,b'\x6c'+encode_battle_settings_body(settings),self.battle_members_packet(battle,owner),
            *self.tactical_mark_packets(battle,owner),self.battle_order_packet(battle,owner),battle['ground'])
        self.put(owner,*view.refresh(),*skills,
            *(field.combat.inventory_packet(i) for i in field.actor_ids(owner)),*field.combat.hazard_packets(owner),*self.ranked_packets(battle,owner,scene=True),*self.mine_scene_flags(battle,owner),*self.assault_packets(battle,owner),b'\x41')

    def restore_turn(self,battle,owner):
        arena=battle['arena'];room=battle['room'];field=battle['field']
        turn=arena._turns.get(room.room_id)
        if turn is None:return
        full=battle.get('full_turn')
        if turn[0]==owner and full and full[0]==owner and self.clock()<turn[2]:
            # Restore the original absolute deadline, never give extra time.
            arena._turns[room.room_id]=(turn[0],turn[1],max(turn[2],full[1]))
            turn=arena._turns[room.room_id]
        remaining=max(0,int(turn[2]-self.clock()))
        if 'points' in battle:
            from tio.protocol.ranked import encode_turn
            self.put(owner,encode_turn(field.teams[turn[0]],self.players[owner].probe_character_id if turn[0]==owner else turn[0],next(iter(turn[1]))))
        self.put(owner,*field.ability_status_packets(owner,field.actor_ids(owner)))
        if turn[0]==owner and remaining:
            self.put(owner,encode_your_turn(remaining))
        else:self.put(owner,b'\x39',encode_turn_now(turn[0],remaining))

    def detach(self,session,owner):
        if owner not in self.battles and owner not in self.completed:return False
        self.offline[owner]=self.clock()+RECONNECT_SECONDS
        self.returning.pop(owner,None);self.queues[owner].clear()
        self.identities.pop(session,None)
        self.account_owners[session.account]=owner
        if owner in self.battles:
            b=self.battles[owner];arena=b['arena'];room=b['room']
            b['field'].combat.exchange_sessions.pop(owner,None)
            b['field'].combat.cancel_equipment_batch(owner,forget_receipts=True)
            # A disconnected loader must not hold every other participant.
            arena._loading[room.room_id].add(owner)
            turn=arena._turns.get(room.room_id)
            if turn and turn[0]==owner:
                b.setdefault('full_turn',(owner,turn[2]))
                deadline=min(turn[2],self.clock()+max(0,turn[2]-self.clock())/2)
                arena._turns[room.room_id]=(turn[0],turn[1],deadline)
                self.announce_turn(b,owner,max(0,int(deadline-self.clock())))
        LOG.info('battle_disconnected account=%s owner=%d grace=%d',session.account,owner,RECONNECT_SECONDS)
        self.notify_online(self.battles.get(owner) or self.completed[owner],exclude=owner)
        journal=getattr(self,'journal',None)
        if journal is not None:
            with journal.unit(self.battles.get(owner) or self.completed[owner]):pass
        return True

    def battle_members_packet(self,battle,viewer,update=False):
        room=battle['room'];field=battle['field'];session=self.players[viewer]
        records=tuple(BattleMemberRecord(session.probe_character_id if m==viewer else m,
            battle['names'][m],0,bytes((1,1,i,field.teams[m],1,int(m not in self.offline))))
            for i,m in enumerate(room.members))
        return encode_battle_members(room.request.mode,int(update),records)

    def notify_online(self,battle,exclude=None):
        for target in battle['humans']:
            if target!=exclude and (self.battles.get(target) is battle or self.completed.get(target) is battle):
                self.put(target,self.battle_members_packet(battle,target,True),self.battle_order_packet(battle,target))

    def battle_order_packet(self,battle,viewer):
        # Match the authoritative interleaved turn sequence, using the viewer's
        # local character ID exactly as BattleMemberList does.
        session=self.players[viewer]
        return encode_members_arranged(session.probe_character_id if owner==viewer else owner
            for owner in battle['room'].members)

    def retain_private(self,session):
        if not getattr(session,'account',None) or not getattr(session,'arena',None):return False
        if not session.arena._fields:return False
        if not all(i in session.arena._scene_headers for i in session.arena._fields):return False
        if getattr(session.arena,'_faulted',False):return True
        self.private[session.account]=(session,self.clock()+RECONNECT_SECONDS)
        manager=getattr(session.arena,'_durable',None)
        for field in session.arena._fields.values():
            field.combat.cancel_equipment_batch(session.probe_character_id,forget_receipts=True)
        if manager is not None:
            manager.offline_until=manager.wall()+RECONNECT_SECONDS
            with manager.unit():pass
        LOG.info('private_battle_disconnected account=%s',session.account)
        return True

    def resume_private(self,session):
        old,_=self.private.pop(session.account)
        for name in ('arena','training_matches','visibility_views'):
            setattr(session,name,getattr(old,name))
        for name in ('mining','shooting_range','encounters'):
            if getattr(session,name,None) is not None:getattr(session,name).arena=session.arena
        manager=getattr(session.arena,'_durable',None)
        if manager is not None:
            manager.session=session;manager.offline_until=None;manager.attach()
        owner=session.probe_character_id
        room=next(r for r in session.arena.rooms.snapshot() if owner in r.members)
        field=session.arena._fields[room.room_id]
        previous=session.visibility_views[room.room_id]
        view=VisibilityView(field,owner,dict(previous.templates));view.door_states={}
        session.visibility_views[room.room_id]=view;field.result_view=view
        field.combat.repair_selections.pop(owner,None)
        field.combat.exchange_sessions.pop(owner,None)
        field.combat.cancel_equipment_batch(owner,forget_receipts=True)
        for identity in field.actor_ids(owner):field.loot.sessions.pop(identity,None)
        from tio.protocol.abilities import encode_abilities
        from tio.weapon_effects import battle_skills
        skills=tuple(encode_abilities(i,battle_skills(field.combat.learned.get(i,()),field.combat.inventories[i],field.combat.human[i])) for i in field.actor_ids(owner))
        mining=getattr(field,'mining',None)
        explored=tuple(mining.sent_deposits.get(owner,{}).values()) if mining is not None else ()
        session.private_resume_packets=(*session.arena._scene_headers[room.room_id],*explored,*view.refresh(),*skills,
            *(field.combat.inventory_packet(i) for i in field.actor_ids(owner)),*field.combat.hazard_packets(owner),b'\x41')
        session.private_resume_loading=self.clock()+RELOAD_SECONDS
        LOG.info('private_battle_reconnected account=%s',session.account)

    def private_resume_pump(self,session,game,reader,cipher,encode_reply):
        import socket
        if self.clock()>=session.private_resume_loading:raise TimeoutError('Battle reload timed out')
        game.settimeout(.1)
        try:data=game.recv(65535)
        except socket.timeout as exc:
            if exc.errno is not None:raise
            return
        if not data:raise EOFError('Battle reload disconnected')
        owner=session.probe_character_id
        for packet in reader.feed(data):
            replies=()
            if packet==b'\x70':replies=(b'\x9e',)
            elif packet==b'\x36':
                arena=session.arena;room=next(r for r in arena.rooms.snapshot() if owner in r.members)
                field=arena._fields[room.room_id]
                replies=arena.member_loaded(owner,packet)
                if room.room_id not in arena._turns and room.room_id not in arena._last_turn and field.living_actor_ids(owner):
                    from tio.protocol.battle_turn import turn_seconds
                    replies+=arena.begin_turn_packets(owner,field.living_actor_ids(owner),turn_seconds(len(field.living_actor_ids(owner))))
                turn=arena._turns.get(room.room_id)
                replies+=field.ability_status_packets(owner,field.actor_ids(owner))
                if turn and turn[0]==owner and turn[2]>arena._clock():
                    replies+=(encode_your_turn(max(1,int(turn[2]-arena._clock()))),)
                else:replies+=(b'\x39',)
                session.private_resume_loading=False
            elif packet[:1]==b'\x2f':
                from tio.protocol.item_list import decode_item_list_request
                replies=session.arena.inventory_packets(owner,decode_item_list_request(packet)) or ()
            for reply in replies:game.sendall(encode_reply(reply,cipher))

    def forget(self,owner):
        self.wager_listing_cache.pop(owner,None)
        self.ranked_waiting.pop(owner,None)
        session=self.players.pop(owner,None)
        if session is not None:
            self.identities.pop(session,None)
            if self.account_owners.get(session.account)==owner:self.account_owners.pop(session.account,None)
        self.offline.pop(owner,None);self.returning.pop(owner,None);self.completed.pop(owner,None)
        self.results.discard(owner);self.tickets.pop(owner,None);self.queues.pop(owner,None)

    def expire_reconnects(self):
        now=self.clock()
        for account,(session,deadline) in tuple(self.private.items()):
            if now>=deadline:
                try:self.finish_private(session)
                except Exception as error:
                    if storage_failure(error):raise
                    self.fail_private(session,error)
                else:self.private.pop(account,None)
        for owner,deadline in tuple(self.returning.items()):
            if now>=deadline:
                self.returning.pop(owner,None)
                self.players[owner].stop()
        for owner,deadline in tuple(self.offline.items()):
            if now<deadline:continue
            if owner in self.battles:
                b=self.battles[owner]
                if b.get('faulted'):continue
                try:
                    if b.get('kind') == 'contract':
                        self.abort_contract(b, 'reconnect_timeout')
                        self.forget(owner)
                        continue
                    if 'points' in b:b['ranked_winner']=1-b['field'].teams[owner]
                    self.settle(b,owner,0,escaped=True)
                    self.remove_from_battle(b,owner)
                except Exception as error:
                    if storage_failure(error):raise
                    self.quarantine(b,error)
                    continue
            LOG.info('battle_reconnect_expired owner=%d',owner)
            self.forget(owner)

    def shutdown_battles(self):
        """Preserve pending HP/XP/ranks exactly once on a planned service stop."""
        with self.lock:
            self.stop_wagers()
            for battle in {id(b):b for b in self.battles.values()}.values():
                owners=tuple(battle['humans'])
                try:
                    if battle.get('kind') == 'contract':
                        self.abort_contract(battle, 'graceful_shutdown')
                        continue
                    if battle.get('kind')=='wager':
                        battle.setdefault('wager_report',dict(version=1,winner_side=None,refund_reason='graceful_shutdown'))
                    self.abort_assault(battle,'graceful_shutdown')
                    if self.team_rating_report(battle) is None:
                        self.cancel_team_rating(battle,'graceful_shutdown')
                    requests=tuple((o,battle.get('settlement_inputs',{}).get(o,(0,))[0],True) for o in owners)
                    self.prepare_settlements(battle,requests)
                    for owner,result,_ in requests:self.settle(battle,owner,result,escaped=True)
                    for owner in owners:self.remove_from_battle(battle,owner)
                except Exception as error:
                    if storage_failure(error):raise
                    self.quarantine(battle,error)
            for owner in tuple(self.offline):self.forget(owner)
            for session,_ in tuple(self.private.values()):
                try:self.finish_private(session)
                except Exception as error:
                    if storage_failure(error):raise
                    self.fail_private(session,error)
            self.private.clear()
