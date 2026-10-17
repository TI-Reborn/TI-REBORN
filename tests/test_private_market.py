from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tio.characters import CharacterStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.onboarding import prepare
from tio.city_catalogs import CityCatalogs
from tio.protocol.shop_purchase import ShopPurchase
from tio.shop import ShopStore
from tio.private_shops import PrivateShopStore
from tio.sc_auction import SCAuctionStore,policy
from tio.protocol.item_list import decode_item_list
from tio.warehouse import WarehouseStore
from tio.wallets import WalletStore
from tio.db_transaction import transaction

ROOT=Path(__file__).resolve().parents[1]


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db'
        self.characters=CharacterStore(self.path)
        for account in ('Alice','Bobby','Clara','David'):
            self.characters.create(account,CharacterCreateRequest(account.encode(),0,(1,0,0,0)));prepare(self.path,account)
        self.shop=ShopStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'))
        self.shops=PrivateShopStore(self.path);self.wallets=WalletStore(self.path)

    def ammo(self,account='Alice'):
        result=self.shop.purchase(account,ShopPurchase(1,0,3,1))
        return next(i for i in decode_item_list(result.inventory)[1] if i.template_id==3 and not i.equipped)

    def balance(self,name):return self.wallets.ensure(name).credits

    def listing(self,account='Alice',*,count=20,price=100,package=False):
        item=self.ammo(account);self.shops.publish_sales(account,[(item.instance_id,count,price)],package=package)
        return self.shops.ensure(account),self.shops.get(self.shops.ensure(account))['revision'],item

    def test_real_saves_trade_partial_native_metadata_and_receipt(self):
        ident,revision,item=self.listing(price=11)
        before={a:self.balance(a) for a in ('Alice','Bobby')}
        result=self.shops.buy('Bobby',ident,[(1,7)],revision=revision,request='buy-first-native-01')
        self.assertEqual(result,dict(credits=1,items=1))
        self.assertEqual([self.balance(a) for a in before],[before['Alice']+1,before['Bobby']-1])
        received=WarehouseStore(self.path).items('Bobby')[0]
        self.assertEqual(replace(received,instance_id=item.instance_id),replace(item,unknown_u32_01=7))
        self.assertEqual(self.shops.buy('Bobby',ident,[(1,7)],revision=revision,request='buy-first-native-01'),result)
        self.assertEqual(WarehouseStore(self.path).items('Bobby')[0].count,7)
        with self.assertRaises(ValueError):self.shops.buy('Clara',ident,[(1,1)],revision=revision,request='buy-second-stale01')

    def test_packages_racing_buyers_only_one_atomic_payout(self):
        ident,revision,item=self.listing(package=True)
        with self.assertRaises(ValueError):self.shops.buy('Bobby',ident,[(1,1)],revision=revision,request='package-partial01')
        def run(account):
            try:self.shops.buy(account,ident,[(1,20)],revision=revision,request='package-race-'+account);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(run,('Bobby','Clara'))),1)
        self.assertEqual(sum(i.count for a in ('Bobby','Clara') for i in WarehouseStore(self.path).items(a)),20)

    def test_replacing_sales_uses_old_native_identity_and_cancel_returns_once(self):
        ident,_,item=self.listing()
        self.shops.publish_sales('Alice',[(item.instance_id,15,200)])
        self.assertEqual(self.shops.get(ident)['sales'][0][1].count,15)
        self.shops.publish_sales('Alice',[]);self.shops.publish_sales('Alice',[])
        with transaction(self.path) as db:
            from tio.market_inventory import owned
            self.assertEqual(sum(i.count for i,_,_ in owned(db,'Alice').values() if i.template_id==3),50)

    def test_funded_requests_filled_partial_cancel_refunds_remaining(self):
        ammo=self.ammo('Alice');self.shops.publish_orders('Bobby',[(3,20,10,None)])
        ident=self.shops.ensure('Bobby');revision=self.shops.get(ident)['revision'];before=self.balance('Alice')
        self.assertEqual(self.balance('Bobby'),2998)
        result=self.shops.sell('Alice',ident,[(1,ammo.instance_id,10)],revision=revision,request='purchase-request1')
        self.assertEqual(result['credits'],1);self.assertEqual(self.balance('Alice'),before+1)
        self.shops.publish_orders('Bobby',[]);self.shops.publish_orders('Bobby',[])
        self.assertEqual(self.balance('Bobby'),2999)
        self.assertEqual(WarehouseStore(self.path).items('Bobby')[0].count,10)

    def test_invalid_funded_request_or_item_rolls_back_old_escrow(self):
        self.shops.publish_orders('Bobby',[(3,2,100,None)])
        before=self.shops.get(self.shops.ensure('Bobby'))
        for rows in [[(3,100000,100,None)],[(65487,1,100,None)],[(3,1,100,28)]]:
            with self.assertRaises(ValueError):self.shops.publish_orders('Bobby',rows)
            self.assertEqual(self.shops.get(before['id']),before);self.assertEqual(self.balance('Bobby'),2998)
        ammo=self.ammo();self.shops.publish_orders('Clara',[(3,1,100,5)])
        with self.assertRaises(ValueError):self.shops.sell('Alice',self.shops.ensure('Clara'),[(1,ammo.instance_id,1)],revision=1,request='wrong-enhancement')
        self.assertEqual(self.balance('Alice'),2950)

    def test_trader_filter_signature_and_restart_state(self):
        ident,_,_=self.listing();self.shops.signature('Alice','Патроны поштучно')
        restored=PrivateShopStore(self.path)
        self.assertEqual(restored.traders(0,3)[0]['signature'],'Патроны поштучно')
        self.assertEqual(restored.traders(0,9),());self.assertEqual(restored.traders(1),())
        self.assertEqual(restored.get(ident)['sales'][0][1].count,20)

    def test_unowned_wallet_not_created_and_secondary_self_trade_rejected(self):
        with self.assertRaises(ValueError):self.shops.ensure('Unknown')
        with transaction(self.path) as db:self.assertIsNone(db.execute("SELECT 1 FROM wallets WHERE account='Unknown'").fetchone())
        self.characters.create('Alice',CharacterCreateRequest(b'AnotherAlice',0,(1,0,0,0)));prepare(self.path,'@character:Alice:2')
        ident,revision,_=self.listing()
        with self.assertRaises(ValueError):self.shops.buy('@character:Alice:2',ident,[(1,1)],revision=revision,request='own-secondary-buy')

    def test_inventory_and_money_atomic_on_injected_delivery_failure(self):
        ident,revision,_=self.listing();before=[self.balance(a) for a in ('Alice','Bobby')]
        with transaction(self.path) as db:db.execute("CREATE TRIGGER deny_delivery BEFORE INSERT ON warehouse_items WHEN NEW.account='Bobby' BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.shops.buy('Bobby',ident,[(1,20)],revision=revision,request='failed-trade-roll')
        self.assertEqual([self.balance(a) for a in ('Alice','Bobby')],before);self.assertEqual(self.shops.get(ident)['sales'][0][1].count,20)

    def auction(self,*,automatic=True):
        rules=policy();rules['offers']=[{**rules['offers'][0],'duration':10,'extension':3,'automatic':automatic}]
        store=SCAuctionStore(self.path,rules=rules,choose=lambda names:names[0]);store.tick(now=100)
        return store

    def test_sc_bid_fee_extension_winner_mail_once_and_restart(self):
        sc=self.auction();sc.bid('Alice',1,request='native-sc-bid-001',now=101)
        self.assertEqual(self.balance('Alice'),2995);self.assertEqual((sc.get(1)['price'],sc.get(1)['ends']),(101,113))
        sc.bid('Bobby',1,request='native-sc-bid-002',now=102)
        sc.tick(now=116,replenish=False)
        result=sc.claim('Bobby',1,request='native-sc-buy-001',now=117)
        self.assertEqual(self.balance('Bobby'),2893)
        self.assertEqual(sc.claim('Bobby',1,request='native-sc-buy-002',now=118),result)
        restarted=SCAuctionStore(self.path,rules=sc.rules);self.assertEqual(restarted.get(1)['message'],result['message'])
        from tio.mail import MailStore
        mail=MailStore(self.path);self.assertEqual(len(mail.listing('Bobby',now=118)),1)
        mail.claim('Bobby',result['message'],now=118);mail.claim('Bobby',result['message'],now=118)
        item=WarehouseStore(self.path).items('Bobby')[0];self.assertEqual((item.template_id,item.count),(9,5))

    def test_sc_last_second_one_random_bot_and_unused_budget_refund(self):
        sc=self.auction()
        for a in ('Alice','Bobby'):sc.set_bot(a,1,0,0,3,request='native-sc-bot-'+a,now=101)
        sc.tick(now=108,replenish=False);self.assertEqual(sc.get(1)['bids'],0)
        sc.tick(now=109,replenish=False);self.assertEqual((sc.get(1)['bids'],sc.get(1)['bidder']),(1,'Alice'))
        self.assertEqual((sc.bot('Alice',1)['held'],sc.bot('Bobby',1)['held']),(10,15))
        sc.tick(now=109,replenish=False);self.assertEqual(sc.get(1)['bids'],1)
        sc.tick(now=112,replenish=False);self.assertEqual(sc.get(1)['bidder'],'Bobby')
        sc.tick(now=116,replenish=False)
        self.assertEqual([self.balance(a) for a in ('Alice','Bobby')],[2995,2995])
        self.assertEqual(sc.bot('Alice',1)['held'],0)

    def test_sc_manual_bid_blocks_bot_window_and_delete_refunds(self):
        sc=self.auction();sc.set_bot('Alice',1,0,0,4,request='native-bot-delete1',now=101)
        sc.bid('Bobby',1,request='manual-in-window1',now=108)
        sc.tick(now=109,replenish=False);self.assertEqual(sc.get(1)['bids'],1)
        sc.set_bot('Alice',1,0,0,0,request='native-deletebot1',now=109)
        self.assertEqual(self.balance('Alice'),3000)
        self.assertEqual(sc.bot('Alice',1)['remaining'],0)

    def test_sc_bot_price_bounds_manual_lot_and_no_phantom_bid_on_restart(self):
        sc=self.auction();sc.set_bot('Alice',1,150,200,3,request='bounded-nativebot',now=101)
        sc.tick(now=109,replenish=False);self.assertEqual(sc.get(1)['bids'],0)
        restored=SCAuctionStore(self.path,rules=sc.rules);restored.tick(now=111,replenish=False)
        self.assertEqual(restored.get(1)['state'],'unsold');self.assertEqual(self.balance('Alice'),3000)
        sc=self.auction(automatic=False);sc.tick(now=112)
        key=sc.list()[0]['id']
        with self.assertRaises(ValueError):sc.set_bot('Alice',key,0,0,1,request='illegal-manualbot',now=113)

    def test_sc_concurrent_bid_same_version_and_replay_only_one_fee(self):
        sc=self.auction()
        def run(a):
            try:sc.bid(a,1,request='race-native-sc-'+a,expected_bids=0,now=101);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sum(pool.map(run,('Alice','Bobby'))),1)
        leader=sc.get(1)['bidder'];sc.bid(leader,1,request='race-native-sc-'+leader,expected_bids=0,now=102)
        self.assertEqual(sc.get(1)['bids'],1);self.assertEqual(sum(self.balance(a) for a in ('Alice','Bobby')),5995)

    def test_sc_insufficient_bot_budget_and_winner_mail_failure_roll_back(self):
        sc=self.auction()
        with self.assertRaises(ValueError):sc.set_bot('Alice',1,0,0,1000,request='invalid-sc-budget',now=101)
        self.assertEqual(self.balance('Alice'),3000)
        sc.bid('Alice',1,request='mail-fault-sc-bid',now=101);sc.tick(now=114,replenish=False)
        with transaction(self.path) as db:db.execute("CREATE TRIGGER deny_mail BEFORE INSERT ON mail_items BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):sc.claim('Alice',1,request='mail-fault-native',now=115)
        self.assertEqual(self.balance('Alice'),2995);self.assertIsNone(sc.get(1)['message'])
        with transaction(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM mail_messages').fetchone()[0],0)

    def test_sc_nested_transaction_and_overflow_payable_never_lost(self):
        from tio import market_inventory as inv
        self.shops.publish_orders('Bobby',[(3,10,100,None)])
        with transaction(self.path) as db:db.execute('UPDATE wallets SET credits=? WHERE account=?',(inv.MAX,'Bobby'))
        with transaction(self.path):self.shops.publish_orders('Bobby',[])
        with transaction(self.path) as db:
            self.assertEqual(db.execute("SELECT amount FROM market_payables WHERE account='Bobby'").fetchone()[0],10)
            inv.debit(db,'Bobby',20);inv.collect(db,'Bobby')
        self.assertEqual(self.balance('Bobby'),inv.MAX-10)

    def test_native_city_adapter_replay_fence_and_atomic_same_account_view(self):
        from server.private_market import PrivateMarketSession
        from tio.protocol.binary import Writer
        ident,revision,item=self.listing();sc=self.auction()
        session=PrivateMarketSession(self.shops,sc,'Bobby')
        listing=session.handle(b'\xae\1\0\0\0\0\0')
        self.assertEqual(listing[0][:2],b'\xae\2')
        self.assertEqual([p[:2] for p in listing[1:]],[b'\xae\4',b'\xae\5'])
        query=Writer().u8(0xae).u8(3).u32(ident).build()
        self.assertEqual(session.handle(query)[0][:2],b'\xae\4')
        buy=Writer().u8(0xae).u8(6).u32(ident).u32(1).u32(1).u32(7).build()
        with self.assertRaises(ValueError):session.handle(buy,allow_mutation=False)
        from tio.protocol.asset_count import decode_asset_count
        replies=session.handle(buy);self.assertEqual(decode_asset_count(replies[0]).credits,2993)
        self.assertEqual(WarehouseStore(self.path).items('Bobby')[0].count,7)
        with self.assertRaises(ValueError):session.handle(buy)
        self.assertEqual(WarehouseStore(self.path).items('Bobby')[0].count,7)
        self.assertEqual(self.shops.get(ident)['sales'][0][1].count,13)

    def test_passive_city_poll_preserves_balances_without_opening_private_stores(self):
        from server.private_market import PrivateMarketSession
        from tio.protocol.asset_count import decode_asset_count
        from tio.protocol.warehouse import decode_warehouse_list
        session=PrivateMarketSession(self.shops,self.auction(),'Bobby',clock=lambda:101)
        with patch('server.private_market.time.monotonic',return_value=10):
            replies=session.refresh()
        self.assertEqual(decode_asset_count(replies[0]).credits,3000)
        self.assertEqual(decode_warehouse_list(replies[1])[:3],(0,1,0))
        self.assertFalse(any(packet[:1]==b'\xae' for packet in replies))

    def test_refresh_after_explicit_market_query_cannot_reopen_closed_native_window(self):
        from server.private_market import PrivateMarketSession
        session=PrivateMarketSession(self.shops,self.auction(),'Bobby',clock=lambda:101)
        # Close is local to the stock client: there is no AE close packet.
        # A remembered query must therefore never authorize a later UI push.
        for kind in (0,1):
            replies=session.handle(bytes((0xae,1,kind))+bytes(4))
            self.assertEqual([packet[:2] for packet in replies],[b'\xae\2',b'\xae\4',b'\xae\5'])
            session.next_refresh=0
            with patch('server.private_market.time.monotonic',return_value=10):
                passive=session.refresh()
            self.assertFalse(any(packet[:1]==b'\xae' for packet in passive))

    def test_peer_trade_still_updates_passive_wallet_and_private_warehouse(self):
        from server.private_market import PrivateMarketSession
        from tio.protocol.asset_count import decode_asset_count
        from tio.protocol.warehouse import decode_warehouse_list
        identity,revision,item=self.listing(price=100)
        sc=self.auction()
        sessions={account:PrivateMarketSession(self.shops,sc,account,clock=lambda:101)
                  for account in ('Alice','Bobby')}
        before={account:self.balance(account) for account in sessions}
        self.shops.buy('Bobby',identity,[(1,7)],revision=revision,request='passive-peer-buy01')
        for account,session in sessions.items():
            with patch('server.private_market.time.monotonic',return_value=10):
                replies=session.refresh()
            self.assertEqual(decode_asset_count(replies[0]).credits,
                             before[account]+(7 if account=='Alice' else -7))
            warehouse=decode_warehouse_list(replies[1])[3]
            if account=='Bobby':
                self.assertEqual([(entry.template_id,entry.count) for entry in warehouse],[(item.template_id,7)])
            self.assertFalse(any(packet[:1]==b'\xae' for packet in replies))

    def test_closed_lot_rejects_other_winner_and_claim_does_not_touch_progression(self):
        sc=self.auction()
        with transaction(self.path) as db:
            before=tuple(db.execute('SELECT account,pet_packet FROM owned_pets ORDER BY account'))
        sc.bid('Alice',1,request='true-winner-only01',now=101);sc.tick(now=114,replenish=False)
        with self.assertRaises(ValueError):sc.claim('Clara',1,request='wrong-winner-sc01',now=115)
        sc.claim('Alice',1,request='winner-native-buy',now=115)
        with transaction(self.path) as db:self.assertEqual(tuple(db.execute('SELECT account,pet_packet FROM owned_pets ORDER BY account')),before)


class CodecTests(unittest.TestCase):
    def test_strict_private_request_native_fields_and_truncations(self):
        from tio.protocol.private_shops import decode
        import struct
        # Correct native payload is count,template,units,f32,enhance,filtered.
        request=b'\xae\x09'+struct.pack('<III f BB',1,3,50,0.5,5,1)
        self.assertEqual(decode(request),(9,(((3,50,50,5),),)))
        for cut in range(len(request)):
            with self.assertRaises(ValueError):decode(request[:cut])
        for price in (float('nan'),float('inf'),-1,0):
            with self.assertRaises(ValueError):decode(b'\xae\x08\0'+struct.pack('<III f',1,1,1,price))

    def test_sc_u16_page_and_bot_fields(self):
        from tio.protocol.sc_auction import decode
        import struct
        self.assertEqual(decode(b'\xbd\x01\2\x34\x12'),(1,(2,0x1234)))
        self.assertEqual(decode(b'\xbd\x14\1'+struct.pack('<IIII',4,0,10,250)),(20,(1,4,0,250,10)))


if __name__=='__main__':unittest.main()
