from wallet_fixture import fund_wallet
import json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import closing
from tio.battle_recovery import decode_treatment,treat,save_wounds
from tio.battle_recovery import RecoveryStore
from tio.battle_rewards import settle
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import decode_pet_info


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db'
        self.wallet=WalletStore(self.path);fund_wallet(self.wallet.path, 'alice', credits=10_000, gold=10_000)
        data=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        self.store=OwnedPetStore(self.path)
        self.store.ensure('alice',bytes.fromhex(data['packet_hex']),bytes.fromhex(data['inventory_packet_hex']),human=True)

    def hp(self):
        return decode_pet_info(self.store.list('alice')[0][1],human_equipment=True).fields['0x8c4ab1']

    def test_wounds_without_checkbox_and_atomic_reward_retry(self):
        settle(self.path,'alice','match',1,health={1:1})
        self.assertEqual(self.hp(),1)
        settle(self.path,'alice','match',1,health={1:99})
        self.assertEqual(self.hp(),1)
        assets,cost=treat(self.path,'alice',(1,))
        self.assertEqual(cost,198);self.assertEqual(self.hp(),100)
        self.assertEqual(assets.credits,10000-198)
        self.assertEqual(treat(self.path,'alice',(1,))[1],0)
        self.assertEqual(self.wallet.ensure('alice').credits,9802)

    def test_failed_charge_or_unknown_pet_rolls_back_all(self):
        settle(self.path,'alice','loss',0,health={1:0})
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE wallets SET credits=199')
        for ids in ((1,),(1,999)):
            with self.assertRaises(ValueError):treat(self.path,'alice',ids)
            self.assertEqual(self.hp(),0);self.assertEqual(self.wallet.ensure('alice').credits,199)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE wallets SET credits=200')
        self.assertEqual(treat(self.path,'alice',(1,))[0].credits,0)
        self.assertEqual(self.hp(),100)

    def test_reservation_treatment_is_free_for_levels_one_through_three(self):
        from dataclasses import replace
        from tio.locations import LocationStore
        from tio.protocol.pet_info import encode_pet_info

        LocationStore(self.path)
        pet=decode_pet_info(self.store.list('alice')[0][1],human_equipment=True)
        for town,level,expected_cost in ((3,1,0),(3,2,0),(3,3,0),(3,4,20),(2,3,20),(-1,3,20)):
            with self.subTest(town=town,level=level):
                with closing(sqlite3.connect(self.path)) as db,db:
                    db.execute('INSERT OR REPLACE INTO character_locations(account,town_id) VALUES (?,?)',('alice',town))
                    packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':level,'0x8c4ab1':90}))
                    db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(packet,'alice'))
                    db.execute('UPDATE wallets SET credits=? WHERE account=?',(expected_cost,'alice'))
                assets,cost=treat(self.path,'alice',(1,))
                self.assertEqual((assets.credits,cost,self.hp()),(0,expected_cost,100))

    def test_reward_and_wounds_rollback_together(self):
        before=self.hp()
        with self.assertRaises(ValueError):settle(self.path,'alice','bad',1,health={1:1,999:0})
        self.assertEqual(self.hp(),before);self.assertEqual(self.wallet.ensure('alice').credits,10000)

    def test_packet_bounds(self):
        self.assertEqual(decode_treatment(bytes.fromhex('7c020100000004000000')),(1,4))
        for raw in ('7c00','7c0101','7c020100000001000000','7c010100000000','2a01'):
            with self.assertRaises(ValueError):decode_treatment(bytes.fromhex(raw))


