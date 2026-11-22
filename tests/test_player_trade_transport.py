"""Real independent TCP accounts through the production session dispatcher."""
from contextlib import closing
import sqlite3,time,unittest
import test_multi_account as helpers
from tio.protocol import player_trade as wire
from tio.protocol.item_list import decode_item_list
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase

class TradeTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture=helpers.MultiAccountTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.start();self.path=self.fixture.config.database;self.server=self.fixture.server
        self.a=self.fixture.handoff(self.fixture.begin('alice'));self.fixture.enter(self.a,'Alice')
        self.b=self.fixture.handoff(self.fixture.begin('bob'));self.fixture.enter(self.b,'Bob')

    def buy(self):
        self.a.send(encode_shop_purchase(ShopPurchase(1,0,3,1)))
        self.fixture.ping(self.a)
        # Resolve the existing first-purchase achievement before measuring
        # trade conservation; its delayed 100-credit award is unrelated.
        from tio.achievements import AchievementStore
        AchievementStore(self.path).flush('alice')
        with closing(sqlite3.connect(self.path)) as db:
            raw=db.execute("SELECT inventory_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
        return next(i for i in decode_item_list(raw)[1] if i.template_id==3 and not i.equipped)

    def begin_trade(self):
        self.a.send(wire.invite_request(b'Bob',1));self.assertEqual(self.b.until(b'\x85'),wire.invitation(b'Alice'))
        self.b.send(wire.answer_request(True,1))
        self.assertEqual(self.a.until(b'\x87')[:1],b'\x87');self.assertEqual(self.b.until(b'\x87')[:1],b'\x87')

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT account,credits,gold FROM wallets ORDER BY account').fetchall(),db.execute('SELECT account,pet_id,inventory_packet FROM owned_pets ORDER BY account,pet_id').fetchall()

    def test_two_accounts_trade_real_bag_and_money_and_reconnect(self):
        item=self.buy();before=self.state();self.begin_trade()
        self.a.send(wire.offer_request(item.instance_id,7));self.a.until(b'\x89');self.b.until(b'\x8a')
        self.b.send(wire.offer_request(wire.CREDITS_ID,120));self.b.until(b'\x89');self.a.until(b'\x8a')
        self.a.send(wire.confirm_request())
        self.assertEqual(self.a.until(b'\xf0\x83'), bytes.fromhex('f08300000000000000'))
        self.assertEqual(self.b.until(b'\xf0\x7d'), bytes.fromhex('f07d00000000000000'))
        self.assertEqual(self.state(),before)
        self.b.send(wire.confirm_request());self.a.until(b'\x8c');self.b.until(b'\x8c');after=self.state()
        self.assertEqual(after[0][0][1],before[0][0][1]+120);self.assertEqual(after[0][1][1],before[0][1][1]-120)
        with closing(sqlite3.connect(self.path)) as db:
            raw=db.execute("SELECT inventory_packet FROM owned_pets WHERE account='bob' AND pet_id=1").fetchone()[0]
            self.assertEqual(db.execute('SELECT count(*) FROM player_trade_receipts').fetchone()[0],1)
        self.assertEqual(sum(i.count for i in decode_item_list(raw)[1] if i.template_id==3),7)
        self.b.send(wire.confirm_request());self.fixture.ping(self.b);self.assertEqual(self.state(),after)
        self.b.sock.close()
        deadline=time.monotonic()+5
        while any(s.account=='bob' for s in self.server.multi.active_accounts.values()):
            if time.monotonic()>deadline:self.fail('Disconnected account retained')
            time.sleep(.01)
        again=self.fixture.handoff(self.fixture.begin('bob'));self.fixture.enter(again,'Bob')
        self.assertEqual(self.state(),after)

    def test_peer_disconnect_after_confirmation_cancels_without_writes(self):
        self.begin_trade();self.a.send(wire.offer_request(wire.CREDITS_ID,100))
        self.a.until(b'\x89');self.b.until(b'\x8a');before=self.state()
        self.b.send(wire.confirm_request())
        self.assertEqual(self.b.until(b'\xf0\x83'), bytes.fromhex('f08300000000000000'))
        self.assertEqual(self.a.until(b'\xf0\x7d'), bytes.fromhex('f07d00000000000000'))
        self.b.sock.close()
        self.a.until(b'\x8c');self.assertEqual(self.state(),before)
        self.assertEqual(self.server.multi.player_trade.by_session,{})

    def test_travel_request_cancels_before_confirm_can_move_assets(self):
        self.begin_trade();before=self.state()
        self.a.send(wire.offer_request(wire.CREDITS_ID,100));self.a.until(b'\x89');self.b.until(b'\x8a')
        self.a.send(b'\x1b') # Malformed travel still invalidates a stale barter.
        self.a.until(b'\x8c');self.b.until(b'\x8c')
        self.b.send(wire.confirm_request());self.fixture.ping(self.b)
        self.assertEqual(self.state(),before)
