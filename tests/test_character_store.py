import tempfile
import unittest
from pathlib import Path
from tio.characters import CharacterStore,CreateRejected
from tio.protocol.character_create import CharacterCreateRequest

class CharacterStoreTests(unittest.TestCase):
    def test_reopen_and_account_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'characters.db';store=CharacterStore(path)
            request=CharacterCreateRequest(b'ProbeNew',0,(0,)*4)
            result=store.create('a',request)
            self.assertEqual(CharacterStore(path).list('a'),result)
            self.assertEqual(store.list('b'),())
            with self.assertRaises(CreateRejected) as e:store.create('b',CharacterCreateRequest(b'probenew',0,(0,)*4))
            self.assertEqual(e.exception.status,3)
            records=store.create('a',CharacterCreateRequest(b'Another',0,(0,)*4))
            self.assertEqual([(r.record_id,r.name_bytes) for r in records],[(1,b'ProbeNew'),(2,b'Another')])
            for name in (b'Third',b'Fourth',b'Fifth'):store.create('a',CharacterCreateRequest(name,0,(0,)*4))
            before=store.list('a')
            with self.assertRaises(CreateRejected) as e:store.create('a',CharacterCreateRequest(b'Sixth',0,(0,)*4))
            self.assertEqual(e.exception.status,2)
            self.assertEqual(store.list('a'),before)
    def test_rejection_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            store=CharacterStore(Path(d)/'characters.db')
            with self.assertRaises(CreateRejected) as e:store.create('a',CharacterCreateRequest(b'1',0,(0,)*4))
            self.assertEqual(e.exception.status,4)
            with self.assertRaises(CreateRejected):store.create('a',CharacterCreateRequest(b'Probe',7,(0,)*4))
            self.assertEqual(store.list('a'),())
