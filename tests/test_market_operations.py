"""Market registry, legacy receipts, rollback and concurrent-owner integration."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict
import sqlite3,unittest
from unittest.mock import patch
import test_player_auction as auction_fixture
import test_private_market as shop_fixture
import test_player_trade as trade_fixture
from server.player_auction import AuctionSession
from server.private_market import PrivateMarketSession
from server.market_operations import (MARKET_OPERATIONS,MarketContext,market_unit,
                                      prepare_market,execute_market,auction_packet)
from tio.db_transaction import transaction
from tio.protocol.binary import Writer
from tio.protocol.player_auction import decode_create
from tio.protocol import player_trade as trade_wire
from tio.protocol.private_shops import put_price


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return {t:sorted(map(repr,db.execute('SELECT * FROM "'+t+'"').fetchall()))
                for t, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


class AuctionOperationTests(unittest.TestCase):
    def setUp(self):
        self.f=auction_fixture.AuctionTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.path=self.f.path;self.store=self.f.store
        self.sessions={n:AuctionSession(self.store,n,n) for n in ('seller','buyer','other')}

    def call(self,who,packet):
        with patch('server.player_auction.time.time',return_value=101):return self.sessions[who].handle(packet)

    def test_create_roundtrip_exact_original_packet_and_replay_keeps_one_escrow(self):
        packet=auction_fixture.create_packet(count=2)
        self.assertEqual(auction_packet(asdict(decode_create(packet))),packet)
        with patch.object(MARKET_OPERATIONS,'execute',wraps=MARKET_OPERATIONS.execute) as run:
            self.call('seller',packet);self.call('seller',packet)
            self.assertEqual([c.args[0].name for c in run.call_args_list],['auction_create']*2)
        self.assertEqual(len(self.store.lots()),1);self.assertEqual(self.f.wallets.ensure('seller').credits,9950)
        self.assertEqual(self.f.store.get(1)[1][0].count,2)

    def test_bid_refund_and_buyout_use_registry_and_one_buyer_wins(self):
        lot=self.f.create(count=2)
        self.call('buyer',Writer().u8(0xc8).u8(13).u32(lot).u32(1000).u32(0).build())
        with patch.object(MARKET_OPERATIONS,'execute',wraps=MARKET_OPERATIONS.execute) as run:
            self.call('other',Writer().u8(0xc8).u8(15).u32(lot).build())
            self.assertEqual(run.call_args.args[0].name,'auction_buyout')
        self.assertEqual([self.f.wallets.ensure(a).credits for a in ('seller','buyer','other')],[13000,10000,7000])
        before=snapshot(self.path)
        with self.assertRaises(ValueError):self.call('buyer',Writer().u8(0xc8).u8(15).u32(lot).build())
        self.assertEqual(snapshot(self.path),before)

    def test_competing_adapters_cannot_buy_same_physical_lot(self):
        lot=self.f.create(count=2);packet=Writer().u8(0xc8).u8(15).u32(lot).build()
        def buy(who):
            try:self.sessions[who].handle(packet);return True
            except ValueError:return False
        with patch('server.player_auction.time.time',return_value=101),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(buy,('buyer','other')))
        self.assertEqual(sum(results),1)
        self.assertEqual(sum(self.f.wallets.ensure(a).credits for a in self.sessions),30000)

    def test_create_projection_failure_rolls_back_escrow_pledge_and_sequence(self):
        before=snapshot(self.path)
        with patch.object(self.sessions['seller'],'balances',side_effect=RuntimeError('projection')):
            with self.assertRaises(RuntimeError):self.call('seller',auction_fixture.create_packet())
        self.assertEqual(snapshot(self.path),before)
        self.call('seller',auction_fixture.create_packet());self.assertEqual(len(self.store.lots()),1)

    def test_buyout_projection_failure_restores_previous_bidder_and_items(self):
        lot=self.f.create(count=2);self.store.bid('buyer','buyer',lot,1000,0,now=101)
        before=snapshot(self.path)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE outer_marker(id INTEGER)');db.execute('INSERT INTO outer_marker VALUES (1)')
            with patch.object(self.sessions['other'],'balances',side_effect=RuntimeError('projection')):
                with self.assertRaises(RuntimeError):self.call('other',Writer().u8(0xc8).u8(15).u32(lot).build())
        after=snapshot(self.path);self.assertEqual(after.pop('outer_marker'),['(1,)']);self.assertEqual(after,before)

    def test_cancel_replay_returns_goods_once_without_refunding_pledge(self):
        lot=self.f.create(count=2);packet=Writer().u8(0xc8).u8(14).u32(lot).build()
        self.call('seller',packet);before=snapshot(self.path);self.call('seller',packet)
        self.assertEqual(before,snapshot(self.path));self.assertEqual(self.f.wallets.ensure('seller').credits,9950)

    def test_gate_is_rechecked_inside_transaction_and_owner_cannot_cancel_foreign_lot(self):
        self.sessions['seller'].gate=lambda:False;before=snapshot(self.path)
        with self.assertRaises(ValueError):self.call('seller',auction_fixture.create_packet())
        self.assertEqual(before,snapshot(self.path));lot=self.f.create()
        with self.assertRaises(ValueError):self.call('buyer',Writer().u8(0xc8).u8(14).u32(lot).build())
        self.assertEqual(self.store.get(lot)[0]['state'],'active')

    def test_auction_store_joins_without_changing_outer_row_factory(self):
        lot=self.f.create()
        with transaction(self.path) as db:
            self.assertIsNone(db.row_factory);self.assertEqual(self.store.get(lot)[0]['id'],lot)
            self.assertIsNone(db.row_factory);self.assertEqual(db.execute('SELECT 1').fetchone(),(1,))

    def test_bad_created_lot_result_is_programming_error_and_rolls_back(self):
        before=snapshot(self.path);original=self.store.create
        def invalid(*args,**kwargs):original(*args,**kwargs);return 'not-a-lot'
        with patch.object(self.store,'create',side_effect=invalid):
            with self.assertRaises(RuntimeError):self.call('seller',auction_fixture.create_packet())
        self.assertEqual(before,snapshot(self.path))

    def test_unapplied_bid_result_is_not_accepted(self):
        lot=self.f.create();before=snapshot(self.path)
        with patch.object(self.store,'bid',return_value=None):
            with self.assertRaises(RuntimeError):self.call('buyer',Writer().u8(0xc8).u8(13).u32(lot).u32(1000).u32(0).build())
        self.assertEqual(before,snapshot(self.path))

    def test_context_rejects_wrong_database_and_no_transaction_and_mutable_gates(self):
        command=prepare_market('auction_cancel','market-request-0001',dict(lotId=1))
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(RuntimeError):MARKET_OPERATIONS.execute(command,MarketContext(db,self.path,'seller',self.store,True,101))
        with market_unit(self.path) as db:
            for path,allowed in ((self.path.with_name('foreign.db'),True),(self.path,1)):
                with self.assertRaises(RuntimeError):MARKET_OPERATIONS.execute(command,MarketContext(db,path,'seller',self.store,allowed,101))
            with self.assertRaises(ValueError):MARKET_OPERATIONS.execute(command,MarketContext(db,self.path,'seller',self.store,False,101))


class PrivateMarketOperationTests(unittest.TestCase):
    def setUp(self):
        self.f=shop_fixture.MarketTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        from tio.sc_auction import SCAuctionStore,policy
        rules=policy();rules['offers']=[{**rules['offers'][0],'duration':10,'extension':3,'automatic':True}]
        self.path=self.f.path;self.start=1791600000;self.now=self.start+1
        self.sc=SCAuctionStore(self.path,rules=rules,choose=lambda names:names[0]);self.sc.tick(now=self.start)
        self.sessions={n:PrivateMarketSession(self.f.shops,self.sc,n,clock=lambda:self.now) for n in ('Alice','Bobby','Clara')}

    def buy_packet(self,ident,count=7):return Writer().u8(0xae).u8(6).u32(ident).u32(1).u32(1).u32(count).build()
    def select(self,who,ident):self.sessions[who].handle(Writer().u8(0xae).u8(3).u32(ident).build())

    def test_private_buy_rechecks_quote_and_does_not_charge_second_packet(self):
        ident,revision,item=self.f.listing();self.select('Bobby',ident)
        with patch.object(MARKET_OPERATIONS,'execute',wraps=MARKET_OPERATIONS.execute) as run:
            self.sessions['Bobby'].handle(self.buy_packet(ident));self.assertEqual(run.call_args.args[0].name,'shop_buy')
        before=snapshot(self.path)
        with self.assertRaises(ValueError):self.sessions['Bobby'].handle(self.buy_packet(ident))
        self.assertEqual(before,snapshot(self.path))

    def test_private_projection_failure_rolls_back_both_wallets_goods_receipt_and_quote(self):
        ident,revision,item=self.f.listing();self.select('Bobby',ident)
        session=self.sessions['Bobby'];before=snapshot(self.path)
        with patch.object(session,'own',side_effect=RuntimeError('projection')):
            with self.assertRaises(RuntimeError):session.handle(self.buy_packet(ident))
        self.assertEqual(before,snapshot(self.path));self.assertEqual(session.quotes[ident],revision)
        session.handle(self.buy_packet(ident));self.assertEqual(self.f.balance('Bobby'),2993)

    def test_publish_sales_orders_and_signature_use_shared_registry(self):
        item=self.f.ammo();w=Writer().u8(0xae).u8(8).u8(0).u32(1).u32(item.instance_id).u32(7);put_price(w,100)
        orders=Writer().u8(0xae).u8(9).u32(1).u32(3).u32(7);put_price(orders,100);orders.u8(0).u8(0)
        signature=b'\xae\x0a'+'Trade test\0'.encode('utf-16-le')
        with patch.object(MARKET_OPERATIONS,'execute',wraps=MARKET_OPERATIONS.execute) as run:
            self.sessions['Alice'].handle(w.build());self.sessions['Bobby'].handle(orders.build());self.sessions['Alice'].handle(signature)
            self.assertEqual([c.args[0].name for c in run.call_args_list],['shop_sales','shop_orders','shop_signature'])

    def test_private_sell_to_funded_order_is_atomic_and_rejects_stale_quote(self):
        item=self.f.ammo();self.f.shops.publish_orders('Bobby',[(3,7,100,None)])
        ident=self.f.shops.ensure('Bobby');self.select('Alice',ident)
        packet=Writer().u8(0xae).u8(7).u32(ident).u32(1).u32(1).u32(item.instance_id).u32(7).build()
        self.sessions['Alice'].handle(packet);before=snapshot(self.path)
        with self.assertRaises(ValueError):self.sessions['Alice'].handle(packet)
        self.assertEqual(before,snapshot(self.path))

    def test_invalid_publish_revision_rolls_back_escrow(self):
        item=self.f.ammo();w=Writer().u8(0xae).u8(8).u8(0).u32(1).u32(item.instance_id).u32(7);put_price(w,100)
        before=snapshot(self.path);original=self.f.shops.publish_sales
        def invalid(*args,**kwargs):original(*args,**kwargs);return None
        with patch.object(self.f.shops,'publish_sales',side_effect=invalid):
            with self.assertRaises(RuntimeError):self.sessions['Alice'].handle(w.build())
        self.assertEqual(before,snapshot(self.path))

    def test_sc_native_duplicate_bid_has_one_fee_and_query_is_not_advanced(self):
        session=self.sessions['Alice'];session.handle_sc(b'\xbd\1\0\0\0')
        packet=Writer().u8(0xbd).u8(6).u32(1).build()
        with patch.object(MARKET_OPERATIONS,'execute',wraps=MARKET_OPERATIONS.execute) as run:
            session.handle_sc(packet);self.assertEqual(run.call_args.args[0].name,'sc_bid')
        before=snapshot(self.path);session.handle_sc(packet)
        self.assertEqual(before,snapshot(self.path));self.assertEqual(session.sc_quotes[1],0)
        self.assertEqual(self.f.balance('Alice'),2995)

    def test_sc_bot_apply_delete_and_chat_all_use_same_operation(self):
        session=self.sessions['Alice'];session.handle_sc(Writer().u8(0xbd).u8(20).u8(0).u32(1).build())
        apply=Writer().u8(0xbd).u8(20).u8(1).u32(1).u32(0).u32(2).u32(0).build()
        session.handle_sc(apply);before=snapshot(self.path);session.handle_sc(apply)
        self.assertEqual(before,snapshot(self.path));self.assertEqual(self.f.balance('Alice'),2990)
        session.handle_sc(Writer().u8(0xbd).u8(20).u8(2).u32(1).build())
        self.assertEqual(self.f.balance('Alice'),3000)
        with patch.object(MARKET_OPERATIONS,'execute',wraps=MARKET_OPERATIONS.execute) as run:
            session.command('!sc bid 1');self.assertEqual(run.call_args.args[0].name,'sc_bid')

    def test_sc_claim_reply_failure_keeps_winner_money_and_mail_then_retry_once(self):
        self.sc.bid('Alice',1,request='sc-initial-bid-001',now=self.start+1)
        self.sc.tick(now=self.start+14,replenish=False);self.now=self.start+15
        session=self.sessions['Alice'];session.handle_sc(Writer().u8(0xbd).u8(7).u32(1).build())
        packet=Writer().u8(0xbd).u8(9).u32(1).u8(1).build();before=snapshot(self.path)
        with patch.object(session,'sc_catalogue',side_effect=RuntimeError('projection')):
            with self.assertRaises(RuntimeError):session.handle_sc(packet)
        self.assertEqual(before,snapshot(self.path));session.handle_sc(packet)
        after=snapshot(self.path);session.handle_sc(packet);self.assertEqual(after,snapshot(self.path))
        self.assertEqual(len(after['mail_messages']),1)

    def test_bad_private_result_rolls_back_even_in_caught_outer_transaction(self):
        ident,revision,item=self.f.listing();self.select('Bobby',ident);before=snapshot(self.path)
        original=self.f.shops.buy
        def invalid(*args,**kwargs):original(*args,**kwargs);return dict(credits='invalid',items=1)
        with transaction(self.path),patch.object(self.f.shops,'buy',side_effect=invalid):
            with self.assertRaises(RuntimeError):self.sessions['Bobby'].handle(self.buy_packet(ident))
        self.assertEqual(before,snapshot(self.path))

    def test_no_mutation_when_city_gate_false_for_shop_or_sc(self):
        ident,revision,item=self.f.listing();self.select('Bobby',ident);before=snapshot(self.path)
        with self.assertRaises(ValueError):self.sessions['Bobby'].handle(self.buy_packet(ident),allow_mutation=False)
        self.sessions['Alice'].handle_sc(b'\xbd\1\0\0\0');before=snapshot(self.path)
        with self.assertRaises(ValueError):self.sessions['Alice'].handle_sc(Writer().u8(0xbd).u8(6).u32(1).build(),allow_mutation=False)
        self.assertEqual(before,snapshot(self.path))


class BarterOperationTests(unittest.TestCase):
    def setUp(self):
        self.f=trade_fixture.ServiceTests(methodName='runTest');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.path=self.f.path;self.service=self.f.service

    def test_barter_commit_uses_registry_and_only_second_confirm_moves_assets(self):
        self.f.opened();self.f.send('alice',trade_wire.offer_request(200,7));before=self.f.state()
        self.f.send('alice',trade_wire.confirm_request());self.assertEqual(before,self.f.state())
        with patch.object(MARKET_OPERATIONS,'execute',wraps=MARKET_OPERATIONS.execute) as run:
            self.f.send('bobby',trade_wire.confirm_request());self.assertEqual(run.call_args.args[0].name,'trade_commit')
        after=self.f.state();self.f.send('bobby',trade_wire.confirm_request());self.assertEqual(after,self.f.state())

    def test_barter_projection_failure_rolls_back_and_does_not_queue_success(self):
        draft=self.f.opened();self.f.send('alice',trade_wire.offer_request(200,7));self.f.send('alice',trade_wire.confirm_request())
        before=snapshot(self.path)
        for queue in self.f.presence.messages.values():queue.clear()
        with patch.object(self.service,'closing_packets',side_effect=RuntimeError('projection')):
            with self.assertRaises(RuntimeError):self.service.confirm(self.f.sessions['bobby'],True)
        self.assertEqual(before,snapshot(self.path));self.assertEqual(draft.confirmed,{'alice'})
        self.assertTrue(all(not queue for queue in self.f.presence.messages.values()))
        self.service.confirm(self.f.sessions['bobby'],True);self.assertEqual(self.service.by_session,{})

    def test_corrupt_barter_result_rolls_back_both_owners(self):
        self.f.opened();self.f.send('alice',trade_wire.offer_request(200,7));self.f.send('alice',trade_wire.confirm_request())
        before=snapshot(self.path);original=self.service.store.commit
        def invalid(*args,**kwargs):original(*args,**kwargs);return {}
        with patch.object(self.service.store,'commit',side_effect=invalid):
            with self.assertRaises(RuntimeError):self.service.confirm(self.f.sessions['bobby'],True)
        self.assertEqual(before,snapshot(self.path))


if __name__=='__main__':unittest.main()
