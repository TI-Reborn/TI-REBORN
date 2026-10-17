"""Registration -> authenticated TCP provisioning with disposable player data."""
from contextlib import closing
import re
import sqlite3
import unittest

try:
    from registration.app import create_app as registration_app
    from registration.game_bridge import create_app as bridge_app
    HAS_REGISTRATION=True
except ModuleNotFoundError as error:
    if error.name!='flask':raise
    HAS_REGISTRATION=False
from tio.characters import CharacterStore
from tio.onboarding import prepare
from tio.protocol.character_create import CharacterCreateRequest
from tio.wallets import WalletStore
import test_multi_account as fixtures

PASSWORD=fixtures.PASSWORD

KEY='starting-funds-test-only-private-key-0000'


class StartingFundsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.MultiAccountTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.config.database
        self.wallets=WalletStore(self.path)
        # Previously funded accounts remain outside the new-account policy.
        self.wallets.ensure('alice');self.wallets.ensure('bob')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=9876,gold=4321 WHERE account='alice'")
            db.execute("UPDATE wallets SET credits=77,gold=9 WHERE account='bob'")
        self.previous=self.balances()

    def balances(self):
        with closing(sqlite3.connect(self.path)) as db:
            return dict((account,(credits,gold)) for account,credits,gold in db.execute(
                'SELECT account,credits,gold FROM wallets ORDER BY account'))

    def authenticate_new_account(self,name):
        self.assertNotIn(name,self.balances(),'Registration itself must not eagerly seed funds')
        self.case.start()
        self.case.begin(name,password='Wrong-password-123',denied=True)
        self.assertNotIn(name,self.balances(),'Failed auth must not allocate a wallet')
        peer=self.case.handoff(self.case.begin(name))
        self.assertEqual(self.case.character_screen(peer),())
        self.assertEqual(self.balances()[name],(3000,0))
        for account,balance in self.previous.items():self.assertEqual(self.balances()[account],balance)
        return peer

    def test_cli_account_create_and_game_authentication_seed_only_once(self):
        self.case.accounts.create('fresh_cli',PASSWORD)
        self.authenticate_new_account('fresh_cli')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=2450 WHERE account='fresh_cli'")
        self.case.accounts.create('fresh_cli','Replacement-password-123',reset=True)
        self.assertEqual(self.wallets.ensure('fresh_cli').credits,2450)
        self.assertEqual(self.balances()['fresh_cli'],(2450,0))

    @unittest.skipUnless(HAS_REGISTRATION,'Run with the existing registration virtualenv for Flask routes')
    def test_registration_form_to_game_auth_and_onboarding_preserve_balance(self):
        origin='https://registration.example.test'
        app=registration_app(self.path,KEY,origin);client=app.test_client()
        response=client.get('/register/',base_url=origin)
        token=re.search(rb'name="csrf" value="([^"]+)"',response.data)[1].decode()
        response=client.post('/register/',data=dict(csrf=token,login='fresh_form',
            password=PASSWORD,confirm=PASSWORD),base_url=origin,headers={'Origin':origin})
        self.assertEqual(response.status_code,201)
        self.authenticate_new_account('fresh_form')
        request=CharacterCreateRequest(b'NewFighter',0,(1,0,0,0))
        CharacterStore(self.path).create('fresh_form',request)
        prepare(self.path,'fresh_form');prepare(self.path,'fresh_form')
        self.assertEqual(self.balances()['fresh_form'],(3000,0))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=2410 WHERE account='fresh_form'")
        prepare(self.path,'fresh_form')
        self.assertEqual(self.balances()['fresh_form'],(2410,0))

    @unittest.skipUnless(HAS_REGISTRATION,'Run with the existing registration virtualenv for Flask routes')
    def test_portal_private_api_create_retry_and_password_change_do_not_refund(self):
        app=bridge_app(self.path,KEY,self.path.parent/'web-status.json')
        client=app.test_client();headers={'Authorization':'Bearer '+KEY}
        request=dict(username='fresh_api',password=PASSWORD,requestId='starting-funds-create-001')
        def post(endpoint,payload):return client.post('/v1/accounts/'+endpoint,json=payload,headers=headers)
        self.assertEqual(post('create',request).status_code,201)
        self.assertEqual(post('create',request).status_code,200)
        self.assertEqual(post('verify',dict(username='fresh_api',password=PASSWORD)).status_code,200)
        self.authenticate_new_account('fresh_api')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=2800 WHERE account='fresh_api'")
        self.assertEqual(post('create',request).status_code,200)
        change=dict(username='fresh_api',currentPassword=PASSWORD,newPassword='Replacement-password-123',
                    requestId='starting-funds-password-001')
        self.assertEqual(post('password',change).status_code,200)
        self.assertEqual(post('password',change).status_code,200)
        self.assertEqual(self.wallets.ensure('fresh_api').credits,2800)
        self.assertEqual(self.balances()['fresh_api'],(2800,0))
        for account,balance in self.previous.items():self.assertEqual(self.balances()[account],balance)

    def test_previous_uninitialized_account_gets_new_default_without_migration(self):
        self.case.accounts.create('old_unfunded',PASSWORD)
        self.assertNotIn('old_unfunded',self.balances())
        self.assertEqual((self.wallets.ensure('old_unfunded').credits,self.wallets.ensure('old_unfunded').gold),(3000,0))
        for account,balance in self.previous.items():self.assertEqual(self.balances()[account],balance)


if __name__=='__main__':unittest.main()
