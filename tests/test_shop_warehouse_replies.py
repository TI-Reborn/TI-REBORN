"""Replies to a committed warehouse purchase in a live hub session."""
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest

from server import warehouse_capacity
from tio.city_catalogs import CityCatalogs
from tio.db_transaction import transaction
from tio.protocol.asset_count import encode_asset_count
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_capacity import OPT_IN
from tio.shop import WAREHOUSE, ShopStore
from tio.warehouse import WarehouseStore
from wallet_fixture import fund_wallet
import test_ranked as fixture

ROOT = Path(__file__).resolve().parents[1]


class WarehousePurchaseReplyTests(unittest.TestCase):
    def setUp(self):
        base = fixture.RankedServerTests()
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.path = base.path
        self.session = base.case.sessions[0]
        WarehouseStore(self.path)
        router = SimpleNamespace(lock=threading.RLock(), team_arena=base.hub,
                                 active_accounts={s.account: s for s in base.case.sessions})
        for session in base.case.sessions:
            session.router = router
            session.authenticated_account = session.account
            session.owned_pet_probe = True
        with transaction(self.path) as database:
            database.execute('CREATE TABLE characters(account TEXT, slot INTEGER)')
            database.execute('INSERT INTO characters VALUES (?,1)', (self.session.account,))
        fund_wallet(self.path, self.session.account, credits=1000, gold=0)
        self.store = ShopStore(self.path, CityCatalogs(ROOT/'config/city_catalogs.json'))

    def buy(self):
        return self.store.purchase(self.session.account, ShopPurchase(WAREHOUSE, 0, 81, 1))

    def test_replies_hold_the_stored_list_and_the_wallet(self):
        result = self.buy()
        replies = warehouse_capacity.purchase_replies(self.session, result)
        stock = next(packet for packet in replies if packet[:1] == b'\x6a')
        self.assertEqual([item.instance_id for item in decode_warehouse_list(stock)[3]],
                         [item.instance_id for item in result.warehouse])
        self.assertEqual(replies[-1], encode_asset_count(result.assets))

    def test_opted_in_client_gets_the_capacity_counter_once(self):
        warehouse_capacity.opt_in(self.session, OPT_IN)
        replies = warehouse_capacity.purchase_replies(self.session, self.buy())
        self.assertTrue(any(packet[:1] == b'\xfa' for packet in replies))
        warehouse_capacity.state(self.session).next_poll = 0
        self.assertEqual(warehouse_capacity.poll(self.session, now=1e9), ())

    def test_session_without_a_capacity_view_still_gets_the_stored_list(self):
        result = self.buy()
        self.session.router.active_accounts.clear()
        self.assertEqual(warehouse_capacity.purchase_replies(self.session, result), result.packets())


if __name__ == '__main__':
    unittest.main()
