from contextlib import closing
from dataclasses import replace
import json,sqlite3,tempfile,unittest
from pathlib import Path

from tio.ability_progression import AbilityProgression,decrease
from tio.owned_pets import OwnedPetStore
from tio.roster_progression import profile
from tio.wallets import WalletStore
from tio.protocol.abilities import encode_ability_request,decode_abilities
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.protocol.proficiency_decrease import (ProficiencyDecrease,encode_proficiency_decrease,
    decode_proficiency_decrease,parse_command)
from tio.weapon_proficiency import SAVED,BASE,number,bits

ROOT=Path(__file__).resolve().parents[1]


class AbilityProgressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'players.db'
        self.store=AbilityProgression.from_workspace(self.path,ROOT)
        self.template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        owned=OwnedPetStore(self.path)
        for account,name in (('alice',b'Alice Prime'),('bob',b'Bob Prime')):
            raw=profile(self.template,1,1,name)
            pet=decode_pet_info(raw,human_equipment=True)
            raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4}))
            owned.ensure(account,raw,encode_item_list(1,()),human=True)
            WalletStore(self.path).ensure(account)
            with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE wallets SET credits=20000 WHERE account=?',(account,))
        owned.ensure('alice',profile(self.template,2,3,b'Rex'),encode_item_list(2,()),human=False)

    def credits(self,account='alice'):return WalletStore(self.path).ensure(account).credits

    def raw(self,account='alice',identity=1):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,identity)).fetchone()[0]

    def learn(self,ability=1,ranks=1):
        self.store.lists('alice',1)
        for _ in range(ranks):self.store.handle('alice',encode_ability_request(1,ability))

    def test_native_90_forgets_all_ranks_once_and_requotes(self):
        self.learn(ranks=3);before=self.credits()
        learned=decode_abilities(self.store.lists('alice',1)[0])[1]
        self.assertEqual(learned[0].unknown_u32,300)
        replies=self.store.handle('alice',encode_ability_request(1,1,opcode=0x90))
        self.assertEqual([p[0] for p in replies],[0x80,0xaa,0xc8,0x66])
        self.assertEqual(decode_abilities(replies[0])[1],())
        self.assertEqual(self.credits(),before-300);self.assertEqual(self.credits('bob'),20000)
        with self.assertRaises(ValueError):self.store.handle('alice',encode_ability_request(1,1,opcode=0x90))
        self.assertEqual(self.credits(),before-300)
        self.store.handle('alice',encode_ability_request(1,1))
        self.assertEqual(self.store.state.read('alice',1)[1][0].level,1)

    def test_native_tree_and_my_perks_query_offer_forget_price(self):
        self.learn();second=AbilityProgression.from_workspace(self.path,ROOT)
        replies=second.handle('alice',b'\xc8\x12\1\0\0\0')
        self.assertEqual(decode_abilities(replies[0])[1][0].unknown_u32,100)
        second.handle('alice',encode_ability_request(1,1,opcode=0x90))
        self.assertEqual(second.state.read('alice',1)[1],())

    def test_unquoted_stale_or_foreign_forget_cannot_charge(self):
        self.learn();second=AbilityProgression.from_workspace(self.path,ROOT)
        with self.assertRaises(ValueError):second.forget('alice',1,1)
        second.tree('alice',1);self.store.learn('alice',1,1);before=self.credits()
        with self.assertRaises(ValueError):second.forget('alice',1,1)
        with self.assertRaises(ValueError):self.store.forget('bob',1,1)
        with self.assertRaises(ValueError):self.store.forget('bob',2,23)
        self.assertEqual(self.credits(),before)

    def test_forgetting_health_bonus_clamps_without_healing_and_preserves_base_stats(self):
        self.learn(ranks=2)
        with closing(sqlite3.connect(self.path)) as db,db:
            raw=self.raw();pet=decode_pet_info(raw,human_equipment=True)
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",
                       (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4ab1':pet.fields['0x8c4a07']+8})),))
        replies=self.store.forget('alice',1,1)
        displayed=decode_pet_info(replies[-1],human_equipment=True).fields
        saved=decode_pet_info(self.raw(),human_equipment=True).fields
        self.assertEqual(saved['0x8c4ab1'],saved['0x8c4a07'])
        self.assertEqual(displayed['0x8c4a07'],saved['0x8c4a07'])
        self.assertEqual(number(saved[SAVED[1]]),35)

    def test_forget_storage_failure_restores_wallet_state_and_profile(self):
        self.learn();before=(self.credits(),self.store.state.read('alice',1),self.raw())
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER refuse_forget BEFORE UPDATE ON ability_states BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.forget('alice',1,1)
        self.assertEqual((self.credits(),self.store.state.read('alice',1),self.raw()),before)

    def test_native_decrease_preserves_fractional_progress_and_other_actor(self):
        pet=decode_pet_info(self.raw(),human_equipment=True)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",
                       (encode_pet_info(replace(pet,fields={**pet.fields,SAVED[1]:bits(42.25),BASE[1]:bits(42.25)})),))
        other=self.raw('bob');before=self.credits()
        replies=decrease(self.path,'alice',encode_proficiency_decrease(ProficiencyDecrease('alice prime','light')))
        changed=decode_pet_info(self.raw(),human_equipment=True).fields
        self.assertEqual(number(changed[SAVED[1]]),37.25);self.assertEqual(changed[SAVED[1]],changed[BASE[1]])
        self.assertEqual(number(changed[SAVED[0]]),35);self.assertEqual(self.raw('bob'),other)
        self.assertEqual(self.credits(),before-1000);self.assertEqual([p[0] for p in replies],[0x66,0xc8])

    def test_decrease_busy_unknown_foreign_ambiguous_or_wrong_species_rejected(self):
        packet=encode_proficiency_decrease(ProficiencyDecrease('Alice Prime','light'));before=(self.raw(),self.credits())
        with self.assertRaises(ValueError):decrease(self.path,'alice',packet,allowed=False)
        with self.assertRaises(ValueError):decrease(self.path,'bob',packet)
        with self.assertRaises(ValueError):decrease(self.path,'alice',encode_proficiency_decrease(ProficiencyDecrease('Rex','light')))
        OwnedPetStore(self.path).ensure('alice',profile(self.template,3,1,b'Alice Prime'),encode_item_list(3,()),human=True)
        with self.assertRaises(ValueError):decrease(self.path,'alice',packet)
        self.assertEqual((self.raw(),self.credits()),before)

    def test_decrease_floor_funds_and_database_failure_roll_back(self):
        packet=encode_proficiency_decrease(ProficiencyDecrease('Alice Prime','light'))
        pet=decode_pet_info(self.raw(),human_equipment=True)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",
                       (encode_pet_info(replace(pet,fields={**pet.fields,SAVED[1]:bits(4),BASE[1]:bits(4)})),))
        before=(self.raw(),self.credits())
        with self.assertRaises(ValueError):decrease(self.path,'alice',packet)
        self.assertEqual((self.raw(),self.credits()),before)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",(encode_pet_info(pet),))
            db.execute("UPDATE wallets SET credits=999 WHERE account='alice'")
        before=(self.raw(),self.credits())
        with self.assertRaises(ValueError):decrease(self.path,'alice',packet)
        self.assertEqual((self.raw(),self.credits()),before)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=5000 WHERE account='alice'")
            db.execute("CREATE TRIGGER refuse_skill BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT,'injected'); END")
        before=(self.raw(),self.credits())
        with self.assertRaises(sqlite3.IntegrityError):decrease(self.path,'alice',packet)
        self.assertEqual((self.raw(),self.credits()),before)

    def test_original_console_grammar_and_wire_reject_extra_text_and_channels(self):
        request=ProficiencyDecrease('Иван Петров','mines');packet=encode_proficiency_decrease(request)
        self.assertEqual(decode_proficiency_decrease(packet),request)
        self.assertEqual(parse_command('/decreaseability Alice Prime LIGHT'),ProficiencyDecrease('Alice Prime','light'))
        for text in ('/decreaseability','/decreaseability 2 medical','/decreaseability Alice Prime light extra','/decreaseability A\nlight'):
            with self.subTest(text=text),self.assertRaises(ValueError):parse_command(text)
        with self.assertRaises(ValueError):decode_proficiency_decrease(b'\x21\2'+packet[2:])


if __name__=='__main__':unittest.main()
