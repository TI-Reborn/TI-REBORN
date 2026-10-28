"""Bounded loopback experiment for the statically recovered initial challenge."""
import json
import sqlite3
import zlib
import socket
import threading
import time
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tio.protocol.transport import InitialChallenge,InitialCipher,InitialFrameReader,encode_initial_challenge,encode_initial_frame,decode_initial_reply,expected_reply_fields
from tio.protocol.transport import InitialCompletion,encode_initial_completion
from tio.protocol.login import decode_basic_login_request,transform_auth_value,encode_login_success,encode_login_failure
from tio.protocol.binary import PacketError
from server.auth_errors import LoginRejected

from tio.protocol.server_list import ServerList,ServerEntry,encode_server_list,decode_server_list_request

from tio.protocol.server_login import decode_server_login_request,encode_server_login_result

from tio.protocol.mode1 import derive_mode1_key,encode_mode1_challenge_frame,decode_mode1_reply,encode_mode1_completion

from tio.protocol.auth2 import decode_auth2_request,encode_auth2_result

from tio.protocol.character_select import encode_empty_character_list,CharacterRecord,encode_character_list

from tio.protocol.city_services import city_service_reply
from tio.protocol.item_list import decode_item_list_request,encode_empty_item_list
from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore, STARTING_CREDITS, STARTING_GOLD
from tio.protocol.asset_count import AssetCount, encode_asset_count
from tio.shop import PurchaseResult, ShopStore, WarehousePurchaseResult
from tio.equipment import equip_primary_weapon
from tio.shop_errors import shop_error_reply
from tio.roster_progression import RecruitmentStore as HireStore
from tio.arena_service import ArenaService
from tio.protocol.hire import decode_hire_request,decode_dismiss_request
from tio.protocol.city_catalogs import encode_pet_shop
from tio.protocol.shop_purchase import decode_shop_purchase
from tio.protocol.shop_sale import decode_sale_request, encode_sale_quote
from tio.protocol.system_message import encode_current_town, encode_open_town_view
from tio.protocol.town_info import encode_town_info, diagnostic_town_info
from tio.protocol.world_bootstrap import SelectResult,MyCharInfo,encode_select_result,encode_mychar_info
from tio.protocol.shared_config import SharedConfigEntry,SharedConfigData,encode_shared_config_set,encode_shared_config_data

