from wallet_fixture import fund_wallet
from contextlib import closing
from dataclasses import replace
import json,random,sqlite3,tempfile,unittest
from pathlib import Path
from test_combat import item,FixedRandom
from tio.battle_loot import BattleLoot
from tio.combat import Combat
from tio.battle_state import BattleActor,BattleField
from tio.weapons import WeaponCatalog
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.item_action import ItemAction,encode_item_action
from tio.protocol.battle_position import BattlePositionRequest,encode_position_request
from tio.protocol.battle_loot import LootTransfer,encode_loot_transfer,decode_loot_transfer,encode_container,decode_container
from tio.weight import project_base_weight,inventory_weight
from tio.arena_service import ArenaService

ROOT=Path(__file__).resolve().parents[1]


class BattleLootTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db'
        self.pet=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        self.initial=encode_item_list(1,(item(100,9,2),item(101,3,10)))
        self.pets=OwnedPetStore(self.path);self.pets.ensure('alice',self.pet,self.initial,human=True)
        self.field=BattleField(8,8,[BattleActor(1,7,1,1,15,20,100),BattleActor(2,8,3,1,15,100,100)],step_cost=1)
        self.field.combat=self.combat=Combat(self.field,WeaponCatalog(),rng=FixedRandom())
        self.combat.register(1,self.initial,human=True,path=self.path,account='alice',
                             pet_packet=project_base_weight(self.pet,True,self.initial))
        self.combat.register(2,encode_item_list(2,()),human=True)
        self.field.loot=self.loot=BattleLoot(self.combat,[(2,2),(6,6)],rng=random.Random(81))
        self.request=BattlePositionRequest(1,2,2)

    def saved(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT inventory_packet FROM owned_pets WHERE pet_id=1').fetchone()[0]

    def supply(self,*entries):
        self.loot.open(7,self.request,1)
        self.loot.boxes[(2,2)]=tuple(replace(item(0x60001000+n,t,count),unknown_words=(int(self.loot.metadata[t].get('durability',0)),)*3) for n,(t,count) in enumerate(entries))
        self.combat.temporary_items.update(i.instance_id for i in self.loot.boxes[(2,2)])
        return self.loot.boxes[(2,2)]

    def take(self,items,turn=1):
        return self.loot.transfer(7,LootTransfer(1,2,2,(),tuple((i.instance_id,i.count) for i in items)),turn)

    def test_native_wire_layout_and_malformed_requests(self):
        request=LootTransfer(17,18,11,((1001,3),),((0x60000001,20),))
        self.assertEqual(decode_loot_transfer(encode_loot_transfer(request)),request)
        items=self.supply((301,1),(3,50))
        self.assertEqual(decode_container(encode_container(1,2,2,items)),(1,2,2,items))
        for packet in (b'\x40',encode_loot_transfer(request)+b'\0',
                       encode_loot_transfer(replace(request,deposits=((1,1),(1,1)))),
                       encode_loot_transfer(replace(request,withdrawals=((1001,1),))),
                       encode_loot_transfer(replace(request,withdrawals=((2,0),)))):
            with self.assertRaises(ValueError):decode_loot_transfer(packet)

    def test_positions_match_real_fragment_records(self):
        from tio.arena_map import load_arena_map
        from tools.import_arena_fragments import read_fragment,BASE
        arena=load_arena_map(ROOT/'config/arena_map.json')
        self.assertEqual(set(arena.containers),{(4,8),(7,4),(18,11),(18,24)})
        stored=json.loads((ROOT/'config/arena_fragments.json').read_text())
        for name in stored:
            if not name.startswith(('ashfor_','autfor_','wetfor_')):
                self.assertEqual(stored[name],read_fragment(BASE/'maps'/name));continue
            import copy,hashlib,zlib
            prefix=name[:6];biome={'ashfor':'ash','autfor':'autumn','wetfor':'blight'}[prefix]
            source=ROOT/'reports/forest-biomes/client/base/maps'/name
            original_name=name.replace(prefix,'forest');original=(BASE/'maps'/original_name).read_bytes()
            original=zlib.decompress(original[16:]) if original[:4]==b'\x03ZIP' else original
            self.assertEqual(source.read_bytes(),original.replace(b'forest',prefix.encode()))
            expected=copy.deepcopy(stored[original_name]);expected['models']=[m.replace('forest',prefix) for m in expected['models']]
            expected['sha256']=hashlib.sha256(source.read_bytes()).hexdigest();hashes={}
            for model in expected['models']:
                path=ROOT/'reports/forest-biomes/client/base/setting/biomes'/biome/model
                original_model=next((BASE/'setting').rglob(model.replace(prefix,'forest')))
                self.assertEqual(path.read_bytes(),original_model.read_bytes().replace(b'forest',prefix.encode()))
                hashes[model]=hashlib.sha256(path.read_bytes()).hexdigest()
            expected['door_models_sha256']=hashes;self.assertEqual(stored[name],expected)

    def test_open_and_reopen_charge_original_cost_without_reroll(self):
        replies=self.loot.open(7,self.request,1)
        self.assertEqual([p[0] for p in replies],[0x4e,0x30,0x44,0x47])
        self.assertEqual(replies[-2],b'\x44\x02\x02\x01\x00')
        self.assertEqual(self.field.actor(1).action_points,11)
        first=replies[-1]
        reopened=self.loot.open(7,self.request,1)
        self.assertEqual(reopened[-1],first)
        self.assertNotIn(0x44,[p[0] for p in reopened])
        self.assertEqual(self.field.actor(1).action_points,10)
        self.loot.transfer(7,LootTransfer(1,2,2),1)
        self.assertEqual(self.loot.open(7,self.request,1)[-1],first)
        self.assertEqual(self.field.actor(1).action_points,9)
        self.loot.open(7,self.request,2)
        self.assertEqual(self.field.actor(1).action_points,8)
        self.assertEqual(self.saved(),self.initial)

    def test_rejected_open_has_no_cost_or_random_roll(self):
        for owner,request in ((8,self.request),(7,BattlePositionRequest(1,6,6)),(7,BattlePositionRequest(1,1,2))):
            with self.assertRaises(ValueError):self.loot.open(owner,request,1)
        self.combat.human[1]=False
        with self.assertRaises(ValueError):self.loot.open(7,self.request,1)
        self.combat.human[1]=True
        self.field._actors[1]=replace(self.field.actor(1),action_points=3)
        with self.assertRaises(ValueError):self.loot.open(7,self.request,1)
        self.assertFalse(self.loot.opened)
        self.assertIsNone(self.loot.boxes[(2,2)])
        self.assertEqual(self.field.actor(1).action_points,3)

    def test_looted_crate_stays_open_and_new_battle_resets_visual(self):
        replies=self.loot.open(7,self.request,1)
        self.assertEqual(replies[-2],b'\x44\x02\x02\x01\x00')
        found=self.loot.boxes[(2,2)]
        transfer=self.take(found)
        self.assertEqual(self.loot.boxes[(2,2)],())
        self.assertEqual([p[0] for p in transfer],[0x30])
        reopened=self.loot.open(7,self.request,1)
        self.assertEqual(decode_container(reopened[-1])[3],())
        self.assertNotIn(0x44,[p[0] for p in reopened])
        self.assertNotIn(0x45,[p[0] for p in reopened])
        fresh=BattleLoot(self.combat,[(2,2)],rng=random.Random(81))
        self.assertEqual(fresh.open(7,self.request,2)[-2],b'\x44\x02\x02\x01\x00')

    def test_random_items_use_source_packs_and_source_durability(self):
        seen=set()
        for _ in range(40):
            items=self.loot._roll();weapon=items[0];seen.add(weapon.template_id)
            self.assertTrue(all(i.unknown_words==(int(self.loot.metadata[i.template_id].get('durability',0)),)*3 and not i.equipped for i in items))
            self.assertTrue(all(i.instance_id in self.combat.temporary_items for i in items))
            ammo=int(self.loot.metadata[weapon.template_id].get('ammo_id',0))
            if ammo:
                found=next(i for i in items if i.template_id==ammo)
                self.assertIn(found.count,(int(self.loot.metadata[ammo]['packamount']),2*int(self.loot.metadata[ammo]['packamount'])))
        self.assertGreater(len(seen),5)

    def test_take_split_return_no_duplication_and_weight(self):
        ammo,=self.supply((3,50))
        before=inventory_weight(self.initial)
        self.loot.transfer(7,LootTransfer(1,2,2,(),((ammo.instance_id,20),)),1)
        self.assertEqual(self.loot.boxes[(2,2)][0].count,30)
        self.assertEqual(self.saved(),self.initial)
        items=decode_item_list(self.combat.inventories[1])[1]
        temporary=next(i for i in items if i.instance_id in self.combat.temporary_items)
        self.assertNotEqual(temporary.instance_id,ammo.instance_id)
        self.assertGreater(inventory_weight(self.combat.inventories[1]),before)
        with self.assertRaises(ValueError):self.loot.transfer(7,LootTransfer(1,2,2,(),((ammo.instance_id,20),)),1)
        self.loot.open(7,self.request,1)
        self.loot.transfer(7,LootTransfer(1,2,2,((temporary.instance_id,20),),()),1)
        self.assertEqual(self.loot.boxes[(2,2)][0].count,50)
        self.assertEqual(self.combat.inventories[1],self.initial)

    def test_temp_and_permanent_matching_zero_durability_never_merge(self):
        permanent=replace(item(100,3,10),unknown_words=(0,0,0))
        self.initial=encode_item_list(1,(permanent,))
        self.combat.inventories[1]=self.initial
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=?',(self.initial,))
        self.take(self.supply((3,50)))
        self.assertEqual(len(decode_item_list(self.combat.inventories[1])[1]),2)
        self.assertEqual(self.saved(),self.initial)

    def test_own_supplies_deposit_split_and_retrieve_remain_permanent(self):
        self.loot.open(7,self.request,1)
        self.loot.transfer(7,LootTransfer(1,2,2,((101,4),),()),1)
        saved=decode_item_list(self.saved())[1]
        self.assertEqual(next(i.count for i in saved if i.instance_id==101),6)
        deposited=next(i for i in self.loot.boxes[(2,2)] if i.instance_id not in self.combat.temporary_items)
        self.assertEqual(deposited.count,4)
        self.loot.open(7,self.request,1)
        self.take((deposited,))
        self.assertEqual(self.saved(),self.initial)
        self.assertEqual(self.combat.inventories[1],self.initial)

    def test_owned_equipment_loses_half_current_on_deposit_only(self):
        weapon=replace(item(150,301),unknown_words=(101,250,300))
        self.initial=encode_item_list(1,(weapon,));self.combat.inventories[1]=self.initial
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=?',(self.initial,))
        self.loot.open(7,self.request,1)
        self.loot.transfer(7,LootTransfer(1,2,2,((150,1),),()),1)
        deposited=next(i for i in self.loot.boxes[(2,2)] if i.instance_id not in self.combat.temporary_items)
        self.assertNotEqual(deposited.instance_id,150)
        self.assertEqual(deposited.unknown_words,(50,250,300))
        self.loot.open(7,self.request,1);self.take((deposited,))
        self.assertEqual(decode_item_list(self.saved())[1][0].unknown_words,(50,250,300))

    def test_temporary_equipment_works_and_consumption_never_persists_loot(self):
        weapon,ammo,bandage=self.supply((301,1),(3,50),(9,2))
        self.take((weapon,ammo,bandage))
        self.combat.equip(7,ItemAction(1,weapon.instance_id,255))
        from tio.protocol.battle_attack import AttackRequest
        self.combat.attack(7,AttackRequest(1,3,1))
        self.assertLess(self.field.actor(2).health,100)
        self.combat.use_medical(7,ItemAction(1,bandage.instance_id,255))
        self.combat.use_medical(7,ItemAction(1,100,255))
        saved=decode_item_list(self.saved())[1]
        self.assertEqual({i.instance_id for i in saved},{100,101})
        self.assertEqual(next(i.count for i in saved if i.instance_id==100),1)
        self.assertLess(next(i.count for i in saved if i.instance_id==101),10)
        # Fresh load after a crash/relog only sees persistent inventory.
        self.assertEqual(OwnedPetStore(self.path).inventory('alice',1),self.saved())

    def test_temporary_armor_equips_and_changes_defense(self):
        armor,=self.supply((210,1))
        self.take((armor,))
        before=self.combat.defense(1);points=self.field.actor(1).action_points
        self.combat.equip(7,ItemAction(1,armor.instance_id,255))
        self.assertGreater(self.combat.defense(1),before)
        self.assertEqual(self.field.actor(1).action_points,points-2)
        self.assertEqual(self.saved(),self.initial)

    def test_failed_transfer_is_atomic_and_stale_sessions_rejected(self):
        supplies=self.supply((3,30),(301,1))
        before=(self.combat.inventories[1],dict(self.loot.boxes),set(self.combat.temporary_items),self.field.actor(1))
        for request,turn in ((LootTransfer(1,2,2,(),((supplies[0].instance_id,31),)),1),
                             (LootTransfer(1,2,2,(),((supplies[0].instance_id,1),)),2)):
            with self.assertRaises(ValueError):self.loot.transfer(7,request,turn)
            self.assertEqual((self.combat.inventories[1],dict(self.loot.boxes),set(self.combat.temporary_items),self.field.actor(1)),before)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=?',(b'changed',))
        with self.assertRaisesRegex(ValueError,'outside battle'):self.take(supplies)
        self.assertEqual((self.combat.inventories[1],dict(self.loot.boxes),set(self.combat.temporary_items),self.field.actor(1)),before)

    def test_inventory_capacity_is_checked_after_merge(self):
        self.initial=encode_item_list(1,tuple(item(n+100,317) for n in range(18)))
        self.combat.inventories[1]=self.initial
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=?',(self.initial,))
        supplies=self.supply((301,1))
        with self.assertRaisesRegex(ValueError,'full'):self.take(supplies)
        self.assertEqual(self.saved(),self.initial)
        self.assertEqual(self.loot.boxes[(2,2)],supplies)

    def test_actual_arena_routes_enforce_turn_and_finish_without_loot(self):
        from tio.abilities import AbilityCatalog,AbilityLevel
        from tio.matchmaking import SurvivalQueue
        from tools.survival_scene import prepare_survival
        from tio.wallets import WalletStore
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        source=json.loads((ROOT/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        scene=prepare_survival(self.path,'alice',SurvivalQueue().join(42,self.pets.list('alice')),catalog,seed=42)
        arena=ArenaService(clock=lambda:10)
        room,_=arena.start_survival(42,b'Alice',scene)
        arena.member_loaded(42,b'\x36')
        actor=scene.field.actor(1)
        x,y=next(iter(scene.field.loot.boxes))
        from tio.map_generation import generate_map, reachable_cells
        reached=reachable_cells(generate_map(seed=42).arena)
        adjacent=next(p for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)) if p in reached)
        scene.field._actors[1]=replace(actor,x=adjacent[0],y=adjacent[1])
        packet=encode_position_request(BattlePositionRequest(1,x,y))
        with self.assertRaises(ValueError):arena.loot_action(42,packet)
        arena.begin_turn_packets(42,(1,),40)
        opened=arena.loot_action(42,packet)
        found=decode_container(opened[-1])[3]
        arena.loot_action(42,encode_loot_transfer(LootTransfer(1,x,y,(),tuple((i.instance_id,i.count) for i in found))))
        self.assertTrue(scene.field.combat.temporary_items)
        self.assertEqual(self.saved(),self.initial)
        for identity in scene.field.actor_ids(scene.bot_owner):
            scene.field._actors[identity]=replace(scene.field.actor(identity),health=0)
        self.assertTrue(arena.finish_training(42,self.path,'alice'))
        self.assertFalse(arena._fields)
        self.assertEqual(self.saved(),self.initial)

    def test_encrypted_transport_open_take_reject_and_refresh(self):
        import socket,threading
        from tools.loopback_exchange import LoopbackExchange
        from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        exchange=LoopbackExchange(Path(self.temp.name)/'events.json',database=self.path,open_town_probe=True,observation_seconds=0)
        exchange.probe_character_id=7;exchange.probe_character_name=b'Alice';exchange.locations=None
        exchange.arena=ArenaService(clock=lambda:10)
        arena=exchange.arena
        arena.create(7,b'Alice',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        arena.start_loading(7,b'\x2e',lambda room:(ground,b'\x41'))
        arena.configure_field(7,self.field);arena.member_loaded(7,b'\x36')
        arena.begin_turn_packets(7,(1,),40)
        server,client=socket.socketpair();client.settimeout(3)
        thread=threading.Thread(target=exchange.observe_game,args=(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C')))
        thread.start()
        try:
            cipher=InitialCipher('C2S');reader=InitialFrameReader(InitialCipher('S2C'))
            def request(packet,count):
                client.sendall(encode_initial_frame(packet,cipher))
                packets=[]
                while len(packets)<count:
                    try:chunk=client.recv(65535)
                    except TimeoutError:raise AssertionError((count,[p.hex() for p in packets],exchange.events))
                    if not chunk:raise AssertionError('Transport closed before the expected reply')
                    packets.extend(reader.feed(chunk))
                return packets
            opened=request(encode_position_request(self.request),6)
            self.assertEqual([p[0] for p in opened],[0x4e,0x30,0x4e,0x4e,0x44,0x47])
            from tio.armor_display import encode_armor
            self.assertEqual(opened[3],encode_armor(1,self.field.combat.displayed_armor(1)))
            loot=decode_container(opened[-1])[3]
            transfer=encode_loot_transfer(LootTransfer(1,2,2,(),tuple((i.instance_id,i.count) for i in loot)))
            taken=request(transfer,3)
            self.assertEqual([p[0] for p in taken],[0x30,0x4e,0x4e])
            self.assertTrue({i.instance_id for i in loot}<={i.instance_id for i in decode_item_list(taken[0])[1]})
            rejected=request(transfer,4)
            self.assertEqual([p[0] for p in rejected],[0xf0,0x30,0x4e,0x4e])
            self.assertEqual(rejected[1],taken[0])
            self.assertEqual(self.saved(),self.initial)
        finally:
            client.close();thread.join(3);exchange.stop();server.close()
        self.assertFalse(thread.is_alive())