class RecoveryPassiveTests(unittest.TestCase):
    from test_ability_learning import AbilityLearningTests
    setUp=AbilityLearningTests.setUp

    def test_finished_roster_refresh_includes_dog_and_reserve(self):
        from tio.arena_service import ArenaService
        arena=ArenaService();store=OwnedPetStore(self.path)
        packet=b'\x50\x01'
        self.assertEqual(arena.city_roster_refresh(7,packet,self.path,'alice'),())
        arena._completed.add(7)
        expected=tuple(p for _,pet,bag in store.list('alice') for p in (pet,bag))
        for packet in (b'\x50\x01',b'\x50\x03',bytes.fromhex('4affffffff')):
            self.assertEqual(arena.city_roster_refresh(7,packet,self.path,'alice'),expected)
        self.assertEqual(arena.city_roster_refresh(7,b'\x2f\x01',self.path,'alice'),())
        self.assertEqual(arena.city_roster_refresh(8,b'\x50\x01',self.path,'alice'),())
        arena._completed.clear()
        self.assertEqual(arena.city_roster_refresh(7,b'\x50\x01',self.path,'alice'),())

    def test_human_dog_learned_maximum_and_no_double_bonus(self):
        for owner,ability in ((1,1),(2,16)):
            self.service.lists('alice',owner);self.service.learn('alice',owner,ability)
        with closing(sqlite3.connect(self.path)) as db,db:save_wounds(db,'alice',{1:1,2:0})
        store=OwnedPetStore(self.path)
        maxima=[decode_pet_info(p,human_equipment=i==1).fields['0x8c4a07'] for i,p,_ in store.list('alice')]
        _,cost=treat(self.path,'alice',(1,2))
        self.assertEqual(cost,2*(sum(maxima)-1))
        for _ in range(2):
            for i,p,_ in store.list('alice'):
                fields=decode_pet_info(p,human_equipment=i==1).fields
                self.assertEqual(fields['0x8c4ab1'],maxima[i-1])
                self.assertEqual(fields['0x8c4a07'],maxima[i-1])
        self.assertEqual(treat(self.path,'alice',(1,2))[1],0)


