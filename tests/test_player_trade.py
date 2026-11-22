from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,sqlite3,tempfile,threading,unittest
from tio.characters import CharacterStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.onboarding import prepare
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import ItemRecord,encode_item_list,decode_item_list
from tio.protocol.player_trade import CREDITS_ID,GOLD_ID
from tio.protocol import player_trade as wire
from tio.player_trade import TradeStore
from tio.db_transaction import transaction
from tio.wallets import WalletStore
from server.presence import Presence
from server.player_trade import PlayerTrade

ROOT=Path(__file__).resolve().parents[1]

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db'
        characters=CharacterStore(self.path)
        for a in ('alice','bobby','clara'):
            characters.create(a,CharacterCreateRequest(a.title().encode(),0,(1,0,0,0)))
            prepare(self.path,a)
        self.store=TradeStore(self.path)
        self.items={}
        for a,tpl in (('alice',3),('bobby',9),('clara',3)):
            item=ItemRecord(200,tpl,bytes(2),50,0,0,(1,1,1),bytes(4),None,bytes(3))
            self.items[a]=item
            with transaction(self.path) as db:
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,(item,)),a))
                db.execute('UPDATE wallets SET credits=1000,gold=0 WHERE account=?',(a,))
        self.parties=(('alice',1),('bobby',1))
        self.offers={'alice':{200:7,CREDITS_ID:12},'bobby':{200:3,CREDITS_ID:4}}
        self.expected={a:{'200':encode_item_list(1,(self.items[a],)).hex()} for a,p in self.parties}

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return (db.execute('SELECT account,pet_id,inventory_packet FROM owned_pets ORDER BY account,pet_id').fetchall(),
                    db.execute('SELECT * FROM wallets ORDER BY account').fetchall())

    def commit(self):return self.store.commit('native-trade-1',self.parties,self.offers,self.expected,100)

    def test_atomic_two_way_trade_partial_stacks_money_metadata_and_replay(self):
        result=self.commit();after=self.state()
        self.assertEqual((result['alice']['credits'],result['alice']['gold']),(992,0))
        self.assertEqual((result['bobby']['credits'],result['bobby']['gold']),(1008,0))
        items=decode_item_list(bytes.fromhex(result['alice']['inventory']))[1]
        self.assertEqual([(i.template_id,i.count) for i in items],[(3,43),(9,3)])
        self.assertEqual(replace(items[1],instance_id=200,unknown_u32_01=50),self.items['bobby'])
        self.assertNotEqual(items[1].instance_id,200)
        self.assertEqual(self.commit(),result);self.assertEqual(self.state(),after)

    def test_changed_durability_or_count_rejects_every_write(self):
        for item in (replace(self.items['alice'],unknown_words=(0,1,1)),replace(self.items['alice'],unknown_u32_01=49)):
            with transaction(self.path) as db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,(item,)),'alice'))
            before=self.state()
            with self.assertRaisesRegex(ValueError,'изменился'):self.commit()
            self.assertEqual(self.state(),before)

    def test_insufficient_money_and_wallet_overflow_roll_back_items(self):
        for credits in (0,0xffffffff):
            with transaction(self.path) as db:db.execute('UPDATE wallets SET credits=? WHERE account=?',(credits,'alice' if credits==0 else 'bobby'))
            before=self.state()
            with self.assertRaises(ValueError):self.commit()
            self.assertEqual(self.state(),before)

    def test_unequipped_owner_bound_quest_and_marked_items_rejected(self):
        for item in (replace(self.items['alice'],unknown_u8_01=1),replace(self.items['alice'],location_raw=16),replace(self.items['alice'],unknown_bytes_02=b'\0\0\1\0'),replace(self.items['alice'],unknown_bytes_02=b'\0\0\0\1'),replace(self.items['alice'],unknown_bytes_03=b'\0\0\1'),replace(self.items['alice'],template_id=65488)):
            with transaction(self.path) as db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,(item,)),'alice'))
            self.assertEqual(self.store.available('alice',1)[0],())
            before=self.state()
            with self.assertRaises(ValueError):self.commit()
            self.assertEqual(self.state(),before)

    def test_foreign_pet_and_duplicate_account_rejected(self):
        with self.assertRaises(ValueError):self.store.available('alice',999)
        with self.assertRaises(ValueError):self.store.commit('x',(('alice',1),('alice',1)),self.offers,self.expected,100)

    def test_destination_capacity_and_late_sql_failure_are_atomic(self):
        fillers=tuple(replace(self.items['bobby'],instance_id=201+i,template_id=8,unknown_u32_01=1) for i in range(18))
        with transaction(self.path) as db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,(self.items['bobby'],*fillers)),'bobby'))
        before=self.state()
        with self.assertRaisesRegex(ValueError,'full'):self.commit()
        self.assertEqual(self.state(),before)
        with transaction(self.path) as db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,(self.items['bobby'],)),'bobby'))
        before=self.state()
        with patch('tio.player_trade.merge_stacks',side_effect=[(replace(self.items['alice'],unknown_u32_01=43),),RuntimeError('late failure')]):
            with self.assertRaises(RuntimeError):self.commit()
        self.assertEqual(self.state(),before)

    def test_competing_commits_only_one_can_take_original_goods(self):
        def run(identity):
            try:self.store.commit(identity,self.parties,self.offers,self.expected,100);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(run,('race1','race2'))),1)

    def test_id_collision_across_bags_is_not_legitimized(self):
        with transaction(self.path) as db:
            raw=db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=1',('alice',)).fetchone()
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',200,encode_item_list(0,(self.items['alice'],))))
        with self.assertRaisesRegex(ValueError,'ID'):self.store.available('alice',1)

