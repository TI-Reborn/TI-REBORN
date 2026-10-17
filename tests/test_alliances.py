"""Real local account/clan stores, transaction races and manual alliance costs.

Treasury/level provisioning below is explicitly a disposable test fixture. The
runtime never creates accounts/clans or grants balances, and no VPS is accessed.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from server.accounts import Accounts
from tio.alliances import (AlliancesStore,AllianceRejected,alliance_for_clan,configured_member,
                          warfare_locked,COOLDOWN,INVITE_TTL,MAX_U32)
from tio.clans import ClansStore,ClanRejected,KNOWN_RIGHTS
from tio.db_transaction import connect,transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.wallets import WalletStore


class AllianceTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.path=Path(directory.name)/'alliances.sqlite3';self.now=1000.
        trial=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        pet=decode_pet_info(bytes.fromhex(trial['packet_hex']),human_equipment=True);pet.fields['0x8c4aef']=4
        self.pets=OwnedPetStore(self.path)
        with patch('server.accounts.ITERATIONS',1000):
            for account in ('alice','bob','carol','dave','member'):
                Accounts(self.path).create(account,'LocalAllianceFixtureOnly',character=account.title())
                self.pets.ensure(account,encode_pet_info(pet),encode_item_list(1,()),human=True)
                WalletStore(self.path).ensure(account)
        self.clans=ClansStore(self.path)
        self.ids={a:self.clans.create(a,name) for a,name in zip(('alice','bob','carol','dave'),(b'Alpha',b'Beta',b'Gamma',b'Delta'))}
        self.clans.invite('alice',b'Member');self.clans.accept('member',1)
        with closing(connect(self.path)) as db,db:
            db.execute('UPDATE clans SET level=1,credits=500000,influence=100000')
        self.store=AlliancesStore(self.path,clock=lambda:self.now)

    def create(self):
        self.aid=self.store.create('alice',b'Alliance One');return self.aid

    def join(self,account='bob'):
        self.store.invite('alice',self.ids[account]);return self.store.accept(account,1)

    def funds(self,account):
        with closing(connect(self.path)) as db:
            return db.execute('SELECT credits,influence FROM clans WHERE id=?',(self.ids[account],)).fetchone()

    def rows(self):
        with closing(connect(self.path)) as db:
            return {n:tuple(db.execute('SELECT * FROM "'+n+'" ORDER BY rowid'))
                for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")}

    def lock(self,account):
        with closing(connect(self.path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS warfare_clan_locks(clan_id INTEGER PRIMARY KEY,event_id TEXT NOT NULL)')
            db.execute('INSERT INTO warfare_clan_locks VALUES (?,?)',(self.ids[account],'real-owned-war-event-fixture'))

    def test_additive_initialization_preserves_existing_accounts_saves_and_assets(self):
        before=self.rows();AlliancesStore(self.path)
        self.assertEqual(before,self.rows())
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM alliances').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],5)

    def test_manual_costs_from_clan_treasury_and_aggregate_rating_without_mint(self):
        with closing(connect(self.path)) as db:
            wallets=tuple(db.execute('SELECT * FROM wallets ORDER BY account'))
        aid=self.create();self.assertEqual(self.join(),aid)
        self.assertEqual(self.funds('alice'),(450000,90000));self.assertEqual(self.funds('bob'),(475000,95000))
        info=self.store.info('bob');self.assertEqual((info['leader'],info['level'],info['influence']),('alice',1,185000))
        with closing(connect(self.path)) as db:
            active=alliance_for_clan(db,self.ids['bob'])
            self.assertEqual(active['clans'],(self.ids['alice'],self.ids['bob']));self.assertEqual(active['influence'],185000)
        self.store.upgrade('alice');self.assertEqual(self.funds('alice'),(350000,70000))
        self.assertEqual(self.store.info('alice')['level'],2)
        with closing(connect(self.path)) as db:
            self.assertEqual(wallets,tuple(db.execute('SELECT * FROM wallets ORDER BY account')))
            details=[json.loads(r[0]) for r in db.execute('SELECT detail FROM alliance_ledger WHERE operation IN (\'create\',\'join\',\'upgrade\') ORDER BY id')]
            self.assertEqual([d['charge']['credits'] for d in details],[50000,25000,100000])
            self.assertEqual([d['charge']['influence'] for d in details],[10000,5000,20000])

    def test_leader_only_level_gate_and_no_right_mask_elevation(self):
        self.clans.permissions('alice',self.clans.info('member')['member_id'],KNOWN_RIGHTS,1)
        with self.assertRaises(ClanRejected):self.store.create('member',b'Unauthorized')
        with closing(connect(self.path)) as db,db:db.execute('UPDATE clans SET level=0 WHERE id=?',(self.ids['alice'],))
        before=self.rows()
        with self.assertRaises(AllianceRejected):self.store.create('alice',b'Underlevel')
        self.assertEqual(before,self.rows())

    def test_current_leading_clan_head_changes_automatically_and_old_invite_is_revoked(self):
        self.create();self.store.invite('alice',self.ids['bob'])
        self.clans.transfer_leader('alice',b'Member')
        self.assertEqual(self.store.info('alice')['leader'],'member')
        before=self.funds('bob')
        with self.assertRaises(ClanRejected):self.store.accept('bob',1)
        with self.assertRaises(ClanRejected):self.store.upgrade('alice')
        self.assertEqual(before,self.funds('bob'))
        self.store.upgrade('member');self.assertEqual(self.store.info('member')['level'],2)

    def test_transfer_leading_clan_rechecks_current_head_and_roster_without_new_fees(self):
        self.create();self.join();before=[self.funds(a) for a in ('alice','bob')]
        for account,target in (('bob','bob'),('member','bob'),('alice','carol'),('alice','alice')):
            state=self.rows()
            with self.assertRaises(ClanRejected):self.store.transfer_leading(account,self.ids[target])
            self.assertEqual(state,self.rows())
        self.store.transfer_leading('alice',self.ids['bob'])
        info=self.store.info('alice')
        self.assertEqual((info['leading_clan'],info['leader'],info['clans']),
            (self.ids['bob'],'bob',(self.ids['bob'],self.ids['alice'])))
        self.assertEqual(before,[self.funds(a) for a in ('alice','bob')])
        with self.assertRaises(ClanRejected):self.store.upgrade('alice')
        self.store.upgrade('bob');self.assertEqual(self.funds('bob'),(375000,75000))
        self.store.leave('alice');self.assertEqual(self.store.info('bob')['leader'],'bob')

    def test_transfer_leading_clan_respects_warfare_and_rolls_back_on_audit_failure(self):
        self.create();self.join();self.lock('bob');before=self.rows()
        with self.assertRaises(AllianceRejected):self.store.transfer_leading('alice',self.ids['bob'])
        self.assertEqual(before,self.rows())
        with closing(connect(self.path)) as db,db:
            db.execute('DELETE FROM warfare_clan_locks')
            db.execute("CREATE TRIGGER fail_transfer_audit BEFORE INSERT ON alliance_ledger WHEN NEW.operation='transfer_leading' BEGIN SELECT RAISE(ABORT,'test audit failure'); END")
        before=self.rows()
        with self.assertRaises(sqlite3.IntegrityError):self.store.transfer_leading('alice',self.ids['bob'])
        self.assertEqual(before,self.rows())

    def test_acceptance_rechecks_expiry_level_funds_and_does_not_charge_on_refusal(self):
        self.create();self.store.invite('alice',self.ids['bob']);self.now+=INVITE_TTL
        before=self.rows()
        with self.assertRaises(AllianceRejected):self.store.accept('bob',1)
        self.assertEqual(before,self.rows())
        self.store.invite('alice',self.ids['bob'])
        with closing(connect(self.path)) as db,db:db.execute('UPDATE clans SET level=0 WHERE id=?',(self.ids['bob'],))
        before=self.rows()
        with self.assertRaises(AllianceRejected):self.store.accept('bob',1)
        self.assertEqual(before,self.rows())
        with closing(connect(self.path)) as db,db:db.execute('UPDATE clans SET level=1 WHERE id=?',(self.ids['bob'],))
        with closing(connect(self.path)) as db,db:db.execute('UPDATE clans SET credits=24999 WHERE id=?',(self.ids['bob'],))
        before=self.rows()
        with self.assertRaises(AllianceRejected):self.store.accept('bob',1)
        self.assertEqual(before,self.rows())
        self.assertEqual(self.store.accept('bob',0),0);self.assertEqual(self.funds('bob'),(24999,100000))

    def test_concurrent_acceptances_fill_one_slot_once_without_overbooking(self):
        self.create();self.store.invite('alice',self.ids['bob']);self.store.invite('alice',self.ids['carol'])
        def accept(account):
            try:self.store.accept(account,1);return True
            except ClanRejected:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(accept,('bob','carol'))),[False,True])
        self.assertEqual(len(self.store.info('alice')['clans']),2)
        self.assertEqual(sum(self.funds(a)[0] for a in ('bob','carol')),975000)
        with closing(connect(self.path)) as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM alliance_ledger WHERE operation='join'").fetchone()[0],1)

    def test_one_alliance_per_clan_and_three_slots_at_level_two(self):
        self.create();self.join();self.store.upgrade('alice');self.join('carol')
        self.assertEqual(len(self.store.info('alice')['clans']),3)
        with self.assertRaises(AllianceRejected):self.store.invite('alice',self.ids['dave'])
        with self.assertRaises(AllianceRejected):self.store.create('bob',b'Duplicate Affiliation')
        self.assertEqual(self.funds('bob'),(475000,95000))

    def test_leave_kick_cooldown_no_refund_and_leading_clan_cannot_leave(self):
        self.create();self.join();before=self.funds('bob')
        self.store.leave('bob');self.assertEqual(self.funds('bob'),before)
        self.assertIsNone(self.store.info('bob'))
        with self.assertRaises(AllianceRejected):self.store.create('bob',b'Cooldown Bypass')
        with self.assertRaises(AllianceRejected):self.store.invite('alice',self.ids['bob'])
        with self.assertRaises(AllianceRejected):self.store.leave('alice')
        self.now+=COOLDOWN;self.join();self.store.kick('alice',self.ids['bob'])
        with self.assertRaises(AllianceRejected):self.store.create('bob',b'Kick Bypass')

    def test_dissolution_restore_keeps_same_identity_name_roster_and_spends_nothing(self):
        aid=self.create();self.join();before=[self.funds(a) for a in ('alice','bob')]
        self.store.dissolve('alice');pending=self.store.info('bob')
        self.assertEqual(pending['state'],'dissolving')
        with closing(connect(self.path)) as db:
            self.assertIsNone(alliance_for_clan(db,self.ids['bob']))
            self.assertTrue(configured_member(db,self.ids['bob'],now=self.now))
        with self.assertRaises(AllianceRejected):self.store.restore('bob')
        self.now+=COOLDOWN-1;self.store.restore('alice')
        info=self.store.info('bob');self.assertEqual((info['id'],info['name'],info['clans']),(aid,b'Alliance One',(self.ids['alice'],self.ids['bob'])))
        self.assertEqual(before,[self.funds(a) for a in ('alice','bob')])
        self.store.leave('bob')  # Restoring clears only this dissolution cooldown.

    def test_expiry_prevents_restore_and_new_identity_is_monotonic(self):
        first=self.create();self.join();self.store.dissolve('alice');self.now+=COOLDOWN
        self.assertIsNone(self.store.info('bob'))
        with self.assertRaises(AllianceRejected):self.store.restore('alice')
        second=self.store.create('alice',b'Alliance One');self.assertGreater(second,first)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT state FROM alliances WHERE id=?',(first,)).fetchone(),('dissolved',))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM alliance_ledger WHERE alliance_id=?',(first,)).fetchone()[0],5)

    def test_duplicate_actions_never_repeat_fees_or_refunds(self):
        self.create();self.join();self.store.upgrade('alice');before=self.rows()
        for action in (lambda:self.store.create('alice',b'Alliance One'),lambda:self.store.accept('bob',1),lambda:self.store.upgrade('alice')):
            with self.assertRaises(ClanRejected):action()
            self.assertEqual(before,self.rows())

    def test_audit_failure_rolls_back_fees_membership_revision_and_sequence(self):
        with closing(connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER fail_alliance_audit BEFORE INSERT ON alliance_ledger BEGIN SELECT RAISE(ABORT,'test audit failure'); END")
        before=self.rows()
        with self.assertRaises(sqlite3.IntegrityError):self.create()
        self.assertEqual(before,self.rows())

    def test_audit_is_immutable_and_store_joins_outer_gameplay_transaction(self):
        self.create()
        with closing(connect(self.path)) as db,db:
            for sql in ('DELETE FROM alliance_ledger','UPDATE alliance_ledger SET actor=\'tamper\''):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)
        before=self.rows()
        with self.assertRaises(RuntimeError):
            with transaction(self.path):self.join();raise RuntimeError('Rollback enclosing native action')
        self.assertEqual(before,self.rows())

    def test_id_and_revision_overflow_fail_atomically_and_rating_keeps_full_sum(self):
        with closing(connect(self.path)) as db,db:
            db.execute("INSERT INTO sqlite_sequence(name,seq) VALUES ('alliances',?)",(MAX_U32,))
        before=self.rows()
        with self.assertRaises(AllianceRejected):self.create()
        self.assertEqual(before,self.rows())
        with closing(connect(self.path)) as db,db:db.execute("DELETE FROM sqlite_sequence WHERE name='alliances'")
        self.create();self.join()
        with closing(connect(self.path)) as db,db:
            db.execute('UPDATE clans SET influence=?',(MAX_U32,))
            db.execute('UPDATE alliances SET revision=? WHERE id=?',(MAX_U32,self.aid))
        self.assertEqual(self.store.info('alice')['influence'],2*MAX_U32)
        before=self.rows()
        with self.assertRaises(AllianceRejected):self.store.upgrade('alice')
        self.assertEqual(before,self.rows())

    def test_warfare_cohort_and_target_locks_block_affiliation_changes(self):
        self.create();self.join();self.lock('bob');before=self.rows()
        with closing(connect(self.path)) as db:self.assertTrue(warfare_locked(db,(self.ids['bob'],)))
        for action in (lambda:self.store.leave('bob'),lambda:self.store.kick('alice',self.ids['bob']),
                       lambda:self.store.dissolve('alice'),lambda:self.store.upgrade('alice'),lambda:self.store.invite('alice',self.ids['carol']),
                       lambda:self.store.transfer_leading('alice',self.ids['bob'])):
            with self.assertRaises(AllianceRejected):action()
            self.assertEqual(before,self.rows())
        with closing(connect(self.path)) as db,db:db.execute('DELETE FROM warfare_clan_locks')
        self.store.upgrade('alice');self.store.invite('alice',self.ids['carol']);self.lock('carol');before=self.rows()
        with self.assertRaises(AllianceRejected):self.store.accept('carol',1)
        self.assertEqual(before,self.rows())


if __name__=='__main__':unittest.main()
