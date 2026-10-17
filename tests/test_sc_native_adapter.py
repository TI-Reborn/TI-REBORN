from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.characters import CharacterStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.onboarding import prepare
from tio.private_shops import PrivateShopStore
from tio.sc_auction import SCAuctionStore,policy
from tio.wallets import WalletStore
from tio.db_transaction import transaction
from tio.protocol.sc_auction import decode as request
from tio.protocol import sc_auction_view as view
from server.private_market import PrivateMarketSession

BASE=1791446400


def bid(lot):return lot_request(6,lot)
def lot_request(op,lot):return b'\xbd'+bytes((op,))+struct.pack('<I',lot)
def open_bot(lot):return b'\xbd\x14\0'+struct.pack('<I',lot)
def setup(lot,low,high,count):return b'\xbd\x14\1'+struct.pack('<IIII',lot,low,count,high)


class NativeSCAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=Path(temporary.name)/'state.db';characters=CharacterStore(self.path)
        for account,name in (('alice-login','Alice'),('bobby-login','Bobby'),('clara-login','Clara'),('untouched-login','David')):
            characters.create(account,CharacterCreateRequest(name.encode(),0,(1,0,0,0)));prepare(self.path,account)
        rules=policy();rules['offers']=[dict(rules['offers'][0],duration=10,extension=3)]
        self.sc=SCAuctionStore(self.path,rules=rules);self.shops=PrivateShopStore(self.path)
        self.now=BASE;self.sc.tick(now=self.now)
        self.sessions={a:PrivateMarketSession(self.shops,self.sc,a,clock=lambda:self.now) for a in ('alice-login','bobby-login','clara-login')}
        self.wallets=WalletStore(self.path)
        with transaction(self.path) as db:
            self.foreign=(db.execute("SELECT * FROM wallets WHERE account='untouched-login'").fetchall(),
                db.execute("SELECT * FROM characters WHERE account='untouched-login'").fetchall(),
                db.execute("SELECT * FROM owned_pets WHERE account='untouched-login'").fetchall())
            self.progression=db.execute('SELECT account,pet_id,pet_packet FROM owned_pets ORDER BY account,pet_id').fetchall()

    def tearDown(self):
        with transaction(self.path) as db:
            self.assertEqual((db.execute("SELECT * FROM wallets WHERE account='untouched-login'").fetchall(),
                db.execute("SELECT * FROM characters WHERE account='untouched-login'").fetchall(),
                db.execute("SELECT * FROM owned_pets WHERE account='untouched-login'").fetchall()),self.foreign)
            self.assertEqual(db.execute('SELECT account,pet_id,pet_packet FROM owned_pets ORDER BY account,pet_id').fetchall(),self.progression)

    def credits(self,account='alice-login'):return self.wallets.ensure(account).credits
    def open(self,account='alice-login'):
        replies=self.sessions[account].handle_sc(b'\xbd\1\0\0\0');self.assertTrue(all(isinstance(p,bytes) for p in replies))
        return view.decode(replies[0])[1]

    def test_native_bid_paid_once_full_models_and_public_names(self):
        self.open();self.now+=1;s=self.sessions['alice-login']
        replies=s.handle_sc(bid(1));self.assertEqual(self.credits(),2995)
        catalogue=view.decode(next(p for p in replies if p[:3]==b'\xf8\1\1'))[1]
        self.assertEqual(catalogue[0][1][1],'Alice');self.assertNotIn('alice-login',str(catalogue))
        s.handle_sc(bid(1));self.assertEqual(self.credits(),2995);self.assertEqual(self.sc.get(1)['bids'],1)
        self.open('bobby-login');self.sessions['bobby-login'].handle_sc(bid(1))
        # Same unrenewed native quote remains the same operation after a rival bid.
        s.handle_sc(bid(1));self.assertEqual(self.credits(),2995)
        self.open();s.handle_sc(bid(1));self.assertEqual(self.credits(),2990)

    def test_native_bot_gui_field_order_delete_and_replay(self):
        s=self.sessions['alice-login'];self.open();s.handle_sc(open_bot(1))
        packet=setup(1,100,250,7);self.assertEqual(request(packet),(20,(1,1,100,250,7)))
        s.handle_sc(packet);self.assertEqual(self.sc.bot('alice-login',1),dict(from_price=100,to_price=250,remaining=7,held=35))
        s.handle_sc(packet);self.assertEqual(self.credits(),2965)
        delete=b'\xbd\x14\2'+struct.pack('<I',1)
        s.handle_sc(delete);s.handle_sc(delete);self.assertEqual(self.credits(),3000)
        self.assertEqual(self.sc.bot('alice-login',1)['held'],0)
        # Inline catalogue mode0 opens the original bot form without a payment.
        s.clear_sc();self.open();s.handle_sc(open_bot(1))
        self.assertEqual(self.credits(),3000)

    def test_claim_actual_expiry_defer_replay_and_once_only_mail(self):
        s=self.sessions['alice-login'];self.open();self.now+=1;s.handle_sc(bid(1))
        self.now=BASE+14;self.sc.tick(now=self.now,replenish=False)
        expiry=self.sc.get(1)['expires_at'];self.assertEqual(expiry,self.now+604800)
        packet=s.handle_sc(lot_request(7,1))[0];op,fields=view.decode(packet)
        self.assertEqual(op,4);self.assertEqual(fields,(1,view.datetime_days(expiry),101,0,1))
        s.handle_sc(lot_request(9,1)+b'\0');self.assertEqual(self.credits(),2995)
        with self.assertRaises(ValueError):s.handle_sc(lot_request(9,1)+b'\1')
        s.handle_sc(lot_request(7,1))
        s.handle_sc(lot_request(9,1)+b'\1');s.handle_sc(lot_request(9,1)+b'\1')
        self.assertEqual(self.credits(),2894)
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mail_messages').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM mail_items').fetchone()[0],1)
        with self.assertRaises(ValueError):self.sessions['clara-login'].handle_sc(lot_request(7,1))

    def test_expiry_at_deadline_no_final_price_charge_or_spent_bid_refund(self):
        self.sc.set_bot('alice-login',1,0,0,3,request='unused-native-bot',now=BASE+1)
        self.sc.bid('alice-login',1,request='expire-native-bid',now=BASE+2)
        self.sc.tick(now=BASE+14,replenish=False);self.assertEqual(self.credits(),2995)
        expiry=self.sc.get(1)['expires_at'];self.sc.tick(now=expiry,replenish=False)
        self.sc.tick(now=expiry+1,replenish=False);self.assertEqual(self.sc.get(1)['state'],'expired')
        with self.assertRaises(ValueError):self.sc.claim('alice-login',1,request='too-late-nativeclaim',now=expiry)
        self.assertEqual(self.credits(),2995)
        with transaction(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM sc_auction_history WHERE action='expired'").fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM mail_messages').fetchone()[0],0)

    def test_old_won_lot_expiry_migration_uses_durable_closed_event(self):
        self.sc.bid('alice-login',1,request='migration-old-bid',now=BASE+1)
        self.sc.tick(now=BASE+100,replenish=False)
        with transaction(self.path) as db:db.execute('ALTER TABLE sc_auction_lots DROP COLUMN expires_at')
        restored=SCAuctionStore(self.path,rules=self.sc.rules)
        self.assertEqual(restored.get(1)['expires_at'],BASE+100+604800)
        restarted=SCAuctionStore(self.path,rules=self.sc.rules)
        self.assertEqual(restarted.get(1),restored.get(1));self.assertEqual(self.credits(),2995)

    def test_expiry_event_failure_rolls_back_without_lost_hold_or_prize(self):
        self.sc.bid('alice-login',1,request='expiry-event-failbid',now=BASE+1)
        self.sc.tick(now=BASE+14,replenish=False);expiry=self.sc.get(1)['expires_at']
        with transaction(self.path) as db:
            db.execute("CREATE TRIGGER deny_expire BEFORE INSERT ON sc_auction_history WHEN NEW.action='expired' BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.sc.tick(now=expiry,replenish=False)
        self.assertEqual(self.sc.get(1)['state'],'won');self.assertEqual(self.credits(),2995)

    def test_catalogue_live_cap_never_omits_own_unclaimed_win(self):
        self.sc.rules['maximum_rows']=2;self.sc.rules['maximum_live_lots']=2
        self.sc.bid('alice-login',1,request='bounded-live-first',now=BASE+1)
        self.sc.tick(now=BASE+14)
        self.sc.bid('clara-login',2,request='bounded-live-second',now=BASE+15)
        self.sc.tick(now=BASE+28)
        rows=self.sc.catalogue('clara-login');self.assertEqual([r['id'] for r in rows],[2,1])
        self.assertEqual(len(self.sc.list()),0)
        self.sc.claim('alice-login',1,request='bounded-live-claim',now=BASE+29);self.sc.tick(now=BASE+29)
        rows=self.sc.catalogue('clara-login');self.assertEqual([r['id'] for r in rows],[2,3])

    def test_history_native_pagination_no_private_owner_keys(self):
        self.sc.rules['history_page_rows']=1;self.open();self.now+=1
        self.sessions['alice-login'].handle_sc(bid(1))
        packet=self.sessions['alice-login'].handle_sc(lot_request(3,1)+b'\2\0')[0]
        op,fields=view.decode(packet);self.assertEqual(op,2);self.assertEqual(fields[1:3],(2,2))
        self.assertEqual(fields[4][0][1],'Alice')
        with self.assertRaises(ValueError):self.sessions['alice-login'].handle_sc(lot_request(3,1)+b'\0\0')

    def test_clear_and_combat_fences_do_not_create_native_quotes_or_holds(self):
        s=self.sessions['alice-login'];self.open();s.handle_sc(open_bot(1))
        for packet in (bid(1),setup(1,0,0,2),lot_request(9,1)+b'\1'):
            with self.assertRaises(ValueError):s.handle_sc(packet,allow_mutation=False)
        self.assertEqual(s.clear_sc(),(b'\xf8\1\0',));self.assertEqual(s.sc_quotes,{})
        self.assertEqual(s.sc_claims,{});self.assertEqual(s.sc_bots,{})
        with self.assertRaises(ValueError):s.handle_sc(bid(1))
        self.assertEqual(self.credits(),3000)

    def test_simultaneous_claim_or_expire_has_one_authoritative_outcome(self):
        self.sc.bid('alice-login',1,request='race-expiry-bid001',now=BASE+1)
        self.sc.tick(now=BASE+14,replenish=False);expiry=self.sc.get(1)['expires_at']
        def claim():
            try:self.sc.claim('alice-login',1,request='race-expiry-claim1',now=expiry-1);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(claim);b=pool.submit(self.sc.tick,now=expiry,replenish=False);a.result();b.result()
        state=self.sc.get(1)['state'];self.assertIn(state,('expired','delivered'))
        self.assertEqual(self.credits(),2894 if state=='delivered' else 2995)
        with transaction(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM mail_messages').fetchone()[0],int(state=='delivered'))

    def test_native_manual_lot_has_bid_but_no_automatic_budget_form(self):
        self.sc.rules['offers'].append(dict(self.sc.rules['offers'][0],key='manual',automatic=False))
        self.sc.tick(now=self.now);s=self.sessions['alice-login'];self.open()
        s.handle_sc(bid(2));self.assertEqual(self.credits(),2995)
        with self.assertRaises(ValueError):s.handle_sc(open_bot(2))
        self.assertNotIn(2,s.sc_bots)
        with self.assertRaises(ValueError):s.handle_sc(lot_request(7,2))

    def test_native_integer_limits_reject_without_charges_or_lost_bot_budget(self):
        s=self.sessions['alice-login'];self.open();s.handle_sc(open_bot(1))
        for packet in (setup(1,0,0x80000000,3),setup(1,0x80000000,0,3)):
            with self.assertRaises(ValueError):s.handle_sc(packet)
        self.assertEqual(self.credits(),3000);self.assertEqual(self.sc.bot('alice-login',1)['held'],0)
        with transaction(self.path) as db:db.execute('UPDATE sc_auction_lots SET price=? WHERE id=1',(0x7fffffff,))
        with self.assertRaises(ValueError):s.handle_sc(bid(1))
        self.assertEqual(self.credits(),3000);self.assertEqual(self.sc.get(1)['bids'],0)
        with transaction(self.path) as db:
            db.execute('UPDATE sc_auction_lots SET price=100,ends=? WHERE id=1',(BASE+2147483,))
        with self.assertRaises(ValueError):s.handle_sc(bid(1))
        self.assertEqual(self.credits(),3000);self.assertEqual(self.sc.get(1)['bids'],0)


class OriginalSCRequestTests(unittest.TestCase):
    def test_verified_bid_and_delete_modes_only(self):
        self.assertEqual(request(bid(42)),(6,(42,)))
        for mode in (0,2):self.assertEqual(request(b'\xbd\x14'+bytes((mode,))+struct.pack('<I',42)),(20,(mode,42,0,0,0)))
        for packet in (b'\xbd\5\0'+struct.pack('<I',42)+b'\0',bid(42)+b'\0',b'\xbd\5\3'+struct.pack('<I',42)+b'\0'):
            with self.assertRaises(ValueError):request(packet)


if __name__=='__main__':unittest.main()
