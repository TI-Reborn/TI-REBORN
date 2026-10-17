"""Private introductory scenes on the real shared authoritative hub/journal.

The player uses native loading/move/attack/end-turn/exit requests. Only accepted
actions advance durable lesson facts. Temporary equipment, wounds and practice
statistics never settle into the ordinary save or create economic rewards.
"""
from contextlib import closing
from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
from uuid import uuid4

from tio.db_transaction import connect
from tio.protocol.chat import encode_system_message
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.battle_over import encode_battle_over
from tio.protocol.system_message import encode_shop_error
from tio.protocol.quest_ack import encode_ack
from tio.roster_progression import (TUTORIAL_EVENTS,TUTORIAL_TIPS,tutorial_status,
    tutorial_begin,tutorial_progress,tutorial_leave)

ROOT=Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def rules():
    p=json.loads((ROOT/'config/tutorial.json').read_text(encoding='utf-8'))
    if p['version']!=1 or p['events']!=list(TUTORIAL_EVENTS) or not 1<=p['turn_seconds']<=3600:
        raise ValueError('Invalid tutorial rules')
    if not 1<=p['target_health']<=65535 or not 1<=p['ammo_count']<=65535:raise ValueError('Invalid tutorial equipment')
    if p['dialogue_steps']!=[1002,1004,1023,1004,1018]:raise ValueError('Invalid original tutorial dialogue mapping')
    return p


def tutorial_map():
    from collections import deque
    from tio.arena_map import build_arena_map
    raw=json.loads((ROOT/'config/tutorial_map.json').read_text(encoding='utf-8'));f=raw['fragment']
    w,h=f['width'],f['height']
    blocked={(x,y) for y in range(h) for x in range(w) if f['tiles'][y*w+x] in (2,3,4)}
    blocked-={tuple(d[:2]) for d in f['doors']};blocked.update(map(tuple,f['containers']))
    initial=sorted({(x,y) for y in range(h) for x in range(w)}-blocked)
    if len(initial)<2:raise ValueError('Original tutorial map has no deployment cells')
    provisional=build_arena_map(dict(width=w,height=h,ground_id=0,player_spawns=(initial[0],),bot_spawns=(initial[1],),
        objects=[dict(file='tutorial.s',x=0,y=0)]),{'tutorial.s':f})
    doors={d[:2] for d in provisional.doors};free={(x,y) for y in range(h) for x in range(w)}-set(provisional.blocked)-set(provisional.containers)
    groups=[]
    while free:
        start=min(free);group={start};queue=deque([start]);free.remove(start)
        while queue:
            x,y=queue.popleft()
            for n in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if n in free:free.remove(n);group.add(n);queue.append(n)
        groups.append(group)
    group=max(groups,key=lambda g:(len(g),-min(g)[0],-min(g)[1]))
    candidates=[(x,y) for x,y in group-doors if {(x,y+1),(x+1,y),(x+2,y),(x+3,y),(x+3,y+1)}<=group-doors]
    if not candidates:raise ValueError('Original tutorial map has no connected lesson cells')
    x,y=min(candidates,key=lambda p:((p[0]-10)**2+(p[1]-3)**2,p))
    return replace(provisional,player_spawns=((x,y),),bot_spawns=((x+3,y),))