class Session:pass

class ServiceTests(StoreTests):
    def setUp(self):
        super().setUp();self.presence=Presence();self.now=100
        self.hub=SimpleNamespace(lock=threading.RLock(),busy=lambda s:False,retained=lambda a:False)
        self.router=SimpleNamespace(presence=self.presence,team_arena=self.hub)
        self.service=PlayerTrade(self.router,self.path,clock=lambda:self.now)
        self.sessions={}
        for n,a in enumerate(('alice','bobby','clara')):
            s=Session();s.account=a;s.database=self.path;s.router=self.router;s.probe_character_id=n+1
            s.probe_character_name=a.title().encode();s.game_authenticated=True;s.stopping=threading.Event()
            s.locations=SimpleNamespace(current=lambda a:3,travelling=lambda a:False)
            s.arena=SimpleNamespace(_fields={},rooms=SimpleNamespace(snapshot=lambda:()))
            s.survival=SimpleNamespace(searching=lambda a:False)
            self.presence.players[s]=(3,SimpleNamespace(name=s.probe_character_name))
            self.presence.messages[s]=deque();self.sessions[a]=s

    def send(self,who,packet):self.assertTrue(self.service.handle(self.sessions[who],packet))
    def opened(self):
        self.send('alice',wire.invite_request(b'Bobby',1));self.send('bobby',wire.answer_request(True,1))
        return self.service.by_session[self.sessions['alice']]

    def test_invitation_reaches_only_target_and_requires_second_party(self):
        self.send('alice',wire.invite_request(b'Bobby',1))
        self.assertIn(wire.invitation(b'Alice'),self.presence.messages[self.sessions['bobby']])
        self.assertEqual(self.presence.messages[self.sessions['clara']],deque())
        self.send('alice',wire.answer_request(True,1));self.assertEqual(self.service.by_session,{})

    def test_native_additions_replace_cumulative_rows_and_duplicate_confirm_is_inert(self):
        draft=self.opened();before=self.state()
        self.send('alice',wire.offer_request(200,5));self.send('alice',wire.offer_request(200,2))
        self.assertEqual(draft.offers['alice'][200],7)
        self.assertEqual(self.state(),before)
        self.send('alice',wire.confirm_request());self.send('alice',wire.confirm_request())
        for account, command in (('alice', 131), ('bobby', 125)):
            notices = [packet for packet in self.presence.messages[self.sessions[account]]
                       if packet.startswith(b'\xf0')]
            self.assertEqual(notices, [bytes((0xf0, command)) + bytes(7)])
        self.assertEqual(self.presence.messages[self.sessions['clara']], deque())
        self.assertEqual(self.state(),before)
        self.send('bobby',wire.confirm_request());after=self.state()
        self.send('bobby',wire.confirm_request());self.assertEqual(self.state(),after)
        self.assertEqual(self.service.by_session,{})

    def test_edit_after_first_confirmation_cancels_without_transfer(self):
        self.opened();self.send('alice',wire.offer_request(200,5));before=self.state()
        self.send('alice',wire.confirm_request());self.send('bobby',wire.offer_request(200,3))
        self.send('bobby',wire.confirm_request());self.assertEqual(self.state(),before)
        self.assertEqual(self.service.by_session,{})

    def test_cancel_timeout_disconnect_and_restart_do_not_escrow(self):
        for action in ('cancel','timeout','disconnect','restart'):
            draft=self.opened();self.send('alice',wire.offer_request(CREDITS_ID,12));before=self.state()
            if action=='cancel':self.send('alice',wire.confirm_request(False))
            elif action=='timeout':self.now+=301;self.service.tick()
            elif action=='disconnect':self.service.disconnect(self.sessions['bobby'])
            else:self.service=PlayerTrade(self.router,self.path,clock=lambda:self.now)
            self.assertEqual(self.state(),before);self.assertEqual(self.service.by_session,{})
            self.now+=3

    def test_other_mutation_cancels_but_chat_and_inventory_reads_do_not(self):
        self.opened()
        for packet in (b'\x70',b'\x2f\x01\0\x01\0\0\0',b'\x21\0H\0i\0\0\0'):
            self.service.guard(self.sessions['alice'],packet);self.assertEqual(len(self.service.by_session),2)
        self.service.guard(self.sessions['alice'],b'\x1b');self.assertEqual(self.service.by_session,{})

    def test_third_party_foreign_item_and_wrong_town_are_rejected(self):
        self.opened();self.send('clara',wire.offer_request(200,1));self.assertEqual(len(self.service.by_session),2)
        self.send('alice',wire.offer_request(999,1));self.assertEqual(self.service.by_session,{})
        self.now+=3;self.sessions['bobby'].locations.current=lambda a:2
        self.send('alice',wire.invite_request(b'Bobby',1));self.assertEqual(self.service.by_session,{})

    def test_new_server_messages_translate_for_english_recipient(self):
        from tio.localization import for_language
        self.opened()
        notices=[p for p in self.presence.messages[self.sessions['bobby']] if p[:1]==b'\x22']
        self.assertTrue(notices)
        self.assertTrue(any(b'C\0h\0o\0o\0s\0e\0' in for_language(p,'english') for p in notices))
        self.assertTrue(any(for_language(p,'russian')!=for_language(p,'english') for p in notices))

class ProtocolTests(unittest.TestCase):
    def test_original_requests_and_strict_lengths(self):
        cases=((wire.invite_request(b'Bob',7),(0x84,(b'Bob',7))),
               (wire.answer_request(True,9),(0x86,(True,9))),
               (wire.offer_request(100,3),(0x88,(100,3))),
               (wire.confirm_request(),(0x8b,(True,))))
        for packet,result in cases:
            self.assertEqual(wire.decode_request(packet),result)
            for wrong in (packet[:-1],packet+b'\0'):
                with self.assertRaises(ValueError):wire.decode_request(wrong)
        for wrong in (b'\x86\x02\0\0\0\0',b'\x8b\x02',b'\x84\0\0\0\0\0'):
            with self.assertRaises(ValueError):wire.decode_request(wrong)
