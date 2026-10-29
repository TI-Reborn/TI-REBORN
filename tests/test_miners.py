from wallet_fixture import fund_wallet
from tio.protocol.map_route import route_words
from tio.roads import ROADS
from contextlib import closing
from dataclasses import replace
import json,sqlite3,struct,tempfile,unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from tio.locations import LocationStore,TOWNS,center
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.item_action import ItemAction,encode_item_action
from tio.protocol.system_message import decode_current_town
from tio.equipment import equip_primary_weapon

ROOT=Path(__file__).resolve().parents[1]


class MinerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db'
        self.trial=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.template=bytes.fromhex(self.trial['packet_hex'])
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        self.hire=HireStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'),self.template)
        self.now=[1000.]
        self.locations=LocationStore(self.path,clock=lambda:self.now[0])

    def travel(self,town,**kw):
        self.locations.travel('alice',struct.pack('<Bii',0x1b,*center(town)),42,**kw)
        self.now[0]+=1000
        return self.locations.refresh('alice',42)

    def test_location_persistence_and_rejected_travel(self):
        self.assertEqual(self.locations.current('alice'),3)
        replies=self.travel(9)
        self.assertEqual(decode_current_town(replies[2]),9)
        self.assertEqual(LocationStore(self.path).current('alice'),9)
        self.assertEqual(self.locations.current('bob'),3)
        for packet in (b'\x1b',struct.pack('<Bii',0x1b,512,0),struct.pack('<Bii',0x1b,*center(9))+b'\0'):
            with self.assertRaises(ValueError):self.locations.travel('alice',packet,42)
        with self.assertRaises(ValueError):self.travel(3,busy=True)
        self.assertEqual(self.locations.current('alice'),9)
        self.travel(3);self.assertEqual(self.locations.current('alice'),3)

    def test_atomic_hiring_only_at_mine_and_reopen(self):
        with self.assertRaises(ValueError):self.hire.hire('alice',6)
        self.travel(9)
        self.assertEqual([c.resource_type for c in self.hire.available('alice')],[6])
        with self.assertRaises(ValueError):self.hire.hire('alice',1)
        p,inv,wallet=self.hire.hire('alice',6)
        self.assertEqual(wallet.credits,6500)
        f=decode_pet_info(p,human_equipment=True).fields
        self.assertEqual(tuple(f[k] for k in ('0x8c446f','0x8c4a07','0x8c4ab1','0x8c4a1b','0x8c4a2f','0x8c4b57')),(6,98,98,8,14,1000))
        self.assertEqual(OwnedPetStore(self.path).list('alice'),((1,p,inv),))
        reopened=HireStore(self.path,self.hire.catalogs,self.template)
        self.assertEqual([c.candidate_id for c in reopened.available('alice')],[1006])
        with self.assertRaises(ValueError):reopened.hire('alice',6)
        self.travel(3)
        with self.assertRaises(ValueError):reopened.hire('alice',1006)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,6500)

    def test_miner_custom_name_survives_restarts(self):
        from tio.protocol.pet_info import encode_pet_info
        self.travel(9)
        p,inv,_=self.hire.hire('alice',6)
        pet=decode_pet_info(p,human_equipment=True)
        pet.fields['0x8c4489']=b'Custom Miner'
        p=encode_pet_info(pet)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',(p,'alice'))
        for _ in range(2):
            HireStore(self.path,self.hire.catalogs,self.template)
            self.assertEqual(OwnedPetStore(self.path).list('alice'),((1,p,inv),))
            self.assertEqual(WalletStore(self.path).ensure('alice').credits,6500)

    def test_no_money_and_transaction_rollback(self):
        self.travel(9)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE wallets SET credits=3499')
        with self.assertRaises(ValueError):self.hire.hire('alice',6)
        self.assertEqual(OwnedPetStore(self.path).list('alice'),())
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=3500')
            db.execute("CREATE TRIGGER deny BEFORE UPDATE ON wallets BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.hire.hire('alice',6)
        self.assertEqual(OwnedPetStore(self.path).list('alice'),())
        self.assertEqual(self.hire.available('alice')[0].candidate_id,6)

    def test_miner_in_survival_squad_and_default_fists(self):
        self.travel(9);self.hire.hire('alice',6);self.travel(3)
        from tio.squad import SquadStore
        from tio.matchmaking import SurvivalQueue
        from tio.abilities import AbilityCatalog,AbilityLevel
        from tools.survival_scene import prepare_survival
        from tio.protocol.battle_soldier import decode_battle_soldier
        SquadStore(self.path).assign('alice',1,1)
        ticket=SurvivalQueue().join(42,OwnedPetStore(self.path).list('alice'))
        data=json.loads((ROOT/'config/abilities.json').read_text())
        scene=prepare_survival(self.path,'alice',ticket,AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in data['records']))
        a=scene.field.actor(1)
        self.assertEqual((a.action_points,a.sight_radius,a.max_health,a.weapons[0].template_id),(14,8,98,337))
        self.assertEqual(scene.field.combat.resources[1],6)
        for p in scene.packets:
            if p[:1]==b'\x3b':
                f=decode_battle_soldier(p,human_equipment=True).fields
                self.assertEqual((f['0x8c50fb'],f['0x8c571d'],f['0x8c567f']),(6,14,8))

    def test_miner_equipment_class_validation(self):
        self.hire.hire('alice',1);self.travel(9);self.hire.hire('alice',6)
        original=decode_item_list(bytes.fromhex(self.trial['inventory_packet_hex']))[1][0]
        for owner,template,valid in ((1,335,False),(2,301,False),(2,335,True),(1,258,False),(2,258,True)):
            # Raise both to level20 only in this isolated fixture to test class restrictions.
            from tio.protocol.pet_info import encode_pet_info
            with closing(sqlite3.connect(self.path)) as db,db:
                p=decode_pet_info(db.execute('SELECT pet_packet FROM owned_pets WHERE pet_id=?',(owner,)).fetchone()[0],human_equipment=True)
                p.fields['0x8c4aef']=20
                item=replace(original,template_id=template,unknown_u8_01=0,location_raw=0)
                inv=encode_item_list(owner,(item,))
                db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE pet_id=?',(encode_pet_info(p),inv,owner))
            action=encode_item_action(ItemAction(owner,item.instance_id,255))
            if valid:self.assertEqual(decode_item_list(equip_primary_weapon(self.path,'alice',action))[1][0].equipped,1)
            else:
                with self.assertRaises(ValueError):equip_primary_weapon(self.path,'alice',action)
                self.assertEqual(OwnedPetStore(self.path).inventory('alice',owner),inv)

    def test_client_zone_bounds_match_server_and_keep_ids(self):
        towns=ET.parse(ROOT/'evidence/zones_diagnostic.xml').getroot().findall('town')
        self.assertEqual([int(t.get('id')) for t in towns],list(range(1,18)))
        for t in towns:
            i=int(t.get('id'));v={e.get('key'):e.get('val') for e in t}
            if i in TOWNS:self.assertEqual(tuple(int(v[k]) for k in ('x1','y1','x2','y2')),TOWNS[i])
        self.assertEqual(TOWNS[9],(-90,-460,-64,-434))

    def test_gradual_progress_and_no_hiring_before_arrival(self):
        start=center(3)
        packets=self.locations.travel('alice',struct.pack('<Bii',0x1b,*center(9)),42)
        self.assertEqual(self.locations.position('alice'),start)
        self.assertIsNone(self.locations.current('alice'))
        self.assertEqual(packets[-1][-1],0)
        self.assertEqual(self.hire.available('alice'),())
        with self.assertRaises(ValueError):self.hire.hire('alice',6)
        self.now[0]+=5
        x,y=self.locations.position('alice')
        self.assertGreater(x,start[0]);self.assertLess(y,start[1])
        self.assertNotEqual((x,y),center(9))
        self.assertEqual(self.locations.refresh('alice',42)[0][-1],0)
        self.assertEqual(self.locations.refresh('alice',42),())
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10000)

    def test_rerouting_from_current_position_and_wilderness_stop(self):
        self.locations.travel('alice',struct.pack('<Bii',0x1b,0,0),42)
        self.now[0]+=10
        point=self.locations.position('alice')
        reply=self.locations.travel('alice',struct.pack('<Bii',0x1b,120,0),42)
        # No repeated leave-city reset: only the new route, announced in 1D packets.
        self.assertEqual({p[0] for p in reply},{0x1d})
        header=struct.unpack_from('<I',reply[0],13)[0]
        self.assertEqual(len(reply),(header&0xffff)+1)
        self.assertEqual(struct.unpack_from('<ii',reply[0],5),point)
        self.now[0]+=1000
        reply=self.locations.refresh('alice',42)
        self.assertEqual([p[0] for p in reply],[0x1e])
        self.assertEqual(self.locations.position('alice'),(120,0))
        self.assertIsNone(self.locations.current('alice'))
        self.assertFalse(self.locations.travelling('alice'))
        self.assertEqual(self.hire.available('alice'),())

    def test_reconnect_in_transit_and_offline_arrival(self):
        self.locations.travel('alice',struct.pack('<Bii',0x1b,*center(9)),42)
        self.now[0]+=10
        other=LocationStore(self.path,clock=lambda:self.now[0])
        self.assertEqual(other.position('alice'),self.locations.position('alice'))
        self.assertIsNone(other.current('alice'))
        resumed=other.resume('alice',42)
        self.assertEqual(resumed[0][0],0xf0)
        self.assertEqual({p[0] for p in resumed[1:]},{0x1d})  # Current turn and the dashed route.
        self.assertEqual(resumed[-1][-1],0)
        self.now[0]+=1000
        self.assertEqual(len(other.refresh('alice',42)),4)
        self.assertEqual(other.current('alice'),9)
        self.assertEqual(other.position('alice'),center(9))
        self.assertEqual(other.refresh('alice',42),())

    def test_existing_names_are_migrated_without_changing_inventory_or_wallet(self):
        from tio.protocol.pet_info import encode_pet_info
        self.travel(9)
        p,inv,_=self.hire.hire('alice',6)
        pet=decode_pet_info(p,human_equipment=True);pet.fields['0x8c4489']='Шахтёр'.encode('cp1251')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',(encode_pet_info(pet),'alice'))
        HireStore(self.path,self.hire.catalogs,self.template)
        self.assertEqual(OwnedPetStore(self.path).list('alice'),((1,p,inv),))
        self.assertEqual(decode_pet_info(p,human_equipment=True).fields['0x8c4489'],b'Shrek')
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,6500)

    def test_old_city_schema_parks_at_miners_town_road(self):
        legacy=Path(self.temp.name)/'legacy.db'
        with closing(sqlite3.connect(legacy)) as db,db:
            db.execute('CREATE TABLE character_locations (account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.execute('INSERT INTO character_locations VALUES (?,9)',('alice',))
        store=LocationStore(legacy)
        self.assertEqual(store.position('alice'),(-62,-351))
        self.assertEqual(store.current('alice'),9)

    def test_live_session_routes_map_catalog_and_hire(self):
        import socket,threading
        from tools.loopback_exchange import LoopbackExchange
        from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
        from tio.protocol.city_catalogs import decode_pet_shop
        from tio.protocol.hire import encode_hire_request
        fund_wallet(self.path, 'probe_user', credits=10_000, gold=10_000)
        exchange=LoopbackExchange(Path(self.temp.name)/'events.json',database=self.path,
                                  open_town_probe=True,owned_pet_probe=True,observation_seconds=0)
        exchange.probe_character_id=42;exchange.probe_character_name=b'Test'
        exchange.locations=self.locations
        exchange.hiring=HireStore(self.path,self.hire.catalogs,self.template)
        server,client=socket.socketpair();client.settimeout(3)
        thread=threading.Thread(target=exchange.observe_game,args=(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C')))
        thread.start()
        try:
            cipher=InitialCipher('C2S');reader=InitialFrameReader(InitialCipher('S2C'))
            def request(p):client.sendall(encode_initial_frame(p,cipher))
            def receive(count):
                packets=[]
                while len(packets)<count:packets.extend(reader.feed(client.recv(65535)))
                return packets
            request(struct.pack('<Bii',0x1b,*center(9)))
            started=receive(1+len(route_words(ROADS.plan(center(3),center(9)))))
            self.assertEqual([p[0] for p in started[:2]],[0xf0,0x1d])
            self.assertEqual(started[-1][-1],0)
            request(b'\x61')
            self.assertEqual(receive(1)[0][0],0xf0)  # No shop access in transit.
            self.now[0]+=1000
            request(b'\x70')
            arrival=receive(5)
            self.assertEqual(sorted(p[0] for p in arrival),sorted((0x1e,0xc8,0xf0,0xf0,0x9e)))
            request(b'\x61');request(encode_hire_request(6))
            packets=receive(7)
            self.assertEqual([p[0] for p in packets],[0x62,0x66,0x30,0x4e,0x4e,0xc8,0x62])
            from tio.armor_display import encode_armor
            self.assertEqual(packets[4],encode_armor(1,0))
            self.assertEqual([c.resource_type for c in decode_pet_shop(packets[0])],[6])
            self.assertEqual(decode_pet_info(packets[1],human_equipment=True).fields['0x8c446f'],6)
            self.assertEqual(WalletStore(self.path).ensure('probe_user').credits,6500)
        finally:
            client.close();thread.join(3);exchange.stop();server.close()
        self.assertFalse(thread.is_alive())
