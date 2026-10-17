"""Legacy save preservation, five-slot isolation and native selection TCP."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from server.accounts import Accounts
from server.auth_errors import LoginRejected
from tio.character_identity import alias,auth_account,owners,owner_for_name
from tio.characters import CharacterStore,CreateRejected
from tio.onboarding import prepare,pending,pending_owner
from tio.owned_pets import OwnedPetStore
from tio.protocol.character_create import CharacterCreateRequest,encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.world_bootstrap import decode_mychar_info
from tio.wallets import WalletStore
from tio.appearance import encode_request,change

ROOT=Path(__file__).resolve().parents[1]
PASSWORD='Character-test-password-123'


class CharacterSlotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'state.sqlite3'
        self.accounts=Accounts(self.path)
        self.accounts.create('alice',PASSWORD,character='Alice')
        self.accounts.create('bob',PASSWORD,character='Bob')
        self.store=CharacterStore(self.path)

    def create(self,name=b'AliceTwo',sex=1):
        return self.store.create('alice',CharacterCreateRequest(name,0,(sex,0,0,0)))

    def test_startup_schema_does_not_rewrite_legacy_rows_or_issue_money(self):
        WalletStore(self.path).ensure('alice')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=157,gold=12 WHERE account='alice'")
            before={name:db.execute('SELECT * FROM '+name).fetchall() for name in ('accounts','characters','wallets')}
        for _ in range(3):CharacterStore(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(before,{name:db.execute('SELECT * FROM '+name).fetchall() for name in before})
            self.assertEqual(db.execute('SELECT * FROM character_identities').fetchall(),[])
        self.assertEqual(owners(self.path,'alice'),('alice',))
        self.assertEqual(self.accounts.verify(b'alice',PASSWORD.encode()),'alice')

    def test_five_slots_global_names_reopen_and_strict_ownership(self):
        for name in (b'AliceTwo',b'AliceThree',b'AliceFour',b'AliceFive'):self.create(name)
        for slot,record in enumerate(CharacterStore(self.path).list('alice'),1):
            owner,selected=self.store.select('alice',slot)
            self.assertEqual(owner,alias('alice',slot));self.assertEqual(selected,record)
            self.assertEqual(auth_account(self.path,owner),'alice')
        self.assertEqual(len(owners(self.path,'alice')),5)
        with self.assertRaises(CreateRejected) as full:self.create(b'AliceSix')
        self.assertEqual(full.exception.status,2)
        with self.assertRaises(CreateRejected) as taken:
            self.store.create('bob',CharacterCreateRequest(b'alicetwo',0,(1,0,0,0)))
        self.assertEqual(taken.exception.status,3)
        for slot in (0,2,5,6,0xffffffff):
            with self.assertRaises(ValueError):self.store.owner('bob',slot)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(owner_for_name(db,b'AliceTwo'),alias('alice',2))

    def test_additional_owner_is_not_an_authentication_login(self):
        self.create()
        with self.assertRaises(LoginRejected):self.accounts.verify(alias('alice',2).encode(),PASSWORD.encode())
        with self.assertRaises(ValueError):self.accounts.create(alias('alice',2),PASSWORD)
        with self.assertRaises(ValueError):self.store.create(alias('alice',2),CharacterCreateRequest(b'Nested',0,(1,0,0,0)))
        with self.assertRaises(ValueError):auth_account(self.path,alias('alice',5))

    def test_wallet_roster_appearance_progress_and_location_are_per_slot(self):
        self.create()
        owner=self.store.owner('alice',2)
        prepare(self.path,'alice');prepare(self.path,owner)
        pets=OwnedPetStore(self.path)
        primary=pets.list('alice')
        before=WalletStore(self.path).ensure('alice')
        self.assertEqual((before.credits,before.gold),(3000,0))
        self.assertEqual((WalletStore(self.path).ensure(owner).credits,WalletStore(self.path).ensure(owner).gold),(3000,0))
        self.assertEqual(decode_pet_info(pets.list(owner)[0][1],human_equipment=True).fields['0x8c4489'],b'AliceTwo')
        raw=pets.list(owner)[0][1]
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=555 WHERE account=?',(owner,))
            pet=decode_pet_info(raw,human_equipment=True)
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',
                       (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':2})),owner))
        pending(self.path,owner)
        change(self.path,owner,encode_request(1,b'\x01\0\0\x01\0\0'),finish_creation=True)
        self.assertEqual(pets.list('alice'),primary)
        self.assertEqual(WalletStore(self.path).ensure('alice'),before)
        self.assertEqual([record.unknown_u8_02 for record in self.store.list('alice')],[1,2])
        from tio.locations import LocationStore
        locations=LocationStore(self.path)
        self.assertEqual(locations.current('alice'),3)
        self.assertEqual(locations.current(owner),3)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO character_locations VALUES (?,9,0,0)',(owner,))
        self.assertEqual(locations.current('alice'),3)
        self.assertEqual(locations.current(owner),9)
        self.assertEqual(WalletStore(self.path).ensure(owner).credits,555)

    def test_unfinished_secondary_creation_resumes_its_owner_only(self):
        prepare(self.path,'alice')
        self.create(sex=2)
        owner=self.store.owner('alice',2)
        self.assertEqual(pending_owner(self.path,'alice'),owner)
        prepare(self.path,owner)
        self.assertEqual(pending_owner(self.path,'alice'),owner)
        change(self.path,owner,encode_request(1,b'\x02\x08\0\x01\0\0'),finish_creation=True)
        self.assertIsNone(pending_owner(self.path,'alice'))
        self.assertEqual([record.resource_type for record in self.store.list('alice')],[1,2])

    def test_failure_rolls_back_character_and_mapping_together(self):
        self.create()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER reject_third BEFORE INSERT ON characters WHEN NEW.account='@character:alice:3' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.create(b'AliceThree')
        self.assertEqual(owners(self.path,'alice'),('alice',alias('alice',2)))
        self.assertEqual(len(self.store.list('alice')),2)


class CharacterSlotsTCPTests(unittest.TestCase):
    def setUp(self):
        from test_multi_account import MultiAccountTests
        self.case=MultiAccountTests('test_server_load_counts_unique_accounts_and_releases_disconnects')
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.config.database

    def ready(self):self.case.start()

    def connect(self,login='alice'):
        return self.case.handoff(self.case.begin(login))

    def create_native(self,peer,name,slot,sex=1):
        peer.send(encode_character_create(CharacterCreateRequest(name,0,(sex,0,0,0))))
        self.assertEqual(peer.receive(),b'\x12\x05')
        editing=decode_character_list(peer.receive())
        # Existing free-editor patch scans the first nonempty record; expose
        # exactly the new slot so it cannot edit an old character for free.
        self.assertEqual([(record.record_id,record.name_bytes) for record in editing],[(slot,name)])
        self.assertTrue(editing[0].optional_six)
        peer.send(encode_request(slot,editing[0].optional_six))
        return decode_character_list(peer.until(b'\x10'))

    def enter_slot(self,peer,slot,name):
        peer.send(b'\x17'+slot.to_bytes(4,'little'))
        self.assertEqual(peer.receive(),b'\x18\0'+bytes(8))
        peer.send(b'\x19')
        character=decode_mychar_info(peer.until(b'\x1a'))
        self.assertEqual((character.character_id,character.name_bytes),(slot,name))
        assets=decode_asset_count(peer.until(b'\xc8\x39'))
        pet=decode_pet_info(peer.until(b'\x66'),human_equipment=True)
        self.assertEqual(pet.fields['0x8c4489'],name)
        self.case.ping(peer)
        # These cases test slots and ordinary city actions. Leave a new
        # character's introductory mission through its real native exit.
        hub=self.case.server.multi.team_arena
        session=next(s for s in hub.players.values() if s.probe_character_name==name)
        battle=hub.battles.get(hub.identities[session])
        if battle and battle.get('kind')=='tutorial':
            peer.send(b'\x2a\1');self.case.ping(peer)
        return assets

    def disconnect(self,peer):
        peer.sock.close();deadline=time.monotonic()+5
        while self.case.server.multi.server_population()[0]:
            if time.monotonic()>deadline:self.fail('Authentication login was not released')
            time.sleep(.01)

    def test_native_creation_secondary_selection_purchase_restart_primary_preserved(self):
        from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
        self.ready();peer=self.connect()
        records=self.case.character_screen(peer)
        self.assertEqual([(r.record_id,r.name_bytes) for r in records],[(1,b'Alice')])
        records=self.create_native(peer,b'AliceTwo',2)
        self.assertEqual([(r.record_id,r.name_bytes) for r in records],[(1,b'Alice'),(2,b'AliceTwo')])
        self.assertEqual(self.enter_slot(peer,2,b'AliceTwo').credits,3000)
        owner=alias('alice',2)
        self.assertEqual(self.case.server.multi.active_accounts['alice'].account,owner)
        self.case.begin('alice',denied=True)
        peer.send(encode_shop_purchase(ShopPurchase(1,0,81,2)))
        from tio.city_catalogs import CityCatalogs
        price=next(offer.unknown_u32_03 for offer in CityCatalogs(ROOT/'config/city_catalogs.json').items[0] if offer.unknown_u32_01==81)
        balance=3000-price*2
        self.assertEqual(decode_asset_count(peer.until(b'\xc8\x39')).credits,balance)
        self.case.ping(peer)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10000)
        secondary_inventory=OwnedPetStore(self.path).inventory(owner,1)
        self.disconnect(peer)
        self.case.stop();self.case.start()
        restored=self.connect();self.case.character_screen(restored)
        self.assertEqual(self.enter_slot(restored,2,b'AliceTwo').credits,balance)
        self.assertEqual(OwnedPetStore(self.path).inventory(owner,1),secondary_inventory)
        self.disconnect(restored)
        primary=self.connect();self.case.character_screen(primary)
        self.assertEqual(self.enter_slot(primary,1,b'Alice').credits,10000)

    def test_native_all_five_slots_and_sixth_rejection(self):
        self.ready();peer=self.connect();self.case.character_screen(peer)
        for slot in range(2,6):
            records=self.create_native(peer,f'Alice{slot}'.encode(),slot,sex=2 if slot%2 else 1)
            self.assertEqual([record.record_id for record in records],list(range(1,slot+1)))
        peer.send(encode_character_create(CharacterCreateRequest(b'AliceSix',0,(1,0,0,0))))
        self.assertEqual(peer.receive(),b'\x12\x02')
        self.assertEqual(self.enter_slot(peer,5,b'Alice5').credits,3000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM accounts").fetchone()[0],2)

    def test_forged_slot_is_not_another_accounts_character(self):
        self.ready();peer=self.connect('bob');self.case.character_screen(peer)
        peer.send(b'\x17\x02\0\0\0')
        with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
        self.assertEqual(CharacterStore(self.path).list('alice')[0].name_bytes,b'Alice')

    def test_unfinished_native_secondary_creation_resumes_after_server_restart(self):
        self.ready();peer=self.connect();self.case.character_screen(peer)
        peer.send(encode_character_create(CharacterCreateRequest(b'AliceTwo',0,(2,0,0,0))))
        self.assertEqual(peer.receive(),b'\x12\x05')
        self.assertEqual(decode_character_list(peer.receive())[0].record_id,2)
        self.disconnect(peer);self.case.stop();self.case.start()
        resumed=self.connect()
        editing=self.case.character_screen(resumed,appearance=True)
        self.assertEqual([(r.record_id,r.name_bytes) for r in editing],[(2,b'AliceTwo')])
        resumed.send(encode_request(2,editing[0].optional_six))
        self.assertEqual(len(decode_character_list(resumed.until(b'\x10'))),2)
        self.assertEqual(self.enter_slot(resumed,2,b'AliceTwo').credits,3000)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10000)

    def test_retained_shared_battle_forbids_other_slot_and_reconnects_exact_owner(self):
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        self.ready();alice=self.connect();self.case.character_screen(alice)
        self.create_native(alice,b'AliceTwo',2)
        self.enter_slot(alice,2,b'AliceTwo')
        bob=self.connect('bob');self.case.character_screen(bob);self.enter_slot(bob,1,b'Bob')
        request=encode_create_request(ArenaCreateRequest(1,0,4,2,40,1,1,0,0))
        for peer in (alice,bob):peer.send(request);peer.until(b'\x25');peer.send(b'\x2e')
        for peer in (alice,bob):peer.until(b'\x41');peer.send(b'\x36')
        self.case.ping(alice);self.case.ping(bob)
        hub=self.case.server.multi.team_arena
        owner=alias('alice',2)
        actor_owner=hub.account_owners[owner]
        battle=hub.battles[actor_owner]
        actor_id=battle['field'].actor_ids(actor_owner)[0]
        before=battle['field'].actor(actor_id)
        alice.sock.close();deadline=time.monotonic()+5
        while 'alice' in self.case.server.multi.active_accounts:
            if time.monotonic()>deadline:self.fail('Disconnected authentication login was retained')
            time.sleep(.01)
        self.assertTrue(hub.retained(owner))
        restored=self.connect();self.case.character_screen(restored)
        restored.send(b'\x17\x01\0\0\0')
        self.assertEqual(restored.receive(),b'\x18\x01')
        self.assertTrue(restored.receive().startswith(b'\xf0'))
        self.assertEqual(len(decode_character_list(restored.receive())),2)
        self.assertEqual(self.case.server.multi.active_accounts['alice'].account,'alice')
        self.enter_slot(restored,2,b'AliceTwo')
        self.assertIs(hub.battles[actor_owner],battle)
        self.assertEqual(battle['field'].actor(actor_id),before)
        self.assertEqual(self.case.server.multi.active_accounts['alice'].arena._durable.account,owner)
        restored.send(b'\x36');self.case.ping(restored);self.case.ping(bob)

    def test_quarantined_secondary_checkpoint_blocks_login_and_preserves_primary(self):
        from tio import battle_checkpoints as checkpoints
        self.ready();peer=self.connect();self.case.character_screen(peer)
        self.create_native(peer,b'AliceTwo',2)
        self.enter_slot(peer,2,b'AliceTwo');self.disconnect(peer)
        with closing(sqlite3.connect(self.path)) as db,db:
            checkpoints.save(db,'secondary-quarantined','{}',{alias('alice',2):2},status='quarantined')
        self.assertEqual(self.case.begin('alice',denied=True),b'\x04\x10')
        bob=self.connect('bob');self.case.character_screen(bob)
        self.assertEqual(self.enter_slot(bob,1,b'Bob').credits,10000)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10000)
