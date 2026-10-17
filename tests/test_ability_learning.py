from wallet_fixture import fund_wallet
import json,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import closing
from tio.ability_learning import AbilityLearning
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.pet_info import PetInfo,SCHEMAS,decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.protocol.abilities import decode_abilities,encode_ability_request

ROOT=Path(__file__).resolve().parents[1]

class AbilityLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.db'
        self.service=AbilityLearning.from_workspace(self.path,ROOT)
        data=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        pet=bytes.fromhex(data['packet_hex']);fields=decode_pet_info(pet,human_equipment=True).fields
        dogfields={**fields,'0x8c43eb':2,'0x8c446f':3,'0x8c4aef':8}
        dogfields={k:dogfields.get(k,0) for k,_,_ in SCHEMAS[(False,bool(fields['0x6d0203']),bool(fields['0x8c4565']))]}
        for account in ('alice','bob'):
            OwnedPetStore(self.path).ensure(account,pet,encode_item_list(1,()),human=True)
            fund_wallet(self.path, account, credits=10_000, gold=10_000)
        OwnedPetStore(self.path).ensure('alice',encode_pet_info(PetInfo(False,dogfields)),encode_item_list(2,()),human=False)

    def credits(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute("SELECT credits FROM wallets WHERE account='alice'").fetchone()[0]

    def test_human_level_gate_and_dog_consecutive_ranks(self):
        for owner,ability in ((1,1),(2,23)):
            replies=self.service.lists('alice',owner)
            available=decode_abilities(replies[1])[1]
            self.assertIn(ability,{e.ability_id for e in available})
            self.assertNotIn(23 if owner==1 else 1,{e.ability_id for e in available})
            result=self.service.handle('alice',encode_ability_request(owner,ability))
            self.assertEqual(decode_abilities(result[0])[1][0].level,1)
            if owner==1:
                with self.assertRaises(ValueError):self.service.handle('alice',encode_ability_request(owner,ability))
        self.assertEqual(self.credits(),9800)
        reopened=AbilityLearning.from_workspace(self.path,ROOT)
        self.assertEqual(decode_abilities(reopened.lists('alice',2)[0])[1][0].ability_id,23)
        self.assertEqual(decode_abilities(reopened.lists('bob',1)[0])[1],())
        for level in (2,3,4):
            self.assertEqual(decode_abilities(reopened.learn('alice',2,23)[0])[1][0].level,level)
        reopened.lists('alice',2)
        with self.assertRaises(ValueError):reopened.learn('alice',2,23)

    def test_ownership_species_and_unquoted_request(self):
        for account,owner,ability in [('bob',2,23),('alice',1,1)]:
            with self.assertRaises(ValueError):self.service.learn(account,owner,ability)
        self.service.lists('alice',1)
        with self.assertRaises(ValueError):self.service.learn('alice',1,23)
        with self.assertRaises(ValueError):self.service.handle('alice',encode_ability_request(1,1,opcode=0x90))
        self.assertEqual(self.credits(),10000)

    def test_human_can_buy_four_ranks_with_one_tree_request(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            packet=db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
            pet=decode_pet_info(packet,human_equipment=True);pet.fields['0x8c4aef']=4
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",(encode_pet_info(pet),))
        self.service.handle('alice',b'\xa9\1\0\0\0')
        for rank in range(1,5):
            replies=self.service.handle('alice',encode_ability_request(1,1))
            self.assertEqual(decode_abilities(replies[0])[1][0].level,rank)
            self.assertEqual(replies[1][0],0xaa)
            self.assertEqual(self.credits(),10000-100*rank)
        with self.assertRaises(ValueError):self.service.handle('alice',encode_ability_request(1,1))
        self.assertEqual(self.credits(),9600)

    def test_insufficient_funds_and_rollback(self):
        self.service.lists('alice',1)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=99 WHERE account='alice'")
        with self.assertRaises(ValueError):self.service.learn('alice',1,1)
        self.assertEqual(self.credits(),99)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=10000 WHERE account='alice'")
            db.execute("CREATE TRIGGER reject_skill BEFORE INSERT ON ability_states BEGIN SELECT RAISE(ABORT,'failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.service.learn('alice',1,1)
        self.assertEqual(self.credits(),10000)
        self.assertEqual(self.service.state.read('alice',1),(0,()))

    def test_stale_second_session(self):
        second=AbilityLearning.from_workspace(self.path,ROOT)
        self.service.lists('alice',1);second.lists('alice',1)
        self.service.learn('alice',1,1)
        with self.assertRaises(ValueError):second.learn('alice',1,1)
        self.assertEqual(self.credits(),9900)

    def test_manual_human_mastery_and_critical_level_gates(self):
        self.assertNotIn(10,{e.ability_id for e in decode_abilities(self.service.lists('alice',1)[1])[1]})
        def level(value):
            with closing(sqlite3.connect(self.path)) as db,db:
                packet=db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
                pet=decode_pet_info(packet,human_equipment=True);pet.fields['0x8c4aef']=value
                db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",(encode_pet_info(pet),))
            self.service.lists('alice',1)
        level(3)
        self.service.learn('alice',1,10)
        with self.assertRaises(ValueError):self.service.learn('alice',1,10)
        self.service.learn('alice',1,4);self.service.learn('alice',1,4)
        with self.assertRaises(ValueError):self.service.learn('alice',1,4)
        level(4);self.service.learn('alice',1,4)
        with self.assertRaises(ValueError):self.service.learn('alice',1,4)
        level(5);self.service.learn('alice',1,10)
        level(7);self.service.learn('alice',1,4)