class PassiveRecoveryTests(unittest.TestCase):
    setUp=RecoveryTests.setUp
    hp=RecoveryTests.hp

    def recovery(self,hp=50):
        with closing(sqlite3.connect(self.path)) as db,db:save_wounds(db,'alice',{1:hp})
        self.now=1000.
        self.recover=RecoveryStore(self.path,clock=lambda:self.now)
        self.assertEqual(self.recover.refresh('alice'),())

    def test_time_remainder_reconnect_and_health_cap(self):
        self.recovery()
        self.now+=9;self.assertEqual(self.recover.refresh('alice'),())
        self.now+=16
        packets=self.recover.refresh('alice');self.assertEqual(len(packets),1)
        self.assertEqual(self.hp(),52)
        # Another process/reconnect uses the same clock, without double healing.
        other=RecoveryStore(self.path,clock=lambda:self.now)
        self.assertEqual(other.refresh('alice'),())
        self.now+=5;other.refresh('alice');self.assertEqual(self.hp(),53)
        self.now+=86400;other.refresh('alice');self.assertEqual(self.hp(),100)
        self.assertEqual(self.wallet.ensure('alice').credits,10000)

    def test_battle_and_offline_suspension_no_catchup(self):
        self.recovery(0)
        self.now+=5;self.recover.refresh('alice',blocked=True)
        self.now+=3600
        reconnect=RecoveryStore(self.path,clock=lambda:self.now)
        reconnect.refresh('alice');self.assertEqual(self.hp(),0)
        self.now+=10;reconnect.refresh('alice');self.assertEqual(self.hp(),1)
        with self.assertRaises(ValueError):treat(self.path,'alice',(1,),blocked=True)
        self.assertEqual(self.hp(),1);self.assertEqual(self.wallet.ensure('alice').credits,10000)

    def test_fresh_wound_and_clock_rollback(self):
        self.recovery(100)
        self.now+=3600
        with closing(sqlite3.connect(self.path)) as db,db:save_wounds(db,'alice',{1:10})
        self.recover.refresh('alice');self.assertEqual(self.hp(),10)
        self.now-=100;self.recover.refresh('alice');self.assertEqual(self.hp(),10)
        self.now+=10;self.recover.refresh('alice');self.assertEqual(self.hp(),11)

    def test_treatment_after_partial_recovery_and_account_isolation(self):
        self.recovery(98)
        self.now+=10;self.recover.refresh('bob');self.assertEqual(self.hp(),98)
        self.recover.refresh('alice');self.assertEqual(self.hp(),99)
        assets,cost=treat(self.path,'alice',(1,))
        self.assertEqual((cost,assets.credits,self.hp()),(2,9998,100))
        self.now+=100;self.recover.refresh('alice');self.assertEqual(self.hp(),100)

    def test_session_passive_updates_and_city_treatment_without_finished_battle(self):
        import socket,threading
        from unittest.mock import patch
        from tools.loopback_exchange import LoopbackExchange
        from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame
        fund_wallet(self.wallet.path, 'probe_user', credits=10_000, gold=10_000)
        pet,bag=self.store.list('alice')[0][1:]
        self.store.ensure('probe_user',pet,bag,human=True)
        with closing(sqlite3.connect(self.path)) as db,db:save_wounds(db,'probe_user',{1:98})
        now=[1000.]
        exchange=LoopbackExchange(self.path.with_suffix('.json'),database=self.path,
                                 open_town_probe=True,owned_pet_probe=True,observation_seconds=0)
        exchange.probe_character_id=42;exchange.probe_character_name=b'Test'
        exchange.recovery=RecoveryStore(self.path,clock=lambda:now[0])
        exchange.recovery.refresh('probe_user')
        server,client=socket.socketpair();client.settimeout(3)
        thread=threading.Thread(target=exchange.observe_game,args=(server,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C')))
        thread.start();cipher=InitialCipher('C2S');reader=InitialFrameReader(InitialCipher('S2C'))
        def request(p):client.sendall(encode_initial_frame(p,cipher))
        def receive(n):
            packets=[]
            while len(packets)<n:packets.extend(reader.feed(client.recv(65535)))
            return packets
        try:
            now[0]+=10;request(b'\x70')
            packets=receive(2)
            from tio.protocol.health import encode_health
            self.assertIn(encode_health(1,99),packets)
            self.assertFalse(any(p[0] in (0x66,0x30) for p in packets))
            with patch.object(exchange.survival,'searching',return_value=True):
                request(bytes.fromhex('7c0101000000'));self.assertEqual(receive(1)[0][0],0xf0)
            self.assertEqual(self.wallet.ensure('probe_user').credits,10000)
            request(bytes.fromhex('7c0101000000'))
            packets=receive(3);self.assertEqual([p[0] for p in packets],[0xc8,0x66,0x4e])
            self.assertEqual(decode_pet_info(packets[1],human_equipment=True).fields['0x8c4ab1'],100)
            self.assertEqual(self.wallet.ensure('probe_user').credits,10000)
            request(bytes.fromhex('7c0101000000'));receive(3)
            self.assertEqual(self.wallet.ensure('probe_user').credits,10000)
        finally:
            client.close();thread.join(3);exchange.stop();server.close()
        self.assertFalse(thread.is_alive())


class MinerRecoveryTests(unittest.TestCase):
    from test_miner_abilities import MinerAbilityTests
    setUp=MinerAbilityTests.setUp
    travel=MinerAbilityTests.travel
    miner=MinerAbilityTests.miner

    def test_health_perk_treatment_before_any_battle(self):
        self.miner(2)  # Vitality rank 2 now requires actor level 2.
        for _ in range(2):
            self.service.tree('alice',1);self.service.learn('alice',1,20)
        assets,cost=treat(self.path,'alice',(1,))
        self.assertEqual(cost,66)  # 98 HP -> level-2 base 103 + Vitality 28.
        fields=decode_pet_info(OwnedPetStore(self.path).list('alice')[0][1],human_equipment=True).fields
        self.assertEqual((fields['0x8c4ab1'],fields['0x8c4a07']),(131,131))

    def test_new_health_capacity_does_not_bank_idle_time(self):
        self.miner()
        now=[1000.];recovery=RecoveryStore(self.path,clock=lambda:now[0])
        recovery.refresh('alice')
        now[0]+=3600
        self.service.tree('alice',1);self.service.learn('alice',1,20)
        self.assertEqual(recovery.refresh('alice'),())
        now[0]+=10
        packets=recovery.refresh('alice')
        from tio.protocol.health import encode_health
        self.assertEqual(packets,(encode_health(1,99),))
        pet=decode_pet_info(OwnedPetStore(self.path).list('alice')[0][1],human_equipment=True)
        self.assertEqual((pet.fields['0x8c4ab1'],pet.fields['0x8c4a07']),(99,118))
