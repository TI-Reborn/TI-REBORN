from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import hashlib,hmac,json,sqlite3,tempfile,unittest

from tio import bank_economy as b
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.asset_count import AssetCount
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.item_marks import metadata
from tio.protocol.warehouse import encode_private_warehouse_snapshot,decode_warehouse_list
from tio.warehouse import WarehouseStore
from tio.market_inventory import tradable

ROOT=Path(__file__).resolve().parents[1]


class BankFixture(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'players.sqlite3'
        trial=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text());raw=bytes.fromhex(trial['packet_hex'])
        sample=decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))[1][0]
        self.item=replace(sample,instance_id=17,template_id=301,unknown_u32_01=1,unknown_u8_01=0,location_raw=0,unknown_words=(300,300,300),unknown_bytes_02=bytes(4),optional_u32=None,unknown_bytes_03=bytes(3))
        self.pets=OwnedPetStore(self.path);self.warehouse=WarehouseStore(self.path)
        for a in ('alice','bob','carol'):self.pets.ensure(a,raw,encode_item_list(1,(self.item,) if a=='alice' else (replace(self.item,template_id=302),) if a=='bob' else ()),human=True)
        with transaction(self.path) as db:
            b.schema(db);db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB)')
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER CHECK(credits BETWEEN 0 AND 4294967295),gold INTEGER CHECK(gold BETWEEN 0 AND 4294967295))')
            for a in ('alice','bob','carol'):
                db.execute('INSERT INTO characters VALUES (?,1,?)',(a,a.title().encode()));db.execute('INSERT INTO wallets VALUES (?,10000,100)',(a,))
        self.now=int(datetime(2026,10,8,tzinfo=timezone.utc).timestamp())

    def call(self,fn,*args,**kwargs):
        with transaction(self.path) as db:return fn(db,*args,**kwargs)

    def read(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()


class EconomyTests(BankFixture):
    def test_gold_conversion_exact_atomic_owned_and_retry(self):
        first=self.call(b.convert_gold,'alice',7,'conversion1')
        self.assertEqual(first,dict(gold_spent=7,credits_received=700))
        self.assertEqual(first,self.call(b.convert_gold,'alice',7,'conversion1'))
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='alice'")[0],(10700,93))
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='bob'")[0],(10000,100))
        for amount in (0,-1,True,101):
            with self.assertRaises(b.BankRejected):self.call(b.convert_gold,'alice',amount,'bad')
        with self.assertRaises(b.BankRejected):self.call(b.convert_gold,'missing',1,'bad')
        with self.assertRaises(b.BankRejected):self.call(b.convert_gold,'alice',8,'conversion1')

    def test_concurrent_conversion_and_overflow_or_audit_failure_roll_back(self):
        with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda _:self.call(b.convert_gold,'alice',10,'once'),range(4)))
        self.assertTrue(all(r==rows[0] for r in rows));self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='alice'")[0][0],90)
        with transaction(self.path) as db:
            db.execute("UPDATE wallets SET credits=? WHERE account='alice'",(b.MAX,))
            db.execute("CREATE TRIGGER faileconomy BEFORE INSERT ON bank_economy_receipts WHEN NEW.account='bob' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(b.BankRejected):self.call(b.convert_gold,'alice',1,'overflow')
        with self.assertRaises(sqlite3.IntegrityError):self.call(b.convert_gold,'bob',1,'storagefailure')
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='bob'")[0],(10000,100))

    def test_shared_stock_quote_no_instant_arbitrage_and_price_replay(self):
        quote=self.call(b.stock_quote,now=self.now)
        self.assertEqual(quote,dict(price=100,currency='credits'))
        buy=self.call(b.securities_trade,'alice','stocks','buy',3,'buy1',quote=100,now=self.now)
        self.assertEqual(buy['balance'],3)
        self.call(b.securities_trade,'alice','stocks','sell',3,'sell1',quote=100,now=self.now)
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='alice'")[0],(10000,100))
        next_quote=self.call(b.stock_quote,now=self.now+86400*2);self.assertEqual(next_quote['price'],102)
        with self.assertRaises(b.BankRejected):self.call(b.securities_trade,'bob','stocks','buy',1,'stale',quote=100,now=self.now+86400*2)
        self.call(b.securities_trade,'bob','stocks','buy',1,'current',quote=102,now=self.now+86400*2)
        self.assertEqual(self.call(b.securities_trade,'alice','stocks','buy',3,'buy1',quote=100,now=self.now+86400*2),buy)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(b.project_assets(db,'bob',AssetCount(1,2)).spectra_stock,1)
            self.assertEqual(b.project_assets(db,'carol',AssetCount(1,2)).spectra_stock,0)
        history=self.call(b.quote_history,'stocks',now=self.now+86400*2)
        self.assertEqual([r['price'] for r in history],[100,102]) # only accepted quotes, no fake missing daily candles.
        self.assertEqual(self.call(b.stock_quote,now=self.now)['price'],102)

    def test_bonds_sale_window_redemption_day_carryover_and_native_balances(self):
        oct8=self.now;oct21=int(datetime(2026,10,21,tzinfo=timezone.utc).timestamp());nov25=int(datetime(2026,11,25,tzinfo=timezone.utc).timestamp())
        self.call(b.securities_trade,'alice','bonds','buy',3,'bondbuy',quote=1,now=oct8)
        with self.assertRaises(b.BankRejected):self.call(b.securities_trade,'bob','bonds','buy',1,'closed',quote=1,now=oct21)
        with self.assertRaises(b.BankRejected):self.call(b.securities_trade,'alice','bonds','sell',3,'early',quote=150,now=oct21)
        quote=self.call(b.bond_quote,now=nov25)
        self.assertTrue(quote['redemption_open']);self.assertFalse(quote['sale_open']);self.assertEqual(quote['redemption_credits'],155)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(b.project_assets(db,'alice',AssetCount(1,2)).spectra_bonds,3)
        redeemed=self.call(b.securities_trade,'alice','bonds','sell',3,'redeem',quote=155,now=nov25)
        self.assertEqual(redeemed['amount'],465)
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='alice'")[0],(10465,97))
        self.assertEqual(self.call(b.securities_trade,'alice','bonds','sell',3,'redeem',quote=155,now=nov25+86400),redeemed)
        with self.assertRaises(b.BankRejected):self.call(b.securities_trade,'alice','bonds','sell',1,'double',quote=155,now=nov25)

    def test_financial_failure_leaves_quote_holdings_and_wallet_unchanged(self):
        with transaction(self.path) as db:db.execute("CREATE TRIGGER failshares BEFORE INSERT ON bank_economy_receipts BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.call(b.securities_trade,'alice','stocks','buy',1,'fail',quote=100,now=self.now)
        self.assertEqual(self.read('SELECT * FROM bank_securities'),[])
        self.assertEqual(self.read('SELECT * FROM bank_quotes'),[])
        self.assertEqual(self.read("SELECT credits FROM wallets WHERE account='alice'")[0][0],10000)

    def mark(self,*,days=2,pin='123456',key='mark1'):
        return self.call(b.mark_item,'alice',17,days,pin,key,now=self.now)

    def test_mark_fee_actual_bit_hash_and_native_projection(self):
        mark=self.mark();self.assertEqual(mark['charged'],200);self.assertEqual(mark,self.mark())
        self.assertEqual(self.read("SELECT credits FROM wallets WHERE account='alice'")[0][0],9800)
        item=decode_item_list(self.pets.inventory('alice',1))[1][0]
        self.assertEqual(item.unknown_bytes_02,bytes((0,0,1,0)));self.assertFalse(tradable(item))
        stored=self.read('SELECT salt,pin_hash FROM bank_item_marks')[0]
        self.assertEqual(len(stored[0]),16);self.assertNotIn(b'123456',stored)
        with closing(sqlite3.connect(self.path)) as db:
            projected=b.project_marks(db,'alice',self.pets.inventory('alice',1),now=self.now+1)
        self.assertEqual(metadata(projected),{17:('Alice',2*86400-1)})
        self.assertEqual(decode_item_list(self.pets.inventory('alice',1))[1][0].optional_u32,None) # projection never contaminates stored codec.
        with self.assertRaises(b.BankRejected):self.call(b.mark_item,'bob',999,1,'1234','foreign',now=self.now)

    def test_mark_lend_and_pin_reclaim_preserve_wear_unique_ids_and_other_item(self):
        mark=self.mark();mid=mark['mark_id'];loan=self.call(b.lend_marked,'alice',mid,'bob','loan',now=self.now)
        self.assertEqual(self.pets.inventory('alice',1),encode_item_list(1,()))
        self.assertEqual(loan['instance'],18)
        with closing(sqlite3.connect(self.path)) as db:
            packet=encode_private_warehouse_snapshot(self.warehouse.items('bob'))[0]
            projected=b.project_marks(db,'bob',packet,now=self.now+1)
            self.assertEqual(metadata(projected),{18:('Alice',2*86400-1)})
            self.assertEqual(metadata(b.project_marks(db,'carol',packet,now=self.now+1)),{})
            self.assertIsNone(decode_warehouse_list(packet)[3][0].mark_time_left)
        with transaction(self.path) as db:
            raw=db.execute('SELECT item_packet FROM warehouse_items WHERE account=? AND instance_id=?',('bob',18)).fetchone()[0]
            worn=replace(decode_item_list(raw)[1][0],unknown_words=(251,300,300))
            db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=?',(encode_item_list(0,(worn,)),'bob',18))
        with self.assertRaises(b.BankRejected):self.call(b.reclaim_marked,'bob',mid,'123456','steal',now=self.now)
        result=self.call(b.reclaim_marked,'alice',mid,'123456','return',now=self.now)
        self.assertEqual(result['instance'],18)
        returned=self.warehouse.items('alice')[0];self.assertEqual(returned.unknown_words,(251,300,300));self.assertEqual(returned.template_id,301)
        self.assertEqual(decode_item_list(self.pets.inventory('bob',1))[1][0].template_id,302)
        self.assertEqual(self.warehouse.items('bob'),())
        self.assertEqual(result,self.call(b.reclaim_marked,'alice',mid,'9999','return',now=self.now))
        unmarked=self.call(b.reclaim_marked,'alice',mid,'123456','unmark',remove=True,now=self.now)
        self.assertTrue(unmarked['removed']);self.assertEqual(self.warehouse.items('alice')[0].unknown_bytes_02[2],0)
        self.assertTrue(tradable(self.warehouse.items('alice')[0]))

    def test_pin_rejections_commit_rate_limit_without_mutating_item(self):
        mid=self.mark()['mark_id']
        for i in range(5):self.assertIn('rejected',self.call(b.reclaim_marked,'alice',mid,'0000','bad'+str(i),now=self.now))
        locked=self.call(b.reclaim_marked,'alice',mid,'123456','locked',remove=True,now=self.now)
        self.assertEqual(locked['retry_after'],300)
        done=self.call(b.reclaim_marked,'alice',mid,'123456','valid',remove=True,now=self.now+301)
        self.assertTrue(done['removed']);self.assertEqual(self.read('SELECT failures,locked_until FROM bank_item_marks')[0],(0,0))

    def test_marks_busy_expiry_defers_then_returns_and_destroyed_never_respawns(self):
        mid=self.mark(days=1)['mark_id']
        with self.assertRaises(b.BankRejected):self.call(b.lend_marked,'alice',mid,'bob','busy',now=self.now,busy=('bob',))
        self.call(b.lend_marked,'alice',mid,'bob','loan',now=self.now)
        self.assertEqual(self.call(b.expire_marks,now=self.now+86400,busy=('bob',)),())
        changed=self.call(b.expire_marks,now=self.now+86400)
        self.assertEqual(changed,('alice','bob'));self.assertEqual(self.warehouse.items('alice')[0].unknown_bytes_02[2],0)
        self.assertEqual(self.call(b.expire_marks,now=self.now+90000),())
        instance=self.warehouse.items('alice')[0].instance_id
        second=self.call(b.mark_item,'alice',instance,1,'1234','second',now=self.now+90000)['mark_id']
        with transaction(self.path) as db:db.execute("DELETE FROM warehouse_items WHERE account='alice'")
        self.call(b.expire_marks,now=self.now+90000+86400)
        self.assertEqual(self.read('SELECT state FROM bank_item_marks WHERE id=?',(second,))[0][0],'destroyed')
        self.assertEqual(self.warehouse.items('alice'),())

    def test_mark_item_mutation_guards_and_storage_rollback(self):
        self.mark()
        for op in ('sell','destroy','enhance','mail','auction'):
            with self.assertRaises(b.BankRejected):self.call(b.assert_item_mutation,'alice',17,op)
        for op in ('equip','use','repair','wear'):self.call(b.assert_item_mutation,'alice',17,op)
        with transaction(self.path) as db:db.execute("CREATE TRIGGER faildelivery BEFORE INSERT ON warehouse_items BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.call(b.lend_marked,'alice',1,'bob','fail',now=self.now)
        self.assertEqual(decode_item_list(self.pets.inventory('alice',1))[1][0].instance_id,17)
        self.assertEqual(self.read('SELECT holder,current_instance FROM bank_item_marks')[0],('alice',17))

    def test_two_accounts_do_not_mark_foreign_items_or_return_alias(self):
        first=self.mark();second=self.call(b.mark_item,'bob',17,1,'1234','bobmark',now=self.now)
        self.assertNotEqual(first['mark_id'],second['mark_id'])
        with self.assertRaises(b.BankRejected):self.call(b.lend_marked,'bob',first['mark_id'],'carol','steal',now=self.now)
        with self.assertRaises(b.BankRejected):self.call(b.mark_item,'alice',17,1,'1234','repeatother',now=self.now)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(len(b.marked_items(db,'alice')),1)


class StripeLedgerTests(BankFixture):
    def setUp(self):
        super().setUp();self.calls=[]
        self.config={**b.policy()['provider'], 'enabled':True,'type':'stripe_checkout','currency':'rub','minor_units_per_gold':100,'minimum_gold':1,
            'success_url':'https://merchant.example/success','cancel_url':'https://merchant.example/cancel'}
        self.environ={'STRIPE_SECRET_KEY':'sk_live_fixture_only','STRIPE_WEBHOOK_SECRET':'whsec_fixture_only'}
        def transport(fields,order):
            self.calls.append((fields,order));return dict(id='cs_live_'+order,url='https://checkout.stripe.com/c/pay/'+order,currency=fields['line_items[0][price_data][currency]'],amount_total=int(fields['line_items[0][price_data][unit_amount]'])*int(fields['line_items[0][quantity]']),livemode=True)
        self.adapter=b.StripeCheckout(self.config,environ=self.environ,transport=transport)
        self.bank=b.BankStore(self.path,provider=self.adapter,clock=lambda:self.now)

    def test_approved_eur_cent_price_minimum_before_provider_io(self):
        self.adapter.config.update(currency='eur',minor_units_per_gold=1,minimum_gold=50)
        with self.assertRaises(b.BankRejected):self.bank.create_order('alice',49,'below-eur-minimum')
        self.assertEqual(self.calls,[]);self.assertEqual(self.read('SELECT * FROM bank_payment_orders'),[])
        order=self.bank.create_order('alice',50,'eur-minimum')
        self.assertEqual((order['gold'],order['amount_minor'],order['currency']),(50,50,'eur'))

    def signed(self,order,*,event_id='evt_fixture',changes=None,stamp=None):
        session=dict(id=order['session_id'] or 'cs_live_'+order['id'],object='checkout.session',mode='payment',client_reference_id=order['id'],payment_status='paid',amount_total=order['amount_minor'],currency=order['currency'],livemode=True,metadata={'tio_order':order['id']})
        session.update(changes or {})
        event=dict(id=event_id,type='checkout.session.completed',livemode=True,data=dict(object=session));body=b.canonical(event).encode();stamp=self.now if stamp is None else stamp
        sig=hmac.new(self.environ['STRIPE_WEBHOOK_SECRET'].encode(),str(stamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
        return body,{'Stripe-Signature':f't={stamp},v1={sig}'}

    def test_default_provider_cannot_issue_order_url_or_gold(self):
        disabled=b.BankStore(self.path)
        self.assertFalse(disabled.status()['configured'])
        with self.assertRaises(b.BankRejected):disabled.create_order('alice',5,'disabled')
        with self.assertRaises(b.BankRejected):disabled.callback(b'{}',{})
        self.assertEqual(self.read('SELECT * FROM bank_payment_orders'),[])
        self.assertEqual(self.calls,[])

    def test_real_adapter_fields_idempotency_and_account_order_isolation(self):
        order=self.bank.create_order('alice',7,'order1')
        self.assertEqual(order,self.bank.create_order('alice',7,'order1'));self.assertEqual(len(self.calls),1)
        fields,nonce=self.calls[0]
        self.assertEqual(fields['line_items[0][quantity]'],7);self.assertEqual(fields['line_items[0][price_data][unit_amount]'],100)
        self.assertEqual(fields['metadata[tio_order]'],order['id']);self.assertEqual(nonce,order['id'])
        self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='alice'")[0][0],100) # opening successURL never pays.
        with self.assertRaises(b.BankRejected):self.bank.order('bob',order['id'])
        with self.assertRaises(b.BankRejected):self.bank.create_order('alice',8,'order1')

    def test_signed_live_paid_callback_credits_once_per_order_not_event(self):
        order=self.bank.create_order('alice',7,'order1');body,headers=self.signed(order)
        first=self.bank.callback(body,headers);self.assertEqual(first['gold_collected'],7)
        self.assertEqual(first,self.bank.callback(body,headers))
        other=self.signed(order,event_id='evt_second_delivery');self.bank.callback(*other)
        self.assertEqual(self.read("SELECT credits,gold FROM wallets WHERE account='alice'")[0],(10000,107))
        self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='bob'")[0][0],100)
        self.assertEqual(self.read('SELECT state FROM bank_payment_orders')[0][0],'paid')

    def test_unsigned_stale_wrong_amount_currency_session_or_testmode_never_credit(self):
        order=self.bank.create_order('alice',7,'order1');body,headers=self.signed(order)
        with self.assertRaises(b.BankRejected):self.bank.callback(body,{})
        with self.assertRaises(b.BankRejected):self.bank.callback(body+b' ',headers)
        with self.assertRaises(b.BankRejected):self.bank.callback(*self.signed(order,stamp=self.now-301))
        for n,changes in enumerate(({'amount_total':1},{'currency':'eur'},{'id':'cs_live_other'},{'livemode':False},{'metadata':{'tio_order':'unknown'}},{'mode':'subscription'},{'client_reference_id':'wrong'})):
            with self.assertRaises(b.BankRejected):self.bank.callback(*self.signed(order,event_id='evt_bad'+str(n),changes=changes))
        self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='alice'")[0][0],100)
        self.assertEqual(self.read('SELECT * FROM bank_payment_events'),[])
        ignored=self.bank.callback(*self.signed(order,changes={'payment_status':'unpaid'}));self.assertEqual(ignored,dict(ignored=True))

    def test_paid_overflow_preserved_collect_later_and_event_failure_rolls_back(self):
        order=self.bank.create_order('alice',7,'order1')
        with transaction(self.path) as db:
            db.execute("UPDATE wallets SET gold=? WHERE account='alice'",(b.MAX-2,))
            db.execute("CREATE TRIGGER failpay BEFORE INSERT ON bank_payment_events BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.bank.callback(*self.signed(order))
        self.assertEqual(self.read('SELECT state FROM bank_payment_orders')[0][0],'pending')
        self.assertEqual(self.read('SELECT * FROM bank_gold_payables'),[])
        with transaction(self.path) as db:db.execute('DROP TRIGGER failpay')
        self.bank.callback(*self.signed(order));self.assertEqual(self.read('SELECT gold FROM bank_gold_payables')[0][0],5)
        with transaction(self.path) as db:db.execute("UPDATE wallets SET gold=gold-5 WHERE account='alice'")
        self.assertEqual(self.call(b.collect_paid_gold,'alice'),5)
        self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='alice'")[0][0],b.MAX)
        self.assertEqual(self.call(b.collect_paid_gold,'alice'),0)

    def test_concurrent_checkout_and_confirm_race_keep_one_order_one_award(self):
        with ThreadPoolExecutor(max_workers=4) as pool:orders=list(pool.map(lambda _:self.bank.create_order('alice',7,'oneorder'),range(4)))
        self.assertEqual(len({o['id'] for o in orders}),1)
        signed=self.signed(orders[0])
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:self.bank.callback(*signed),range(4)))
        self.assertTrue(all(r==results[0] for r in results));self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='alice'")[0][0],107)

    def test_unresolved_old_provider_call_and_outer_gameplay_lock_cannot_retry_io(self):
        with patch.object(self.adapter,'create_checkout',side_effect=TimeoutError('fixture')):
            with self.assertRaises(TimeoutError):self.bank.create_order('alice',7,'timeout')
        self.now+=24*3600
        with self.assertRaises(b.BankRejected):self.bank.create_order('alice',7,'timeout')
        with transaction(self.path):
            with self.assertRaises(RuntimeError):self.bank.create_order('alice',7,'inlock')
        self.assertEqual(self.read("SELECT gold FROM wallets WHERE account='alice'")[0][0],100)


if __name__=='__main__':unittest.main()
