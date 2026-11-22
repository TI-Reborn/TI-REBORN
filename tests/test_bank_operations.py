"""Bank pipeline integration using inspected hosted runtime and real SQLite."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import sqlite3
import threading
from unittest.mock import patch
import unittest
from urllib.request import Request,urlopen

import test_city_operations as fixture
from server.bank_gameplay import BankGameSession
from server.bank_operations import (BANK_ACTION_FIELDS,BANK_OPERATIONS,BankContext,
                                    prepare_bank,execute_bank)
from server.city_operations import CityError
from server.city_http import CityHTTP
from tio import bank_economy as bank
from tio.characters import CharacterStore
from tio.character_identity import owner_for_slot
from tio.db_transaction import transaction,connect
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.item_list import decode_item_list
from tio.protocol.asset_count import decode_asset_count

PIN='135790'
NONCE='shared-bank-request-0001'


def messages(reply):
    return '\n'.join(p[p.index(b'\0',6)+1:-2].decode('utf-16-le') for p in reply.packets if p[:1]==b'\x22')


class BankOperationTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.CityOperationsTests(methodName='runTest');self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.ops=self.case.ops;self.path=self.case.path
        self.native={a:BankGameSession(self.path,a,clock=lambda:self.case.now) for a in ('alice','bob')}

    def request(self,kind='stocks_buy',owner='alice',nonce=NONCE,**args):
        return self.case.request(kind,username=owner,requestId=nonce,**args)

    def buy(self,owner='alice',nonce=NONCE,count=2):
        return self.ops.action(self.request(owner=owner,nonce=nonce,count=count,quote=100))

    def command(self,text,owner='alice',**gates):
        return self.native[owner].command(text,city_idle=gates.pop('city_idle',True),**gates)

    def rows(self):return self.case.rows()
    def wallet(self,owner='alice'):
        return self.case.read('SELECT credits,gold FROM wallets WHERE account=?',(owner,))[0]

    def mark(self):
        item=self.case.buy_item()
        response=self.ops.action(self.request('mark',instanceId=item,days=2,pin=PIN))
        return item,response['status']['marks'][0]['id']

    def test_both_adapters_use_registry_and_share_exact_receipt(self):
        with patch.object(BANK_OPERATIONS,'execute',wraps=BANK_OPERATIONS.execute) as execute:
            first=self.buy()
            again=self.command(f'!bank stocks buy 2 100 {NONCE}')
            self.assertEqual([c.args[0].name for c in execute.call_args_list],['stocks_buy','stocks_buy'])
        self.assertEqual(first['receipt']['creditsDelta'],-200)
        self.assertEqual(first['receipt']['goldDelta'],0)
        self.assertEqual(again.changed_accounts,())
        self.assertEqual(self.wallet(),(9800,10000));self.assertEqual(self.wallet('bob'),(10000,10000))
        self.assertEqual(len(self.case.read('SELECT * FROM bank_economy_receipts')),1)

    def test_native_receipt_replays_through_city_and_survives_new_session(self):
        first=self.command(f'!bank stocks buy 2 100 {NONCE}')
        self.assertEqual(first.changed_accounts,('alice',))
        self.native['alice']=BankGameSession(self.path,'alice',clock=lambda:self.case.now)
        self.assertTrue(self.buy()['replayed'])
        self.assertEqual(self.command(f'!bank stocks buy 2 100 {NONCE}').changed_accounts,())
        self.assertEqual(self.wallet(),(9800,10000))

    def test_concurrent_transports_with_one_identity_charge_once(self):
        barrier=threading.Barrier(2)
        def portal():barrier.wait();return self.buy()
        def native():barrier.wait();return self.command(f'!bank stocks buy 2 100 {NONCE}')
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(portal);b=pool.submit(native);responses=(a.result(),b.result())
        self.assertEqual(int(not responses[0]['replayed'])+int(bool(responses[1].changed_accounts)),1)
        self.assertEqual(self.wallet(),(9800,10000))
        self.assertEqual(self.case.read('SELECT stocks FROM bank_securities WHERE account=?',('alice',)),[(2,)])

    def test_owner_scoped_identity_and_conflicting_arguments(self):
        self.buy();self.buy(owner='bob')
        self.assertEqual(self.wallet(),self.wallet('bob'));before=self.rows()
        with self.assertRaises(CityError):self.buy(count=3)
        denied=self.command(f'!bank stocks buy 3 100 {NONCE}')
        self.assertEqual(denied.changed_accounts,());self.assertEqual(before,self.rows())

    def test_direct_historical_receipt_remains_compatible(self):
        with transaction(self.path) as db:
            bank.securities_trade(db,'alice','stocks','buy',2,NONCE,quote=100,now=self.case.now)
        self.assertTrue(self.buy()['replayed']);self.assertEqual(self.wallet(),(9800,10000))

    def test_old_gold_conversion_and_payments_stay_closed(self):
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('convert',gold=1))
        reply=self.command('!bank convert 1 '+NONCE)
        self.assertIn('обмен закрыт',messages(reply));self.assertEqual(self.rows(),before)
        with self.assertRaises(bank.BankRejected):self.native['alice'].store.create_order('alice',10,NONCE)

    def test_bonds_use_credits_and_preserve_calendar_and_replay(self):
        before=self.wallet()
        price=bank.policy()['bonds']['credits_each']
        first=self.ops.action(self.request('bonds_buy',count=2,quote=price))
        self.assertEqual(self.wallet(),(before[0]-2*price,before[1]))
        self.assertEqual(first['receipt']['creditsDelta'],-2*price)
        self.case.now=int(datetime(2026,10,21,tzinfo=timezone.utc).timestamp())
        self.assertTrue(self.ops.action(self.request('bonds_buy',count=2,quote=price))['replayed'])
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('bonds_buy',nonce='new-bond-request-0001',count=1,quote=price))
        self.assertEqual(before,self.rows())
        self.case.now=int(datetime(2026,11,25,tzinfo=timezone.utc).timestamp())
        sold=self.ops.action(self.request('bonds_sell',nonce='bond-redemption-0001',count=2,quote=155))
        self.assertEqual(sold['receipt']['creditsDelta'],310)

    def test_stale_quote_and_insufficient_funds_roll_back_every_write(self):
        before=self.rows()
        for count,quote in ((2,101),(100000,100)):
            with self.assertRaises(CityError):self.ops.action(self.request(count=count,quote=quote))
            self.assertEqual(before,self.rows())

    def test_city_projection_failure_rolls_back_money_holdings_and_journals(self):
        before=self.rows()
        with patch.object(self.ops,'_status',side_effect=RuntimeError('projection fixture')):
            with self.assertRaises(RuntimeError):self.buy()
        self.assertEqual(before,self.rows())

    def test_native_projection_failure_rolls_back_savepoint_inside_outer_unit(self):
        before=self.rows()
        with transaction(self.path):
            with patch.object(self.native['alice'],'_reply',side_effect=RuntimeError('projection fixture')):
                with self.assertRaises(RuntimeError):self.command(f'!bank stocks buy 2 100 {NONCE}')
        self.assertEqual(before,self.rows())

    def test_bad_domain_result_rolls_back_before_any_response(self):
        before=self.rows();original=bank.securities_trade
        def corrupt(*args,**kwargs):
            value=original(*args,**kwargs);return dict(value,kind='bonds')
        with patch.object(bank,'securities_trade',side_effect=corrupt):
            with self.assertRaises(RuntimeError):self.buy()
        self.assertEqual(before,self.rows())

    def test_unexpected_financial_rejection_result_is_not_committed(self):
        before=self.rows();original=bank.securities_trade
        def corrupt(*args,**kwargs):
            original(*args,**kwargs);return dict(rejected='invalid financial result')
        with patch.object(bank,'securities_trade',side_effect=corrupt):
            with self.assertRaises(RuntimeError):self.buy()
        self.assertEqual(before,self.rows())

    def test_live_http_preserves_bank_receipt_shape_and_replay(self):
        service=CityHTTP(self.case.router,fixture.KEY,port=0,operations=self.ops).start()
        self.addCleanup(service.close)
        def call(payload):
            request=Request('http://127.0.0.1:'+str(service.http.server_port)+'/v1/city/action',
                data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',
                'Authorization':'Bearer '+fixture.KEY})
            with urlopen(request,timeout=3) as reply:return json.loads(reply.read())
        first=call(self.request(count=2,quote=100));again=call(self.request(count=2,quote=100))
        self.assertFalse(first['replayed']);self.assertTrue(again['replayed'])
        self.assertEqual(first['receipt'],again['receipt'])
        self.assertEqual(set(first['receipt']),{'requestId','action','creditsDelta','goldDelta'})
        self.assertEqual(self.wallet(),(9800,10000))

    def test_bank_context_requires_correct_active_transaction_and_rechecks_gates(self):
        command=prepare_bank('stocks_buy',NONCE,dict(count=2,quote=100))
        with sqlite3.connect(self.path) as foreign:
            with self.assertRaises(RuntimeError):execute_bank(command,db=foreign,path=self.path,owner='alice',allowed=True,blocked=frozenset(),now=self.case.now)
        with transaction(self.path) as db:
            context=BankContext(db,self.path,'alice',True,frozenset(),self.case.now)
            BANK_OPERATIONS.check(command,context)
            with self.assertRaises(bank.BankRejected):
                BANK_OPERATIONS.execute(command,BankContext(db,self.path,'alice',True,frozenset(('alice',)),self.case.now))
            with self.assertRaises(RuntimeError):
                BANK_OPERATIONS.execute(command,BankContext(db,self.path.with_name('foreign.db'),'alice',True,frozenset(),self.case.now))
            with self.assertRaises(RuntimeError):
                BANK_OPERATIONS.execute(command,BankContext(db,self.path,'alice',1,frozenset(),self.case.now))
            # Store leases are supported without opening a separate connection.
            leased=connect(self.path)
            result=execute_bank(command,db=leased,path=self.path,owner='alice',allowed=True,blocked=frozenset(),now=self.case.now)
            self.assertFalse(result.replayed)

    def test_strict_schema_keeps_pin_out_of_command_and_context_repr(self):
        self.assertIn('pin',BANK_ACTION_FIELDS['mark']);self.assertNotIn('pin',BANK_OPERATIONS.specs['mark'].fields)
        command=prepare_bank('mark',NONCE,dict(instanceId=1,days=2))
        context=BankContext(None,self.path,'alice',True,frozenset(),self.case.now,pin=PIN)
        self.assertNotIn(PIN,repr(command)+repr(context))
        for args in (dict(count=True,quote=100),dict(count=1,quote=100,owner='bob'),dict(count=0,quote=100)):
            with self.assertRaises(bank.BankRejected):prepare_bank('stocks_buy',NONCE,args)
        with self.assertRaises(bank.BankRejected):prepare_bank('mark',NONCE,dict(instanceId=1,days=2,pin=PIN))

    def test_mark_lend_return_between_adapters_preserves_single_physical_item(self):
        item=self.case.buy_item()
        marked=self.command(f'!bank mark {item} 2 {PIN} {NONCE}')
        self.assertEqual(marked.changed_accounts,('alice',))
        mark=self.case.read('SELECT id FROM bank_item_marks')[0][0]
        lent=self.ops.action(self.request('lend',nonce='cross-channel-lend-0001',markId=mark,recipientName='Bob'))
        self.assertEqual(lent['status']['marks'][0]['holderName'],'Bob')
        returned=self.command(f'!bank reclaim {mark} {PIN} cross-channel-return-01 remove')
        self.assertEqual(set(returned.changed_accounts),{'alice','bob'})
        again=self.ops.action(self.request('reclaim',nonce='cross-channel-return-01',markId=mark,pin=PIN,remove=True))
        self.assertTrue(again['replayed'])
        self.assertEqual(self.case.read("SELECT count(*) FROM warehouse_items WHERE account='bob'"),[(0,)])
        self.assertEqual(self.case.read("SELECT count(*) FROM warehouse_items WHERE account='alice'"),[(1,)])
        self.assertEqual(self.case.read('SELECT state FROM bank_item_marks'),[('removed',)])

    def test_wrong_pin_budget_is_shared_and_committed_without_secret_receipt(self):
        _,mark=self.mark();wallet=self.wallet()
        for i in range(5):
            with transaction(self.path):
                if i%2:
                    result=self.command(f'!bank reclaim {mark} 999999 wrong-shared-pin-{i:04}')
                    self.assertEqual(result.changed_accounts,())
                else:
                    result=self.ops.action(self.request('reclaim',nonce=f'wrong-shared-pin-{i:04}',markId=mark,pin='999999',remove=False))
                    self.assertEqual(result['error'],'pin_rejected')
        self.assertEqual(self.case.read('SELECT failures,locked_until FROM bank_item_marks'),[(0,self.case.now+300)])
        self.assertEqual(self.wallet(),wallet)
        self.assertNotIn(PIN,repr(self.rows()));self.assertNotIn('999999',repr(self.rows()))

    def test_mark_retry_still_checks_pin_and_does_not_charge_again(self):
        item,mark=self.mark();wallet=self.wallet()
        wrong=self.command(f'!bank mark {item} 2 999999 {NONCE}')
        self.assertIn('Неверный PIN',messages(wrong));self.assertEqual(wrong.changed_accounts,())
        self.assertEqual(self.case.read('SELECT failures FROM bank_item_marks'),[(1,)])
        self.assertEqual(self.wallet(),wallet)
        self.assertTrue(self.ops.action(self.request('mark',instanceId=item,days=2,pin=PIN))['replayed'])

    def test_recipient_gate_rechecks_before_move_and_foreign_mark_is_rejected(self):
        _,mark=self.mark()
        with transaction(self.path) as db:db.execute("INSERT INTO map_journeys VALUES ('bob',0,0,100,100,0,100)")
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(self.request('lend',nonce='busy-recipient-0001',markId=mark,recipientName='Bob'))
        denied=self.command(f'!bank lend {mark} Bob busy-recipient-0002',busy=('bob',))
        self.assertEqual(denied.changed_accounts,());self.assertEqual(before,self.rows())
        denied=self.command(f'!bank reclaim {mark} {PIN} foreign-reclaim-0001',owner='bob')
        self.assertEqual(denied.changed_accounts,());self.assertEqual(before,self.rows())

    def test_secondary_owned_slot_uses_its_own_wallet_and_receipt(self):
        CharacterStore(self.path).create('alice',CharacterCreateRequest(b'AliceOther',0,(1,0,0,0)))
        with transaction(self.path) as db:
            owner=owner_for_slot(db,'alice',2);self.case.locations._save(db,owner,3,-154,-318)
        before=self.wallet();request=self.request(count=2,quote=100);request['slot']=2
        credits, gold = self.wallet(owner)
        first=self.ops.action(request)
        self.assertEqual(first['status']['balances'], dict(credits=credits - 200, gold=gold))
        self.assertEqual(self.wallet(), before)
        self.assertEqual(self.wallet(owner), (credits - 200, gold))
        self.assertTrue(self.ops.action(request)['replayed'])

    def test_scene_fences_still_reject_replay_and_action_id_reuse(self):
        request=self.request(count=2,quote=100);self.ops.action(request)
        self.case.router.team_arena.private['alice']=(None,None)
        before=self.rows()
        with self.assertRaises(CityError):self.ops.action(request)
        denied=self.command(f'!bank stocks buy 2 100 {NONCE}',busy=('alice',))
        self.assertEqual(denied.changed_accounts,());self.assertEqual(before,self.rows())
        self.case.router.team_arena.private.clear()
        with self.assertRaises(CityError):self.ops.action(self.request('stocks_sell',count=2,quote=100))


if __name__=='__main__':unittest.main()