class LoopbackExchange:
    account = 'probe_user'
    router = None
    completion_token = 0x11223344
    initial_challenge = InitialChallenge(0,0x12345678,0,0xabcdef01)
    mode1_handoff = None
    def __init__(self, output, completion=False,login_result=False,server_list=False,server_entry=False,server_login=False,mode1_challenge=False,mode1_complete=False,auth2_result=False,empty_characters=False,character_record=False,shared_config=False,create_probe=False,create_success_probe=False,select_probe=False,mychar_probe=False,inspect_window=False,town_probe=False,enter_town_probe=False,open_town_probe=False,observation_seconds=None,database=None,owned_pet_probe=False,battle_settings_probe=False,*,listener=None,advertised_address='127.0.0.1',router=None):
        self.output=output
        self.router=router
        self.advertised_address=socket.inet_aton(advertised_address)
        self.external_listener=listener is not None
        self.quiet=False
        self.failure=None
        self.owned_pet_probe=owned_pet_probe
        self.battle_settings_probe=battle_settings_probe
        self.battle_members_probe=False
        self.battle_scene_probe=False
        self.battle_actor_probe=False
        self.arena=ArenaService()
        from tio.survival_service import SurvivalService
        self.survival=SurvivalService()
        self.training_matches={}
        self.visibility_views={}
        self.failed_searches=set()
        self._achievement_city_confirmed=False
        self.hiring=None
        self.ability_learning=None
        self.database=Path(database) if database is not None else None
        self._economy_inventory_snapshot: tuple[bytes, ...] | None = None
        self._economy_inventory_identity: tuple[str, str] | None = None
        from tio.squad import SquadStore
        self.squad=SquadStore(self.database) if self.database is not None else None
        from tio.locations import LocationStore
        self.locations=LocationStore(self.database) if self.database is not None else None
        contracts = getattr(self.router, 'contracts', None)
        if contracts is not None and self.locations is not None:
            self.locations = contracts.locations(self.locations)
        from tio.mining_service import MiningService
        self.mining=MiningService(self.database,self.arena,self.locations) if self.database is not None else None
        from tio.world_encounters import EncounterService
        self.encounters=EncounterService(self.database,self.arena,self.locations) if self.database is not None else None
        from tio.shooting_range import ShootingRangeService
        self.shooting_range=ShootingRangeService(self.database,self.arena,self.locations) if self.database is not None else None
        if self.shooting_range is not None and self.router is None:self.shooting_range.admission.assets(self.account)
        self.completion=completion
        self.login_result=login_result
        self.server_list=server_list
        self.server_entry=server_entry
        self.server_login=server_login
        self.mode1_challenge=mode1_challenge
        self.mode1_complete=mode1_complete
        self.auth2_result=auth2_result
        self.empty_characters=empty_characters
        self.character_record=character_record
        self.shared_config=shared_config
        self.create_probe=create_probe
        self.create_success_probe=create_success_probe
        self.select_probe=select_probe
        self.mychar_probe=mychar_probe
        self.town_probe=town_probe
        self.enter_town_probe=enter_town_probe
        self.open_town_probe=open_town_probe
        self.catalogs=CityCatalogs(Path(__file__).resolve().parents[1]/"config/city_catalogs.json") if open_town_probe else None
        if observation_seconds is not None and (type(observation_seconds) is not int or not 0 <= observation_seconds <= 3600):
            raise ValueError("Observation duration must be 0..3600 seconds (0 means unlimited)")
        self.observation_seconds=observation_seconds
        self.inspect_window=inspect_window
        self.events=[]
        self.stopping=threading.Event()
        self.connections=[]
        self.listener=listener if listener is not None else socket.socket()
        if not self.external_listener:
            self.listener.bind(('127.0.0.1',0))
            self.listener.listen(1)
            self.listener.settimeout(20)
        self.port=self.listener.getsockname()[1]
        self.thread=threading.Thread(target=self.run,daemon=True)

    def start(self): self.thread.start()

    def run(self):
        try:
            with self.accept_connection() as conn:
                conn.settimeout(5)
                self.events.append({'event':'accepted'})
                challenge=self.initial_challenge
                payload=encode_initial_challenge(challenge)
                outbound=InitialCipher('S2C')
                outbound.language=getattr(self,'language','russian')
                frame=encode_initial_frame(payload,outbound)
                conn.sendall(frame)
                self.events.append({'direction':'S2C','stage':'transport_challenge','raw_hex':frame.hex(),'plain_hex':payload.hex()})
                reader=InitialFrameReader(InitialCipher('C2S'))
                data,packets=self.receive_frame(conn,reader)
                self.events.append({'direction':'C2S','stage':'transport_reply','raw_hex':data.hex()})
                reply=decode_initial_reply(packets[0])
                self.events[-1]['plain_hex']=packets[0].hex()
                if (reply.transformed_u32_01,reply.transformed_u32_02)!=expected_reply_fields(challenge):
                    raise ValueError('Native challenge reply mismatch')
                self.events.append({'event':'native_challenge_reply_verified'})
                if self.completion:
                    plain=encode_initial_completion(InitialCompletion(0,0,self.completion_token))
                    frame=encode_initial_frame(plain,outbound)
                    conn.sendall(frame)
                    self.events.append({'direction':'S2C','stage':'transport_completion','raw_hex':frame.hex(),'plain_hex':plain.hex()})
                    try:
                        data,received=self.receive_frame(conn,reader)
                        self.events.append({'direction':'C2S','stage':'after_completion','raw_hex':data.hex(),'packets_hex':[p.hex() for p in received]})
                        if self.login_result:
                            packets=self.events[-1]['packets_hex']
                            if len(packets)!=1: raise ValueError('Expected one login request')
                            packet=bytes.fromhex(packets[0])
                            try: login=decode_basic_login_request(packet)
                            except PacketError:
                                if self.router is not None:
                                    self.router.login_protocol_rejected(self,packet[0] if packet else -1)
                                raise
                            if login.transformed_auth_u32!=transform_auth_value(self.completion_token):
                                raise ValueError('Login challenge mismatch')
                            if self.router is not None:
                                try: self.account=self.router.authorize(self,login)
                                except LoginRejected as denial:
                                    self.router.login_rejected(self,login,denial)
                                    conn.sendall(encode_initial_frame(encode_login_failure(denial.status),outbound))
                                    self.events.append({'event':'login_rejected','category':denial.category})
                                    return
                                self.shooting_range.admission.assets(self.account)
                            elif (login.login_bytes,login.password_bytes)!=(b'probe_user',b'probe_password'):
                                raise ValueError('Synthetic login validation failed')
                            self.events.append({'event':'synthetic_login_verified'})
                            plain=encode_login_success();frame=encode_initial_frame(plain,outbound)
                            conn.sendall(frame)
                            self.events.append({'direction':'S2C','stage':'login_success','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                            data,received=self.receive_frame(conn,reader)
                            self.events.append({'direction':'C2S','stage':'after_login_success','raw_hex':data.hex(),'packets_hex':[p.hex() for p in received]})
                            if self.server_list:
                                self.send_server_list(conn,outbound,received[0])
                                if self.server_login:
                                    deadline=time.monotonic()+300;choices=[]
                                    while True:
                                        if not choices:
                                            data,choices=self.receive_choice(conn,reader,outbound,deadline=deadline,allow_batch=True)
                                        choice=choices.pop(0)
                                        if choice[:1]==b'\x05':
                                            self.send_server_list(conn,outbound,choice)
                                            continue
                                        if choices:raise ValueError('Unexpected request after server selection')
                                        received=[choice]
                                        break
                                    login=decode_server_login_request(received[0])
                                    if login.server_id!=1: raise ValueError('Unexpected selected server ID')
                                    self.events.append({'direction':'C2S','stage':'server_login','plain_hex':received[0].hex(),'raw_hex':data.hex()})
                                    if self.router is not None:self.router.expect_game(self,reply.transformed_u32_02)
                                    plain=encode_server_login_result(0);frame=encode_initial_frame(plain,outbound);conn.sendall(frame)
                                    self.events.append({'direction':'S2C','stage':'server_login_success','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                                    if self.router is None:self.listener.settimeout(5)
                                    with self.accept_connection() as game:
                                        self.events.append({'event':'second_connection_accepted'})
                                        if self.mode1_challenge:
                                            seed=self.mode1_handoff[0] if self.mode1_handoff else bytes(range(8))
                                            frame=encode_mode1_challenge_frame(seed)
                                            if self.mode1_handoff is None:game.sendall(frame)
                                            self.events.append({'direction':'S2C','stage':'mode1_challenge','raw_hex':frame.hex(),'plain_hex':frame[2:].hex()})
                                            if self.mode1_handoff is None:
                                                game_reader=InitialFrameReader(InitialCipher('C2S',derive_mode1_key(seed)))
                                                data,packets=self.receive_frame(game,game_reader)
                                            else:
                                                _,game_reader,data,packets=self.mode1_handoff
                                            result=decode_mode1_reply(packets[0])
                                            self.events.append({'direction':'C2S','stage':'mode1_reply','raw_hex':data.hex(),'plain_hex':packets[0].hex()})
                                            if (result.previous_transport_u32,result.completion_u32)!=(reply.transformed_u32_02,self.completion_token):
                                                raise ValueError('Mode1 reply does not match earlier transport values')
                                            self.events.append({'event':'mode1_reply_verified','key_after_hex':game_reader.cipher.key.hex()})
                                            if self.mode1_complete:
                                                game_outbound=InitialCipher('S2C',derive_mode1_key(seed))
                                                game_outbound.language=getattr(self,'language','russian')
                                                plain=encode_mode1_completion(0);frame=encode_initial_frame(plain,game_outbound)
                                                game.sendall(frame)
                                                self.events.append({'direction':'S2C','stage':'mode1_completion','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                                                data,packets=self.receive_frame(game,game_reader)
                                                self.events.append({'direction':'C2S','stage':'after_mode1_completion','raw_hex':data.hex(),'packets_hex':[p.hex() for p in packets]})
                                                if self.auth2_result:
                                                    auth=decode_auth2_request(packets[0])
                                                    if auth.server_list_trailing_bytes!=b'':raise ValueError('Unexpected trailing06 echo')
                                                    self.events.append({'event':'auth2_request_decoded','unknown_string_01_hex':auth.unknown_string_01.hex(),'server_list_trailing_hex':auth.server_list_trailing_bytes.hex()})
                                                    plain=encode_auth2_result(0);frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                    if self.router is not None:self.router.game_authenticated(self)
                                                    self.events.append({'direction':'S2C','stage':'auth2_success','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                                                    if self.shared_config:
                                                        self.deliver_shared_config(game,game_reader,game_outbound)
                                                        self.deliver_shared_config(game,game_reader,game_outbound,b'skills')
                                                        if self.mychar_probe:self.deliver_shared_config(game,game_reader,game_outbound,b'zones')
                                                        if self.router is not None:self.deliver_shared_config(game,game_reader,game_outbound,b'customization')
                                                        if self.router is not None:self.deliver_shared_config(game,game_reader,game_outbound,b'premiumaccount')
                                                        if self.router is not None:self.deliver_shared_config(game,game_reader,game_outbound,b'services')
                                                    session_records=()
                                                    if self.database is not None:
                                                        from tio.characters import CharacterStore
                                                        self.database.parent.mkdir(parents=True,exist_ok=True)
                                                        session_records=CharacterStore(self.database).list(self.account)
                                                        self.events.append({'event':'saved_characters_loaded','database':str(self.database),'count':len(session_records)})
                                                    if self.empty_characters or self.character_record:
                                                        if self.router is not None:
                                                            from tio.onboarding import pending_owner,prepare,OPEN_APPEARANCE
                                                            self._creation_owner=pending_owner(self.database,self.account)
                                                            if self._creation_owner:
                                                                prepare(self.database,self._creation_owner)
                                                                character_store=CharacterStore(self.database)
                                                                session_records=tuple(record for record in character_store.list(self.account)
                                                                    if character_store.owner(self.account,record.record_id)==self._creation_owner)
                                                                game.sendall(encode_initial_frame(OPEN_APPEARANCE,game_outbound))
                                                        if self.character_record:
                                                            session_records=(CharacterRecord(7,b'Probe',1,0,0,0,0,b'',(0,)*19,0,0,0),)
                                                        plain=encode_character_list(session_records)
                                                        frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                        self.events.append({'direction':'S2C','stage':'character_list','record_count':len(session_records),'plain_hex':plain.hex(),'raw_hex':frame.hex()})

                                                    if self.create_probe and not session_records:
                                                        from tio.protocol.character_create import decode_character_create,encode_character_create_result
                                                        raw,received=self.receive_choice(game,game_reader,game_outbound)
                                                        request=decode_character_create(received[0])
                                                        if request.name_bytes!=(b'ProbeNew' if self.create_success_probe else b'1') or request.unknown_u16!=0 or request.options!=(0,0,0,0):
                                                            raise ValueError('Unexpected synthetic character create request')
                                                        self.events.append({'direction':'C2S','stage':'character_create','plain_hex':received[0].hex(),'raw_hex':raw.hex()})
                                                        if self.create_success_probe:
                                                            from tio.characters import CharacterStore
                                                            database=self.database or self.output.parent/'characters.sqlite3'
                                                            store=CharacterStore(database)
                                                            records=store.create(self.account,request)
                                                            restored=CharacterStore(database).list(self.account)
                                                            if restored!=records:raise ValueError('Persisted character reload mismatch')
                                                            self.events.append({'event':'character_persisted_and_reloaded','database':str(database),'record_id':records[0].record_id})
                                                            ack=encode_character_create_result(0)
                                                            ack_frame=encode_initial_frame(ack,game_outbound);game.sendall(ack_frame)
                                                            self.events.append({'direction':'S2C','stage':'character_create_default_status_trial','plain_hex':ack.hex(),'raw_hex':ack_frame.hex()})
                                                            session_records=restored
                                                            plain=encode_character_list(restored)
                                                        else:
                                                            plain=encode_character_create_result(4)
                                                        frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                        self.events.append({'direction':'S2C','stage':'character_create_list_trial' if self.create_success_probe else 'character_create_invalid_name','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                                                    if self.select_probe:
                                                        if self.router is not None:
                                                            session_records,raw,packets=self.choose_character(game,game_reader,game_outbound)
                                                        else:
                                                            raw,packets=self.receive_choice(game,game_reader,game_outbound)
                                                        self.events.append({'direction':'C2S','stage':'character_select','raw_hex':raw.hex(),'packets_hex':[p.hex() for p in packets]})
                                                        if self.router is None and packets!=[bytes.fromhex('1701000000')]:raise ValueError('Unexpected character selection request')
                                                        plain=encode_select_result(SelectResult(0,0,0));frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                        self.events.append({'direction':'S2C','stage':'character_select_result','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                                                    if self.mychar_probe:
                                                        raw,packets=self.receive_frame(game,game_reader)
                                                        self.events.append({'direction':'C2S','stage':'mychar_request','packets_hex':[p.hex() for p in packets]})
                                                        if packets!=[b'\x19']:raise ValueError('Expected19')
                                                        self.probe_character_id=session_records[0].record_id if session_records else 1
                                                        self.probe_character_name=session_records[0].name_bytes if session_records else b'ProbeNew'
                                                        from tio.locations import center, MAP_SPEED
                                                        if self.locations:self.locations.refresh(self.account,self.probe_character_id)
                                                        town=self.locations.current(self.account) if self.locations else 3
                                                        x,y=self.locations.position(self.account) if self.locations else center(3)
                                                        plain=encode_mychar_info(MyCharInfo(self.probe_character_id,self.probe_character_name,MAP_SPEED,x&0xffffffff,y&0xffffffff,0))
                                                        frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                        self.events.append({'direction':'S2C','stage':'mychar_info','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                                                        assets = WalletStore(self.database).ensure(self.account) if self.database is not None else AssetCount(STARTING_CREDITS, STARTING_GOLD)
                                                        plain = encode_asset_count(assets)
                                                        game.sendall(encode_initial_frame(plain, game_outbound))
                                                        self.events.append({'direction':'S2C','stage':'asset_count','credits':assets.credits,'gold':assets.gold,'plain_hex':plain.hex()})
                                                    if self.town_probe and (not self.locations or self.locations.current(self.account) is not None):
                                                        from tio.locations import town_packets
                                                        town=self.locations.current(self.account) if self.locations else 3
                                                        from server.world_runtime import project_town
                                                        plain=project_town(self,town_packets(town,self.database)[0])
                                                        frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                        self.events.append({'direction':'S2C','stage':'town_info_trial','plain_hex':plain.hex(),'raw_hex':frame.hex()})
                                                    if self.enter_town_probe and (not self.locations or self.locations.current(self.account) is not None):
                                                        plain=encode_current_town(self.locations.current(self.account) if self.locations else 3)
                                                        frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                        self.events.append({'direction':'S2C','stage':'enter_town_command_trial','plain_hex':plain.hex()})
                                                    if self.open_town_probe and (not self.locations or self.locations.current(self.account) is not None):
                                                        plain=encode_open_town_view()
                                                        frame=encode_initial_frame(plain,game_outbound);game.sendall(frame)
                                                        self.events.append({'direction':'S2C','stage':'open_town_view_command','plain_hex':plain.hex()})
                                                    if self.owned_pet_probe:
                                                        trial=Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json'
                                                        trial_data=json.loads(trial.read_text())
                                                        plain=bytes.fromhex(trial_data['packet_hex'])
                                                        self.owned_inventory=bytes.fromhex(trial_data['inventory_packet_hex'])
                                                        if self.database is not None:
                                                            plain,self.owned_inventory=OwnedPetStore(self.database).ensure(self.account,plain,self.owned_inventory,human=trial_data['human_equipment'])
                                                            self.hiring=HireStore(self.database,self.catalogs,bytes.fromhex(trial_data['packet_hex']))
                                                            from tio.rental import RentalStore
                                                            self.rentals=RentalStore(self.database)
                                                            retained=bool(self.router and self.router.team_arena.retained(self.account))
                                                            self.rentals.refresh(self.account,in_battle=retained)
                                                            from tio.battle_recovery import RecoveryStore
                                                            self.recovery=RecoveryStore(self.database)
                                                            self.recovery.refresh(self.account,blocked=retained)
                                                            from tio.item_stacking import compact_saved_items
                                                            if not retained:self.events.append({'event':'item_stacks_compacted', **compact_saved_items(self.database,self.account)})
                                                            self.events.append({'event':'owned_pet_snapshot_loaded','database':str(self.database)})
                                                        roster=OwnedPetStore(self.database).list(self.account) if self.database is not None else ((1,plain,self.owned_inventory),)
                                                        for owner,pet_packet,inventory_packet in roster:
                                                            if self.database is not None:
                                                                from tio.armor_display import project_city_pet
                                                                pet_packet=project_city_pet(self.database,self.account,pet_packet)
                                                            game.sendall(encode_initial_frame(pet_packet,game_outbound))
                                                            self.events.append({'direction':'S2C','stage':'owned_pet_trial','owner_id':owner,'plain_hex':pet_packet.hex()})
                                                    self.observe_game(game,game_reader,game_outbound)



                                        else:
                                            game.settimeout(2)
                                            try:
                                                data=game.recv(65535)
                                                self.events.append({'direction':'C2S','stage':'second_connection_raw','raw_hex':data.hex()})
                                            except socket.timeout:
                                                self.events.append({'event':'second_connection_no_initial_bytes'})
                                else:
                                    # No automatic next C2S packet is assumed. Keep connection
                                    # alive briefly so original host can consume its queued callback.
                                    conn.settimeout(2)
                                    try:
                                        data=conn.recv(65535)
                                        self.events.append({'direction':'C2S','stage':'after_server_list','raw_hex':data.hex()})
                                    except socket.timeout:
                                        self.events.append({'event':'list_observation_window_complete'})

                    except socket.timeout:
                        self.events.append({'event':'after_completion_timeout'})
        except Exception as exc:
            self.failure=exc
            if not self.stopping.is_set():self.events.append({'error':repr(exc)})
        finally:
            if not self.external_listener:self.listener.close()
            if self.output is not None:
                self.output.write_text(json.dumps(self.events,indent=2)+'\n',encoding='utf-8')

    def send_server_list(self,conn,outbound,packet):
        request=decode_server_list_request(packet)
        self.events.append({'event':'server_list_request_decoded','unknown_u8':request.unknown_u8_01,'unknown_u32':request.unknown_u32_01,'trailing_hex':request.trailing_bytes.hex()})
        # Updated native UI uses raw online u16 and final availability byte.
        players,capacity,available=self.router.server_status() if self.router else (0,1,True)
        entries=(ServerEntry(1,self.advertised_address,self.port,players,capacity-1,int(available)),) if self.server_entry else ()
        plain=encode_server_list(ServerList(0,entries))
        frame=encode_initial_frame(plain,outbound);conn.sendall(frame)
        self.events.append({'direction':'S2C','stage':'server_list','entry_count':len(entries),'plain_hex':plain.hex(),'raw_hex':frame.hex()})

    def deliver_shared_config(self,conn,reader,outbound,name=b'items'):
        if name==b'services':
            from tio.services import shared_xml
            xml=shared_xml()
        elif name==b'premiumaccount':
            from tio.premium import shared_xml
            xml=shared_xml()
        elif name==b'items':
            from tio.item_presentation import items_xml
            xml=items_xml(getattr(self,'interface','new'))
        else:
            contracts = getattr(self.router, 'contracts', None)
            xml = (contracts.zones_xml() if name == b'zones' and contracts is not None else
                   (Path(__file__).resolve().parents[1]/('evidence/'+name.decode('ascii')+'_diagnostic.xml')).read_bytes())
        # Missing local file has comparison value zero; a nonzero diagnostic
        # manifest value requests delivery without claiming a checksum algorithm.
        messages=[('shared_config_set',encode_shared_config_set((SharedConfigEntry(name,1),))),
                  ('shared_config_data',encode_shared_config_data(SharedConfigData(name,len(xml),zlib.compress(xml))))]
        for stage,plain in messages:
            frame=encode_initial_frame(plain,outbound);conn.sendall(frame)
            self.events.append({'direction':'S2C','stage':stage,'plain_hex':plain.hex(),'raw_hex':frame.hex()})
            raw,packets=self.receive_frame(conn,reader)
            expected=b'\xb9\x02'+name+b'\0' if stage=='shared_config_set' else b'\xb9\x04'
            self.events.append({'direction':'C2S','stage':stage+'_reply','raw_hex':raw.hex(),'packets_hex':[p.hex() for p in packets]})
            if packets != [expected]:raise ValueError('Unexpected shared config reply')
        self.events.append({'event':'shared_config_delivery_acknowledged','xml_size':len(xml)})

    def choose_character(self,conn,reader,outbound):
        from tio.characters import CharacterStore,CreateRejected
        from tio.protocol.character_create import decode_character_create,encode_character_create_result
        store=CharacterStore(self.database)
        login=getattr(self,'authenticated_account',self.account)
        from tio.onboarding import pending,pending_owner,prepare,OPEN_APPEARANCE
        creation=getattr(self,'_creation_owner',None) or pending_owner(self.database,login)
        while not self.stopping.is_set():
            raw,packets=self.receive_choice(conn,reader,outbound)
            if packets[0][:1] == b'\x13':
                from server.character_operations import delete_character
                for reply in delete_character(self, packets[0]):
                    conn.sendall(encode_initial_frame(reply, outbound))
                creation = pending_owner(self.database, login)
                continue
            packet=packets[0]
            if packet[:1]==b'\x11':
                if creation and pending(self.database,creation):
                    # Finish the current native editor before allocating another
                    # slot. Preserve the prior single-creation rejection ABI.
                    conn.sendall(encode_initial_frame(encode_character_create_result(2),outbound))
                    continue
                try:
                    before={record.record_id for record in store.list(login)}
                    records=store.create(login,decode_character_create(packet))
                except CreateRejected as error:
                    conn.sendall(encode_initial_frame(encode_character_create_result(error.status),outbound))
                    continue
                created=next(record.record_id for record in records if record.record_id not in before)
                creation=store.owner(login,created)
                if not pending(self.database,creation):raise ValueError('Missing appearance step')
                prepare(self.database,creation)
                records=tuple(record for record in store.list(login) if record.record_id==created)
                conn.sendall(encode_initial_frame(OPEN_APPEARANCE,outbound))
                conn.sendall(encode_initial_frame(encode_character_list(records),outbound))
                self.events.append({'event':'character_created','account':login,'slot':created})
                continue
            records=store.list(login)
            if packet[:1]==b'\x92' and creation and pending(self.database,creation):
                from tio.appearance import change,decode_request,encode_request
                native_owner,values=decode_request(packet)
                slot=next(record.record_id for record in records if store.owner(login,record.record_id)==creation)
                if native_owner not in (1,slot):raise ValueError('Select the character being created')
                # The native selection record identifies a slot; each private
                # roster retains its old main-fighter id 1 in saved PetInfo.
                replies=change(self.database,creation,encode_request(1,values),finish_creation=True)
                # Selection screen uses CharSelectInfo, not a city PetInfo panel.
                for reply in replies[1:] if replies[0][:1]==b'\x66' else replies:
                    conn.sendall(encode_initial_frame(reply,outbound))
                if pending(self.database,creation):
                    conn.sendall(encode_initial_frame(OPEN_APPEARANCE,outbound))
                    records=tuple(record for record in store.list(login) if store.owner(login,record.record_id)==creation)
                else:
                    creation=None
                    records=store.list(login)
                conn.sendall(encode_initial_frame(encode_character_list(records),outbound))
                continue
            if packet[:1]==b'\x17' and len(packet)==5 and records:
                slot=int.from_bytes(packet[1:],'little')
                owner,record=store.select(login,slot)
                if pending(self.database,owner):
                    creation=owner
                    prepare(self.database,owner)
                    conn.sendall(encode_initial_frame(OPEN_APPEARANCE,outbound))
                    conn.sendall(encode_initial_frame(encode_character_list((record,)),outbound))
                    continue
                try:self.router.select_character(self,owner)
                except ValueError as error:
                    from tio.protocol.system_message import encode_shop_error
                    conn.sendall(encode_initial_frame(encode_select_result(SelectResult(1)),outbound))
                    conn.sendall(encode_initial_frame(encode_shop_error(str(error)),outbound))
                    conn.sendall(encode_initial_frame(encode_character_list(records),outbound))
                    continue
                self.account=owner
                self.selected_character_slot=slot
                return (record,),raw,packets
            # A forged selection must never enter the world with a fallback pet.
            raise ValueError('Select an existing character owned by this account')
        raise InterruptedError('Server stopping')

    def receive_choice(self,conn,reader,outbound,*,deadline=None,allow_batch=False):
        """Human UI choices need more time than an automatic handshake reply."""
        if not self.external_listener:return self.receive_frame(conn,reader)
        if deadline is None:deadline=time.monotonic()+300
        raw=bytearray()
        while not self.stopping.is_set():
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('UI choice timed out after 300 seconds')
            conn.settimeout(min(0.5,remaining))
            try:chunk=conn.recv(65535)
            except socket.timeout:continue
            if not chunk:raise EOFError('Client disconnected while choosing')
            raw.extend(chunk)
            received=[]
            for packet in reader.feed(chunk):
                if packet==b'\x70':
                    conn.sendall(encode_initial_frame(b'\x9e',outbound))
                else:received.append(packet)
            if received:
                reader.finish()
                if not allow_batch and len(received)!=1:raise ValueError('Expected one UI choice')
                return bytes(raw),received
            # Do not retain an ever-growing trace of keepalive requests.
            if not reader.buffer:raw.clear()
        raise InterruptedError('Server stopping')

    @staticmethod
    def receive_frame(conn,reader):
        deadline=time.monotonic()+5
        raw=bytearray()
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0: raise TimeoutError('Timed out receiving complete frame')
            conn.settimeout(remaining)
            chunk=conn.recv(65535)
            if not chunk: raise EOFError('Connection closed before expected frame')
            raw.extend(chunk)
            packets=reader.feed(chunk)
            if packets:
                reader.finish()
                if len(packets)!=1: raise ValueError('Expected exactly one phase response')
                return bytes(raw),packets

    def accept_connection(self):
        if self.router is not None:
            connection=self.router.accept(self)
            self.connections.append(connection)
            if self.stopping.is_set() or self.router.server.stopping.is_set():
                connection.close()
                raise InterruptedError('Server stopping')
            return connection
        if not self.external_listener:
            connection=self.listener.accept()[0]
            self.connections.append(connection)
            return connection
        # The original protocol expects login, then game, on the same port.
        # Wait indefinitely for login, but bound the second connection phase.
        deadline=time.monotonic()+10 if self.connections else None
        self.listener.settimeout(0.5)
        while not self.stopping.is_set():
            if deadline is not None and time.monotonic()>=deadline:
                raise TimeoutError('Timed out waiting for game connection')
            try:connection,address=self.listener.accept()
            except socket.timeout:continue
            # The native client closes the login socket before opening mode1.
            # getpeername() on that disconnected socket fails on Linux (ENOTCONN).
            # Retain the accepted address, rather than querying a dead socket.
            if self.connections and address[0]!=self.login_peer_address:
                connection.close()
                continue
            if not self.connections:self.login_peer_address=address[0]
            self.connections.append(connection)
            return connection
        raise InterruptedError('Server stopping')

    def achievement_delivery_ready(self,character):
        """Keep prizes out of scenes, but allow delivery after town confirms.

        `_completed` is retained for repeat Finish and late native treatment ID
        translation. It cannot also mean that the result screen is still open.
        """
        private=any(character in room.members for room in self.arena.rooms.snapshot())
        shared=bool(self.router and self.router.team_arena.busy(self))
        if private or shared:
            self._achievement_city_confirmed=False
            return False
        return character not in self.arena._completed or self._achievement_city_confirmed

    def observe_game(self,game,reader,outbound):
        from server import warehouse_capacity
        warehouse_capacity.reset(self)
        from tio.protocol.item_list import decode_item_list
        def encode_reply(packet, cipher):
            weight_update=None
            armor_update=None
            if packet[:2]==b'\xc8\x39' and self.database is not None:
                from tio.premium import project_packet
                packet=project_packet(self.database,self.account,packet)
                from tio.clans import project_asset_packet
                packet=project_asset_packet(self.database,self.account,packet)
            if packet[:1]==b'\x66' and self.database is not None:
                # Recompute from canonical storage, not a previously projected
                # total, so health/skill refreshes cannot accumulate armor.
                from tio.armor_display import project_city_pet
                packet=project_city_pet(self.database,self.account,packet)
                from tio.weight import city_profile_weight_update
                weight_update=city_profile_weight_update(self.database,self.account,packet)
            if packet[:2]==b'\xc8\x39' and self.mining is not None:
                from tio.protocol.asset_count import decode_asset_count
                packet=encode_asset_count(self.mining.market.project(self.account,decode_asset_count(packet)))
            # Project outgoing city ItemLists, including purchases, upgrades and
            # warehouse withdrawals. Stored snapshots stay canonical for CAS.
            if packet[:1]==b'\x30' and self.database is not None:
                owner=int.from_bytes(packet[1:5],'little')
                in_combat=any(owner in getattr(getattr(field,'combat',None),'inventories',{})
                              for field in self.arena._fields.values())
                if in_combat:
                    combat=next(field.combat for field in self.arena._fields.values()
                                if owner in getattr(getattr(field,'combat',None),'inventories',{}))
                    weight_update=combat.weight_packet(owner,packet)
                    from tio.armor_display import encode_armor
                    armor_update=encode_armor(owner,combat.displayed_armor(owner))
                if not in_combat:
                    from tio.weight import city_weight_update
                    weight_update=city_weight_update(self.database,self.account,packet)
                    from tio.enhancement_limits import project_owned_inventory
                    projected=project_owned_inventory(self.database,self.account,packet)
                    if projected!=packet:
                        self.events.append({'event':'item_enhancement_projected','owner':owner,'plain_hex':projected.hex()})
                    packet=projected
                    from tio.clans import project_inventory as project_clan_money
                    packet=project_clan_money(self.database,self.account,packet)
                    from tio.armor_display import city_armor,encode_armor
                    armor_update=encode_armor(owner,city_armor(self.database,self.account,owner))
            if self.database is not None:
                from server.economy_runtime import project_packet
                packet=project_packet(self.database,self.account,packet)
            capacity_frame=warehouse_capacity.frames(self,packet,cipher)
            if capacity_frame is not None:return capacity_frame
            frame=encode_initial_frame(packet,cipher)
            if weight_update is not None:
                frame+=encode_initial_frame(weight_update,cipher)
                self.events.append({'direction':'S2C','stage':'carried_weight','plain_hex':weight_update.hex()})
            if armor_update is not None:
                frame+=encode_initial_frame(armor_update,cipher)
                self.events.append({'direction':'S2C','stage':'total_armor','plain_hex':armor_update.hex()})
            if packet[:1]==b'\x3b':
                # 3B recreates equipped TSItems from template IDs only. It
                # erases instance metadata even for an already-known actor
                # (notably after skill training). Restore the owner's full30
                # AFTER that snapshot, including rental flags/time/upgrades.
                from tio.battle_equipment import inventory_after_snapshot
                inventory=inventory_after_snapshot(self.arena._fields.values(),
                    getattr(self,'probe_character_id',None),packet)
                if inventory is not None:
                    frame+=encode_reply(inventory,cipher)
                    self.events.append({'direction':'S2C','stage':'battle_equipment_restored','plain_hex':inventory.hex()})
            return frame

        if self.locations and getattr(self,'probe_character_id',None) is not None:
            for reply in self.locations.resume(self.account,self.probe_character_id):game.sendall(encode_reply(reply,outbound))

        if self.database is not None and getattr(self,'probe_character_id',None) is not None:
            from tio.services import snapshots
            for reply in snapshots(self.database,self.account):
                game.sendall(encode_reply(reply,outbound))
        if self.router is not None and getattr(self,'probe_character_id',None) is not None:
            if not self.router.team_arena.resume(self):
                self.router.team_arena.tutorial_auto(self)
            group=self.router.team_arena.assault_group(self)
            if group and not self.router.team_arena.in_battle(self):
                owner=self.router.team_arena.identity(self)
                self.router.team_arena.put(owner,self.router.team_arena.assault_room_packet(group,owner))
            from server.player_auction import AuctionSession
            from server.economy_runtime import city_idle
            from tio.protocol.player_auction import encode_settings
            self.player_auction=AuctionSession(self.router.player_auction,self.account,self.probe_character_name.decode('cp1251'),
                gate=lambda:city_idle(self),lock=self.router.team_arena.lock)
            game.sendall(encode_reply(encode_settings(int(time.time()),clan_warfare=True,mail=True),outbound))
            self.private_market=self.router.economy.session(self)
            self.bank_session=self.router.economy.bank_session(self)
            for reply in self.private_market.clear_sc():game.sendall(encode_reply(reply,outbound))
            hub=self.router.team_arena
            with hub.lock:
                if not hub.busy(self):
                    owner=hub.identity(self)
                    try:listing=hub.wager_list_packet(owner)
                    except ValueError:listing=None
                    if listing is not None:
                        hub.put(owner,listing);hub.wager_listing_cache[owner]=listing

        seconds=self.observation_seconds
        if seconds is None:
            seconds=45 if self.inspect_window else (8 if self.character_record else 2)
        deadline=None if seconds == 0 else time.monotonic()+seconds
        self.events.append({'event':'city_session_started','seconds':seconds})
        achievement_tick=0
        for reply in getattr(self,'private_resume_packets',()):game.sendall(encode_reply(reply,outbound))
        while not self.stopping.is_set():
            for capacity_reply in warehouse_capacity.poll(self):
                game.sendall(encode_initial_frame(capacity_reply,outbound))
            character=getattr(self,'probe_character_id',None)
            achievement_ready=self.achievement_delivery_ready(character)
            if self.router is not None:
                contracts = getattr(self.router, 'contracts', None)
                if contracts is not None:
                    contracts.sync(self)
                if getattr(self.router, "player_trade", None) is not None:
                    self.router.player_trade.tick()
                self.router.presence.sync(self)
                self.router.presence.drain(self,game,outbound)
                hub=self.router.team_arena
                if getattr(self,'private_resume_loading',False):
                    hub.private_resume_pump(self,game,reader,outbound,encode_reply)
                    continue
                hub.drain(self,game,outbound)
                if hub.busy(self):
                    hub.pump(self,game,reader,outbound)
                    continue
            if hasattr(self,'private_market'):
                from server.economy_runtime import city_idle,refresh_inventory
                if city_idle(self) and time.monotonic()>=getattr(self,'_economy_refresh_at',0):
                    self._economy_refresh_at=time.monotonic()+2
                    from server.clan_gameplay import prizes
                    for reply in (*self.private_market.refresh(),*prizes(self),*refresh_inventory(self)):
                        game.sendall(encode_reply(reply,outbound))
            if hasattr(self,'player_auction') and not self.arena._fields:
                for reply in self.player_auction.refresh():
                    game.sendall(encode_reply(reply,outbound))
            if self.database is not None and self.owned_pet_probe and character is not None and time.monotonic()>=achievement_tick:
                achievement_tick=time.monotonic()+2
                if achievement_ready:
                    from tio.achievements import AchievementStore
                    if not hasattr(self,'achievement_store'):
                        self.achievement_store=AchievementStore(self.database,capacity=self.catalogs.warehouse_capacity)
                    for reply in self.achievement_store.flush(self.account):
                        game.sendall(encode_reply(reply,outbound))
                        self.events.append({'direction':'S2C','stage':'achievement_update','plain_hex':reply.hex()})
            if hasattr(self,'recovery'):
                blocked=any(character in room.members for room in self.arena.rooms.snapshot())
                for reply in self.recovery.refresh(self.account,blocked=blocked):
                    game.sendall(encode_reply(reply,outbound))
                    self.events.append({'direction':'S2C','stage':'passive_recovery','plain_hex':reply.hex()})
            if self.locations and character is not None:
                contracts = getattr(self.router, 'contracts', None)
                if self.encounters is not None and not (contracts and contracts.member(self)):
                    started=self.encounters.tick(self.account,character,self.probe_character_name,
                        busy=self.survival.searching(character) or bool(self.router and self.router.team_arena.busy(self)))
                    if started is not None:
                        (room,prepared),replies=started
                        self.training_matches[room.room_id]=prepared.participants[1:]
                        self.visibility_views[room.room_id]=prepared.visibility
                        for reply in replies:game.sendall(encode_reply(reply,outbound))
                        self.events.append({'event':'world_encounter_started','room':room.room_id,**prepared.field.scene_metadata})
                for reply in self.locations.refresh(self.account,character):
                    from server.world_runtime import project_town
                    reply=project_town(self,reply)
                    game.sendall(encode_reply(reply,outbound))
                    self.events.append({'direction':'S2C','stage':'map_travel','plain_hex':reply.hex()})
            if hasattr(self,'rentals'):
                in_battle=any(character in room.members and room.room_id in self.arena._fields
                              for room in self.arena.rooms.snapshot())
                for reply in self.rentals.refresh(self.account,in_battle=in_battle):
                    game.sendall(encode_reply(reply,outbound))
                    self.events.append({'direction':'S2C','stage':'rental_expired','plain_hex':reply.hex()})
            proposal=self.survival.queue.propose(character)
            if proposal is not None and proposal.uses_bot and proposal.first not in self.failed_searches:
                try:
                    from tools.survival_scene import prepare_survival
                    from tio.abilities import AbilityCatalog,AbilityLevel
                    source=json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
                    catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
                    prepared=prepare_survival(self.database,self.account,proposal.first,catalog,mode=proposal.first.mode)
                    room,replies=self.arena.start_survival(character,self.probe_character_name,prepared)
                    self.survival.queue.consume(proposal)
                    self.survival.disconnected(character)
                    self.training_matches[room.room_id]=prepared.participants[1:]
                    self.visibility_views[room.room_id]=prepared.visibility
                except ValueError as error:
                    self.failed_searches.add(proposal.first)
                    self.events.append({'event':'survival_scene_rejected','reason':str(error)})
                    if not getattr(self,'quiet',False):print(json.dumps(self.events[-1]),flush=True)
                else:
                    for reply in replies:game.sendall(encode_reply(reply,outbound))
                    self.events.append({'event':'survival_scene_started','room':room.room_id,'actors':prepared.actor_ids,
                                        'map':prepared.field.scene_metadata})
                    if not getattr(self,'quiet',False):print(json.dumps(self.events[-1]),flush=True)
            for room in self.arena.rooms.snapshot():
                if room.room_id in self.training_matches:
                    try:
                        field=self.arena._fields[room.room_id]
                        mine=getattr(field,'mining',None)
                        if mine is not None and mine.extracted_amount is None:
                            from tio.protocol.item_list import decode_item_list
                            if any(i.template_id==52 and i.count>0 for a in field.living_actor_ids(character)
                                   for i in decode_item_list(field.combat.inventories[a])[1]):
                                try:mine.exit(character)
                                except ValueError:pass
                        replies=self.arena.finish_training(character,self.database,self.account)
                    except (ValueError,sqlite3.Error) as error:
                        self.events.append({'event':'battle_settlement_failed','room_id':room.room_id,'reason':str(error)})
                        continue
                    if replies:
                        self.training_matches.pop(room.room_id,None)
                        self.visibility_views.pop(room.room_id,None)
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'battle_finished','plain_hex':reply.hex()})
            for character_id,reply in self.arena.expire_turns():
                if character_id==getattr(self,'probe_character_id',None):
                    for update in self.arena.finished_turn_packets(character_id,reply):
                        game.sendall(encode_reply(update,outbound))
                        self.events.append({'direction':'S2C','stage':'arena_turn_expired','plain_hex':update.hex()})
            for room in self.arena.rooms.snapshot():
                bot=self.training_matches.get(room.room_id)
                if bot is not None and room.room_id in self.arena._last_turn and room.room_id not in self.arena._turns:
                    from tio.training_bot import play_turn
                    member=self.arena.next_turn_owner(room.room_id)
                    field=self.arena._fields[room.room_id]
                    if member==room.owner_id:
                        seconds=20*len(field.living_actor_ids(member))+20 if room.request.mode else 40
                        replies=self.arena.begin_turn_packets(member,field.living_actor_ids(member),seconds)
                    else:
                        replies=play_turn(self.arena,room.room_id,member,view=self.visibility_views.get(room.room_id))
                    for reply in replies:game.sendall(encode_reply(reply,outbound))
            remaining=None if deadline is None else deadline-time.monotonic()
            if remaining is not None and remaining <= 0:
                self.events.append({'event':'auth2_observation_window_complete','seconds':seconds})
                return
            interval=0.05 if self.locations and self.locations.travelling(self.account) else 0.5
            game.settimeout(interval if remaining is None else min(interval,remaining))
            try:
                data=game.recv(65535)
            except socket.timeout as exc:
                # Kernel ETIMEDOUT (e.g. exhausted TCP keepalive) is fatal;
                # only the ordinary Python polling deadline has no errno.
                if exc.errno is not None:
                    raise
                continue
            except OSError:
                if self.stopping.is_set():
                    break
                raise
            if not data:
                self.survival.disconnected(getattr(self,'probe_character_id',None))
                self.events.append({'event':'client_disconnected'})
                return
            received_at = self.arena._clock()
            packets=reader.feed(data)
            from server.economy_runtime import private_command
            sensitive=any(private_command(p) for p in packets)
            self.events.append({'direction':'C2S','stage':'after_auth2','raw_hex':None if sensitive else data.hex(),'packets_hex':['<private economy command>' if private_command(p) else p.hex() for p in packets]})
            if self.open_town_probe:
                for packet in packets:
                    capacity_replies=warehouse_capacity.opt_in(self,packet)
                    if capacity_replies is not None:
                        for reply in capacity_replies:game.sendall(encode_initial_frame(reply,outbound))
                        continue
                    # A single TCP read can start a scene and then contain an
                    # action/exit. Observe every transition before processing
                    # the next packet so an older city acknowledgement cannot
                    # carry into another lobby, battle or result screen.
                    self.achievement_delivery_ready(getattr(self,'probe_character_id',None))
                    trades = getattr(self.router, 'player_trade', None)
                    if trades is not None:
                        if trades.handle(self, packet):
                            self.router.presence.drain(self, game, outbound)
                            continue
                        trades.guard(self, packet)
                    # F0/449 opens the town asynchronously. C2S 50/<town>
                    # confirms its controls exist; sending C6/18 earlier can
                    # dereference a missing native arena button (953f31).
                    if (len(packet)==2 and packet[0]==0x50 and self.locations
                            and self.locations.current(self.account)==packet[1]
                            and not (self.router and self.router.team_arena.busy(self))):
                        if not any(self.probe_character_id in room.members for room in self.arena.rooms.snapshot()):
                            self._achievement_city_confirmed=True
                        from tio.arena_gears import catalogue_packet
                        reply=catalogue_packet()
                        game.sendall(encode_reply(reply,outbound))
                        self.events.append({'direction':'S2C','stage':'arena_gears_catalogue','plain_hex':reply.hex()})
                    if packet[:1]==b'\x92' and self.database is not None:
                        from tio.appearance import change
                        busy=(self.survival.searching(self.probe_character_id) or
                              any(self.probe_character_id in room.members for room in self.arena.rooms.snapshot()))
                        if self.router is not None:
                            busy=busy or self.router.team_arena.busy(self)
                        allowed=not busy and (not self.locations or self.locations.current(self.account) is not None)
                        for reply in change(self.database,self.account,packet,allowed=allowed):
                            game.sendall(encode_reply(reply,outbound))
                        continue
                    if packet[:1]==b'\x21' and self.database is not None:
                        from tio.protocol.chat import decode_send
                        channel,text,recipient=decode_send(packet)
                        if channel==0 and not recipient and (text.strip().casefold()=='/tutorial' or text.casefold().startswith('/decreaseability ')):
                            from tio.protocol.system_message import encode_shop_error
                            try:
                                hub=self.router.team_arena if self.router is not None else None
                                if text.strip().casefold()=='/tutorial':
                                    if hub is None:raise ValueError('Для вводной миссии требуется общий сервер')
                                    hub.tutorial_command(self,text)
                                    hub.drain(self,game,outbound)
                                    replies=()
                                else:
                                    from tio.ability_progression import decrease
                                    allowed=bool(self.locations and self.locations.current(self.account) is not None and not (hub and hub.busy(self)) and not self.survival.searching(self.probe_character_id) and not any(self.probe_character_id in r.members for r in self.arena.rooms.snapshot()))
                                    replies=decrease(self.database,self.account,packet,allowed=allowed)
                            except ValueError as error:replies=(encode_shop_error(str(error)),)
                            for reply in replies:game.sendall(encode_reply(reply,outbound))
                            continue
                    if hasattr(self,'bank_session') and packet[:1]==b'\x21':
                        from server.economy_runtime import handle_private
                        replies=handle_private(self,packet)
                        if replies is not None:
                            for reply in replies:game.sendall(encode_reply(reply,outbound))
                            continue
                    if hasattr(self,'private_market') and packet[:1] in (b'\xae',b'\xbd'):
                        from server.economy_runtime import city_idle,refresh_inventory
                        from tio.protocol.system_message import encode_shop_error
                        hub=self.router.team_arena
                        try:
                            with hub.lock:
                                allowed=city_idle(self)
                                handler=self.private_market.handle if packet[0]==0xae else self.private_market.handle_sc
                                replies=handler(packet,allow_mutation=allowed)
                                replies+=refresh_inventory(self,force=True)
                        except ValueError as error:replies=(encode_shop_error(str(error)),)
                        for reply in replies:game.sendall(encode_reply(reply,outbound))
                        continue
                    if self.router is not None and self.router.presence.handle(self,packet):
                        self.router.presence.drain(self,game,outbound)
                        if getattr(self.router, "contracts", None) is not None:
                            # Private command replies use the hub queue, before a same-read70/9E.
                            self.router.team_arena.drain(self,game,outbound)
                        continue
                    contracts = getattr(self.router, 'contracts', None)
                    if contracts is not None and contracts.guard(self, packet):
                        self.router.team_arena.drain(self, game, outbound)
                        continue
                    if self.router is not None and self.database is not None:
                        from server.mail_service import handle as handle_mail
                        if handle_mail(self.router.presence,self,packet):
                            self.router.presence.drain(self,game,outbound)
                            continue
                    if self.router is not None and self.router.team_arena.handle(self,packet):
                        self.router.team_arena.drain(self,game,outbound)
                        continue
                    if self.router is not None and self.database is not None:
                        from server.clan_service import handle as handle_clan
                        if handle_clan(self.router.presence,self,packet):
                            self.router.presence.drain(self,game,outbound)
                            continue
                    if packet != b'\x70':
                        if not getattr(self,'quiet',False):print(json.dumps({'event':'game_request','plain_hex':packet.hex()}),flush=True)
                    if self.shooting_range is not None and packet[:1] in (b'\x1f',b'\x2e'):
                        try:
                            handled=self.shooting_range.handle(self.account,self.probe_character_id,self.probe_character_name,packet,
                                                               searching=self.survival.searching(self.probe_character_id))
                        except (ValueError,sqlite3.Error) as error:
                            from tio.protocol.system_message import encode_shop_error
                            handled=(None,(encode_shop_error(str(error)),))
                            self.events.append({'event':'shooting_range_rejected','request_hex':packet.hex(),'reason':str(error)})
                        if handled is not None:
                            started,replies=handled
                            if started:
                                room,prepared=started
                                self.training_matches[room.room_id]=()
                                self.visibility_views[room.room_id]=prepared.visibility
                                self.events.append({'event':'shooting_range_started','room':room.room_id,**prepared.field.scene_metadata})
                            for reply in replies:game.sendall(encode_reply(reply,outbound))
                            continue
                    if packet[:1]==b'\xb0' and self.mining is not None:
                        try:
                            handled=self.mining.handle(self.account,self.probe_character_id,self.probe_character_name,packet)
                        except (ValueError,sqlite3.Error) as error:
                            from tio.protocol.system_message import encode_shop_error
                            handled=(None,(encode_shop_error(str(error)),))
                            self.events.append({'event':'mining_request_rejected','request_hex':packet.hex(),'reason':str(error)})
                        if handled is not None:
                            started,replies=handled
                            if started:
                                room,prepared=started
                                self.training_matches[room.room_id]=prepared.participants[1:]
                                self.visibility_views[room.room_id]=prepared.visibility
                                self.survival.disconnected(self.probe_character_id)
                                self.events.append({'event':'mine_started','room':room.room_id,**prepared.field.scene_metadata})
                            for reply in replies:game.sendall(encode_reply(reply,outbound))
                            continue
                    if packet[:1]==b'\x1b' and self.locations is not None:
                        from tio.protocol.system_message import encode_shop_error
                        busy=self.survival.searching(self.probe_character_id) or any(self.probe_character_id in r.members for r in self.arena.rooms.snapshot())
                        busy=busy or (self.probe_character_id in self.arena._completed and self.probe_character_id in self.arena._return_maps and self.probe_character_id not in self.arena._map_returned)
                        try:
                            contracts = getattr(self.router, 'contracts', None)
                            replies=(contracts.travel_map(self, packet, busy=busy) if contracts else
                                     self.locations.travel(self.account,packet,self.probe_character_id,busy=busy))
                            from server.world_runtime import project_town
                            replies=tuple(project_town(self,reply) for reply in replies)
                            self.events.append({'event':'map_travel_started','position':self.locations.position(self.account)})
                        except ValueError as error:
                            grouped = contracts and contracts.member(self)
                            replies=(encode_shop_error(str(error) if grouped else 'перехода по карте: запрос не выполнен'),)
                            self.events.append({'event':'travel_rejected','reason':str(error)})
                        for reply in replies:game.sendall(encode_reply(reply,outbound))
                        continue
                    if contracts is not None:
                        replies = contracts.map_query(self, packet)
                        if replies is not None:
                            for reply in replies:game.sendall(encode_reply(reply, outbound))
                            continue
                    map_battle=any(character in r.members for r in self.arena.rooms.snapshot())
                    map_battle_request=(map_battle and (packet[0] in (0x2a,0x2f,0x33,0x36,0x3a,0x3c,0x3e,0x40,0x46,0x49,0x4a,0x50,0x6d,0x6e,0x7c,0x7e,0x81,0xc2) or packet[:2]==b'\xc8\x3d')) or (character in self.arena._completed and packet[0] in (0x2a,0x2f,0x4a,0x50,0x7c))
                    if self.locations and self.locations.current(self.account) is None and packet[:1] not in (b'\x70',b'\xb5',b'\xc5') and not map_battle_request:
                        from tio.protocol.system_message import encode_shop_error
                        game.sendall(encode_reply(encode_shop_error('доступа к городу: сначала дойдите до входа'),outbound))
                        continue
                    if packet[:2] in (b'\xba\x03',b'\xba\x05',b'\xba\x07') and self.database is not None:
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            # Closing the search widget during automatic scene
                            # transition emits its old BA05 cancellation.
                            if packet == b'\xba\x05'+self.probe_character_id.to_bytes(4,'little')+b'\0' and any(self.probe_character_id in r.members and r.room_id in self.training_matches for r in self.arena.rooms.snapshot()):
                                continue
                            if any(self.probe_character_id in r.members for r in self.arena.rooms.snapshot()):
                                raise ValueError('Leave combat before searching')
                            if packet[:2]==b'\xba\x03':
                                if self.locations and self.locations.current(self.account)!=3:raise ValueError('Arena is available in Reservation')
                                roster=OwnedPetStore(self.database).list(self.account)
                                reply=self.survival.join(self.probe_character_id,self.probe_character_name,packet,roster)
                            elif packet[:2]==b'\xba\x07':
                                reply=self.survival.set_ready(self.probe_character_id,packet)
                            else:
                                reply=self.survival.cancel(self.probe_character_id,packet)
                        except ValueError as error:
                            reply=encode_shop_error('поиска боя: запрос не выполнен')
                            self.events.append({'event':'survival_rejected','reason':str(error)})
                        game.sendall(encode_reply(reply,outbound))
                        self.events.append({'direction':'S2C','stage':'survival_reply','plain_hex':reply.hex()})
                        continue
                    if self.owned_pet_probe and packet[:2]==b'\xc8\x12':
                        # In battle the skill bar needs the battle list (scene
                        # ids, Groza27); malformed requests reach the city handler.
                        try:battle_skills=self.arena.skill_list_packets(self.probe_character_id,packet)
                        except ValueError:battle_skills=None
                        if battle_skills is not None:
                            for reply in battle_skills:
                                game.sendall(encode_reply(reply,outbound))
                                self.events.append({'direction':'S2C','stage':'battle_skill_list','plain_hex':reply.hex()})
                            continue
                    if self.owned_pet_probe and self.database is not None and (packet[:2]==b'\xc8\x12' or packet[:1] in (b'\x8f',b'\x90',b'\xa9')):
                        from tio.ability_progression import AbilityProgression as AbilityLearning
                        from tio.protocol.system_message import encode_shop_error
                        if self.ability_learning is None:
                            self.ability_learning=AbilityLearning.from_workspace(self.database,Path(__file__).resolve().parents[1])
                        try:
                            if packet[:1] in (b'\x8f',b'\x90') and (not self.locations or self.locations.current(self.account) is None or self.router is not None and self.router.team_arena.busy(self) or self.survival.searching(self.probe_character_id) or any(self.probe_character_id in r.members for r in self.arena.rooms.snapshot())):
                                raise ValueError('Leave battle or matchmaking before learning')
                            replies=self.ability_learning.handle(self.account,packet)
                        except ValueError as error:
                            replies=(encode_shop_error('обучения: запрос не выполнен'),)
                            self.events.append({'event':'ability_request_rejected','reason':str(error)})
                        else:
                            self.events.append({'event':'ability_request_handled','request_hex':packet.hex()})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'ability_reply','plain_hex':reply.hex()})
                        continue
                    if self.squad is not None and (packet[:2]==b'\xbf\x03' or packet[:1]==b'\x67'):
                        try:
                            from tio.protocol.pet_state import decode_squad_slot,decode_pet_state_request
                            if self.survival.searching(self.probe_character_id) or any(self.probe_character_id in r.members for r in self.arena.rooms.snapshot()):
                                raise ValueError('Leave the room before changing squad')
                            if packet[:2]==b'\xbf\x03':owner,slot=decode_squad_slot(packet)
                            else:
                                owner,slot=decode_pet_state_request(packet)
                                if slot!=0:raise ValueError('Use explicit slot assignment')
                            replies=self.squad.assign(self.account,owner,slot)
                            self.events.append({'event':'squad_changed','actor':owner,'slot':slot})
                        except ValueError as error:
                            from tio.protocol.system_message import encode_shop_error
                            replies=(encode_shop_error('выбора отряда: запрос не выполнен'),)
                            self.events.append({'event':'squad_rejected','reason':str(error)})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'squad_reply','plain_hex':reply.hex()})
                        continue
                    if packet[:2] in (b'\xc8\x06',b'\xc8\x08',b'\xc8\x0a',b'\xc8\x0d',b'\xc8\x0e',b'\xc8\x0f',b'\xc8\x10') and hasattr(self,'player_auction'):
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            if (self.router is not None and self.router.team_arena.busy(self)) or self.arena._fields:
                                raise ValueError('Аукцион доступен вне боя')
                            replies=self.player_auction.handle(packet)
                        except ValueError as error:
                            replies=(encode_shop_error(str(error)),)
                            if packet[:2]==b'\xc8\x0a' and len(packet)>=6:
                                replies=(b'\xc8\x0b'+packet[2:6],*replies)
                            self.events.append({'event':'player_auction_rejected','reason':str(error)})
                        for reply in replies:game.sendall(encode_reply(reply,outbound))
                        continue
                    if packet[:2] in (b'\xb1\x02',b'\xb1\x04') and self.database is not None:
                        from tio import services
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            if packet==b'\xb1\x02':replies=(*services.snapshots(self.database,self.account),services.catalog(self.database,self.account))
                            elif packet[:2]==b'\xb1\x04':
                                if (self.router is not None and self.router.team_arena.busy(self)) or self.arena._fields:raise ValueError('Сервис недоступен во время боя')
                                replies=services.purchase(self.database,self.account,packet)
                            else:raise ValueError('Некорректный запрос сервисов')
                        except ValueError as error:replies=(encode_shop_error(str(error)),)
                        for reply in replies:game.sendall(encode_reply(reply,outbound))
                        continue
                    if packet[:2]==b'\xc8\x3a' and self.database is not None:
                        from tio.premium import purchase
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            if (self.router is not None and self.router.team_arena.in_battle(self)) or self.arena._fields:
                                raise ValueError('Покупка премиума доступна вне боя')
                            replies=(encode_asset_count(purchase(self.database,self.account,packet)),)
                        except ValueError as error:
                            replies=(encode_shop_error(str(error)),)
                        for reply in replies:game.sendall(encode_reply(reply,outbound))
                        continue
                    if packet[:1]==b'\x7c' and self.database is not None:
                        from tio.battle_recovery import decode_treatment,treat
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            blocked=(self.survival.searching(self.probe_character_id) or
                                     any(self.probe_character_id in r.members for r in self.arena.rooms.snapshot()))
                            assets,cost=treat(self.database,self.account,decode_treatment(packet),blocked=blocked)
                            roster=OwnedPetStore(self.database).list(self.account)
                            replies=(encode_asset_count(assets),*(p for _,p,_ in roster))
                            self.events.append({'event':'post_battle_treatment','credits':cost})
                        except ValueError as error:
                            replies=(encode_shop_error('лечения: недостаточно кредитов или неверный запрос'),)
                            self.events.append({'event':'treatment_rejected','reason':str(error)})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'treatment_reply','plain_hex':reply.hex()})
                        continue
                    # The scene teardown triggered by449 is asynchronous. Reload
                    # on the client's subsequent town/panel request, not only in
                    # the same response as449, where teardown can erase the list.
                    if self.database is not None and hasattr(self,'probe_character_id'):
                        for reply in self.arena.city_roster_refresh(self.probe_character_id,packet,self.database,self.account):
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'town_roster_restored','plain_hex':reply.hex()})
                    if packet[:1] == b'\x2a' and hasattr(self,'probe_character_id'):
                        try:
                            replies=self.arena.finish_results(self.probe_character_id,packet)
                            if replies is None:
                                replies=(self.arena.leave(self.probe_character_id,packet),)
                                if self.probe_character_id in self.arena._return_maps:
                                    replies+=self.arena.finish_results(self.probe_character_id,packet) or ()
                            elif self.database is not None:
                                roster=OwnedPetStore(self.database).list(self.account)
                                replies=(*replies,*(p for _,pet,inventory in roster for p in (pet,inventory)))
                        except ValueError as error:
                            from tio.protocol.system_message import encode_shop_error
                            replies=(encode_shop_error('выхода из боя: запрос не выполнен'),)
                            self.events.append({'event':'arena_leave_rejected','reason':str(error)})
                        else:
                            self.events.append({'event':'arena_left','remaining_rooms':len(self.arena.rooms.snapshot())})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'arena_leave_reply','plain_hex':reply.hex()})
                        continue
                    if packet[:1] == b'\x2c' and hasattr(self,'probe_character_id'):
                        try:
                            reply=self.arena.set_ready(self.probe_character_id,packet)
                        except ValueError as error:
                            from tio.protocol.system_message import encode_shop_error
                            reply=encode_shop_error('готовности к бою: запрос не выполнен')
                            self.events.append({'event':'arena_ready_rejected','reason':str(error)})
                        game.sendall(encode_reply(reply,outbound))
                        self.events.append({'direction':'S2C','stage':'arena_ready_reply','plain_hex':reply.hex()})
                        continue
                    if (packet[:1] in (b'\x2e',b'\x36',b'\x3a',b'\x3c',b'\x3e',b'\x81',b'\x49',b'\x6d',b'\x46',b'\x40',b'\x6e',b'\xf6') or packet[:2]==b'\xc8\x3d') and hasattr(self,'probe_character_id'):
                        hazard_room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                        hazard_field=None if hazard_room is None else self.arena._fields.get(hazard_room.room_id)
                        hazard_combat=getattr(hazard_field,'combat',None)
                        hazards_before=hazard_combat.hazard_packets(self.probe_character_id) if hazard_combat else None
                        try:
                            if packet[:1]==b'\xf6':
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                view=None if room is None else self.visibility_views.get(room.room_id)
                                replies=self.arena.equipment_batch(self.probe_character_id,packet,view=view)
                            elif packet[:2]==b'\xc8\x3d':
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                view=None if room is None else self.visibility_views.get(room.room_id)
                                replies=self.arena.mine_action(self.probe_character_id,packet,view=view)
                            elif packet[:1]==b'\x3e':
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                view=None if room is None else self.visibility_views.get(room.room_id)
                                replies=self.arena.door_action(self.probe_character_id,packet,view=view)
                                self.events.append({'event':'battle_door_accepted','request_hex':packet.hex()})
                            elif packet[:1]==b'\x6e':
                                replies=self.arena.exchange_action(self.probe_character_id,packet)
                                self.events.append({'event':'battle_exchange_accepted','request_hex':packet.hex()})
                            elif packet[:1] in (b'\x46',b'\x40'):
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                view=None if room is None else self.visibility_views.get(room.room_id)
                                replies=self.arena.loot_action(self.probe_character_id,packet,view=view)
                                self.events.append({'event':'battle_loot_accepted','request_hex':packet.hex()})
                            elif packet[:1]==b'\x6d':
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                view=None if room is None else self.visibility_views.get(room.room_id)
                                if room is None and self.owned_pet_probe and self.database is not None:
                                    from tio.equipment import swap_city_weapons
                                    replies=(swap_city_weapons(self.database,self.account,packet),)
                                    self.events.append({'event':'city_weapon_swap_accepted','request_hex':packet.hex()})
                                else:
                                    replies=self.arena.swap_weapons(self.probe_character_id,packet,view=view)
                                    self.events.append({'event':'battle_weapon_swap_accepted','request_hex':packet.hex()})
                            elif packet[:1]==b'\x49':
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                view=None if room is None else self.visibility_views.get(room.room_id)
                                replies=self.arena.attack(self.probe_character_id,packet,view=view)
                                self.events.append({'event':'battle_attack_accepted','request_hex':packet.hex()})
                            elif packet[:1]==b'\x81':
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                view=None if room is None else self.visibility_views.get(room.room_id)
                                replies=self.arena.cast_ability(self.probe_character_id,packet,view=view)
                                self.events.append({'event':'battle_ability_accepted','request_hex':packet.hex()})
                            elif packet[:1]==b'\x3c':
                                moved=self.arena.move(self.probe_character_id,packet)
                                replies=(moved,) if isinstance(moved,bytes) else tuple(moved)
                                from tio.protocol.battle_move import decode_move_request
                                from dataclasses import asdict
                                actor_id=decode_move_request(packet).actor_id
                                room=next(r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members)
                                self.events.append({'event':'battle_move_accepted','actor':asdict(self.arena._fields[room.room_id].actor(actor_id))})
                                from tio.protocol.action_points import encode_action_points
                                replies=(*replies,encode_action_points(actor_id,self.arena._fields[room.room_id].actor(actor_id).action_points))
                                view=self.visibility_views.get(room.room_id)
                                if view is not None:replies=(*replies,*view.refresh())
                            elif packet[:1]==b'\x3a':
                                reply=self.arena.end_turn(self.probe_character_id,packet,received_at=received_at)
                                replies=self.arena.finished_turn_packets(self.probe_character_id,reply)
                                if getattr(self,'battle_remove_probe',False):
                                    from tio.protocol.battle_remove import encode_battle_remove
                                    room=next(r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members)
                                    removed=self.arena._fields[room.room_id].remove_owner(self.probe_character_id)
                                    replies=(*replies,*(encode_battle_remove(i) for i in removed))
                                    self.events.append({'event':'battle_actors_removed','actor_ids':removed})
                                if getattr(self,'two_turns_probe',False) and not getattr(self,'second_turn_started',False):
                                    room=next(r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members)
                                    if room.members!=(self.probe_character_id,):
                                        raise ValueError('Two-turn diagnostic requires one connected participant')
                                    addressed=self.arena.advance_turn(room.room_id,40)
                                    if any(owner!=self.probe_character_id for owner,_ in addressed):
                                        raise ValueError('No transport for next turn recipient')
                                    replies=(*replies,*(p for _,p in addressed))
                                    self.second_turn_started=True
                                    self.events.append({'event':'second_turn_started','room_id':room.room_id})
                            elif packet[:1]==b'\x36':
                                replies=self.arena.member_loaded(self.probe_character_id,packet)
                                if replies and (self.battle_actor_probe or any(self.probe_character_id in r.members and r.room_id in self.training_matches for r in self.arena.rooms.snapshot())):
                                    room=next(r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members)
                                    if room.room_id in self.training_matches:
                                        from tio.protocol.battle_loaded import encode_member_loaded
                                        replies=(*replies,*(encode_member_loaded(owner) for owner in self.training_matches[room.room_id]))
                                    actors=self.arena._fields[room.room_id].actor_ids(self.probe_character_id)
                                    seconds=20*len(actors)+20 if room.request.mode else 40
                                    replies=(*replies,*self.arena.begin_turn_packets(self.probe_character_id,actors,2 if getattr(self,'turn_timeout_probe',False) else seconds))
                            elif packet[:1]==b'\x2e' and any(self.probe_character_id==r.owner_id and r.request.mode in (1,4) for r in self.arena.rooms.snapshot()):
                                from tio.protocol.arena import decode_room_start
                                from tio.matchmaking import SurvivalQueue
                                from tio.abilities import AbilityCatalog,AbilityLevel
                                from tools.survival_scene import prepare_survival
                                room=next(r for r in self.arena.rooms.snapshot() if r.owner_id==self.probe_character_id)
                                decode_room_start(packet,mode=room.request.mode)
                                if room.room_id in self.training_matches:
                                    replies=()
                                else:
                                    roster=OwnedPetStore(self.database).list(self.account)
                                    ticket=SurvivalQueue().join(self.probe_character_id,roster,mode=room.request.mode)
                                    if len(ticket.actors)!=room.request.soldiers_count_01:
                                        raise ValueError('Selected squad differs from room settings')
                                    source=json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
                                    catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
                                    prepared=prepare_survival(self.database,self.account,ticket,catalog,mode=room.request.mode)
                                    room,replies=self.arena.start_survival(self.probe_character_id,self.probe_character_name,prepared,existing_room=room)
                                    self.training_matches[room.room_id]=prepared.participants[1:]
                                    self.visibility_views[room.room_id]=prepared.visibility
                            else:
                                prepared=None
                                def prepare_scene(room):
                                    nonlocal prepared
                                    if not self.battle_scene_probe:
                                        raise ValueError('Battle scene preparation currently requires diagnostic mode')
                                    from tio.protocol.battle_ground import BattleGround,encode_battle_ground
                                    from tio.protocol.battle_loaded import encode_battle_load_end
                                    actors=()
                                    if self.battle_actor_probe:
                                        from tools.battle_roster_fixture import prepare_actor
                                        from tio.abilities import AbilityCatalog,AbilityLevel
                                        roster=OwnedPetStore(self.database).list(self.account)
                                        if not roster:raise ValueError('Scene actor requires saved roster')
                                        source=json.loads((Path(__file__).resolve().parents[1]/'config/abilities.json').read_text())
                                        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
                                        selected=getattr(self,'battle_actor_id',None) or roster[0][0]
                                        prepared=prepare_actor(self.database,self.account,selected,self.probe_character_id,catalog)
                                        actors=prepared.packets
                                    from tio.protocol.known_mines import encode_known_mines
                                    return (encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64))),*actors,encode_known_mines(()),encode_battle_load_end())
                                replies=self.arena.start_loading(self.probe_character_id,packet,prepare_scene)
                                if replies and self.battle_actor_probe:
                                    self.arena.configure_field(self.probe_character_id,prepared.field)
                        except ValueError as error:
                            from tio.protocol.system_message import encode_shop_error
                            if packet[:2]==b'\xc8\x3d':
                                replies=(*self.arena.rejected_mine_packets(self.probe_character_id,packet),
                                         encode_shop_error('мины: проверь ход, предмет, AP и свободную соседнюю клетку'))
                            elif packet[:1]==b'\x3e':
                                replies=(encode_shop_error('двери: проверь ход, расстояние, AP и свободный проход'),)
                                from tio.protocol.battle_door import decode_door_request,encode_door_state
                                from dataclasses import replace
                                try:request=decode_door_request(packet)
                                except ValueError:request=None
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                field=None if room is None else self.arena._fields.get(room.room_id)
                                if request is not None and field is not None and hasattr(field,'doors'):
                                    actor=field._actors.get(request.actor_id)
                                    state=field.doors.states.get((request.x,request.y))
                                    if (actor is not None and actor.owner_id==self.probe_character_id and state is not None
                                            and max(abs(actor.x-request.x),abs(actor.y-request.y))<=1):
                                        replies=(*replies,encode_door_state(replace(request,opened=state)))
                            elif packet[:1]==b'\x6e':
                                from tio.battle_exchange import refresh
                                replies=(encode_shop_error(str(error)),)
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                field=None if room is None else self.arena._fields.get(room.room_id)
                                if field is not None:
                                    field.combat.exchange_sessions.pop(self.probe_character_id,None)
                                    ids=tuple(int.from_bytes(packet[i:i+4],'little') for i in (1,5) if len(packet)>=i+4)
                                    replies=(*replies,*refresh(field.combat,self.probe_character_id,ids))
                            elif packet[:1] in (b'\x46',b'\x40'):
                                replies=(encode_shop_error('ящика: проверь ход, расстояние, AP и место в инвентаре'),)
                                # Dragging changes the native bag before40 is
                                # committed. Restore our owned authoritative bag
                                # on rejection and clear the client's wait flag.
                                if len(packet)>=5:
                                    identity=int.from_bytes(packet[1:5],'little')
                                    replies=(*replies,*(self.arena.inventory_packets(self.probe_character_id,(identity,)) or ()))
                            elif packet[:1]==b'\x49':
                                from tio.battle_equipment import attack_error
                                replies=(encode_shop_error(attack_error(error)),)
                            else:
                                replies=(encode_shop_error('загрузки боя: запрос пока не выполнен'),)
                            if packet[:1] in (b'\x3c',b'\x3e',b'\x81'):
                                from tio.battle_rejection import restore_actor
                                room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                                field=None if room is None else self.arena._fields.get(room.room_id)
                                replies=(*replies,*restore_actor(field,self.probe_character_id,packet))
                            self.events.append({'event':'arena_loading_rejected','reason':str(error),'request_hex':packet.hex()})
                        if packet[:1] in (b'\x3c',b'\x49',b'\x81') or packet[:2]==b'\xc8\x3d':
                            room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                            field=None if room is None else self.arena._fields.get(room.room_id)
                            combat=getattr(field,'combat',None)
                            if combat is not None:
                                hazards_after=combat.hazard_packets(self.probe_character_id)
                                if hazards_after!=hazards_before:replies=(*replies,*hazards_after)
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'arena_loading_reply','plain_hex':reply.hex()})
                        continue
                    if packet[:2] == b'\xc8\x2b' and hasattr(self,'probe_character_id'):
                        try:
                            if self.survival.searching(self.probe_character_id):
                                raise ValueError('Cancel survival search before creating a room')
                            roster=OwnedPetStore(self.database).list(self.account) if self.owned_pet_probe and self.database is not None else ()
                            room,replies=self.arena.create(self.probe_character_id,self.probe_character_name,packet,roster=roster)
                            if room.request.mode in (1,4) and len(room.members)==1:
                                room,members=self.arena.fill_training_room(room)
                                replies=(replies[0],members)
                        except ValueError as error:
                            from tio.protocol.system_message import encode_shop_error
                            replies=(encode_shop_error('создания боя: параметры пока не поддерживаются'),)
                            self.events.append({'event':'arena_create_rejected','reason':str(error)})
                        else:
                            self.events.append({'event':'arena_room_created','room_id':room.room_id,'members':room.members,'compatibility_profile':True})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'arena_create_reply','plain_hex':reply.hex()})
                        continue
                    if self.hiring is not None and packet[:1]==b'\x64':
                        from tio.services_completion import ServiceRejected
                        try:
                            from server.services_runtime import native
                            replies=native(self,pet_id=decode_dismiss_request(packet))
                        except ServiceRejected as error:
                            from tio.protocol.system_message import encode_shop_error
                            replies=(encode_shop_error('увольнения: '+str(error)),)
                            self.events.append({'event':'dismiss_rejected','reason':str(error)})
                        except ValueError as error:
                            replies=(shop_error_reply(error),)
                            self.events.append({'event':'dismiss_rejected','reason':str(error)})
                        else:
                            self.events.append({'event':'dismiss_scheduled','request_hex':packet.hex()})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'dismiss_reply','plain_hex':reply.hex()})
                        continue
                    if self.hiring is not None and packet==b'\x61':
                        reply=encode_pet_shop(self.hiring.available(self.account))
                        game.sendall(encode_reply(reply,outbound))
                        self.events.append({'direction':'S2C','stage':'available_hire_candidates','plain_hex':reply.hex()})
                        continue
                    if self.hiring is not None and packet[:1]==b'\x63':
                        try:
                            pet,inventory,assets=self.hiring.hire(self.account,decode_hire_request(packet))
                        except ValueError as error:
                            replies=(shop_error_reply(error),)
                            self.events.append({'event':'hire_rejected','reason':str(error)})
                        else:
                            replies=(pet,inventory,encode_asset_count(assets),encode_pet_shop(self.hiring.available(self.account)))
                            self.events.append({'event':'hire_committed','request_hex':packet.hex()})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'hire_reply','plain_hex':reply.hex()})
                        continue
                    if self.owned_pet_probe and self.database is not None and packet[:1]==b'\x6b':
                        from tio.warehouse_service import transfer_private_items, warehouse_error_reply
                        try:
                            replies=warehouse_capacity.transfer(self,packet,capacity=self.catalogs.warehouse_capacity)
                        except ValueError as error:
                            self.events.append({'event':'warehouse_transfer_rejected','request_hex':packet.hex(),'reason':str(error)})
                            replies=(warehouse_error_reply(error),)
                        else:
                            self.events.append({'event':'warehouse_transfer_saved','request_hex':packet.hex()})
                        frames = warehouse_capacity.encode_transfer_replies(
                            self.database, replies, outbound, encode_reply)
                        game.sendall(frames)
                        for reply in replies:
                            self.events.append({'direction':'S2C','stage':'warehouse_transfer_reply','plain_hex':reply.hex()})
                        continue
                    if self.database is not None and packet[:2]==b'\xc8\x2a':
                        from tio.enhancement import EnhancementStore
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            in_room=any(self.probe_character_id in room.members for room in self.arena.rooms.snapshot())
                            result=EnhancementStore(self.database).handle(self.account,packet,
                                allow_mutation=self.owned_pet_probe and not in_room)
                            replies=result.replies
                        except (ValueError,sqlite3.Error) as error:
                            self.events.append({'event':'enhancement_rejected','request_hex':packet.hex(),'reason':str(error)})
                            reasons={'Maximum enhancement reached':'достигнут максимум +25',
                                     'Upgrade Kit required':'нужен Upgrade Kit',
                                     'Enhancement requires the city':'выйдите из боя',
                                     'Owned enhancement item missing':'предмет или набор уже отсутствует'}
                            replies=(encode_shop_error('улучшения: '+reasons.get(str(error),'предмет или набор недоступен')),)
                        else:
                            self.events.append({'event':'enhancement_committed','request_hex':packet.hex(),
                                                'outcome':result.outcome,'level':result.level,'chance':result.chance})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'enhancement_reply','plain_hex':reply.hex()})
                        continue
                    if self.owned_pet_probe and self.database is not None and (packet[:1]==b'\x7e' or packet[:2]==b'\xc2\x03'):
                        from tio.repair import repair
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                            if room is not None:
                                replies=self.arena.repair(self.probe_character_id,packet,view=self.visibility_views.get(room.room_id))
                            else:
                                replies=repair(self.database,self.account,packet,getattr(self,'repair_selection',None))
                                self.repair_selection=None
                        except (ValueError,sqlite3.Error) as error:
                            self.events.append({'event':'repair_rejected','reason':str(error)})
                            replies=(encode_shop_error('ремонта: '+str(error)[:150]),)
                        for reply in replies:
                            game.sendall(encode_initial_frame(reply,outbound) if reply[:1]==b'\x6a' else encode_reply(reply,outbound))
                        continue
                    if self.owned_pet_probe and self.database is not None and packet[:1]==b'\x33':
                        try:
                            room=next((r for r in self.arena.rooms.snapshot() if self.probe_character_id in r.members),None)
                            if room is None:
                                from tio.repair import select_kit
                                from tio.protocol.repair import repair_message
                                selection=select_kit(self.database,self.account,packet)
                                if selection is not None:
                                    self.repair_selection=selection
                                    game.sendall(encode_reply(repair_message(110),outbound))
                                    continue
                            view=None if room is None else self.visibility_views.get(room.room_id)
                            replies=self.arena.equip(self.probe_character_id,packet,view=view)
                            if replies is None:
                                from tio.protocol.item_action import decode_item_action
                                from tio.item_boosters import use_saved,nontransferable
                                action=decode_item_action(packet)
                                own=OwnedPetStore(self.database).inventory(self.account,action.pet_id)
                                selected=next((i for i in decode_item_list(own)[1] if i.instance_id==action.instance_id),None) if own is not None else None
                                if selected is not None and nontransferable(selected.template_id):
                                    replies=(use_saved(self.database,self.account,action),)
                                else:replies=(equip_primary_weapon(self.database,self.account,packet),)
                                owner=int.from_bytes(replies[0][1:5],'little')
                                # Recompute conditional miner defense after putting
                                # on/removing armor, without changing saved base stats.
                                pet=next(p for i,p,inv in OwnedPetStore(self.database).list(self.account) if i==owner)
                                replies+= (pet,)
                        except ValueError as error:
                            self.events.append({'event':'equipment_rejected','reason':str(error),'request_hex':packet.hex()})
                            replies=(shop_error_reply(error),)
                        else:
                            self.events.append({'event':'equipment_saved','request_hex':packet.hex()})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'equipment_reply','plain_hex':reply.hex()})
                        continue
                    if self.owned_pet_probe and self.database is not None and (packet[:1]==b'\x23' or packet[:2]==b'\xb8\x06'):
                        quote=packet[:2]==b'\xb8\x06'
                        try:
                            request=decode_sale_request(packet,quote=quote)
                            result=ShopStore(self.database,self.catalogs).sell(self.account,request,quote=quote)
                        except ValueError as error:
                            self.events.append({'event':'shop_sale_rejected','reason':str(error),'request_hex':packet.hex()})
                            reply=shop_error_reply(error)
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'shop_error','plain_hex':reply.hex()})
                        else:
                            if quote:
                                replies=(encode_sale_quote(request.owner_id,result),)
                            else:
                                self.owned_inventory=result.inventory
                                replies=(result.inventory,encode_asset_count(result.assets))
                            for reply in replies:
                                game.sendall(encode_reply(reply,outbound))
                                self.events.append({'direction':'S2C','stage':'shop_sale_quote' if quote else 'shop_sale_update','plain_hex':reply.hex()})
                        continue
                    if self.owned_pet_probe and self.database is not None and packet[:1] in (b'\x75', b'\x78'):
                        try:
                            if any(self.probe_character_id in room.members for room in self.arena.rooms.snapshot()):
                                raise ValueError('Shop purchases require the city')
                            store=ShopStore(self.database,self.catalogs)
                            result=(store.purchase_premium(self.account,packet) if packet[:1]==b'\x78'
                                    else store.purchase(self.account,decode_shop_purchase(packet)))
                        except ValueError as error:
                            self.events.append({'event':'shop_purchase_rejected','reason':str(error),'request_hex':packet.hex()})
                            reply=shop_error_reply(error)
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'shop_error','plain_hex':reply.hex()})
                        else:
                            if isinstance(result,PurchaseResult):self.owned_inventory=result.inventory
                            from tio.premium import current
                            from tio.protocol.premium_shop import decode_premium_purchase
                            category=(decode_premium_purchase(packet)[1] if packet[:1]==b'\x78'
                                      else decode_shop_purchase(packet).category)
                            refreshed=store.catalog(self.account,category,gold=packet[:1]==b'\x78',
                                                    discounted=bool(current(self.database,self.account)[0]))
                            if isinstance(result,WarehousePurchaseResult):
                                replies=(*warehouse_capacity.purchase_replies(self,result),refreshed)
                                game.sendall(warehouse_capacity.encode_transfer_replies(self.database,replies,outbound,encode_reply))
                            else:
                                replies=(*result.packets(),refreshed)
                                for reply in replies:game.sendall(encode_reply(reply,outbound))
                            for reply in replies:
                                self.events.append({'direction':'S2C','stage':'shop_purchase_update','plain_hex':reply.hex()})
                            self.events.append({'event':'shop_purchase_committed','charged_credits':result.charged_credits,
                                                'charged_gold':result.charged_gold})
                        continue
                    if self.owned_pet_probe and packet[:1]==b'\x2f':
                        requested=decode_item_list_request(packet)
                        battle_items=self.arena.inventory_packets(self.probe_character_id,requested)
                        if battle_items is not None:
                            for reply in battle_items:
                                game.sendall(encode_reply(reply,outbound))
                                self.events.append({'direction':'S2C','stage':'battle_inventory_update','plain_hex':reply.hex()})
                            continue
                        from tio.city_inventory import city_inventory_replies
                        lookup = (lambda owner: OwnedPetStore(self.database).inventory(self.account,owner)) if self.database is not None else (lambda owner: self.owned_inventory if owner==1 else None)
                        for reply in city_inventory_replies(requested, lookup):
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'owned_pet_inventory_trial','plain_hex':reply.hex()})
                        if self.battle_settings_probe:
                            from tio.protocol.arena import BattleSettings,encode_battle_settings_body
                            # Diagnostic values only: no room or wallet mutation is committed.
                            body=encode_battle_settings_body(BattleSettings(1,0,0,1,0,b'ProbeNew',bytes(5),0,0))
                            reply=b'\x6c'+body
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'battle_settings_probe','plain_hex':reply.hex()})
                            if self.battle_members_probe:
                                from tio.protocol.battle_members import BattleMemberRecord,encode_battle_members
                                # Flag0 enables the original post-list transition check (a0a3df).
                                reply=encode_battle_members(0,0,(BattleMemberRecord(self.probe_character_id,self.probe_character_name,0,bytes(6)),))
                                game.sendall(encode_reply(reply,outbound))
                                self.events.append({'direction':'S2C','stage':'battle_members_probe','plain_hex':reply.hex()})
                                self.battle_members_probe=False
                            self.battle_settings_probe=False
                        continue
                    from tio.warehouse_queries import handles as warehouse_query,reply as warehouse_query_reply
                    if warehouse_query(packet) and self.database is not None:
                        from tio.warehouse_service import warehouse_error_reply
                        try:
                            replies=warehouse_capacity.query(self,packet)
                            if replies is None:replies=warehouse_query_reply(self.database,self.account,packet)
                        except ValueError as error:
                            self.events.append({'event':'warehouse_query_rejected','request_hex':packet.hex(),'reason':str(error)})
                            replies=(warehouse_error_reply(error),)
                        for reply in replies:
                            game.sendall(encode_initial_frame(reply,outbound) if reply[:1] in (b'\xfa',b'\x6a') else encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'warehouse_query','request_hex':packet.hex(),'plain_hex':reply.hex()})
                        continue
                    if packet[:1]==b'\xb4' and self.database is not None and self.catalogs is not None:
                        from tio.sc_shop import SCShopStore
                        from tio.rental import RentalStore
                        rental_request=packet[:2] in (b'\xb4\x0e',b'\xb4\x10')
                        stage='rental' if rental_request else 'sc_shop'
                        try:
                            in_room=any(self.probe_character_id in room.members for room in self.arena.rooms.snapshot())
                            store=RentalStore(self.database) if rental_request else SCShopStore(self.database)
                            replies=store.handle(self.account,packet,
                                allow_mutation=self.owned_pet_probe and not in_room)
                        except ValueError as error:
                            self.events.append({'event':stage+'_rejected','request_hex':packet.hex(),'reason':str(error)})
                            replies=(shop_error_reply(error),)
                        else:
                            self.events.append({'event':stage+'_handled','request_hex':packet.hex()})
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':stage+'_reply','plain_hex':reply.hex()})
                        continue
                    if packet[:1]==b'\xc5' and self.database is not None:
                        from tio.equipment_templates import EquipmentTemplateStore
                        from tio.protocol.system_message import encode_shop_error
                        try:
                            in_room=any(self.probe_character_id in room.members for room in self.arena.rooms.snapshot())
                            travelling=bool(self.locations and self.locations.travelling(self.account))
                            if not hasattr(self,'equipment_template_store'):
                                self.equipment_template_store=EquipmentTemplateStore(
                                    self.database,capacity=self.catalogs.warehouse_capacity)
                            replies=self.equipment_template_store.handle(self.account,packet,
                                allow_mutation=self.owned_pet_probe and not in_room and not travelling)
                        except ValueError as error:
                            self.events.append({'event':'equipment_template_rejected','request_hex':packet.hex(),'reason':str(error)})
                            replies=(encode_shop_error('шаблона экипировки: '+str(error)),)
                        for reply in replies:
                            game.sendall(encode_reply(reply,outbound))
                            self.events.append({'direction':'S2C','stage':'equipment_template_reply','plain_hex':reply.hex()})
                        continue
                    if packet[:1]==b'\xb5' and self.database is not None:
                        from tio.achievements import AchievementStore
                        try:
                            if not hasattr(self,'achievement_store'):
                                self.achievement_store=AchievementStore(self.database,capacity=self.catalogs.warehouse_capacity)
                            reply=self.achievement_store.handle(self.account,packet,self.probe_character_name)
                        except ValueError as error:
                            reply=shop_error_reply(error)
                            self.events.append({'event':'achievement_rejected','reason':str(error)})
                        game.sendall(encode_reply(reply,outbound))
                        self.events.append({'direction':'S2C','stage':'achievement_reply','request_hex':packet.hex(),'plain_hex':reply.hex()})
                        continue
                    try:
                        reply=city_service_reply(packet,self.catalogs)
                        if reply is not None and packet[:1] in (b'\x73',b'\x76') and self.database is not None:
                            from tio.premium import current
                            discounted=bool(current(self.database,self.account)[0])
                            if packet[:1]==b'\x73':reply=ShopStore(self.database,self.catalogs).catalog(self.account,packet[1],discounted=discounted)
                            else:
                                from tio.protocol.premium_shop import decode_premium_request
                                reply=ShopStore(self.database,self.catalogs).catalog(self.account,decode_premium_request(packet),gold=True,discounted=discounted)
                    except ValueError as error:
                        if packet[:1] not in (b'\x73',b'\x76'):raise
                        self.events.append({'event':'shop_catalog_rejected','reason':str(error),'request_hex':packet.hex()})
                        reply=shop_error_reply(error)
                    if reply is not None:
                        game.sendall(encode_reply(reply,outbound))
                        self.events.append({'direction':'S2C','stage':'city_service_reply','request_hex':packet.hex(),'plain_hex':reply.hex()})
        self.events.append({'event':'session_stopped'})

    def stop(self):
        self.stopping.set()
        for connection in self.connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self.router is None:self.listener.close()

    def finish(self):
        if self.thread.ident is None:
            if self.router is None:self.listener.close()
            return
        # Short joins keep Ctrl+C responsive on Windows, including unlimited runs.
        while self.thread.is_alive():
            self.thread.join(0.2)
        if hasattr(self,'probe_character_id'):
            self.survival.disconnected(self.probe_character_id)
            self.arena.disconnect(self.probe_character_id)
