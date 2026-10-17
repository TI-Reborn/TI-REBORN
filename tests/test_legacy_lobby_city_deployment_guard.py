"""Narrow maintenance policy against real SQLite state and frozen sources."""
import base64
from contextlib import closing
import copy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools import deploy_gameplay_completion as established
from tools import deploy_legacy_lobby_projection as release


class CityMaintenanceGuardTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        for table in release.EMPTY_TABLES:
            self.db.execute('CREATE TABLE '+table+'(identity TEXT)')
        self.db.execute('CREATE TABLE wager_matches(match_id TEXT,status TEXT)')
        self.db.execute('CREATE TABLE character_locations(account TEXT,town_id INTEGER)')
        self.db.execute('CREATE TABLE map_journeys(account TEXT)')
        self.db.execute('CREATE TABLE team_ranked_matches(match_id TEXT,state TEXT)')
        self.db.execute('CREATE TABLE wall_ranked_matches(match_id TEXT,state TEXT)')
        self.db.execute('CREATE TABLE mine_claim_leases(match_id TEXT)')

    def tearDown(self):
        self.db.close()

    def city(self):
        return dict(durable=release.durable_state(self.db),game_connections=1,login_connections=0,
            owned_presence=0,presence_count=1,stationary_location_confirmed=True,
            online_account_journeys=0,web_status={'status':'online','playersOnline':1},
            web_status_age_seconds=2)

    def test_one_confirmed_city_session_is_allowed(self):
        release.require_city_safe(self.city(),True)

    def test_more_than_one_socket_is_rejected(self):
        context=self.city();context['game_connections']=2
        with self.assertRaises(RuntimeError):release.require_city_safe(context,True)

    def test_login_connection_cannot_be_treated_as_city(self):
        context=self.city();context['login_connections']=1
        with self.assertRaises(RuntimeError):release.require_city_safe(context,True)

    def test_owned_clients_must_be_closed_and_absent(self):
        with self.assertRaises(RuntimeError):release.require_city_safe(self.city(),False)
        context=self.city();context['owned_presence']=1
        with self.assertRaises(RuntimeError):release.require_city_safe(context,True)

    def test_stale_unknown_or_multiple_online_accounts_are_rejected(self):
        for web,age in ((None,2),({'status':'online','playersOnline':1},16),
                        ({'status':'offline','playersOnline':1},2),
                        ({'status':'online','playersOnline':2},2)):
            with self.subTest(web=web,age=age):
                context=self.city();context.update(web_status=web,web_status_age_seconds=age)
                with self.assertRaises(RuntimeError):release.require_city_safe(context,True)

    def test_unknown_character_or_world_travel_is_rejected(self):
        for key,value in (('presence_count',0),('presence_count',2),
                          ('stationary_location_confirmed',False),('online_account_journeys',1)):
            with self.subTest(key=key,value=value):
                context=self.city();context[key]=value
                with self.assertRaises(RuntimeError):release.require_city_safe(context,True)

    def test_zero_connections_and_no_presence_are_allowed(self):
        context=self.city();context.update(game_connections=0,presence_count=0,web_status=None)
        release.require_city_safe(context,True)
        context['presence_count']=1
        with self.assertRaises(RuntimeError):release.require_city_safe(context,True)

    def test_checkpoint_member_and_settlement_each_block_restart(self):
        for table in release.EMPTY_TABLES:
            with self.subTest(table=table):
                self.db.execute('INSERT INTO '+table+" VALUES ('actual-match')")
                with self.assertRaises(RuntimeError):release.require_city_safe(self.city(),True)
                self.db.execute('DELETE FROM '+table)

    def test_all_active_escrow_phases_block_and_history_is_preserved(self):
        self.db.executemany('INSERT INTO wager_matches VALUES (?,?)',
            (('old-win','settled'),('old-cancel','refunded')))
        release.require_city_safe(self.city(),True)
        for phase in ('held','loading','active'):
            with self.subTest(phase=phase):
                self.db.execute('INSERT INTO wager_matches VALUES (?,?)',('live-match',phase))
                with self.assertRaises(RuntimeError):release.require_city_safe(self.city(),True)
                self.db.execute("DELETE FROM wager_matches WHERE match_id='live-match'")
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM wager_matches').fetchone()[0],2)

    def test_pending_team_wall_and_orphan_mine_leases_block(self):
        for table in ('team_ranked_matches','wall_ranked_matches'):
            with self.subTest(table=table):
                self.db.execute('INSERT INTO '+table+" VALUES ('live-match','pending')")
                with self.assertRaises(RuntimeError):release.require_city_safe(self.city(),True)
                self.db.execute('DELETE FROM '+table)
        self.db.execute("INSERT INTO mine_claim_leases VALUES ('orphan')")
        with self.assertRaises(RuntimeError):release.require_city_safe(self.city(),True)

    def test_missing_authoritative_table_fails_closed(self):
        self.db.execute('DROP TABLE battle_checkpoint_members')
        with self.assertRaises(RuntimeError):release.durable_state(self.db)

    def test_settled_extraction_in_stop_gap_is_rejected_before_code_update(self):
        self.db.execute('CREATE TABLE crystal_extractions(match_id TEXT,account TEXT,amount INTEGER)')
        before=release.settlement_boundary(self.db)
        release.require_settlement_unchanged(before,release.settlement_boundary(self.db))
        self.db.execute("INSERT INTO crystal_extractions VALUES ('gap-match','synthetic-account',2500)")
        # A graceful shutdown may remove the checkpoint; receipts still expose
        # the race even when all current durable bindings now look empty.
        release.require_durable_idle(release.durable_state(self.db))
        with self.assertRaises(RuntimeError):
            release.require_settlement_unchanged(before,release.settlement_boundary(self.db))

    def entries(self):
        folder=release.FOLDER/'runtime-native-lobby-departure/runtime'
        return {name:dict(before=values[0],after=values[1],
            content=base64.b64encode((folder/name).read_bytes()).decode('ascii'))
            for name,values in release.SOURCES.items()}

    def test_exact_two_file_revision_and_changed_source_rejected(self):
        entries=self.entries();release.validate_sources(entries)
        changed=copy.deepcopy(entries)
        name='server/wager_arena.py'
        raw=base64.b64decode(changed[name]['content'])+b'\n'
        changed[name]['content']=base64.b64encode(raw).decode('ascii')
        with self.assertRaises(ValueError):release.validate_sources(changed)
        entries['server/multi.py']=copy.deepcopy(entries[name])
        with self.assertRaises(ValueError):release.validate_sources(entries)

    def test_remote_program_preserves_database_snapshot_and_rollback_boundaries(self):
        old=established.program(release.SOURCES);new=release.program()
        for start,end in (('def fingerprint(path):','def idle_rows():'),
                          ("    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as source,closing", '    for name,raw in sorted(candidate.items()):'),
                          ('    for name in reversed(applied):','    raise\n')):
            before=old[old.index(start):old.index(end,old.index(start))]
            after=new[new.index(start):new.index(end,new.index(start))]
            if start=='def fingerprint(path):':
                after=after[:after.index('EMPTY_TABLES=')]
            self.assertEqual(before,after)
        self.assertIn("    idle_rows()\n    with closing(sqlite3.connect(dbpath.as_uri()",new)
        self.assertIn("if fingerprint(dbpath)!=before:raise RuntimeError('Database changed during preflight')",new)
        self.assertIn("if any(after.get(n)!=entry for n,entry in before.items()):",new)
        self.assertNotIn('shutil.copy2(backup/\'reservation.sqlite3\'',new)
        compile(release.inspector(),'readonly-inspector','exec')

    def test_full_fingerprint_catches_credentials_save_and_wallet_changes(self):
        code=established.program(release.SOURCES)
        fragment=code[code.index('def fingerprint(path):'):code.index('def idle_rows():')]
        namespace={'closing':closing,'sqlite3':sqlite3,'hashlib':hashlib}
        exec(fragment,namespace)
        with tempfile.TemporaryDirectory(prefix='tio-maintenance-guard-') as name:
            path=Path(name)/'synthetic.sqlite3'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE accounts(name TEXT,password_hash TEXT)')
                db.execute('CREATE TABLE owned_pets(account TEXT,health INTEGER,level INTEGER)')
                db.execute('CREATE TABLE wallets(account TEXT,credits INTEGER)')
                db.execute("INSERT INTO accounts VALUES ('synthetic-account','opaque-hash')")
                db.execute("INSERT INTO owned_pets VALUES ('synthetic-account',85,1)")
                db.execute("INSERT INTO wallets VALUES ('synthetic-account',3000)")
            before=namespace['fingerprint'](path)
            self.assertEqual(namespace['fingerprint'](path),before)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute("UPDATE accounts SET password_hash='changed'")
                db.execute('UPDATE owned_pets SET health=84')
                db.execute('UPDATE wallets SET credits=2750')
            after=namespace['fingerprint'](path)
            self.assertEqual({n for n in before if before[n]!=after[n]},set(before))


if __name__=='__main__':unittest.main()
