from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import hashlib
import hmac
import importlib.util
from http.client import HTTPConnection
import json
import sqlite3
import tempfile
import threading
import unittest

from server.accounts import Accounts
from tio.bank_economy import BankStore,StripeCheckout,canonical,policy
from tio.character_identity import initialise,alias
from tio.db_transaction import transaction

AVAILABLE=importlib.util.find_spec('flask') is not None
if AVAILABLE:from server.bank_gateway import create_app,merchant_config


@unittest.skipUnless(AVAILABLE,'Uses the existing registration/requirements.txt Flask runtime')
class BankGatewayTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.path=Path(folder.name)/'players.db'
        for login in ('alice','bob'):Accounts(self.path).create(login,'FixturePassword123!',character=login.title())
        Accounts(self.path).create('newplayer','FixturePassword123!')
        with transaction(self.path) as db:
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER)')
            db.executemany('INSERT INTO wallets VALUES (?,1000,0)',(('alice',),('bob',)))
            initialise(db);owner=alias('alice',2)
            db.execute('INSERT INTO character_identities VALUES (?,2,?)',('alice',owner))
            db.execute('INSERT INTO characters VALUES (?,1,?,?,?)',(owner,b'AliceTwo','alicetwo',b'fixture'))
            db.execute('INSERT INTO wallets VALUES (?,2000,3)',(owner,))
        self.calls=[];self.now=2000000000;self.key='fixture_bank_private_service_key_64_chars_only'
        self.environ={'STRIPE_SECRET_KEY':'sk_live_fixture_only','STRIPE_WEBHOOK_SECRET':'whsec_fixture_only'}
        config=dict(enabled=True,currency='eur',minor_units_per_gold=100,minimum_gold=1,success_url='https://merchant.example/ru/bank',cancel_url='https://merchant.example/ru/bank')
        def transport(fields,order):
            self.calls.append((fields,order));return dict(id='cs_live_'+order,url='https://checkout.stripe.com/c/pay/'+order,currency='eur',amount_total=fields['line_items[0][quantity]']*100,livemode=True)
        provider=StripeCheckout(config,environ=self.environ,transport=transport)
        self.bank=BankStore(self.path,provider=provider,clock=lambda:self.now)
        self.app=create_app(self.path,self.key,bank=self.bank);self.client=self.app.test_client()

    def post(self,path,body,*,auth=True,remote='127.0.0.1'):
        return self.client.post('/v1/bank/'+path,json=body,headers={'Authorization':'Bearer '+self.key} if auth else {},environ_overrides={'REMOTE_ADDR':remote})

    def signed(self,order,**changes):
        session=dict(id=order['session_id'],object='checkout.session',mode='payment',client_reference_id=order['id'],metadata={'tio_order':order['id']},amount_total=order['amount_minor'],currency=order['currency'],livemode=True,payment_status='paid')
        session.update(changes);raw=canonical(dict(id='evt_fixture',type='checkout.session.completed',livemode=True,data=dict(object=session))).encode()
        sig=hmac.new(self.environ['STRIPE_WEBHOOK_SECRET'].encode(),str(self.now).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return raw,{'Authorization':'Bearer '+self.key,'Stripe-Signature':f't={self.now},v1={sig}'}

    def gold(self,owner):
        with closing(sqlite3.connect(self.path)) as db:return db.execute('SELECT gold FROM wallets WHERE account=?',(owner,)).fetchone()[0]

    def test_service_auth_and_loopback_peer_are_required_on_every_route(self):
        for path,body in (('status',dict(username='alice',slot=1)),('orders',dict(username='alice',slot=1,gold=5,requestId='fixture-request-0001')),('order',dict(username='alice',slot=1,orderId='notuuid'))):
            self.assertEqual(self.post(path,body,auth=False).status_code,401)
            self.assertEqual(self.post(path,body,remote='203.0.113.2').status_code,403)
        self.assertEqual(self.client.post('/v1/bank/stripe/webhook',data=b'{}').status_code,401)
        self.assertEqual(self.calls,[])

    def test_real_linked_login_slot_status_is_read_only_and_no_secret_is_returned(self):
        before=self.path.read_bytes();response=self.post('status',dict(username='alice',slot=2))
        self.assertEqual(response.status_code,200);data=response.json
        self.assertEqual(data['character'],'AliceTwo');self.assertEqual(data['balances'],dict(credits=2000,gold=3,payable='0'))
        self.assertEqual(data['characters'],[dict(slot=1,name='Alice'),dict(slot=2,name='AliceTwo')]);self.assertTrue(data['canPurchase'])
        self.assertEqual(self.path.read_bytes(),before)
        self.assertNotIn('secret',response.text);self.assertNotIn(self.key,response.text);self.assertNotIn('salt',response.text)
        self.assertEqual(self.post('status',dict(username='newplayer',slot=1)).json['reason'],'character_required')
        self.assertEqual(self.post('status',dict(username='missing',slot=1)).status_code,404)

    def test_no_arbitrary_owner_and_unowned_slots_cannot_create_orders(self):
        for data in (dict(username='alice',slot=3,gold=1,requestId='fixture-request-0001'),dict(username=alias('alice',2),slot=1,gold=1,requestId='fixture-request-0001'),dict(username='alice',slot=1,owner='bob',gold=1,requestId='fixture-request-0001')):
            self.assertIn(self.post('orders',data).status_code,(400,409))
        self.assertEqual(self.calls,[]);self.assertEqual(self.gold('bob'),0)

    def test_default_disabled_has_explicit_status_no_fake_url_order_or_credit(self):
        bank=BankStore(self.path);client=create_app(self.path,self.key,bank=bank).test_client();headers={'Authorization':'Bearer '+self.key}
        status=client.post('/v1/bank/status',json=dict(username='alice',slot=1),headers=headers).json
        self.assertFalse(status['configured']);self.assertFalse(status['canPurchase']);self.assertEqual(status['reason'],'not_configured');self.assertEqual((status['currency'],status['minorUnitsPerGold'],status['minimumGold']),('eur',1,50))
        response=client.post('/v1/bank/orders',json=dict(username='alice',slot=1,gold=5,requestId='fixture-request-0001'),headers=headers)
        self.assertEqual(response.status_code,503);self.assertEqual(response.json,dict(error='bank_not_configured'))
        self.assertEqual(self.gold('alice'),0);self.assertEqual(self.calls,[])

    def test_checkout_retry_prepaid_state_and_owner_bound_lookup(self):
        body=dict(username='alice',slot=2,gold=5,requestId='fixture-request-0001')
        first=self.post('orders',body);again=self.post('orders',body)
        self.assertEqual(first.status_code,200);self.assertEqual(first.json,again.json);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.gold(alias('alice',2)),3)
        oid=first.json['order']['id']
        self.assertEqual(self.post('order',dict(username='alice',slot=2,orderId=oid)).json,first.json)
        self.assertEqual(self.post('order',dict(username='alice',slot=1,orderId=oid)).status_code,404)
        self.assertEqual(self.post('order',dict(username='bob',slot=1,orderId=oid)).status_code,404)
        self.assertNotIn('account',first.json['order']);self.assertNotIn('session_id',first.json['order'])

    def test_raw_signed_live_paid_webhook_is_the_only_credit_path_and_duplicates_are_safe(self):
        result=self.post('orders',dict(username='alice',slot=2,gold=5,requestId='fixture-request-0001')).json
        order=self.bank.order(alias('alice',2),result['order']['id']);raw,headers=self.signed(order)
        self.assertEqual(self.client.post('/v1/bank/stripe/webhook',data=raw+b' ',headers=headers).status_code,400)
        self.assertEqual(self.gold(alias('alice',2)),3)
        for _ in range(2):
            response=self.client.post('/v1/bank/stripe/webhook',data=raw,headers=headers)
            self.assertEqual(response.status_code,200);self.assertEqual(response.json,dict(received=True))
        self.assertEqual(self.gold(alias('alice',2)),8);self.assertEqual(self.gold('alice'),0);self.assertEqual(self.gold('bob'),0)
        self.assertEqual(self.post('order',dict(username='alice',slot=2,orderId=order['id'])).json['order']['state'],'paid')

    def test_unpaid_wrong_amount_and_storage_failure_do_not_credit(self):
        result=self.post('orders',dict(username='alice',slot=1,gold=5,requestId='fixture-request-0001')).json
        order=self.bank.order('alice',result['order']['id'])
        raw,headers=self.signed(order,payment_status='unpaid');self.assertEqual(self.client.post('/v1/bank/stripe/webhook',data=raw,headers=headers).status_code,200)
        raw,headers=self.signed(order,amount_total=1);self.assertEqual(self.client.post('/v1/bank/stripe/webhook',data=raw,headers=headers).status_code,400)
        with transaction(self.path) as db:db.execute("CREATE TRIGGER fixture BEFORE INSERT ON bank_payment_events BEGIN SELECT RAISE(ABORT,'private_error'); END")
        raw,headers=self.signed(order);response=self.client.post('/v1/bank/stripe/webhook',data=raw,headers=headers)
        self.assertEqual(response.status_code,503);self.assertEqual(response.json,dict(error='service_unavailable'));self.assertEqual(self.gold('alice'),0)

    def test_body_limits_invalid_types_and_bad_database_fail_closed(self):
        response=self.client.post('/v1/bank/stripe/webhook',data=b' '*262145,headers={'Authorization':'Bearer '+self.key})
        self.assertEqual(response.status_code,413)
        for gold in (True,0,100001):self.assertEqual(self.post('orders',dict(username='alice',slot=1,gold=gold,requestId='fixture-request-0001')).status_code,400)
        with self.assertRaises(ValueError):create_app(self.path,'short',bank=self.bank)
        with self.assertRaises(sqlite3.Error):create_app(self.path.parent/'missing.db',self.key)
        with patch.dict('os.environ',{},clear=True):self.assertEqual(merchant_config(),{})

    def test_real_loopback_http_listener_keeps_service_auth_and_disabled_status(self):
        from waitress import create_server
        app=create_app(self.path,self.key,bank=BankStore(self.path))
        server=create_server(app,listen='127.0.0.1:0',threads=1,asyncore_loop_timeout=.05,
            max_request_body_size=262144,clear_untrusted_proxy_headers=True)
        worker=threading.Thread(target=server.run,daemon=True);worker.start()
        try:
            for authorized in (False,True):
                with closing(HTTPConnection('127.0.0.1',int(server.effective_port),timeout=3)) as connection:
                    headers={'Content-Type':'application/json','Connection':'close','X-Forwarded-For':'127.0.0.1'}
                    if authorized:headers['Authorization']='Bearer '+self.key
                    connection.request('POST','/v1/bank/status',json.dumps(dict(username='alice',slot=2)),headers)
                    response=connection.getresponse();data=json.loads(response.read())
                    self.assertEqual(response.status,200 if authorized else 401)
                    if authorized:
                        self.assertEqual(data['character'],'AliceTwo');self.assertFalse(data['configured'])
                        self.assertEqual(data['balances']['gold'],3)
                    else:self.assertEqual(data,dict(error='unauthorized'))
        finally:
            server.task_dispatcher.shutdown();server.close();worker.join(timeout=3)
        self.assertFalse(worker.is_alive());self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
