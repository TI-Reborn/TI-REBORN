from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from tio.appearance import appearance_bytes,change,encode_request,catalog
from tio.characters import CharacterStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tools.battle_actor_fixture import actor_packet
from wallet_fixture import fund_wallet


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.db'
        self.store=CharacterStore(self.path);self.pets=OwnedPetStore(self.path)
        self.fixture=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        for account,sex in [('alice',1),('bob',2)]:
            # Exhaustively exercise paid variants with established funded players.
            fund_wallet(self.path,account,credits=10_000,gold=10_000)
            self.store.create(account,CharacterCreateRequest(account.encode(),0,(sex,0,0,0)))
            self.pets.ensure(account,bytes.fromhex(self.fixture['packet_hex']),bytes.fromhex(self.fixture['inventory_packet_hex']),human=True)

    def pet(self,account):
        return decode_pet_info(self.pets.list(account)[0][1],human_equipment=True)

    def test_new_sexes_and_battle_and_selection_projection(self):
        for account,sex in [('alice',1),('bob',2)]:
            pet=self.pet(account)
            self.assertEqual(pet.fields['0x8c446f'],sex)
            self.assertEqual(pet.fields['0x8c4489'],account.encode())
            self.assertEqual(self.store.list(account)[0].resource_type,sex)
            raw=self.pets.list(account)[0][1]
            battle=decode_battle_soldier(actor_packet(raw,1),human_equipment=True)
            self.assertEqual(appearance_bytes(battle),appearance_bytes(pet))

    def test_persist_price_replay_account_isolation_and_invalid_options(self):
        before=WalletStore(self.path).ensure('alice').credits
        bob=self.pets.list('bob')
        value=bytes((1,3,2,2,0,0))
        request=encode_request(1,value)
        results=change(self.path,'alice',request)
        self.assertEqual(results[0][0],0x66)
        self.assertEqual(appearance_bytes(self.pet('alice')),value)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,before-750)
        self.assertEqual(CharacterStore(self.path).list('alice')[0].optional_six,value)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda _:change(self.path,'alice',request),range(2)))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,before-750)
        self.assertEqual(self.pets.list('bob'),bob)
        saved=self.pets.list('alice')
        for bad in (bytes((1,8,2,2,0,0)),bytes((2,3,2,2,0,0))):
            result=change(self.path,'alice',encode_request(1,bad))
            self.assertEqual(result[-1][0],0xf0)
            self.assertEqual(self.pets.list('alice'),saved)
        self.assertEqual(change(self.path,'alice',encode_request(999,value))[0][0],0xf0)

    def test_native_uninitialized_absent_body_legs_are_not_saved(self):
        change(self.path,'alice',encode_request(1,bytes((1,3,2,2,171,171))))
        self.assertEqual(appearance_bytes(self.pet('alice')),bytes((1,3,2,2,0,0)))

    def test_no_money_and_busy_restore_saved_preview(self):
        request=encode_request(1,bytes((1,16,4,3,0,0)))
        saved=self.pets.list('alice')[0][1]
        self.assertEqual(change(self.path,'alice',request,allowed=False)[0],saved)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=0 WHERE account='alice'")
        self.assertEqual(change(self.path,'alice',request)[0],saved)
        self.assertEqual(self.pets.list('alice')[0][1],saved)

    def test_catalog_contains_every_original_variant(self):
        self.assertEqual(len(catalog()),30)
        for (kind,variant,resource),price in catalog().items():
            account='alice' if resource==1 else 'bob'
            from tio.appearance import TYPES
            value=bytearray(appearance_bytes(self.pet(account)))
            value[TYPES.index(kind)]=variant
            change(self.path,account,encode_request(1,value))
            self.assertEqual(appearance_bytes(self.pet(account)),value)

    def test_creation_is_free_once_then_city_changes_cost_credits(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('CREATE TABLE character_onboarding (account TEXT PRIMARY KEY, completed INTEGER NOT NULL DEFAULT 0)')
            db.execute("INSERT INTO character_onboarding VALUES ('alice',0)")
            db.execute("UPDATE wallets SET credits=0 WHERE account='alice'")
        selected=bytes((1,16,4,3,0,0))
        change(self.path,'alice',encode_request(1,selected),finish_creation=True)
        self.assertEqual(appearance_bytes(self.pet('alice')),selected)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,0)
        other=bytes((1,3,2,2,0,0))
        # Replaying the free-creation path rolls back both the look and wallet.
        change(self.path,'alice',encode_request(1,other),finish_creation=True)
        self.assertEqual(appearance_bytes(self.pet('alice')),selected)
        change(self.path,'alice',encode_request(1,other))
        self.assertEqual(appearance_bytes(self.pet('alice')),selected)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=1000 WHERE account='alice'")
        change(self.path,'alice',encode_request(1,other))
        self.assertEqual(appearance_bytes(self.pet('alice')),other)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,250)
