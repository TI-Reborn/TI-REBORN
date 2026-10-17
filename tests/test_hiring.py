from wallet_fixture import fund_wallet
from contextlib import closing
import json,sqlite3,tempfile,unittest
from pathlib import Path
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import decode_pet_info

ROOT=Path(__file__).resolve().parents[1]


class HiringTests(unittest.TestCase):
    def test_dogs_and_replenishment(self):
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';fund_wallet(path, 'alice', credits=10_000, gold=10_000)
            store=HireStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
            for candidate in (3,4,5):
                pet,inventory,assets=store.hire('alice',candidate)
                dog=decode_pet_info(pet,human_equipment=False)
                self.assertEqual(dog.fields['0x8c446f'],candidate)
                OwnedPetStore.validate(pet,inventory,False)
                with self.assertRaises(ValueError):store.hire('alice',candidate)
            self.assertEqual(assets.credits,9700)
            reopened=HireStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
            self.assertEqual([c.candidate_id for c in reopened.available('alice')],[1,2,1003,1004,1005])
            second,_,_=reopened.hire('alice',1003)
            self.assertEqual(decode_pet_info(second,human_equipment=False).fields['0x8c43eb'],4)
            self.assertEqual(len(OwnedPetStore(path).list('alice')),4)

    def test_hire_reopen_and_duplicate(self):
        trial=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        template=bytes.fromhex(trial['packet_hex'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';fund_wallet(path, 'alice', credits=10_000, gold=10_000)
            OwnedPetStore(path).ensure('alice',template,bytes.fromhex(trial['inventory_packet_hex']),human=True)
            store=HireStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
            pet,inventory,assets=store.hire('alice',2)
            fields=decode_pet_info(pet,human_equipment=True).fields
            self.assertEqual((fields['0x8c43eb'],fields['0x8c446f'],fields['0x8c4489']),(2,2,b'Recruit 2'))
            self.assertEqual(assets.credits,9900)
            self.assertEqual(len(OwnedPetStore(path).list('alice')),2)
            self.assertEqual([c.candidate_id for c in store.available('alice')],[1,1002,3,4,5])
            self.assertEqual(len(store.available('bob')),5)
            with self.assertRaises(ValueError):store.hire('alice',2)
            with self.assertRaises(ValueError):store.hire('alice',999)
            self.assertEqual(WalletStore(path).ensure('alice').credits,9900)
            # Only owned, empty, hired recruits may be dismissed.
            with self.assertRaises(ValueError):store.dismiss('bob',2)
            with self.assertRaises(ValueError):store.dismiss('alice',1)
            with closing(sqlite3.connect(path)) as db,db:
                from tio.protocol.item_list import encode_item_list,decode_item_list
                item=decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))[1][0]
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=2',
                           (encode_item_list(2,(item,)),'alice'))
            with self.assertRaises(ValueError):store.dismiss('alice',2)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=2',(inventory,'alice'))
            self.assertEqual(store.dismiss('alice',2),b'\x65\x02\0\0\0')
            self.assertEqual(len(OwnedPetStore(path).list('alice')),1)
            self.assertEqual(WalletStore(path).ensure('alice').credits,9900)
            with self.assertRaises(ValueError):store.dismiss('alice',2)
            next_pet,_,_=store.hire('alice',1)
            self.assertEqual(decode_pet_info(next_pet,human_equipment=True).fields['0x8c43eb'],3)

    def test_no_funds_and_atomic_rollback(self):
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';fund_wallet(path, 'alice', credits=10_000, gold=10_000)
            store=HireStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE wallets SET credits=0')
            with self.assertRaises(ValueError):store.hire('alice',1)
            self.assertEqual(OwnedPetStore(path).list('alice'),())
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE wallets SET credits=10000')
                db.execute("CREATE TRIGGER deny_wallet BEFORE UPDATE ON wallets BEGIN SELECT RAISE(ABORT,'injected'); END")
            with self.assertRaises(sqlite3.IntegrityError):store.hire('alice',1)
            self.assertEqual(OwnedPetStore(path).list('alice'),())
            self.assertEqual(len(store.available('alice')),5)
