"""Disposable account/clan fixtures only; no hosted grants or admin accounts."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3,struct,unittest
from tests import test_alliances as fixtures
from tio.alliances import AlliancesStore,AllianceRejected,alliance_for_clan,alliance_crest_id
from tio.clans import ClanRejected,CREST
from tio.clan_benefits import set_crest,crest_content
from tio.db_transaction import transaction


def bmp(color=7):return b'BM'+struct.pack('<III',822,0,54)+struct.pack('<IiiHHIIiiII',40,16,16,1,24,0,768,0,0,0,0)+bytes([color])*768


class AllianceCrestTests(unittest.TestCase):
    setUp=fixtures.AllianceTests.setUp
    create=fixtures.AllianceTests.create
    join=fixtures.AllianceTests.join
    funds=fixtures.AllianceTests.funds
    rows=fixtures.AllianceTests.rows

    def read(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def test_only_current_head_of_leading_clan_can_change_even_with_delegated_crest(self):
        self.create();self.join();self.clans.permissions('alice',self.clans.info('member')['member_id'],CREST,1)
        for actor in ('bob','member','carol'):
            before=self.rows()
            with self.assertRaises(ClanRejected):self.store.set_crest(actor,bmp(),'denied-'+actor)
            self.assertEqual(before,self.rows())
        self.clans.transfer_leader('alice',b'Member')
        with self.assertRaises(ClanRejected):self.store.set_crest('alice',bmp(),'old-head')
        first=self.store.set_crest('member',bmp(),'new-head');self.assertEqual(first['charged'],1000)

    def test_personal_cost_durable_replay_identical_remove_and_old_blob_immutable(self):
        self.create();before=self.read('SELECT * FROM wallets ORDER BY account');treasury=self.funds('alice')
        first=self.store.set_crest('alice',bmp(),'install1');self.assertEqual(first['charged'],1000)
        self.assertEqual(first,AlliancesStore(self.path).set_crest('alice',bmp(),'install1'))
        same=self.store.set_crest('alice',bmp(),'install2');self.assertEqual(same['charged'],0)
        self.assertEqual(self.funds('alice'),treasury)
        after=self.read('SELECT * FROM wallets ORDER BY account');self.assertEqual(dict((r[0],r[1]) for r in before)['alice']-dict((r[0],r[1]) for r in after)['alice'],1000)
        self.assertEqual([r for r in before if r[0]!='alice'],[r for r in after if r[0]!='alice'])
        remove=self.store.set_crest('alice',None,'remove1');self.assertEqual(remove,dict(alliance_id=self.aid,crest_id=0,charged=0));self.assertEqual(self.store.info('alice')['crest_id'],0)
        self.assertEqual(remove,self.store.set_crest('alice',None,'remove1'))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(crest_content(db,first['crest_id']),bmp())
        restored=self.store.set_crest('alice',bmp(),'restore1');self.assertEqual(restored['crest_id'],first['crest_id']);self.assertEqual(restored['charged'],1000)
        with self.assertRaises(ClanRejected):self.store.set_crest('alice',None,'restore1')

    def test_global_namespace_and_typed_pointer_do_not_confuse_clan_alliance_same_ids(self):
        self.create()
        with transaction(self.path) as db:clan=set_crest(db,'alice',bmp(),'clan1')
        ally=self.store.set_crest('alice',bmp(),'ally1');self.assertNotEqual(clan['crest_id'],ally['crest_id'])
        rows=self.read('SELECT id,clan_id FROM clan_crest_blobs ORDER BY id');self.assertEqual(rows,[(clan['crest_id'],self.ids['alice']),(ally['crest_id'],-self.aid)])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(crest_content(db,clan['crest_id']),crest_content(db,ally['crest_id']));self.assertEqual(alliance_for_clan(db,self.ids['alice'])['crest_id'],ally['crest_id'])
        with transaction(self.path) as db:db.execute('UPDATE alliance_crests SET crest_id=? WHERE alliance_id=?',(clan['crest_id'],self.aid))
        before=self.read('SELECT * FROM wallets')
        with closing(sqlite3.connect(self.path)) as db:
            with self.assertRaises(AllianceRejected):alliance_crest_id(db,self.aid)
        with self.assertRaises(AllianceRejected):self.store.set_crest('alice',bmp(9),'typed-corruption')
        self.assertEqual(before,self.read('SELECT * FROM wallets'))

    def test_leading_clan_transfer_retains_image_and_changes_mutation_authority(self):
        self.create();self.join();first=self.store.set_crest('alice',bmp(),'before-transfer')
        self.store.transfer_leading('alice',self.ids['bob']);self.assertEqual(self.store.info('alice')['crest_id'],first['crest_id'])
        with self.assertRaises(ClanRejected):self.store.set_crest('alice',None,'old-leading')
        remove=self.store.set_crest('bob',None,'new-leading');self.assertEqual(remove['charged'],0)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(crest_content(db,first['crest_id']),bmp())

    def test_pending_dissolution_and_revoked_rights_block_replay_and_remove(self):
        self.create();first=self.store.set_crest('alice',bmp(),'active');self.store.dissolve('alice')
        for raw,identity in ((bmp(),'active'),(None,'remove-pending')):
            with self.assertRaises(ClanRejected):self.store.set_crest('alice',raw,identity)
        self.assertEqual(self.store.info('alice')['crest_id'],first['crest_id']);self.store.restore('alice')
        self.assertEqual(self.store.set_crest('alice',bmp(),'active'),first)

    def test_concurrent_same_request_creates_one_charge_receipt_and_audit(self):
        self.create();before=self.read("SELECT credits FROM wallets WHERE account='alice'")[0][0]
        with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda _:self.store.set_crest('alice',bmp(),'concurrent'),range(4)))
        self.assertTrue(all(r==rows[0] for r in rows));self.assertEqual(before-self.read("SELECT credits FROM wallets WHERE account='alice'")[0][0],1000)
        self.assertEqual(self.read("SELECT COUNT(*) FROM alliance_ledger WHERE operation='crest'"),[(1,)])
        self.assertEqual(self.read("SELECT COUNT(*) FROM clan_benefit_receipts WHERE operation='alliance_crest'"),[(1,)])

    def test_insufficient_funds_and_invalid_bitmap_do_not_spend_but_remove_is_free(self):
        self.create();first=self.store.set_crest('alice',bmp(),'first')
        with transaction(self.path) as db:db.execute("UPDATE wallets SET credits=0 WHERE account='alice'")
        self.assertEqual(self.store.set_crest('alice',bmp(),'identical')['charged'],0)
        for raw in (bmp(9),b'bad',bmp()+b'x',bmp()[:22]+struct.pack('<i',-16)+bmp()[26:]):
            with self.assertRaises(ClanRejected):self.store.set_crest('alice',raw,'rejected')
        self.assertEqual(self.store.info('alice')['crest_id'],first['crest_id']);self.assertEqual(self.store.set_crest('alice',None,'remove')['charged'],0)

    def test_outer_and_audit_failures_roll_back_blob_pointer_debit_and_receipt(self):
        self.create();before=self.rows()
        with self.assertRaises(RuntimeError):
            with transaction(self.path):self.store.set_crest('alice',bmp(),'rollback');raise RuntimeError('Outer fixture rollback')
        self.assertEqual(before,self.rows())
        with transaction(self.path) as db:db.execute("CREATE TRIGGER rejectcrest BEFORE INSERT ON alliance_ledger WHEN NEW.operation='crest' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before=self.rows()
        with self.assertRaises(sqlite3.IntegrityError):self.store.set_crest('alice',bmp(),'fault')
        self.assertEqual(before,self.rows())


if __name__=='__main__':unittest.main()
