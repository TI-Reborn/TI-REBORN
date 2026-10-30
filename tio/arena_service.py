"""Arena rooms, authenticated actions, turn scheduling and local battle settlement.

Classic team training uses recovered settings/member packets. Unknown settings,
bot filling and first-turn order remain explicit local policies; no wagers.
"""

from .db_transaction import connect
from .arena_rooms import ArenaRooms
from .protocol.arena import BattleSettings, decode_create_request, encode_battle_settings_body
from .protocol.battle_members import BattleMemberRecord, encode_battle_members
from .protocol.arena import decode_room_ready
from dataclasses import replace
from collections.abc import Callable, Iterable
import time
from .turn_repeats import END_TURN_REPEAT_SECONDS, within_end_turn_repeat


class ArenaService:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._settlement_inputs={}
        self.rooms = ArenaRooms()
        self._records = {}
        self._loading = {}
        self._turns = {}
        self._fields = {}
        self._last_turn = {}
        self._match_ids = {}
        self._completed = set()
        self._return_towns = {}
        self._return_maps = {}
        self._map_returned = set()
        self._scene_headers = {}
        self._turn_finish_effects = {}
        self._end_turn_fences: dict[int, float] = {}

    def start_survival(self, character_id, name, prepared, *, existing_room=None):
        """Server-created training match; preparation must finish before entry.

        No create-room packet is accepted from the player for this path.
        The bot is already loaded; the human still acknowledges with36.
        """
        from .protocol.arena import ArenaCreateRequest
        from .protocol.battle_ground import decode_battle_ground
        from .battle_modes import mode_rules
        mode=getattr(prepared,'mode',0)
        policy=mode_rules(mode)
        members=getattr(prepared,'participants',()) or (character_id,prepared.bot_owner)
        if len(members)!=policy.players or members[0]!=character_id or len(set(members))!=len(members):
            raise ValueError('Invalid prepared participants')
        if existing_room is not None and (existing_room.members not in ((character_id,),members) or existing_room.request.mode!=mode or existing_room.room_id in self._loading):
            raise ValueError('Only a waiting training room can start')
        if any(set(members)&set(r.members) for r in self.rooms.snapshot() if r!=existing_room):
            raise ValueError('Match participant already belongs to a room')
        selected = prepared.field.actor_ids(character_id)
        opponents = prepared.field.actor_ids(prepared.bot_owner)
        if set(selected) != set(prepared.actor_ids) or not 1 <= len(selected) <= 3 or (len(opponents) != len(selected) and mode!=7):
            raise ValueError('Invalid prepared survival participants')
        policy.validate(len(selected))
        if mode!=7 and any(len(prepared.field.actor_ids(owner))!=len(selected) for owner in members):
            raise ValueError('Unbalanced prepared teams')
        if mode and any(prepared.field.teams.get(owner)!=index%2 for index,owner in enumerate(members)):
            raise ValueError('Invalid prepared team assignments')
        packets = tuple(prepared.packets)
        if not packets or packets[-1] != b'\x41' or any(not isinstance(p,bytes) or not 0<len(p)<=65533 for p in packets):
            raise ValueError('Invalid prepared survival scene')
        ground = decode_battle_ground(packets[0])
        if (ground.width,ground.height) != (prepared.field.width,prepared.field.height):
            raise ValueError('Scene dimensions do not match authoritative field')
        seconds=20*len(selected)+20 if mode else 40
        request = ArenaCreateRequest(mode,0,policy.players,2,seconds,len(selected),len(selected),0,0)
        settings = BattleSettings(1,policy.players,mode,seconds,2,name,bytes((0,0,len(selected),0,1)),0,0)
        records = tuple(BattleMemberRecord(owner,name if owner==character_id else
                       getattr(prepared.field,'enemy_name',(b'Training bot' if not mode else (b'Ally ' if index%2==0 else b'Enemy ')+str(index//2+1).encode())),
                       0,bytes((1,1,index,index%2,1,1))) for index,owner in enumerate(members))
        replies = (b'\x6c'+encode_battle_settings_body(settings),encode_battle_members(mode,0,records),*packets)
        room = existing_room or self.rooms.create(character_id,request)
        try:
            for owner in members[1:]:room = self.rooms.join(room.room_id,owner)
        except Exception:
            self.rooms.leave(character_id)
            raise
        self._records.update({r.character_id:r for r in records})
        self._loading[room.room_id] = set(members[1:])
        self._fields[room.room_id] = prepared.field
        self._scene_headers[room.room_id] = replies[:3]
        prepared.field.result_view=getattr(prepared,'visibility',None)
        from uuid import uuid4
        self._match_ids[room.room_id]=str(uuid4())
        from .ranks import refresh
        for path,account in set(getattr(getattr(prepared.field,'combat',None),'persistence',{}).values()):
            refresh(path,account,active=True)
        self._completed.discard(character_id)
        self._return_towns[character_id]=getattr(prepared.field,'return_town',3)
        self._map_returned.discard(character_id)
        if hasattr(prepared.field,'return_position'):
            self._return_maps[character_id]=prepared.field.return_position
        else:self._return_maps.pop(character_id,None)
        return room, replies

    def fill_training_room(self, room):
        """Fill local classic team rooms; bots are explicitly named in the UI."""
        from .battle_modes import mode_rules
        policy=mode_rules(room.request.mode)
        if room.request.mode not in (1,4) or room.members!=(room.owner_id,):
            raise ValueError('Expected an empty classic team room')
        source=self._records[room.owner_id]
        bots=tuple(0x7fffffff-i for i in range(policy.players-1))
        if room.owner_id in bots or any(set(bots)&set(r.members) for r in self.rooms.snapshot()):
            raise ValueError('Reserved bot owner collision')
        self._records[room.owner_id]=replace(source,unknown_bytes=bytes((source.average_level,source.level,0,0,1,1)))
        for index,owner in enumerate(bots,1):
            room=self.rooms.join(room.room_id,owner)
            self._records[owner]=replace(source,character_id=owner,
                name=(b'Ally ' if index%2==0 else b'Enemy ')+str(index//2+1).encode(),
                unknown_bytes=bytes((source.average_level,source.level,index,index%2,1,1)))
        return room,encode_battle_members(room.request.mode,0,tuple(self._records[m] for m in room.members))

    def finish_training(self,character_id,path,account):
        """Settle only a server-created match with at most one living side."""
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        if room is None or room.room_id not in self._match_ids:return ()
        field=self._fields[room.room_id]
        practice=getattr(field,'practice',None)
        if practice is not None:
            from .shooting_range import POLICY
            last_round=(room.room_id in self._last_turn and room.room_id not in self._turns and
                        max(field._ability_turns[i] for i in field.actor_ids(character_id))>=POLICY['max_turns'])
            if not practice.complete() and not last_round:return ()
            from .protocol.battle_over import SoldierExperience,encode_battle_over
            from .protocol.pet_info import decode_pet_info
            from .weapon_proficiency import SAVED,BASE
            from .protocol.asset_count import encode_asset_count
            from .wallets import WalletStore
            combat=field.combat;soldiers=[]
            for identity in field.actor_ids(character_id):
                human=combat.human[identity]
                before=decode_pet_info(combat.initial_proficiencies[identity],human_equipment=human).fields
                after=decode_pet_info(combat.proficiencies[identity],human_equipment=human).fields
                soldiers.append(SoldierExperience(identity,0,tuple(before[BASE[i]] for i in (0,1,4,3,2,5,7)),
                                                  tuple(after[k] for pair in zip(SAVED,BASE) for k in pair)))
            replies=(b'\x39',encode_asset_count(WalletStore(path).ensure(account)),
                     encode_battle_over(1,soldiers=soldiers))
            self.disconnect(room.owner_id)
            self._completed.add(character_id)
            return replies
        alive=field.living_sides()
        mining=getattr(field,'mining',None)
        if mining is not None:
            if field.living_actor_ids(character_id) and mining.extracted_amount is None:
                # Merely killing mutants does not extract resources or end mining.
                return ()
            result=int(mining.extracted_amount is not None)
        else:
            if len(alive)>1:return ()
            result=2 if not alive else int(field.side(character_id) in alive)
        from .protocol.battle_over import encode_battle_over
        from .protocol.asset_count import encode_asset_count
        from .battle_rewards import receipt
        statistics=getattr(getattr(field,'combat',None),'statistics',{}).get(character_id,{})
        # Validate statistic widths before committing money/ranks/wounds.
        encode_battle_over(result,**statistics)
        units=getattr(getattr(field,'combat',None),'rental_tax_units',{})
        # Do not leave the combat turn active if settlement needs a retry.
        self._turns.pop(room.room_id,None)
        self._last_turn.pop(room.room_id,None)
        # Only persistent actors belong to the account; mirrored bots never do.
        persistent=getattr(getattr(field,'combat',None),'persistence',{})
        from .combat_completion import settlement_health
        health={i:settlement_health(field.combat,i) for i,a in field._actors.items() if a.owner_id==character_id and i in persistent}
        from .ranks import battle_report
        combat=getattr(field,'combat',None)
        report=battle_report(combat,character_id) if combat is not None else None
        match_id=self._match_ids[room.room_id]
        from .player_statistics import battle_report as statistics_report
        assets=self.settle_final(path,account,match_id,result,health=health,rank_report=report,
                      statistics_report=statistics_report(combat,character_id) if combat is not None else None,
                      experience_report=combat.experience.report(combat,character_id) if combat is not None else None,
                      achievement_report=combat.achievements.report(field,character_id,room.request.mode) if combat is not None else None,
                      encounter_report=getattr(field,'encounter_report',None),
                      mined_crystals=None if mining is None else (mining.extracted_amount or 0),
                      rental_units=tuple(units.get(i,0) for i,a in field._actors.items() if a.owner_id==character_id))
        self.encounter_return(field,character_id,result,health)
        gross,tax=receipt(path,account,match_id)
        from .level_progression import result_packets
        updates,experience=result_packets(path,account,match_id,combat,getattr(field,'result_view',None)) if combat is not None else ((),())
        summary=encode_battle_over(result,credits=gross,rental_tax=tax,soldiers=experience,**statistics)
        bags=()
        if getattr(field,'encounter_report',{}).get('loot_version')==1 and result==1:
            from .owned_pets import OwnedPetStore
            bags=tuple(inv for identity,pet,inv in OwnedPetStore(path).list(account) if identity in persistent)
        replies=(b'\x39',encode_asset_count(assets),*updates,*bags,summary)
        self.disconnect(room.owner_id)
        self._completed.add(character_id)
        self._match_ids.pop(room.room_id,None)
        return replies

    def encounter_return(self,field,character_id,result,health):
        if getattr(field,'encounter_report',None) is not None and result!=1 and health and not any(health.values()):
            from .locations import nearest_city,center
            town=nearest_city(*field.return_position)
            self._return_towns[character_id]=town
            self._return_maps[character_id]=center(town)

    def finish_results(self,character_id,packet):
        from .protocol.arena import validate_room_leave
        from .protocol.system_message import encode_finish_battle_view,encode_current_town,encode_open_town_view
        validate_room_leave(packet)
        if character_id not in self._completed:return None
        if character_id in self._return_maps:
            from .locations import leave_town_packet,stop_packet,town_at,town_packets
            self._map_returned.add(character_id)
            point=self._return_maps[character_id];town=town_at(*point)
            arrival=town_packets(town) if town is not None else ()
            return (encode_finish_battle_view(),leave_town_packet(),stop_packet(character_id,*point),*arrival)
        # Retain acknowledgement state: repeated clicks must repeat only the
        # view transition, never settlement. Cleared when a new match starts.
        return (encode_finish_battle_view(),encode_current_town(self._return_towns.get(character_id,3)),encode_open_town_view())

    def city_roster_refresh(self,character_id,packet,path,account):
        """Reload saved pets after the client's scene/panel transition request."""
        if character_id not in self._completed:return ()
        if any(character_id in r.members for r in self.rooms.snapshot()):return ()
        if not (packet==b'\x4a\xff\xff\xff\xff' or
                (len(packet)==2 and packet[0]==0x50)):return ()
        from .owned_pets import OwnedPetStore
        return tuple(p for _,pet,inventory in OwnedPetStore(path).list(account) for p in (pet,inventory))

    def inventory_packets(self, character_id, actor_ids):
        """Return the current own battle bags, or None outside a combat scene.

        An empty tuple is intentional for requests for opponents or reserves;
        the transport must not fall back to city inventories in that case.
        """
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        combat=getattr(field,'combat',None)
        if combat is None:return None
        owned=set(field.actor_ids(character_id))
        return tuple(combat.inventory_packet(i) for i in dict.fromkeys(actor_ids)
                     if i in owned and i in combat.inventories)

    def skill_list_packets(self, character_id, packet):
        """Answer C8/12 with an own fighter's current battle skills, or None.

        The client requests this list on battle entry and draws its skill bar
        from the reply. None outside a combat scene lets the city handler
        answer from saved ranks; opponents and reserves get no list.
        """
        from .protocol.abilities import decode_skill_list_request,encode_abilities
        from .weapon_effects import battle_skills
        actor_id=decode_skill_list_request(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        combat=getattr(field,'combat',None)
        if combat is None:return None
        if actor_id not in field.actor_ids(character_id) or actor_id not in combat.inventories:return ()
        # Saved ranks plus Groza27 for the current equipment. Mine radio28 is
        # a mine feature, not a bar skill: the original skills.xml defines
        # CallHelpFromBase with hide=1, so it never belongs on this bar.
        entries=battle_skills(combat.learned.get(actor_id,()),combat.inventories[actor_id],combat.human[actor_id])
        return (encode_abilities(actor_id,tuple(e for e in entries if e.ability_id!=28)),)

    def next_turn_owner(self, room_id):
        """Local round-robin policy; return (recipient, packet) notifications.

        Called by the server after end/expiration; no client-supplied next owner.
        Transport must deliver these packets to their individual recipients.
        """
        room=next((r for r in self.rooms.snapshot() if r.room_id==room_id),None)
        if room is None or room_id not in self._last_turn:
            raise ValueError('No completed turn for this room')
        if room_id in self._turns:raise ValueError('A turn is already active')
        field=self._fields.get(room_id)
        if field is None:raise ValueError('Battle field is not initialized')
        previous=self._last_turn[room_id]
        start=room.members.index(previous)+1 if previous in room.members else 0
        order=room.members[start:]+room.members[:start]
        for member in order:
            actors=field.living_actor_ids(member)
            if actors:
                return member
        raise ValueError('No participants with actors remain')

    def advance_turn(self, room_id, seconds):
        member=self.next_turn_owner(room_id)
        actors=self._fields[room_id].living_actor_ids(member)
        return tuple((member,p) for p in self.begin_turn_packets(member,actors,seconds))

    def configure_field(self, character_id, field):
        """Attach server-prepared movement state once, before the first turn."""
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        if room is None or room.owner_id != character_id or room.room_id not in self._loading:
            raise ValueError('Owner must start scene loading first')
        if room.room_id in self._fields or room.room_id in self._turns:
            raise ValueError('Battle field already initialized')
        self._fields[room.room_id]=field

    def cast_healing(self,character_id,packet,*,with_packets=False):
        """Validate turn authority before using prepared server skill rules.

        With packets returns HP, AP and skill state notifications. Native
        serializers/model stores are verified; live transport remains separate.
        """
        from .protocol.ability_cast import decode_ability_cast
        request=decode_ability_cast(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if request.actor_id not in turn[1]:raise ValueError('Actor is not selected for this turn')
        field=self._fields.get(room.room_id)
        if field is None:raise ValueError('Battle state is not initialized')
        return field.cast_healing(character_id,request,with_packets=with_packets)

    def cast_ability(self,character_id,packet,*,view=None):
        from .protocol.ability_cast import decode_ability_cast
        request=decode_ability_cast(packet)
        if request.ability_id not in (9,12,22,26,27):return self.cast_healing(character_id,packet,with_packets=True)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:raise ValueError('Character does not own an active turn')
        if request.actor_id not in turn[1]:raise ValueError('Actor not selected for turn')
        field=self._fields.get(room.room_id)
        if field is None or not hasattr(field,'combat'):raise ValueError('Combat not prepared')
        if request.ability_id==9:
            from .sniper_scope import cast
            replies=cast(field.combat,character_id,request,view=view)
        elif request.ability_id==12:
            from .dog_abilities import cast_scent
            replies=cast_scent(field,character_id,request)
        elif request.ability_id==26:replies=field.combat.cast_deathbite(character_id,request,view=view)
        elif request.ability_id==27:replies=field.combat.cast_subgrenade(character_id,request,view=view)
        else:replies=field.combat.cast_slash(character_id,request,view=view)
        if len(field.living_sides())<=1 and not hasattr(field,'mining'):
            self._turns.pop(room.room_id,None);self._last_turn.pop(room.room_id,None)
        return replies

    def door_action(self,character_id,packet,*,view=None):
        from .protocol.battle_door import decode_door_request
        request=decode_door_request(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if request.actor_id not in turn[1]:raise ValueError('Actor not selected for turn')
        if field is None or not hasattr(field,'doors'):raise ValueError('Battle doors are not prepared')
        return field.doors.change(character_id,request,view=view)

    def loot_action(self,character_id,packet,*,view=None):
        from .protocol.battle_position import decode_position_request
        from .protocol.battle_loot import decode_loot_transfer
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        request=decode_position_request(packet) if packet[:1]==b'\x46' else decode_loot_transfer(packet,allow_empty=hasattr(field,'mining'))
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if request.actor_id not in turn[1]:raise ValueError('Actor not selected for turn')
        if field is None or not hasattr(field,'loot'):raise ValueError('Battle containers are not prepared')
        generation=field._ability_turns[request.actor_id]
        if packet[:1]==b'\x46':return field.loot.open(character_id,request,generation,view=view)
        return field.loot.transfer(character_id,request,generation,view=view)

    def exchange_action(self,character_id,packet,*,view=None):
        from .protocol.battle_exchange import decode_exchange
        from .battle_exchange import exchange
        request=decode_exchange(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Обмен доступен только в свой ход')
        if request.actor_id not in turn[1] or request.target_id not in turn[1]:
            raise ValueError('Оба бойца должны участвовать в текущем ходе')
        if field is None or not hasattr(field,'loot'):raise ValueError('Battle inventory not prepared')
        return exchange(field.combat,character_id,request,field._ability_turns[request.actor_id])

    def equip(self,character_id,packet,*,view=None):
        from .protocol.item_action import decode_item_action
        request=decode_item_action(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        if field is None or not hasattr(field,'combat'):return None
        turn=self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if request.pet_id not in turn[1]:raise ValueError('Actor not selected for turn')
        from .combat import MEDICAL_ITEMS
        from .protocol.item_list import decode_item_list
        items=decode_item_list(field.combat.inventories.get(request.pet_id,b''))[1]
        from .durability import KITS
        kit=next((i for i in items if i.instance_id==request.instance_id and i.template_id in KITS),None)
        if kit is not None:
            if kit.unknown_words[0]<=0:raise ValueError('Ремкомплект израсходован')
            from .protocol.repair import repair_message
            field.combat.repair_selections[character_id]=(request.pet_id,request.instance_id)
            return (repair_message(110),)
        if hasattr(field,'mining') and any(i.instance_id==request.instance_id and i.template_id==52 for i in items):
            return field.mining.install(character_id,request)
        if any(i.instance_id==request.instance_id and i.template_id in MEDICAL_ITEMS for i in items):
            return field.combat.use_medical(character_id,request)
        from .battle_item_effects import handles_use,use
        selected=next((i for i in items if i.instance_id==request.instance_id),None)
        if selected is not None and handles_use(selected.template_id):
            return use(field.combat,character_id,request)
        points=field.actor(request.pet_id).action_points
        inventory=field.combat.equip(character_id,request,view=view)
        if field.actor(request.pet_id).action_points!=points:
            from .protocol.action_points import encode_action_points
            return (inventory,encode_action_points(request.pet_id,field.actor(request.pet_id).action_points),*field.combat.skill_packets(request.pet_id))
        return (inventory,*field.combat.skill_packets(request.pet_id))

    def equipment_batch(self,character_id,packet,*,view=None):
        from .arena_equipment import action
        return action(self,character_id,packet,view=view)

    def repair(self,character_id,packet,*,view=None):
        from .protocol.repair import decode_repair
        identity,_=decode_repair(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if identity not in turn[1]:raise ValueError('Actor not selected for turn')
        field=self._fields[room.room_id]
        return field.combat.repair(character_id,packet)

    def swap_weapons(self,character_id,packet,*,view=None):
        from .protocol.binary import Reader
        r=Reader(packet)
        if r.u8()!=0x6d:raise ValueError('Expected weapon swap6D')
        actor_id=r.u32();r.finish()
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if actor_id not in turn[1]:raise ValueError('Actor not selected for turn')
        field=self._fields.get(room.room_id)
        if field is None or not hasattr(field,'combat'):raise ValueError('Combat not prepared')
        replies=field.combat.swap_weapons(character_id,actor_id,view=view)
        return (*replies,*field.combat.skill_packets(actor_id))

    def attack(self,character_id,packet,*,view=None):
        from .protocol.battle_attack import decode_attack_request
        request=decode_attack_request(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if request.actor_id not in turn[1]:raise ValueError('Actor not selected for turn')
        field=self._fields.get(room.room_id)
        if field is None or not hasattr(field,'combat'):raise ValueError('Combat not prepared')
        replies=field.combat.attack(character_id,request,view=view)
        if len(field.living_sides())<=1 and not hasattr(field,'mining'):
            self._turns.pop(room.room_id,None)
            self._last_turn.pop(room.room_id,None)
        return replies

    def move(self, character_id, packet):
        from .protocol.battle_move import decode_move_request
        request=decode_move_request(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if request.actor_id not in turn[1]:
            raise ValueError('Actor is not selected for this turn')
        field=self._fields.get(room.room_id)
        if field is None:raise ValueError('Movement state is not initialized')
        before=dict(field._actors)
        combat=getattr(field,'combat',None)
        state=combat.rng.getstate() if combat is not None and hasattr(combat.rng,'getstate') else None
        try:
            reply=field.move(character_id,request)
            from .protocol.battle_move import decode_battle_move
            effects=() if combat is None else combat.after_move(request.actor_id,decode_battle_move(reply).path)
        except Exception:
            field._actors=before
            if state is not None:combat.rng.setstate(state)
            raise
        return (reply,*effects) if effects else reply

    def mine_action(self,character_id,packet,*,view=None):
        from .protocol.battle_mines import decode_mine_deploy
        request=decode_mine_deploy(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        if turn is None or turn[0]!=character_id or self._clock()>=turn[2]:
            raise ValueError('Character does not own an active turn')
        if request.actor_id not in turn[1]:raise ValueError('Actor is not selected for this turn')
        field=self._fields.get(room.room_id)
        if field is None or not hasattr(field,'combat'):raise ValueError('Combat is not prepared')
        return field.combat.deploy_mine(character_id,request,view=view)

    def rejected_mine_packets(self,character_id,packet):
        """Native failed-deployment state clears the client's placement action."""
        from .protocol.battle_mines import decode_mine_deploy,MineDeployed,encode_mine_deployed
        try:request=decode_mine_deploy(packet)
        except ValueError:return ()
        template=0
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        if field is not None and hasattr(field,'combat'):
            actor=field._actors.get(request.actor_id)
            if actor is not None and actor.owner_id==character_id:
                from .protocol.item_list import decode_item_list
                items=decode_item_list(field.combat.inventories[actor.actor_id])[1]
                template=next((i.template_id for i in items if i.instance_id==request.instance_id),0)
        return (encode_mine_deployed(MineDeployed(request.actor_id,request.x,request.y,template,4)),)

    def begin_turn(self, character_id: int, actor_ids: Iterable[int], seconds: int) -> bytes:
        from .protocol.battle_turn import encode_your_turn
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        if room is None or self._loading.get(room.room_id)!=set(room.members):
            raise ValueError('Room has not finished loading')
        if room.room_id in self._turns:raise ValueError('A turn is already active')
        actors=frozenset(actor_ids)
        if not actors or any(not isinstance(i,int) or not 0<i<=0xffffffff for i in actors):
            raise ValueError('Server-owned actor IDs required')
        if not 1<=seconds<=3600:raise ValueError('Unsupported turn duration')
        reply=encode_your_turn(seconds)
        deadline=self._clock()+seconds
        field=self._fields.get(room.room_id)
        if field is not None:
            field.prepare_turn(character_id,sorted(actors))
        if room.room_id in self._end_turn_fences:
            # A queued legacy skip can arrive only after the next turn starts.
            self._end_turn_fences[room.room_id] = self._clock() + END_TURN_REPEAT_SECONDS
        self._turns[room.room_id]=(character_id,actors,deadline)
        return reply

    def begin_turn_packets(self, character_id, actor_ids, seconds):
        """Send restored AP before enabling input with YourTurn."""
        from .protocol.action_points import encode_action_points
        actors=tuple(sorted(set(actor_ids)))
        reply=self.begin_turn(character_id,actors,seconds)
        room=next(r for r in self.rooms.snapshot() if character_id in r.members)
        field=self._fields.get(room.room_id)
        updates=() if field is None else tuple(encode_action_points(i,field.actor(i).action_points) for i in actors)
        skills=() if field is None else field.ability_status_packets(character_id,actors)
        combat=None if field is None else getattr(field,'combat',None)
        effects=() if combat is None else combat.turn_effects(character_id,actors)
        # Burns can kill or reduce an actor after the turn budget was restored.
        updates=() if field is None else tuple(encode_action_points(i,field.actor(i).action_points) for i in actors)
        weights=() if combat is None else tuple(p for i in actors if (p:=combat.weight_packet(i)) is not None)
        mining=getattr(field,'mining',None)
        extraction=() if mining is None or getattr(mining,'shared',False) or character_id!=mining.owner else mining.advance(max(field._ability_turns[i] for i in actors))
        return (*effects,*updates,*weights,*skills,*extraction,reply)

    def end_turn(self, character_id: int, packet: bytes, *,
                 received_at: float | None = None) -> bytes | None:
        """Finish an owned turn, or ignore a recent range skip repeat."""
        from .protocol.battle_turn import decode_end_turn,encode_your_turn_finished
        actor=decode_end_turn(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        turn=None if room is None else self._turns.get(room.room_id)
        field = None if room is None else self._fields.get(room.room_id)
        if getattr(field, 'practice', None) is not None:
            if actor and actor not in field.actor_ids(character_id):
                raise ValueError('Actor does not belong to the turn owner')
            fence = self._end_turn_fences.get(room.room_id)
            # The transport timestamps recv(), before expensive journal work.
            # All frames received together belong to the same bounded tail,
            # even when dispatch of the third frame happens after its expiry.
            if received_at is None:
                repeat = within_end_turn_repeat(fence or 0, self._clock())
            else:
                repeat = fence is not None and received_at < fence
            if repeat:
                return None
        if turn is None or turn[0]!=character_id:raise ValueError('Character does not own the current turn')
        if self._clock()>=turn[2]:raise ValueError('Turn deadline has expired')
        if actor and actor not in turn[1]:raise ValueError('Actor does not belong to the turn owner')
        reply=encode_your_turn_finished()
        self.clear_finished_ap(room.room_id,turn)
        del self._turns[room.room_id]
        self._last_turn[room.room_id]=character_id
        return reply

    def clear_finished_ap(self, room_id: int, turn: tuple[int, frozenset[int], float]) -> None:
        from dataclasses import replace
        field=self._fields.get(room_id)
        if field is not None:
            if getattr(field, 'practice', None) is not None:
                self._end_turn_fences[room_id] = self._clock() + END_TURN_REPEAT_SECONDS
            from .battle_item_effects import end_turn
            combat=getattr(field,'combat',None)
            effect_actors=turn[1] if getattr(field,'battle_mode',None)==21 else field.actor_ids(turn[0])
            self._turn_finish_effects[turn[0]]=() if combat is None else end_turn(combat,turn[0],effect_actors)
            for identity in field.living_actor_ids(turn[0]):
                field._actors[identity]=replace(field.actor(identity),action_points=0)

    def finished_turn_packets(self, character_id: int, reply: bytes | None = b'\x39') -> tuple[bytes, ...]:
        """Clear displayed AP before native TurnFinished disables battle input."""
        if reply is None:
            # A repeat must not disable input/AP or tick effects on the new turn.
            return ()
        from .protocol.action_points import encode_action_points
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        field=None if room is None else self._fields.get(room.room_id)
        updates=() if field is None else tuple(encode_action_points(i,0) for i in field.actor_ids(character_id))
        combat=getattr(field,'combat',None)
        restores=() if combat is None else combat.cancel_equipment_batch(character_id)
        from .battle_item_effects import end_turn
        effects=self._turn_finish_effects.pop(character_id,None)
        if effects is None:effects=() if combat is None else end_turn(combat,character_id,field.actor_ids(character_id))
        return (*restores,*effects,*updates,reply)

    def expire_turns(self):
        """Return addressed finish notifications exactly once per expired turn."""
        from .protocol.battle_turn import encode_your_turn_finished
        now=self._clock()
        expired=[(room_id,turn) for room_id,turn in self._turns.items() if now>=turn[2]]
        replies=tuple((turn[0],encode_your_turn_finished()) for _,turn in expired)
        for room_id,turn in expired:
            self.clear_finished_ap(room_id,turn)
            del self._turns[room_id]
            self._last_turn[room_id]=turn[0]
        return replies

    def start_loading(self, character_id, packet, prepare):
        """Authorize Start and commit loading only after scene preparation succeeds.

        prepare(room) supplies the complete scene packet sequence. This tracks
        loading, not turns/combat. Returned packets are sent by the transport.
        """
        from .protocol.arena import decode_room_start
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        if room is None or room.owner_id != character_id:
            raise ValueError('Only the room owner can start loading')
        decode_room_start(packet,mode=room.request.mode)
        if room.room_id in self._loading:
            return ()
        if any(member != character_id and not self._records[member].ready for member in room.members):
            raise ValueError('All other members must be ready')
        replies=tuple(prepare(room))
        if any(not isinstance(p,bytes) or not 0<len(p)<=65533 for p in replies):
            raise ValueError('Invalid scene packet')
        if len(replies)<2 or replies[0][:1]!=b'\x35' or replies[-1]!=b'\x41':
            raise ValueError('Scene requires ground35 and load-end41')
        from .protocol.battle_ground import decode_battle_ground
        decode_battle_ground(replies[0])
        self._loading[room.room_id]=set()
        return replies

    def member_loaded(self, character_id, packet):
        from .protocol.battle_loaded import validate_battle_loaded, encode_member_loaded
        validate_battle_loaded(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        if room is None or room.room_id not in self._loading:
            raise ValueError('Character is not loading a scene')
        loaded=self._loading[room.room_id]
        if character_id in loaded:return ()
        reply=encode_member_loaded(character_id)
        loaded.add(character_id)
        return (reply,)

    def create(self, character_id: int, name: bytes, packet: bytes, *, roster=()):
        request = decode_create_request(packet)
        if request.mode not in (0, 1, 4, 8):
            raise ValueError('Unsupported create mode')
        if not 1 <= request.soldiers_count_01 <= 3 or request.soldiers_count_02 != request.soldiers_count_01:
            raise ValueError('Unsupported soldier selection')
        if request.mode in (1,4):
            from .battle_modes import mode_rules
            policy=mode_rules(request.mode)
            policy.validate(request.soldiers_count_01)
            if request.players_count!=policy.players:raise ValueError('Incorrect classic team size')
            from .matchmaking import SurvivalQueue
            from .battle_modes import level_band
            roster=tuple(roster)
            ticket=SurvivalQueue().join(character_id,roster,mode=request.mode)
            if len(ticket.actors)!=request.soldiers_count_01:raise ValueError('Selected squad differs from room settings')
            if len({level_band(level) for level in ticket.levels})!=1:raise ValueError('Fighters must share a level range')
        from .arena_roster import room_soldiers
        soldiers=room_soldiers(roster,request.soldiers_count_01)
        # Local profile, not a claim about original unknown field semantics:
        # unknown40=1 matches live diagnostic; unknown1f=2, levels=0/0,
        # Native edge exit is enabled; internal room ID is not unknown40.
        # Time follows the create-form formula pending original server evidence.
        seconds = 20 * request.soldiers_count_01 + 20
        settings = BattleSettings(1, request.players_count, request.mode, seconds, 2,
                                  name, bytes((0, 0, request.soldiers_count_01, request.map_size, 1)),
                                  request.stake, 0)
        replies = (b'\x6c' + encode_battle_settings_body(settings),
                   encode_battle_members(request.mode, 0, (BattleMemberRecord(character_id, name, 0, bytes((0, 0, 0, 0, 0, 1)),soldiers),)))
        # Validate and serialize before changing room membership.
        room = self.rooms.create(character_id, request)
        from .protocol.battle_members import decode_battle_members
        self._records.setdefault(character_id, decode_battle_members(replies[1])[2][0])
        replies=(replies[0],encode_battle_members(request.mode,0,tuple(self._records[member] for member in room.members)))
        return room, replies

    def set_ready(self, character_id, packet):
        ready=decode_room_ready(packet)
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        if room is None: raise ValueError('Character is not in a room')
        if room.room_id in self._loading:raise ValueError('Room is already loading')
        record=self._records[character_id]
        raw=bytearray(record.unknown_bytes);raw[4]=int(ready)
        updated=replace(record,unknown_bytes=bytes(raw))
        records=tuple(updated if member==character_id else self._records[member] for member in room.members)
        reply=encode_battle_members(room.request.mode,1,records)
        self._records[character_id]=updated
        return reply

    def disconnect(self, character_id):
        for field in self._fields.values():
            combat=getattr(field,'combat',None)
            if combat is not None:combat.cancel_equipment_batch(character_id,forget_receipts=True)
        self.forfeit(character_id)
        affected=self.rooms.leave(character_id)
        live_rooms={room.room_id for room in self.rooms.snapshot()}
        self._match_ids={i:value for i,value in self._match_ids.items() if i in live_rooms}
        live_matches=set(self._match_ids.values())
        self._settlement_inputs={key:value for key,value in self._settlement_inputs.items() if key[0] in live_matches}
        self._scene_headers={i:value for i,value in self._scene_headers.items() if i in live_rooms}
        # A departing guest can own the first turn: preserve its position in the
        # rotation even when no earlier turn has ended normally.
        for room_id,turn in self._turns.items():
            if room_id in live_rooms and turn[0]==character_id:
                self._last_turn[room_id]=character_id
        self._loading={room_id:loaded-{character_id} for room_id,loaded in self._loading.items() if room_id in live_rooms}
        self._turns={room_id:turn for room_id,turn in self._turns.items() if room_id in live_rooms and turn[0]!=character_id}
        self._fields={room_id:field for room_id,field in self._fields.items() if room_id in live_rooms}
        for field in self._fields.values():
            field.remove_owner(character_id)
        self._last_turn={room_id:owner for room_id,owner in self._last_turn.items() if room_id in live_rooms}
        self._end_turn_fences = {room_id: deadline for room_id, deadline in self._end_turn_fences.items()
                                 if room_id in live_rooms}
        remaining={member for room in self.rooms.snapshot() for member in room.members}
        for member in affected:
            if member not in remaining:self._records.pop(member,None)
        return affected

    def settle_final(self,path,account,match_id,result,**kwargs):
        from . import battle_settlement
        key=(match_id,account)
        if key not in self._settlement_inputs:
            kwargs['now']=time.time()
            self._settlement_inputs[key]=(result,kwargs)
        saved,report=self._settlement_inputs[key]
        if saved!=result:raise ValueError('Conflicting frozen private battle result')
        battle_settlement.enqueue(path,match_id,((account,result,report),))
        return battle_settlement.apply(path,match_id,account)

    def forfeit(self,character_id):
        """Unfinished battle: survivors flee; dead actors keep their death result.

        A completed result has already been journalled; settle is idempotent.
        Waiting rooms/probe scenes contain no persistent match and cost nothing.
        """
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        if room is None or room.room_id not in self._match_ids:return
        combat=getattr(self._fields.get(room.room_id),'combat',None)
        if combat is None:return
        if hasattr(combat.field,'practice'):
            # Ammunition/skill already persisted per shot; practice has no PvP settlement.
            self._completed.add(character_id)
            return
        from .ranks import battle_report
        from contextlib import closing
        import sqlite3
        report=battle_report(combat,character_id)
        if not report:return
        stores={combat.persistence[i] for i in report}
        if len(stores)!=1:raise ValueError('Mixed persistent battle accounts')
        path,account=stores.pop()
        with closing(connect(path)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_rewards'").fetchone() and db.execute(
                    'SELECT 1 FROM battle_rewards WHERE match_id=? AND account=?',(self._match_ids[room.room_id],account)).fetchone():return
        from .player_statistics import battle_report as statistics_report
        from .combat_completion import settlement_health
        match=self._match_ids[room.room_id]
        cached=self._settlement_inputs.get((match,account))
        if cached is not None:
            self.settle_final(path,account,match,cached[0],**cached[1])
        else:self.settle_final(path,account,match,0,rank_report=report,escaped=True,
               encounter_report=getattr(combat.field,'encounter_report',None),
               statistics_report=statistics_report(combat,character_id),
               experience_report=combat.experience.report(combat,character_id),
               achievement_report=combat.achievements.report(combat.field,character_id,room.request.mode),
               health={i:settlement_health(combat,i) for i in report})
        self.encounter_return(combat.field,character_id,cached[0] if cached else 0,
                              cached[1].get('health') if cached else {i:settlement_health(combat,i) for i in report})
        # The following town/panel request must reload the changed rank fields,
        # just as after an ordinary result (native scene teardown is asynchronous).
        self._completed.add(character_id)

    def disconnect_packets(self, character_id):
        """Disconnect and return actor removals addressed to surviving members.

        Owner departure closes the room under the current room policy; its
        return-to-city sequence is separate from these surviving-room packets.
        """
        from .protocol.battle_remove import encode_battle_remove
        room=next((r for r in self.rooms.snapshot() if character_id in r.members),None)
        replies=()
        if room is not None and room.owner_id != character_id:
            field=self._fields.get(room.room_id)
            actors=() if field is None else field.actor_ids(character_id)
            replies=tuple((member,encode_battle_remove(actor))
                          for member in room.members if member != character_id
                          for actor in actors)
        self.disconnect(character_id)
        return replies

    def require_exit(self, character_id: int) -> None:
        room = next((r for r in self.rooms.snapshot() if character_id in r.members), None)
        field = None if room is None else self._fields.get(room.room_id)
        if (field is not None and character_id not in self._completed
                and self._loading.get(room.room_id) == set(room.members)
                and not field.can_exit(character_id)
                and not (hasattr(field, 'mining') and field.mining.at_exit(character_id))):
            raise ValueError('Для выхода подведите всех живых бойцов своего отряда к краю карты')

    def leave(self, character_id, packet):
        from .protocol.arena import validate_room_leave
        from .protocol.system_message import encode_leave_room
        validate_room_leave(packet)
        self.require_exit(character_id)
        reply=encode_leave_room()
        self.disconnect(character_id)
        return reply  # repeat leave is harmless and still clears stale client UI


# Every authoritative private-scene mutation participates in its checkpoint.
# Shared scenes instead use the hub's enclosing unit.
from .arena_equipment import inventory_mutation
for _name in ('equip','repair','swap_weapons','attack','move','mine_action','cast_ability',
              'loot_action','exchange_action'):
    setattr(ArenaService,_name,inventory_mutation(getattr(ArenaService,_name)))
from server.battle_journal import private_method
for _name in ('start_survival','fill_training_room','finish_training','finish_results',
    'configure_field','cast_healing','cast_ability','door_action','loot_action','exchange_action',
    'equip','equipment_batch','repair','swap_weapons','attack','move','mine_action','begin_turn','begin_turn_packets','end_turn',
    'finished_turn_packets','expire_turns','start_loading','member_loaded','disconnect','settle_final','forfeit','leave'):
    setattr(ArenaService,_name,private_method(getattr(ArenaService,_name)))
