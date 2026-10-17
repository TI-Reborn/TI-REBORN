import json,sqlite3,tempfile,unittest
from contextlib import closing
from pathlib import Path
from tio.abilities import AbilityCatalog,AbilityLevel
from tio.ability_state import AbilityStateStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.abilities import AbilityEntry


class AbilityStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db'
        self.catalog=AbilityCatalog([AbilityLevel(23,1,{'name':'Dog Cure','levels':'4'}),AbilityLevel(23,2,{'name':'Dog Cure','levels':'4'})])
        self.store=AbilityStateStore(self.path,self.catalog)
        data=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        for account in ('alice','bob'):
            OwnedPetStore(self.path).ensure(account,bytes.fromhex(data['packet_hex']),bytes.fromhex(data['inventory_packet_hex']),human=True)
        self.entry=AbilityEntry(23,1,0x87654321,1)

    def test_reopen_isolation_and_stale_update(self):
        self.assertEqual(self.store.read('alice',1),(0,()))
        self.assertEqual(self.store.replace('alice',1,[self.entry],expected_revision=0),1)
        reopened=AbilityStateStore(self.path,self.catalog)
        self.assertEqual(reopened.read('alice',1),(1,(self.entry,)))
        self.assertEqual(reopened.read('bob',1),(0,()))
        with self.assertRaises(ValueError):reopened.replace('alice',1,[],expected_revision=0)
        self.assertEqual(reopened.read('alice',1),(1,(self.entry,)))
        self.assertEqual(reopened.replace('alice',1,[],expected_revision=1),2)
        self.assertEqual(reopened.read('alice',1),(2,()))

    def test_invalid_actor_and_level_do_not_write(self):
        for account,owner,entries in [('missing',1,[self.entry]),('alice',2,[self.entry]),('alice',1,[self.entry,self.entry]),('alice',1,[AbilityEntry(23,3,0,1)])]:
            with self.assertRaises(ValueError):self.store.replace(account,owner,entries,expected_revision=0)
        self.assertEqual(self.store.read('alice',1),(0,()))

    def test_failed_write_preserves_snapshot(self):
        self.store.replace('alice',1,[self.entry],expected_revision=0)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_ability_update BEFORE UPDATE ON ability_states BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.replace('alice',1,[],expected_revision=1)
        self.assertEqual(self.store.read('alice',1),(1,(self.entry,)))