class TutorialArena:
    def _tutorial_unit(self,battle):
        manager=getattr(self,'journal',None)
        if manager is None:raise ValueError('Вводная миссия требует серверного журнала боёв')
        return manager.unit(battle)

    def tutorial_auto(self,session):
        """After selection/appearance and successful battle-resume check."""
        if getattr(session,'database',None) is None:return False
        state=tutorial_status(session.database,session.account)
        if state is None or state['completed']:return False
        from tio.onboarding import pending
        if pending(session.database,session.account):return False
        self.start_tutorial(session);return True

    def tutorial_command(self,session,text):
        """Explicit emulator chat command; not a guessed original opcode."""
        if text.strip().casefold()!='/tutorial':return False
        state=tutorial_status(session.database,session.account)
        self.start_tutorial(session,replay=state is None or state['completed']);return True

    def start_tutorial(self,session,*,replay=False):
        if type(replay) is not bool:raise ValueError('Invalid tutorial replay mode')
        with self.lock:
            owner=self.identity(session)
            if session.database is None or not session.account:raise ValueError('Требуется сохранённый персонаж')
            if self.busy(session) or self.retained(session.account) or session.arena._fields or session.survival.searching(session.probe_character_id):
                raise ValueError('Сначала завершите текущий бой или поиск')
            if getattr(self,'journal',None) is None:raise ValueError('Вводная миссия требует серверного журнала боёв')
            state=tutorial_status(session.database,session.account)
            if not replay and (state is None or state['completed']):raise ValueError('Вводная миссия недоступна для этого сохранения')
            if state and state['match_id'] is not None:raise ValueError('Сначала восстановите текущую вводную миссию')
            return self.journal.birth(self._prepare_tutorial,owner,replay)

    def _prepare_tutorial(self,owner,replay):
        from tio.arena_service import ArenaService
        from tio.matchmaking import SearchTicket
        from tio.protocol.arena import ArenaCreateRequest
        from tio.team_scene import prepare
        from tio.durability import refresh_template
        session=self.players[owner];p=rules()
        with closing(connect(session.database)) as db:
            row=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(session.account,)).fetchone()
        if row is None or not row[0]:raise ValueError('Нужен главный персонаж')
        pet=decode_pet_info(bytes(row[1]),human_equipment=True).fields
        ticket=SearchTicket(owner,(1,),(pet['0x8c4aef'],),self.clock(),0)
        bot=0x7fffffff
        field,views,ground,skills=prepare(((owner,0,session.database,session.account,ticket,False),
            (bot,1,session.database,session.account,replace(ticket,character_id=bot),True)),0,
            arena_map=tutorial_map(),selected_ids=True,profile='tutorial')
        match=str(uuid4());state=None if replay else tutorial_begin(session.database,session.account,match)
        events=0 if state is None else state['observed_events']
        # Both participants are battle copies. No pet/inventory/proficiency
        # store can receive temporary tutorial changes through persistence.
        field.combat.persistence.clear();field.combat.city_kill_bonus=0
        player=field.actor_ids(owner)[0];target=field.actor_ids(bot)[0]
        item=lambda identity,template,count,equipped=False:ItemRecord(identity,template,b'\0'*2,count,int(equipped),
            16 if equipped else 0,(300,300,300),b'\0'*4,None,b'\0'*3)
        field.combat.inventories[player]=encode_item_list(player,(item(1,p['weapon_template'],1,True),item(2,p['ammo_template'],p['ammo_count'])))
        field.combat.inventories[target]=encode_item_list(target,())
        field._actors[player]=replace(field.actor(player),weapons=field.combat.catalog.equipped(field.combat.inventories[player],human=True),sight_radius=9)
        field._actors[target]=replace(field.actor(target),health=0 if events&8 else p['target_health'],max_health=p['target_health'],action_points=0,weapons=())
        field._turn_points[target]=0
        for view in views.values():
            refresh_template(field.combat,view,player);refresh_template(field.combat,view,target)
        arena=ArenaService(clock=self.clock)
        room=arena.rooms.create(owner,ArenaCreateRequest(0,0,2,2,p['turn_seconds'],1,1,0,0));room=arena.rooms.join(room.room_id,bot)
        arena._fields[room.room_id]=field;arena._loading[room.room_id]={bot};arena._match_ids[room.room_id]=match
        field.scene_metadata['town_id']=3
        battle=dict(kind='tutorial',arena=arena,room=room,field=field,views=views,bots={bot},humans={owner},
            city_id=3,match_id=match,settled=set(),deadline=self.clock()+60,finished=False,ground=ground,
            captain_name=session.probe_character_name,names={owner:session.probe_character_name,bot:b'Training target'},
            result_packets={},reward_roster={owner:(session.account,ticket.levels,0)},reward_damage=set(),reward_support=set(),reward_started=False,
            return_towns={owner:session.locations.current(session.account) if session.locations else 3},
            tutorial_replay=replay,tutorial_events=events,tutorial_target=target,tutorial_player=player)
        self.tickets[owner]=ticket;self.battles[owner]=battle;self.account_owners[session.account]=owner
        session._battle_treatment_ids=None;self.send_scene(owner);self.tutorial_tip(battle,owner)
        return battle

    def tutorial_tip(self,battle,owner,*,welcome=False):
        step=next((i for i in range(4) if not battle['tutorial_events']&(1<<i)),4)
        text='Вводная миссия завершена. Нажмите «Завершить», чтобы вернуться в город.' if step==4 else TUTORIAL_TIPS[step]
        self.put(owner,encode_system_message(3,b'Training',text))
        # Native ACKs require the battle UI to have finished loading. Their
        # Continue button only drains the client queue; accepted gameplay
        # actions remain the sole source of durable lesson progress.
        if owner not in battle['arena']._loading[battle['room'].room_id]:return
        mask=battle['tutorial_events']
        if battle.get('tutorial_dialogue_mask')==mask:return
        initial='tutorial_dialogue_mask' not in battle
        battle['tutorial_dialogue_mask']=mask
        if initial and welcome and not battle.get('tutorial_welcome_sent'):
            self.put(owner,encode_ack(1000));battle['tutorial_welcome_sent']=True
        elif not initial and step<4:self.put(owner,encode_ack(1111))
        self.put(owner,encode_ack(rules()['dialogue_steps'][step]))

    def send_scene(self,owner,*,reconnect=False):
        result=super().send_scene(owner,reconnect=reconnect)
        battle=self.battles.get(owner) or self.completed.get(owner)
        if battle and battle.get('kind')=='tutorial' and reconnect:
            # A new client has an empty native ACK queue. Resume the pending
            # instruction without replaying the welcome or awarding facts.
            battle.pop('tutorial_dialogue_mask',None)
        return result

    def perform_action(self,battle,owner,packet):
        if battle.get('kind')!='tutorial':return super().perform_action(battle,owner,packet)
        with self._tutorial_unit(battle):
            field=battle['field'];arena=battle['arena'];room=battle['room'];before=dict(field._actors)
            turn=arena._turns.get(room.room_id)
            result=super().perform_action(battle,owner,packet)
            events=[]
            if packet[0]==0x3c and any((a.x,a.y)!=(field.actor(i).x,field.actor(i).y) for i,a in before.items() if a.owner_id==owner):events.append('move')
            if packet[0]==0x49:events.append('attack')
            if packet[0]==0x3a:events.append('end_turn')
            target=battle['tutorial_target']
            if before[target].health>0 and field.actor(target).health==0:events.append('enemy_killed')
            changed=False
            for event in events:
                bit=1<<TUTORIAL_EVENTS.index(event)
                if battle['tutorial_events']&bit:continue
                if not battle['tutorial_replay']:
                    tutorial_progress(self.players[owner].database,self.players[owner].account,battle['match_id'],event,observed=True)
                battle['tutorial_events']|=bit;changed=True
            # Ordinary attack removes the final-enemy turn. A short tutorial
            # still accepts the unfinished movement/explicit-end-turn lesson.
            if packet[0]==0x49 and turn is not None and room.room_id not in arena._turns and battle['tutorial_events']!=15:
                arena._turns[room.room_id]=turn
            if changed:self.tutorial_tip(battle,owner)
            if battle['tutorial_events']==15:self.finish_tutorial(battle)
            return result

    def battle_action(self,owner,packet):
        battle=self.battles[owner]
        if battle.get('kind')!='tutorial':return super().battle_action(owner,packet)
        with self._tutorial_unit(battle):
            if packet==b'\x2a\x01':self.abort_tutorial(battle,'participant_left');return
            if packet[:1] not in (b'\x36',b'\x2f',b'\x3a',b'\x3c',b'\x3e',b'\x49') and packet[:2]!=b'\xba\x05':
                raise ValueError('Во вводной миссии используйте движение, стрельбу и завершение хода')
            result=super().battle_action(owner,packet)
            if packet==b'\x36':self.tutorial_tip(battle,owner,welcome=battle['tutorial_events']==0)
            return result

    def tick_battle(self,battle):
        if battle.get('kind')!='tutorial':return super().tick_battle(battle)
        if battle['finished']:return
        with self._tutorial_unit(battle):
            owner=next(iter(battle['humans']));arena=battle['arena'];room=battle['room'];field=battle['field']
            if owner in self.offline:return
            if arena._loading[room.room_id]!=set(room.members):
                if self.clock()>battle['deadline']:self.abort_tutorial(battle,'loading_timeout')
                return
            for target,reply in arena.expire_turns():self.put(target,*arena.finished_turn_packets(target,reply))
            if battle['tutorial_events']==15:self.finish_tutorial(battle);return
            if room.room_id not in arena._turns:
                seconds=rules()['turn_seconds'];battle['full_turn']=(owner,self.clock()+seconds)
                self.begin_shared_turn(battle,owner,seconds)

    def finish_tutorial(self,battle):
        if battle['finished']:return
        if battle['tutorial_events']!=15:raise ValueError('Вводная миссия ещё не завершена')
        with self._tutorial_unit(battle):
            owner=next(iter(battle['humans']));session=self.players[owner]
            if not battle['tutorial_replay']:tutorial_leave(session.database,session.account,battle['match_id'])
            battle['finished']=True;battle['settled'].add(owner)
            battle['arena']._turns.pop(battle['room'].room_id,None)
            replies=(b'\x39',encode_battle_over(1,credits=0,rental_tax=0,soldiers=()))
            battle['result_packets'][owner]=replies;self.put(owner,*replies)
            self.battles.pop(owner,None);self.results.add(owner);self.completed[owner]=battle

    def finish(self,battle):
        if battle.get('kind')=='tutorial':return self.finish_tutorial(battle)
        return super().finish(battle)

    def settle(self,battle,owner,result,*,escaped=False):
        if battle.get('kind')=='tutorial':
            self.abort_tutorial(battle,'expired_or_shutdown');return
        return super().settle(battle,owner,result,escaped=escaped)

    def prepare_settlements(self,battle,requests):
        if battle.get('kind')=='tutorial':return
        return super().prepare_settlements(battle,requests)

    def to_city(self,owner):
        tutorial=self.completed.get(owner,{}).get('kind')=='tutorial'
        result=super().to_city(owner)
        if tutorial:self.players[owner]._battle_treatment_ids=None
        return result

    def abort_tutorial(self,battle,reason):
        if battle['finished']:return
        with self._tutorial_unit(battle):
            for owner in tuple(battle['humans']):
                session=self.players[owner]
                if not battle['tutorial_replay']:tutorial_leave(session.database,session.account,battle['match_id'])
                battle['arena']._turns.pop(battle['room'].room_id,None)
                self.battles.pop(owner,None);self.tickets.pop(owner,None);battle['finished']=True;battle['settled'].add(owner)
                self.put(owner,encode_system_message(3,b'Training','Тренировку можно продолжить командой /tutorial.'))
                self.to_city(owner)
            battle['humans'].clear()
