"""Operator CLI uses actual saved character aliases and atomic prison rules."""
from contextlib import closing,redirect_stdout,redirect_stderr
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from server.accounts import Accounts
from tio import battle_checkpoints,battle_settlement
from tio import world_completion as world
from tio.characters import CharacterStore
from tio.db_transaction import transaction
from tio.locations import LocationStore,center
from tio.protocol.character_create import CharacterCreateRequest
from tio.wallets import WalletStore
from tools import moderate_prison as tool


class PrisonOperatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_directory=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.seed_directory.cleanup)
        cls.seed=Path(cls.seed_directory.name)/'actual-characters.sqlite3'
        accounts=Accounts(cls.seed)
        accounts.create('private_auth_owner','Never-print-password-123',character='PublicOne')
        accounts.create('private_other_owner','Other-secret-password-123',character='OtherPlayer')
        characters=CharacterStore(cls.seed)
        characters.create('private_auth_owner',CharacterCreateRequest(b'PublicTwo',0,(0,0,0,0)))
        cls.secondary=characters.owner('private_auth_owner',2)
        locations=LocationStore(cls.seed)
        wallets=WalletStore(cls.seed)
        for owner,town in (('private_auth_owner',3),(cls.secondary,18),('private_other_owner',2)):
            wallets.ensure(owner)
            with transaction(cls.seed) as db:LocationStore._save(db,owner,town,*center(town))

    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name);self.path=self.directory/'players.sqlite3'
        shutil.copyfile(self.seed,self.path)

    def rows(self,query,*parameters):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(query,parameters).fetchall()

    def state(self,owner):
        with closing(sqlite3.connect(self.path)) as db:return world.prison_state(db,owner)

    def call(self,**overrides):
        arguments=dict(database=self.path,character='PublicTwo',seconds=60,operation='moderation:stable-request')
        arguments.update(overrides);return tool.moderate(**arguments)

    def cli(self,args):
        stdout,stderr=io.StringIO(),io.StringIO()
        with redirect_stdout(stdout),redirect_stderr(stderr):code=tool.main(args)
        self.assertEqual(stderr.getvalue(),'')
        self.assertEqual(len(stdout.getvalue().splitlines()),1)
        result=json.loads(stdout.getvalue());self.assertEqual(set(result),{'character','remaining','replay','status'})
        for private in ('private_auth_owner','private_other_owner','@character:',
                        'Never-print-password','sensitive-operation','heartbeat-secret'):
            self.assertNotIn(private,stdout.getvalue())
        return code,result

    def test_secondary_public_name_resolves_actual_save_owner_not_primary_login(self):
        baseline=self.rows('SELECT * FROM accounts ORDER BY login')
        primary=self.rows('SELECT * FROM character_locations WHERE account=?','private_auth_owner')
        foreign=self.rows('SELECT * FROM character_locations WHERE account=?','private_other_owner')
        result=self.call(character='pUbLiCtWo')
        self.assertEqual(result,{'character':'PublicTwo','remaining':60,'replay':False,'status':'sentenced'})
        self.assertEqual(self.state(self.secondary),{'remaining':60,'town_id':10})
        self.assertIsNone(self.state('private_auth_owner'))
        self.assertEqual(self.rows('SELECT * FROM character_locations WHERE account=?','private_auth_owner'),primary)
        self.assertEqual(self.rows('SELECT * FROM character_locations WHERE account=?','private_other_owner'),foreign)
        self.assertEqual(self.rows('SELECT * FROM accounts ORDER BY login'),baseline)
        self.assertEqual(self.rows('SELECT account,slot,name FROM characters WHERE account=?',self.secondary),
                         [(self.secondary,1,b'PublicTwo')])

    def test_first_slot_resolves_only_its_public_name_and_does_not_reassign_alias(self):
        result=self.call(character='PublicOne')
        self.assertEqual(result['character'],'PublicOne')
        self.assertEqual(self.state('private_auth_owner')['remaining'],60)
        self.assertIsNone(self.state(self.secondary))
        self.assertEqual(self.rows('SELECT login,slot,owner FROM character_identities'),
                         [('private_auth_owner',2,self.secondary)])

    def test_same_operation_replay_is_unchanged_after_time_has_been_served(self):
        self.call()
        with transaction(self.path) as db:
            world.prison_online(db,self.secondary,'heartbeat-secret',now=100)
            world.prison_online(db,self.secondary,'heartbeat-secret',now=110)
        before=self.path.read_bytes();result=self.call()
        self.assertEqual(result,{'character':'PublicTwo','remaining':50,'replay':True,'status':'replayed'})
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM world_prison_operations'),[(1,)])

    def test_conflicting_seconds_or_character_rolls_back_without_any_new_rows(self):
        self.call();before=self.path.read_bytes()
        for change in ({'seconds':61},{'character':'OtherPlayer'}):
            with self.subTest(change=change):
                with self.assertRaises(tool.ModerationError) as caught:self.call(**change)
                self.assertEqual(caught.exception.status,'conflicting_operation')
                self.assertEqual(self.path.read_bytes(),before)
        self.assertIsNone(self.state('private_other_owner'))

    def test_active_and_quarantined_checkpoint_blocks_alias_before_any_partial_schema(self):
        battle_checkpoints.initialise(self.path)
        for status in ('active','quarantined'):
            with self.subTest(status=status):
                with transaction(self.path) as db:
                    battle_checkpoints.save(db,'real-checkpoint','{}',{self.secondary:1001},status=status,now=0)
                before=self.path.read_bytes()
                with self.assertRaises(tool.ModerationError) as caught:self.call()
                self.assertEqual(caught.exception.status,'battle_pending')
                self.assertEqual(self.path.read_bytes(),before)
                self.assertEqual(self.rows("SELECT name FROM sqlite_master WHERE name LIKE 'world_prison%'"),[])
                with transaction(self.path) as db:battle_checkpoints.delete(db,'real-checkpoint')
        self.assertEqual(self.call()['status'],'sentenced')

    def test_real_settlement_outbox_blocks_only_saved_owner_without_partial_changes(self):
        battle_settlement.enqueue(self.path,'pending-result',[(self.secondary,1,{})])
        before=self.path.read_bytes()
        with self.assertRaises(tool.ModerationError) as caught:self.call()
        self.assertEqual(caught.exception.status,'battle_pending');self.assertEqual(self.path.read_bytes(),before)
        self.assertIsNone(self.state(self.secondary))
        # A different public character's sentence must not remove that outbox.
        self.call(character='OtherPlayer',operation='moderation:other')
        self.assertEqual(self.rows('SELECT account FROM battle_settlement_jobs'),[(self.secondary,)])

    def test_unknown_name_and_auth_alias_do_not_create_schema_or_mutate_database(self):
        before=self.path.read_bytes()
        for character,status in (('UnknownPlayer','character_not_found'),
                                 ('private_auth_owner','invalid_request'),
                                 (self.secondary,'invalid_request')):
            with self.subTest(character=character):
                with self.assertRaises(tool.ModerationError) as caught:self.call(character=character)
                self.assertEqual(caught.exception.status,status);self.assertEqual(self.path.read_bytes(),before)

    def test_sentence_total_limit_and_post_write_failure_roll_back(self):
        self.call(seconds=tool.MAX_SECONDS);before=self.path.read_bytes()
        with self.assertRaises(tool.ModerationError) as caught:self.call(operation='moderation:new',seconds=1)
        self.assertEqual(caught.exception.status,'sentence_limit');self.assertEqual(self.path.read_bytes(),before)
        original=world.sentence
        def fail_after_write(*args):
            original(*args);raise sqlite3.OperationalError('private_auth_owner heartbeat-secret')
        with patch.object(world,'sentence',side_effect=fail_after_write):
            with self.assertRaises(tool.ModerationError) as caught:
                self.call(character='OtherPlayer',operation='moderation:fail')
        self.assertEqual(caught.exception.status,'database_unavailable');self.assertEqual(self.path.read_bytes(),before)

    def test_argument_ranges_and_missing_database_do_not_create_new_file(self):
        before=self.path.read_bytes()
        for seconds in (0,-1,tool.MAX_SECONDS+1,True,1.0,'60'):
            with self.assertRaises(tool.ModerationError) as caught:self.call(seconds=seconds)
            self.assertEqual(caught.exception.status,'invalid_request')
        for operation in ('','space key','key\nsecret','a'*161):
            with self.assertRaises(tool.ModerationError):self.call(operation=operation)
        missing=self.directory/'must-not-create.sqlite3'
        with self.assertRaises(tool.ModerationError) as caught:self.call(database=missing)
        self.assertEqual(caught.exception.status,'database_unavailable');self.assertFalse(missing.exists())
        self.assertEqual(self.path.read_bytes(),before)

    def test_wrong_existing_schema_or_non_sqlite_file_is_preserved(self):
        wrong=self.directory/'wrong.sqlite3'
        with closing(sqlite3.connect(wrong)) as db,db:db.execute('CREATE TABLE unrelated(id INTEGER)')
        before=wrong.read_bytes()
        with self.assertRaises(tool.ModerationError) as caught:self.call(database=wrong)
        self.assertEqual(caught.exception.status,'database_unavailable');self.assertEqual(wrong.read_bytes(),before)
        not_sqlite=self.directory/'not-sqlite.txt';not_sqlite.write_bytes(b'private_auth_owner token')
        with self.assertRaises(tool.ModerationError):self.call(database=not_sqlite)
        self.assertEqual(not_sqlite.read_bytes(),b'private_auth_owner token')

    def test_cli_success_replay_and_errors_redact_auth_owner_operation_and_clock_token(self):
        args=['--database',str(self.path),'--character','publictwo','--seconds','60',
              '--operation','sensitive-operation']
        code,result=self.cli(args);self.assertEqual(code,0);self.assertEqual(result['status'],'sentenced')
        with transaction(self.path) as db:world.prison_online(db,self.secondary,'heartbeat-secret',now=100)
        code,result=self.cli(args);self.assertEqual(code,0);self.assertEqual(result['status'],'replayed')
        conflict=args.copy();conflict[5]='61'
        code,result=self.cli(conflict);self.assertEqual(code,2);self.assertEqual(result['status'],'conflicting_operation')
        for malformed in ([],['--database'],args+['--password','Never-print-password-123'],
                          args[:-2]+['--operation','heartbeat-secret\nprivate_auth_owner'],
                          ['--database',str(self.path),'--character',self.secondary,'--seconds','60','--operation','op']):
            code,result=self.cli(malformed);self.assertEqual(code,2);self.assertEqual(result['status'],'invalid_request')
        unknown=args.copy();unknown[3]='MissingPlayer'
        code,result=self.cli(unknown);self.assertEqual(code,2);self.assertEqual(result['status'],'character_not_found')
        self.assertIsNone(result['character'])

    def test_unexpected_internal_error_never_prints_private_exception_or_traceback(self):
        args=['--database',str(self.path),'--character','PublicTwo','--seconds','60',
              '--operation','sensitive-operation']
        before=self.path.read_bytes()
        with patch.object(world,'sentence',side_effect=RuntimeError('private_auth_owner heartbeat-secret')):
            code,result=self.cli(args)
        self.assertEqual(code,2);self.assertEqual(result['status'],'operation_rejected')
        self.assertEqual(self.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
