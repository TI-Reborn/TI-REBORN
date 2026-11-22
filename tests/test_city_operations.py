"""Portal actions join real public helpers, scene locks, receipts and sockets."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
from importlib.util import find_spec
import json
import socket
import sqlite3
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import test_multi_account as fixture
from server.runtime import Server
from server.multi import MultiServer
from server.city_operations import CityOperations, CityError
from server.city_http import CityHTTP, decode_json, ensure_server
from tio import clan_benefits as benefits, bank_economy as bank
from tio.character_identity import owner_for_slot
from tio.characters import CharacterStore
from tio.clans import schema as clan_schema
from tio.db_transaction import transaction
from tio.locations import LocationStore
from tio.onboarding import prepare
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.shop import ShopStore
from tio.city_catalogs import CityCatalogs

NOW = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
KEY = 'city-test-private-key-000000000000000000'
PIN = '135790'


class CityOperationsTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.MultiAccountTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.server=Server(self.case.config);self.router=MultiServer(self.server);self.server.multi=self.router
        self.path=self.case.config.database;self.now=NOW
        self.ops=CityOperations(self.router,clock=lambda:self.now)
        self.locations=LocationStore(self.path)
        for account in ('alice','bob'):prepare(self.path,account)
        with transaction(self.path) as db:
            for account in ('alice','bob'):self.locations._save(db, account, 3, -153, -317)
            clan_schema(db);benefits.schema(db)
            db.execute("INSERT INTO clans(id,name,name_key,leader,credits) VALUES (1,?,'alpha','alice',10000)",(b'Alpha',))
            for account in ('alice','bob'):db.execute('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,1,0)',(account,))
            db.execute('INSERT INTO territory_claims VALUES (6,1,10,1)')
            db.execute("INSERT INTO territory_claim_history VALUES (6,1,1,10,'fixture','fixture',0)")

    def request(self,action,*,username='alice',slot=1,requestId='city-request-test-0001',**fields):
        return dict(username=username,slot=slot,action=action,requestId=requestId,**fields)

    def read(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {table:tuple(db.execute('SELECT * FROM "'+table+'"').fetchall())
                    for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def buy_item(self):
        shop=ShopStore(self.path,CityCatalogs(fixture.ROOT/'config/city_catalogs.json'))
        offer=next(row for row in shop.catalogs.items[0] if row.item_id==301)
        reply=shop.purchase('alice',ShopPurchase(1,0,offer.unknown_u32_01,1))
        # Purchases may append a separate ammunition bundle after the weapon.
        return next(item.instance_id for item in reversed(decode_item_list(reply.inventory)[1]) if item.template_id==301)

    def mark(self):
        instance=self.buy_item()
        reply=self.ops.action(self.request('mark',instanceId=instance,days=2,pin=PIN))
        return instance,reply['status']['marks'][0]['id']

    def test_status_is_readonly_has_safe_names_and_real_permissions(self):
        before=self.rows();status=self.ops.status(dict(username='alice',slot=1))
        self.assertEqual(self.rows(),before)
        self.assertTrue(status['canOperate']);self.assertEqual(status['balances'],dict(credits=10000,gold=10000))
        self.assertEqual(status['quotes']['stocks'],dict(price=100,currency='credits'))
        self.assertEqual(status['conversion'],dict(creditsPerGold=100))
        self.assertEqual(status['marksLimit'],100);self.assertFalse(status['marksHasMore'])
        self.assertEqual(status['clan']['name'],'Alpha');self.assertTrue(status['bases'][0]['canSetTax'])
        bob=self.ops.status(dict(username='bob',slot=1));self.assertFalse(bob['bases'][0]['canSetTax'])
        text=json.dumps(status);self.assertNotIn('pin_hash',text);self.assertNotIn('changed_accounts',text)

    def test_status_reads_while_another_connection_has_reserved_writer(self):
        with closing(sqlite3.connect(self.path)) as writer, ThreadPoolExecutor(max_workers=1) as pool:
            writer.execute('BEGIN IMMEDIATE')
            try:
                future = pool.submit(self.ops.status, dict(username='alice', slot=1))
                self.assertTrue(future.result(timeout=2)['canOperate'])
            finally:
                writer.rollback()

    def test_city_projection_releases_arena_lock(self):
        projecting, resume = threading.Event(), threading.Event()
        original = self.ops._status

        def project(*args, **kwargs):
            projecting.set()
            self.assertTrue(resume.wait(3))
            return original(*args, **kwargs)

        with patch.object(self.ops, '_status', side_effect=project), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.ops.status, dict(username='alice', slot=1))
            try:
                self.assertTrue(projecting.wait(3))
                lock = self.router.team_arena.lock
                acquired = lock.acquire(blocking=False)
                if acquired:
                    lock.release()
                self.assertTrue(acquired)
            finally:
                resume.set()
            self.assertTrue(future.result(timeout=3)['canOperate'])

    def test_two_shared_battles_can_move_during_portal_reads(self):
        from server.ratings_public import RatingsPublic
        from test_shared_team_arena import SharedTeamTests
        from tio import rating_completion
        from tio.protocol.battle_move import BattleMove, encode_move_request

        fixture = SharedTeamTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.router.team_arena = fixture.hub
        for index in range(4):
            fixture.create(index)
            fixture.send(index, b'\x2e')
        for index in range(4):
            fixture.send(index, b'\x36')
        fixture.hub.tick()
        owners = [fixture.hub.identities[session] for session in fixture.sessions]
        self.assertIsNot(fixture.hub.battles[owners[0]], fixture.hub.battles[owners[2]])
        city_entered, ratings_entered, resume = threading.Event(), threading.Event(), threading.Event()
        original = self.ops._status
        listing = rating_completion.public_listing

        def wait_for_moves(event, method):
            def paused(*args, **kwargs):
                event.set()
                self.assertTrue(resume.wait(5))
                return method(*args, **kwargs)
            return paused

        def move(index):
            battle = fixture.hub.battles[owners[index]]
            field = battle['field']
            field.blocked = frozenset()
            field.doors.states = {}
            identity = field.actor_ids(owners[index])[0]
            other_id = field.actor_ids(owners[index+1])[0]
            field._actors[identity] = replace(field.actor(identity), x=5, y=5, sight_radius=30)
            field._actors[other_id] = replace(field.actor(other_id), x=7, y=5, sight_radius=30)
            for view in battle['views'].values():
                view.refresh()
            replies = fixture.send(index, encode_move_request(BattleMove(identity, ((5, 6),))))
            peer = fixture.hub.queues[owners[index+1]]
            self.assertTrue(any(packet.startswith(b'\x3d') for packet in replies))
            self.assertTrue(any(packet.startswith(b'\x3d') for packet in peer))
            self.assertEqual((field.actor(identity).x, field.actor(identity).y), (5, 6))

        with (patch.object(self.ops, '_status', side_effect=wait_for_moves(city_entered, original)),
              patch.object(rating_completion, 'public_listing', side_effect=wait_for_moves(ratings_entered, listing)),
              ThreadPoolExecutor(max_workers=3) as pool):
            status = pool.submit(self.ops.status, dict(username='alice', slot=1))
            ratings = pool.submit(RatingsPublic(self.router).status,
                                  dict(username='bob', format='wall', scope='all', offset=0, limit=10))
            try:
                self.assertTrue(city_entered.wait(2))
                self.assertTrue(ratings_entered.wait(2))
                pool.submit(move, 0).result(timeout=2)
                pool.submit(move, 2).result(timeout=2)
            finally:
                resume.set()
            self.assertEqual(status.result(timeout=2)['city']['reason'], 'battle_or_search')
            self.assertEqual(ratings.result(timeout=2)['ratings']['total'], 0)

    def test_stock_purchase_concurrent_retry_and_restart_preserve_peer_balance(self):
        request=self.request('stocks_buy',count=7,quote=100)
        with ThreadPoolExecutor(max_workers=4) as pool:replies=list(pool.map(lambda _:self.ops.action(request),range(4)))
        self.assertEqual(sum(not row['replayed'] for row in replies),1)
        self.assertEqual(self.read('SELECT account,credits,gold FROM wallets ORDER BY account'),[('alice',9300,10000),('bob',10000,10000)])
        repeated=CityOperations(self.router,clock=lambda:self.now).action(request);self.assertTrue(repeated['replayed'])
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action({**request,'count':8})
        self.assertEqual(self.rows(),before)

    def test_stock_and_bond_quotes_stale_rejection_and_calendar(self):
        self.ops.action(self.request('stocks_buy',count=2,quote=100));self.assertEqual(self.ops.status(dict(username='alice',slot=1))['securities']['stocks'],2)
        self.ops.action(self.request('stocks_sell',count=2,quote=100,requestId='city-stock-sale-0001'))
        self.ops.action(self.request('bonds_buy',count=2,quote=bank.policy()['bonds']['credits_each'],requestId='city-bond-buy-00001'))
        with self.assertRaises(CityError):self.ops.action(self.request('bonds_sell',count=2,quote=150,requestId='city-bond-sale-0001'))
        self.now=int(datetime(2026,11,25,tzinfo=timezone.utc).timestamp())
        self.ops.action(self.request('bonds_sell',count=2,quote=155,requestId='city-bond-sale-0002'))
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('stocks_buy',count=2,quote=100,requestId='city-stale-quote-001'))
        self.assertEqual(self.rows(),before)

    def test_secondary_slot_owned_mapping_and_empty_wallet_never_seed(self):
        store=CharacterStore(self.path);store.create('alice',CharacterCreateRequest(b'AliceOther',0,(1,0,0,0)))
        with transaction(self.path) as db:
            owner=owner_for_slot(db,'alice',2);self.locations._save(db,owner,3,-153,-317)
        credits, gold = self.read('SELECT credits,gold FROM wallets WHERE account=?', (owner,))[0]
        reply=self.ops.action(self.request('stocks_buy',slot=2,count=1,quote=100))
        self.assertEqual(reply['status']['balances'], dict(credits=credits - 100, gold=gold))
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='alice'")[0],(10000,10000))
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('stocks_buy',slot=3,count=1,quote=100))
        with self.assertRaises(CityError):self.ops.status(dict(username=owner,slot=1))
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:db.execute('DELETE FROM wallets WHERE account=?',(owner,))
        before=self.rows();self.assertFalse(self.ops.status(dict(username='alice',slot=2))['canOperate'])
        with self.assertRaises(CityError):self.ops.action(self.request('stocks_buy',slot=2,count=1,quote=100))
        self.assertEqual(self.rows(),before)

    def test_missing_character_status_and_no_saved_city_failclosed(self):
        self.case.accounts.create('newuser',fixture.PASSWORD)
        before=self.rows();status=self.ops.status(dict(username='newuser',slot=1))
        self.assertEqual(status['characters'],[]);self.assertIsNone(status['balances']);self.assertFalse(status['canOperate'])
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:db.execute("DELETE FROM character_locations WHERE account='alice'")
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('convert',gold=1))
        self.assertEqual(self.rows(),before)

    def test_travel_battle_checkpoint_pending_result_and_stop_fences_include_replay(self):
        request=self.request('stocks_buy',count=1,quote=100);self.ops.action(request)
        with transaction(self.path) as db:db.execute("INSERT INTO map_journeys VALUES ('alice',0,0,100,100,0,100)")
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(request)
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:db.execute('DELETE FROM map_journeys')
        for table,insert in (
            ('battle_checkpoint_members',"INSERT INTO battle_checkpoint_members(account,match_id,owner_id) VALUES ('alice','fixture-match',1)"),
            ('battle_settlement_jobs',"INSERT INTO battle_settlement_jobs(match_id,account,payload) VALUES ('fixture-match','alice','{}')")):
            if insert:
                with transaction(self.path) as db:db.execute(insert)
                with self.assertRaises(CityError):self.ops.action(request)
                with transaction(self.path) as db:db.execute('DELETE FROM '+table)
        self.router.team_arena.private['alice']=(None,None)
        with self.assertRaises(CityError):self.ops.action(request)
        self.router.team_arena.private.clear();self.server.stopping.set()
        with self.assertRaises(CityError):self.ops.action(request)

    def test_prison_and_orphan_failure_audit_block_offline_operations(self):
        from tio.world_completion import prison_schema
        with transaction(self.path) as db:
            prison_schema(db)
            db.execute("INSERT INTO world_prison VALUES ('alice',60,NULL,NULL,3,-153,-317)")
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('convert',gold=1))
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:
            db.execute('DELETE FROM world_prison')
            db.execute("INSERT INTO battle_failure_audit VALUES ('orphan','alice','fixture',0,0)")
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('convert',gold=1))
        self.assertEqual(self.rows(),before)

    def test_mark_lend_return_replay_and_only_actual_idle_peer_refresh(self):
        instance,mark=self.mark();alice=SimpleNamespace(account='alice',_economy_inventory_digest=b'a');bob=SimpleNamespace(account='bob',_economy_inventory_digest=b'b')
        # The real availability checks are retained; these fixture peers only
        # exercise digest invalidation after the transaction has committed.
        with patch.object(self.ops,'_available',return_value=(True,None)):
            self.router.active_accounts={'alice':alice,'bob':bob}
            with patch('server.city_operations.busy_accounts',return_value=set()):
                reply=self.ops.action(self.request('lend',markId=mark,recipientName='Bob',requestId='city-lend-request-01'))
                self.assertIsNone(alice._economy_inventory_digest);self.assertIsNone(bob._economy_inventory_digest)
                self.assertNotIn('changed_accounts',reply['receipt']);self.assertEqual(reply['status']['marks'][0]['holderName'],'Bob')
                returned=self.ops.action(self.request('reclaim',markId=mark,pin=PIN,remove=True,requestId='city-reclaim-00001'))
                self.assertEqual(returned['status']['marks'][0]['state'],'removed');self.assertNotIn(PIN,json.dumps(returned))
                self.assertTrue(self.ops.action(self.request('reclaim',markId=mark,pin=PIN,remove=True,requestId='city-reclaim-00001'))['replayed'])
        self.router.active_accounts={}
        self.assertEqual(self.read("SELECT count(*) FROM warehouse_items WHERE account='bob'")[0][0],0)

    def test_lend_and_reclaim_reject_travelling_recipient_before_physical_move(self):
        _,mark=self.mark()
        with transaction(self.path) as db:db.execute("INSERT INTO map_journeys VALUES ('bob',0,0,100,100,0,100)")
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('lend',markId=mark,recipientName='Bob',requestId='city-busy-lend-0001'))
        self.assertEqual(self.rows(),before)
        with transaction(self.path) as db:db.execute('DELETE FROM map_journeys')
        self.ops.action(self.request('lend',markId=mark,recipientName='Bob',requestId='city-good-lend-0001'))
        with transaction(self.path) as db:db.execute("INSERT INTO map_journeys VALUES ('bob',0,0,100,100,0,100)")
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('reclaim',markId=mark,pin=PIN,remove=False,requestId='city-busy-return-01'))
        self.assertEqual(self.rows(),before)

    def test_wrong_pin_budget_commits_without_pin_receipt_or_echo(self):
        _,mark=self.mark()
        for index in range(5):
            reply=self.ops.action(self.request('reclaim',markId=mark,pin='999999',remove=False,requestId='city-bad-pin-'+str(index).zfill(4)))
            self.assertEqual(reply['error'],'pin_rejected');self.assertNotIn('999999',json.dumps(reply))
        self.assertEqual(self.read('SELECT failures,locked_until FROM bank_item_marks')[0],(0,NOW+300))
        receipts=repr(self.read('SELECT request,receipt FROM bank_economy_receipts'))
        self.assertNotIn(PIN,receipts);self.assertNotIn('999999',receipts)

    def test_base_tax_rights_revision_durable_replay_and_tax_policy(self):
        request=self.request('base_tax',townId=6,tax=5,revision=1)
        reply=self.ops.action(request);self.assertEqual(reply['status']['bases'][0]['revision'],2)
        self.assertTrue(self.ops.action(request)['replayed'])
        before=self.rows()
        for bad in (self.request('base_tax',username='bob',townId=6,tax=6,revision=2),
                    self.request('base_tax',townId=6,tax=6,revision=1,requestId='city-tax-stale-0001')):
            with self.assertRaises(CityError):self.ops.action(bad)
        self.assertEqual(self.rows(),before)

    def test_base_time_real_options_and_owner_fund_clan_treasury_once(self):
        base=self.ops.status(dict(username='alice',slot=1))['bases'][0]
        request=self.request('base_time',townId=6,revision=1,defaultStart=base['defaultStart'],chosenStart=base['timeOptions'][0])
        self.assertEqual(self.ops.action(request)['status']['bases'][0]['chosenStart'],base['timeOptions'][0]);self.assertTrue(self.ops.action(request)['replayed'])
        with transaction(self.path) as db:
            claim=json.dumps(dict(location=6,owner_clan=1,tax_percent=10,revision=1))
            db.execute('INSERT INTO warfare_events VALUES (?,?,?,?,?,?,?,?,?,?)',('city-event-1',6,NOW+1000,NOW+2000,'REGISTRATION',1,NOW,'{}',claim,0))
        request=self.request('base_fund',eventId='city-event-1',credits=500,requestId='city-fund-request-01')
        self.assertEqual(self.ops.action(request)['status']['bases'][0]['events'][0]['fund'],500);self.assertTrue(self.ops.action(request)['replayed'])
        self.assertEqual(self.read('SELECT credits FROM clans WHERE id=1')[0][0],10000)
        self.assertEqual(self.read("SELECT credits FROM wallets WHERE account='alice'")[0][0],9500)

    def test_storage_failure_rolls_back_mark_and_money_before_peer_refresh(self):
        item=self.buy_item()
        with transaction(self.path) as db:db.execute("CREATE TRIGGER city_fail_receipt BEFORE INSERT ON bank_economy_receipts BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before=self.rows()
        with self.assertRaises(sqlite3.IntegrityError):self.ops.action(self.request('mark',instanceId=item,days=2,pin=PIN))
        self.assertEqual(self.rows(),before)

    def test_schema_rejects_bool_extra_owner_path_command_and_duplicate_json(self):
        valid=self.request('convert',gold=1);before=self.rows()
        for bad in ({**valid,'gold':True},{**valid,'slot':True},{**valid,'owner':'bob'},
                    {**valid,'database':'foreign.db'},{**valid,'action':'!bank convert'},
                    {**valid,'requestId':'short'}, {**valid,'gold':1.0}):
            with self.assertRaises(CityError):self.ops.action(bad)
        for raw in (b'{"username":"alice","username":"bob","slot":1}',b'{"x":NaN}',b'\xff'):
            with self.assertRaises(CityError):decode_json(raw)
        self.assertEqual(self.rows(),before)

    def test_online_selected_city_search_and_unselected_session_are_authoritative(self):
        class Session:pass
        session=Session();session.__dict__.update(account='alice',router=self.router,probe_character_id=1,
            locations=self.locations,arena=SimpleNamespace(_fields={},rooms=SimpleNamespace(snapshot=lambda:())),
            survival=SimpleNamespace(searching=lambda _:False))
        self.router.active_accounts['alice']=session
        self.assertTrue(self.ops.status(dict(username='alice',slot=1))['canOperate'])
        owner=self.router.team_arena.identity(session);self.router.team_arena.survival_waiting.add(owner)
        self.assertEqual(self.ops.status(dict(username='alice',slot=1))['city']['reason'], 'battle_or_search')
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('convert',gold=1))

        self.assertEqual(self.rows(),before)
        self.router.team_arena.survival_waiting.clear();session.probe_character_id=None
        self.assertEqual(self.ops.status(dict(username='alice',slot=1))['city']['reason'], 'session_not_idle')
        with self.assertRaises(CityError):self.ops.action(self.request('convert',gold=1))

    def test_operation_waits_for_scene_lock_and_rechecks_busy_before_receipt(self):
        attempted=threading.Event();original=self.ops._running
        def entered():attempted.set();return original()
        before=self.rows()
        with patch.object(self.ops,'_running',side_effect=entered),ThreadPoolExecutor(max_workers=1) as pool:
            with self.router.team_arena.lock:
                future=pool.submit(self.ops.action,self.request('convert',gold=1))
                self.assertTrue(attempted.wait(3))
                self.router.team_arena.private['alice']=(None,None)
            with self.assertRaises(CityError):future.result(timeout=3)
        self.router.team_arena.private.clear();self.assertEqual(self.rows(),before)

    def test_status_eligible_item_cap_announces_remaining_without_owner_or_pin(self):
        from dataclasses import replace
        from tio.protocol.item_list import encode_item_list
        self.buy_item()
        with transaction(self.path) as db:
            original=next(item for item in reversed(decode_item_list(db.execute("SELECT inventory_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0])[1]) if item.template_id==301)
            for index in range(201):db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',10000+index,encode_item_list(0,(replace(original,instance_id=10000+index),))))
        status=self.ops.status(dict(username='alice',slot=1));self.assertEqual(len(status['items']),200)
        self.assertTrue(status['itemsHasMore']);self.assertEqual(status['itemsLimit'],200)

    def test_mark_listing_prioritizes_bag_even_when_legacy_warehouse_ids_are_older(self):
        from dataclasses import replace
        from tio.protocol.item_list import encode_item_list
        instance=self.buy_item()
        with transaction(self.path) as db:
            raw=db.execute("SELECT inventory_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
            items=decode_item_list(raw)[1];original=next(item for item in items if item.instance_id==instance)
            bag_item=replace(original,instance_id=500000)
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=1",(encode_item_list(1,tuple(bag_item if item.instance_id==instance else item for item in items)),))
            for index in range(201):db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',10000+index,encode_item_list(0,(replace(original,instance_id=10000+index),))))
        status=self.ops.status(dict(username='alice',slot=1))
        bag_index=next(index for index,item in enumerate(status['items']) if item['instanceId']==500000)
        warehouse_index=next(index for index,item in enumerate(status['items']) if item['location']=='warehouse')
        self.assertLess(bag_index,warehouse_index)
        self.assertTrue(all(item['location']=='mercenary' for item in status['items'][:warehouse_index]))
        self.assertEqual(len(status['items']),200);self.assertTrue(status['itemsHasMore'])
        self.assertEqual(status['markPolicy']['creditsPerDay'],bank.policy()['marks']['credits_per_day'])


class CityHTTPTests(unittest.TestCase):
    setUp=CityOperationsTests.setUp
    request=CityOperationsTests.request
    def call(self,service,path,payload,key=KEY):
        request=Request('http://127.0.0.1:'+str(service.http.server_port)+path,
            data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key},method='POST')
        try:response=urlopen(request,timeout=3)
        except HTTPError as error:response=error
        with response:return response.status,json.loads(response.read())

    def test_live_loopback_routes_auth_strict_dispatch_and_stop(self):
        service=CityHTTP(self.router,KEY,port=0,operations=self.ops).start();self.addCleanup(service.close)
        self.assertEqual(service.http.server_address[0],'127.0.0.1')
        status,body=self.call(service,'/v1/city/status',dict(username='alice',slot=1));self.assertEqual(status,200);self.assertTrue(body['canOperate'])
        self.assertEqual(self.call(service,'/v1/city/status',dict(username='alice',slot=1),key='wrong')[0],401)
        self.assertEqual(self.call(service,'/v1/city/action',self.request('stocks_buy',count=2,quote=100))[0],200)
        self.assertEqual(self.call(service,'/v1/city/action',{**self.request('stocks_buy',count=2,quote=100),'owner':'bob'})[0],400)
        self.server.stopping.set();service.watcher.join(3);self.assertFalse(service.thread.is_alive());self.assertTrue(service.closed.is_set())

    def test_start_once_key_absence_and_bind_failure_are_failclosed(self):
        economy=SimpleNamespace()
        with patch.dict('os.environ',{},clear=True),patch('server.city_http.CityHTTP') as factory:
            self.assertIsNone(ensure_server(economy,self.router));factory.assert_not_called()
        with patch.dict('os.environ',{'BANK_SERVICE_KEY':KEY},clear=True),patch('server.city_http.CityHTTP',side_effect=OSError('occupied')) as factory:
            self.assertIsNone(ensure_server(economy,self.router));self.assertIsNone(ensure_server(economy,self.router));self.assertEqual(factory.call_count,1)

    def test_connection_workers_are_bounded_before_slow_body_or_core_dispatch(self):
        entered=threading.Event();release=threading.Event();lock=threading.Lock();counts=[0]
        class Operations:
            def status(self,data):
                with lock:
                    counts[0]+=1
                    if counts[0]==8:entered.set()
                release.wait(3);return dict(ok=True)
        service=CityHTTP(self.router,KEY,port=0,operations=Operations()).start();self.addCleanup(service.close)
        self.addCleanup(release.set)
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(self.call,service,'/v1/city/status',dict(username='alice',slot=1)) for _ in range(8)]
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(self.call(service,'/v1/city/status',dict(username='alice',slot=1))[0],429)
            finally:release.set()
            self.assertTrue(all(f.result()[0]==200 for f in futures))


@unittest.skipUnless(find_spec('flask'), 'Uses the existing registration/requirements.txt Flask runtime')
class CityGatewayTests(unittest.TestCase):
    setUp=CityOperationsTests.setUp
    request=CityOperationsTests.request
    read=CityOperationsTests.read

    def gateway(self):
        from server.bank_gateway import create_app
        return create_app(self.path,KEY).test_client()

    def test_gateway_uses_live_core_lock_path_and_owned_slot(self):
        service=CityHTTP(self.router,KEY,port=0,operations=self.ops).start();self.addCleanup(service.close)
        original=urlopen
        def transport(request,timeout):
            self.assertEqual(request.full_url,'http://127.0.0.1:8083/v1/city/'+request.full_url.rsplit('/',1)[1])
            self.assertEqual(request.get_header('Authorization'),'Bearer '+KEY)
            forwarded=Request(request.full_url.replace(':8083/',':'+str(service.http.server_port)+'/'),data=request.data,headers=dict(request.headers),method='POST')
            return original(forwarded,timeout=timeout)
        client=self.gateway();headers={'Authorization':'Bearer '+KEY}
        with patch('urllib.request.urlopen',side_effect=transport):
            reply=client.post('/v1/city/status',json=dict(username='alice',slot=1),headers=headers)
            self.assertEqual(reply.status_code,200);self.assertEqual(reply.json['character'],'Alice')
            reply=client.post('/v1/city/action',json=self.request('stocks_buy',count=3,quote=100),headers=headers)
            self.assertEqual(reply.status_code,200);self.assertEqual(reply.json['receipt']['creditsDelta'],-300)
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='alice'")[0],(9700,10000))

    def test_gateway_rejects_unlinked_and_malformed_before_core(self):
        client=self.gateway();headers={'Authorization':'Bearer '+KEY}
        with patch('urllib.request.urlopen') as transport:
            for payload,status in ((dict(username='unknown',slot=1),404),(dict(username='alice',slot=True),400),
                                   (dict(username='alice',slot=1,owner='bob'),400)):
                self.assertEqual(client.post('/v1/city/status',json=payload,headers=headers).status_code,status)
            self.assertEqual(client.post('/v1/city/action',json=self.request('convert',gold=1),headers={}).status_code,401)
            transport.assert_not_called()

    def test_gateway_offline_or_oversized_malformed_reply_is_503(self):
        client=self.gateway();headers={'Authorization':'Bearer '+KEY}
        class Reply:
            status=200
            def __init__(self,raw):self.raw=raw
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self,maximum):return self.raw[:maximum]
        for value in (Reply(b'['),Reply(b'[]'),Reply(b'x'*65537),Reply(b'{"username":"bob","slot":1,"characters":[]}')):
            with patch('urllib.request.urlopen',return_value=value):
                reply=client.post('/v1/city/status',json=dict(username='alice',slot=1),headers=headers)
                self.assertEqual(reply.status_code,503);self.assertEqual(reply.json,dict(error='service_unavailable'))
        with patch('urllib.request.urlopen',side_effect=OSError('private detail')):
            reply=client.post('/v1/city/action',json=self.request('convert',gold=1),headers=headers)
            self.assertEqual(reply.status_code,503);self.assertNotIn('private detail',repr(reply.json))


if __name__=='__main__':unittest.main()
