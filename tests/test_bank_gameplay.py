from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import hashlib
import hmac
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from server.bank_gameplay import BankGameSession, is_command, redact_command
from tio import bank_economy as bank
from tio.characters import CharacterStore
from tio.city_catalogs import CityCatalogs
from tio.db_transaction import transaction
from tio.onboarding import prepare
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_list import decode_item_list
from tio.protocol.item_marks import metadata
from tio.protocol.shop_purchase import ShopPurchase
from tio.shop import ShopStore
from tio.wallets import WalletStore

ROOT = Path(__file__).resolve().parents[1]
NOW = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
PIN = '135790'
ID = 'test-bank-request-0001'


def lines(reply):
    return tuple(packet[packet.index(b'\0',6)+1:-2].decode('utf-16le') for packet in reply.packets if packet[:1]==b'\x22')


class BankGameplayTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'state.db'; self.now = NOW
        self.characters = CharacterStore(self.path)
        for owner, name in (('alice-login','Alice'),('bobby-login','Bobby'),('clara-login','Clara'),('untouched-login','David')):
            self.characters.create(owner,CharacterCreateRequest(name.encode(),0,(1,0,0,0)));prepare(self.path,owner)
        self.sessions = {a:BankGameSession(self.path,a,clock=lambda:self.now) for a in ('alice-login','bobby-login','clara-login')}
        self.wallets = WalletStore(self.path)
        self.shop = ShopStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'))
        with transaction(self.path) as db:
            self.foreign = tuple(tuple(db.execute('SELECT * FROM '+table+" WHERE account='untouched-login'").fetchall()) for table in ('wallets','characters','owned_pets','warehouse_items'))

    def tearDown(self):
        with transaction(self.path) as db:
            self.assertEqual(tuple(tuple(db.execute('SELECT * FROM '+table+" WHERE account='untouched-login'").fetchall()) for table in ('wallets','characters','owned_pets','warehouse_items')),self.foreign)

    def command(self,text,*,account='alice-login',city_idle=True,busy=()):
        return self.sessions[account].command(text,city_idle=city_idle,busy=busy)

    def balance(self,account='alice-login'):
        value=self.wallets.ensure(account);return value.credits,value.gold

    def buy_item(self):
        offer=next(o for o in self.shop.catalogs.items[0] if o.item_id==301)
        result=self.shop.purchase('alice-login',ShopPurchase(1,0,offer.unknown_u32_01,1))
        # Purchases may append a separate ammunition bundle after the weapon.
        return next(item.instance_id for item in reversed(decode_item_list(result.inventory)[1]) if item.template_id==301)

    def mark(self,*,request=ID):
        item=self.buy_item();reply=self.command(f'!bank mark {item} 2 {PIN} {request}')
        self.assertNotIn('Банк:',str(lines(reply)))
        with transaction(self.path) as db:mid=db.execute('SELECT id FROM bank_item_marks').fetchone()[0]
        return item,mid,reply

    def paid_gold(self,amount):
        # Signed provider adapter fixture only; no privileged wallet write and
        # no real provider IO/payment. Gameplay itself has no checkout route.
        env={'STRIPE_SECRET_KEY':'sk_live_fixture','STRIPE_WEBHOOK_SECRET':'whsec_fixture'}
        config=dict(enabled=True,currency='usd',minor_units_per_gold=100,success_url='https://merchant.example/success',cancel_url='https://merchant.example/cancel')
        def transport(fields,order):
            return dict(id='cs_live_'+order,url='https://checkout.stripe.com/c/'+order,currency='usd',amount_total=100*amount,livemode=True)
        provider=bank.StripeCheckout(config,environ=env,transport=transport)
        store=bank.BankStore(self.path,provider=provider,clock=lambda:self.now)
        order=store.create_order('alice-login',amount,'signed-provider-order')
        session=dict(id=order['session_id'],object='checkout.session',mode='payment',client_reference_id=order['id'],payment_status='paid',amount_total=100*amount,currency='usd',livemode=True,metadata=dict(tio_order=order['id']))
        body=bank.canonical(dict(id='evt_signed_fixture',type='checkout.session.completed',livemode=True,data=dict(object=session))).encode()
        signature=hmac.new(env['STRIPE_WEBHOOK_SECRET'].encode(),str(self.now).encode()+b'.'+body,hashlib.sha256).hexdigest()
        store.callback(body,{'Stripe-Signature':f't={self.now},v1={signature}'})

    def test_default_disabled_constructor_and_unknown_owner_do_not_seed(self):
        with patch('tio.bank_economy.urlopen',side_effect=AssertionError('unexpected provider IO')):
            self.assertFalse(self.sessions['alice-login'].store.status()['configured'])
            for text in ('!bank','!bank help','!bank quotes','!bank history','!bank marks'):
                self.assertTrue(self.command(text).packets)
            with self.assertRaises(bank.BankRejected):BankGameSession(self.path,'missing-login')
        with transaction(self.path) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM wallets WHERE account='missing-login'").fetchone())
            self.assertEqual(db.execute('SELECT count(*) FROM bank_payment_orders').fetchone()[0],0)
        self.assertEqual(self.balance(),(3000,0))

    def test_stock_native_assets_and_persistent_replay_after_restart(self):
        self.command('!bank quotes');text=f'!bank stocks buy 3 100 {ID}'
        reply=self.command(text);self.assertEqual(reply.changed_accounts,('alice-login',))
        assets=decode_asset_count(next(p for p in reply.packets if p[:2]==b'\xc8\x39'))
        self.assertEqual((assets.credits,assets.spectra_stock),(2700,3))
        self.sessions['alice-login']=BankGameSession(self.path,'alice-login',clock=lambda:self.now)
        repeated=self.command(text);self.assertEqual(repeated.changed_accounts,())
        self.assertEqual(self.balance(),(2700,0))
        error=self.command(f'!bank stocks buy 4 100 {ID}')
        self.assertIn('Повтор операции отличается',str(lines(error)));self.assertEqual(self.balance(),(2700,0))
        self.command('!bank stocks sell 3 100 stock-sale-request1');self.assertEqual(self.balance(),(3000,0))

    def test_conversion_stays_closed_and_monthly_bonds_use_credits_once(self):
        reply=self.command('!bank convert 2 conversion-request1')
        self.assertIn('обмен закрыт',str(lines(reply)));self.assertEqual(self.balance(),(3000,0))
        price=bank.policy()['bonds']['credits_each']
        buy=self.command(f'!bank bonds buy 2 {price} bond-buy-request01')
        assets=decode_asset_count(next(p for p in buy.packets if p[:2]==b'\xc8\x39'))
        self.assertEqual((assets.credits,assets.gold,assets.spectra_bonds),(3000-2*price,0,2))
        self.command(f'!bank bonds buy 2 {price} bond-buy-request01');self.assertEqual(self.balance(),(3000-2*price,0))
        self.assertIn('Период',str(lines(self.command('!bank bonds sell 2 150 bond-sell-request1'))))
        self.now=int(datetime(2026,11,25,tzinfo=timezone.utc).timestamp())
        self.command('!bank bonds sell 2 155 bond-sell-request2');self.assertEqual(self.balance(),(3000-2*price+310,0))

    def test_city_and_busy_fences_include_replay_without_item_refresh(self):
        self.command(f'!bank stocks buy 1 100 {ID}')
        for idle,busy in ((False,()),(True,('alice-login',))):
            reply=self.command(f'!bank stocks buy 1 100 {ID}',city_idle=idle,busy=busy)
            self.assertEqual(reply.changed_accounts,());self.assertEqual([p[0] for p in reply.packets],[0x22])
        readonly=self.command('!bank quotes',city_idle=False,busy=('alice-login',))
        self.assertFalse(any(p[0] in (0x30,0x6a,0x66) for p in readonly.packets))
        self.assertEqual(self.balance(),(2900,0))

    def test_mark_canonical_packets_and_no_pin_request_or_owner_key_echo(self):
        stream=StringIO()
        with redirect_stdout(stream):item,mid,reply=self.mark()
        self.assertEqual(stream.getvalue(),'');self.assertEqual(self.balance(),(2650,0))
        self.assertEqual(reply.changed_accounts,('alice-login',))
        public=' '.join(lines(reply));self.assertNotIn(PIN,public);self.assertNotIn(ID,public);self.assertNotIn('alice-login',public)
        for packet in reply.packets:
            if packet[0]==0x30:
                _,records,_=decode_item_list(packet);self.assertEqual(metadata(packet),{})
                if any(i.instance_id==item for i in records):self.assertTrue(next(i for i in records if i.instance_id==item).unknown_bytes_02[2])
        self.assertTrue(any(p[0]==0x66 for p in reply.packets));self.assertTrue(any(p[0]==0x6a for p in reply.packets))
        repeated=self.command(f'!bank mark {item} 2 {PIN} {ID}');self.assertEqual(repeated.changed_accounts,())
        self.assertEqual(self.balance(),(2650,0))
        with transaction(self.path) as db:
            self.assertNotIn(PIN,repr(db.execute('SELECT request,receipt FROM bank_economy_receipts').fetchall()))

    def test_lend_exact_public_name_busy_target_and_reclaim_real_physical_item(self):
        item,mid,_=self.mark()
        error=self.command(f'!bank lend {mid} bobby-login lend-request-00001')
        self.assertIn('публичное имя',str(lines(error)))
        busy=self.command(f'!bank lend {mid} Bobby lend-request-00001',busy=('bobby-login',))
        self.assertIn('вне боя',str(lines(busy)))
        lend=self.command(f'!bank lend {mid} Bobby lend-request-00001')
        self.assertEqual(set(lend.changed_accounts),{'alice-login','bobby-login'})
        self.assertNotIn('bobby-login',' '.join(lines(lend)))
        holder=self.sessions['bobby-login'].snapshot()
        self.assertEqual(metadata(next(p for p in holder if p[0]==0x6a)),{})
        denied=self.command(f'!bank reclaim {mid} {PIN} reclaim-request01 remove',busy=('bobby-login',))
        self.assertIn('выхода обоих',str(lines(denied)))
        returned=self.command(f'!bank reclaim {mid} {PIN} reclaim-request01 remove')
        self.assertEqual(set(returned.changed_accounts),{'alice-login','bobby-login'})
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT state,holder FROM bank_item_marks WHERE id=?',(mid,)).fetchone(),('removed','alice-login'))
            self.assertEqual(db.execute("SELECT count(*) FROM warehouse_items WHERE account='bobby-login'").fetchone()[0],0)
        replay=self.command(f'!bank reclaim {mid} {PIN} reclaim-request01 remove');self.assertEqual(replay.changed_accounts,())

    def test_secondary_character_name_resolves_saved_owner_only(self):
        self.characters.create('bobby-login',CharacterCreateRequest(b'BobbyOther',0,(1,0,0,0)))
        other=self.characters.owner('bobby-login',2);prepare(self.path,other)
        _,mid,_=self.mark();reply=self.command(f'!bank lend {mid} BobbyOther second-lend-request')
        self.assertEqual(set(reply.changed_accounts),{'alice-login',other})
        with transaction(self.path) as db:self.assertEqual(db.execute('SELECT holder FROM bank_item_marks WHERE id=?',(mid,)).fetchone()[0],other)

    def test_wrong_pin_commits_budget_inside_outer_gameplay_transaction(self):
        _,mid,_=self.mark()
        for i in range(5):
            with transaction(self.path):reply=self.command(f'!bank reclaim {mid} 999999 wrong-pin-request-{i}')
            self.assertEqual(reply.changed_accounts,());self.assertEqual([p[0] for p in reply.packets],[0x22])
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT failures,locked_until FROM bank_item_marks WHERE id=?',(mid,)).fetchone(),(0,NOW+300))
        restarted=BankGameSession(self.path,'alice-login',clock=lambda:self.now)
        locked=restarted.command(f'!bank reclaim {mid} {PIN} reclaim-after-lock',city_idle=True)
        self.assertIn('заблокирован',str(lines(locked)))
        self.now+=301
        good=restarted.command(f'!bank reclaim {mid} {PIN} reclaim-after-lock',city_idle=True)
        self.assertEqual(good.changed_accounts,('alice-login',))

    def test_malformed_bounded_native_chat_never_mutates_or_echoes(self):
        malformed=('!bank stocks buy +1 100 valid-request-id01','!bank stocks buy 0 100 valid-request-id01',
                   '!bank convert 1 short','!bank mark 1 366 135790 valid-request-id01',
                   '!bank reclaim 1 135790 valid-request-id01 unknown','!bank '+('\U0001f680'*100))
        for text in malformed:
            reply=self.command(text);self.assertEqual(reply.changed_accounts,());self.assertNotIn(PIN,' '.join(lines(reply)))
        packet=b'\x21\0'+'!bank quotes'.encode('utf-16le')+b'\0\0'
        reply=self.sessions['alice-login'].handle(packet,city_idle=True)
        self.assertTrue(reply.packets);self.assertTrue(all(p[5]==4 for p in reply.packets if p[0]==0x22))
        too_many_units=b'\x21\0'+malformed[-1].encode('utf-16le')+b'\0\0'
        self.assertIn('200',str(lines(self.sessions['alice-login'].handle(too_many_units,city_idle=True))))
        for cut in (0,1,len(packet)-1):
            with self.assertRaises(ValueError):self.sessions['alice-login'].handle(packet[:cut],city_idle=True)
        self.assertIsNone(self.command('hello'));self.assertEqual(self.balance(),(3000,0))
        self.assertTrue(is_command('!bank mark 1 1 135790 '+ID));self.assertEqual(redact_command('!bank reclaim 1 135790 '+ID),'!bank [private]')

    def test_payment_and_canonical_item_changes_rollback_on_failed_receipt(self):
        item=self.buy_item();before=self.sessions['alice-login'].snapshot()
        with transaction(self.path) as db:
            db.execute("CREATE TRIGGER deny_bank_receipt BEFORE INSERT ON bank_economy_receipts BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.command(f'!bank mark {item} 2 {PIN} {ID}')
        self.assertEqual(self.sessions['alice-login'].snapshot(),before)
        with transaction(self.path) as db:self.assertEqual(db.execute('SELECT count(*) FROM bank_item_marks').fetchone()[0],0)

    def test_ordinary_rejection_rolls_back_partial_move_inside_outer_journal(self):
        item,mid,_=self.mark();before=self.sessions['alice-login'].snapshot()
        with transaction(self.path) as db:
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',('bobby-login',0xffff0000))
        with transaction(self.path) as db:
            db.execute('CREATE TABLE outer_test_marker (id INTEGER)');db.execute('INSERT INTO outer_test_marker VALUES (1)')
            reply=self.command(f'!bank lend {mid} Bobby exhausted-lend-id01')
            self.assertIn('Исчерпаны',str(lines(reply)));self.assertEqual(reply.changed_accounts,())
        self.assertEqual(self.sessions['alice-login'].snapshot(),before)
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT holder,current_instance FROM bank_item_marks WHERE id=?',(mid,)).fetchone(),('alice-login',item))
            self.assertEqual(db.execute('SELECT * FROM outer_test_marker').fetchall(),[(1,)])
            self.assertEqual(db.execute("SELECT count(*) FROM warehouse_items WHERE account='bobby-login'").fetchone()[0],0)

    def test_concurrent_real_accounts_and_request_replay_charge_once(self):
        def buy(account):return self.command(f'!bank stocks buy 2 100 {ID}',account=account)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(buy,('alice-login','alice-login','bobby-login','clara-login')))
        self.assertEqual(sum(bool(r.changed_accounts) for r in results),3)
        self.assertEqual([self.balance(a) for a in ('alice-login','bobby-login','clara-login')],[(2800,0)]*3)
        self.now+=86400*2;self.command('!bank history stocks')
        stale=self.command('!bank stocks buy 1 100 stale-quote-request')
        self.assertIn('Котировка изменилась',str(lines(stale)));self.assertEqual(self.balance(),(2800,0))


if __name__=='__main__':unittest.main()
