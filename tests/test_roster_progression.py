from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json,random,sqlite3,tempfile,unittest
from pathlib import Path
from tio.roster_progression import (RecruitmentStore,profile,grant_starters,
    tutorial_status,tutorial_begin,tutorial_progress,tutorial_leave)
from tio.city_catalogs import CityCatalogs
from tio.characters import CharacterStore
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.binary import Writer
from tio.protocol.city_catalogs import decode_service_shop
from tio.weapon_proficiency import SAVED,number,HUMAN_SKILLS
from tio import services

ROOT=Path(__file__).resolve().parents[1]


class RosterProgressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'players.db'
        self.template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        self.catalogs=CityCatalogs(ROOT/'config/city_catalogs.json')
        self.store=RecruitmentStore(self.path,self.catalogs,self.template,rng=random.Random(81))
        for account in ('alice','bob'):
            WalletStore(self.path).ensure(account)
            with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE wallets SET credits=100000 WHERE account=?',(account,))

    def create(self,account):
        # Pre-update save fixture; actual native NEW-create grants are covered
        # by test_shared_tutorial through CharacterStore's transaction.
        CharacterStore(self.path).create(account,CharacterCreateRequest(account.capitalize().encode(),0,(0,0,0,0)))
        raw=profile(self.template,1,1,account.capitalize().encode())
        OwnedPetStore(self.path).ensure(account,raw,encode_item_list(1,()),human=True)

    def rows(self,account='alice'):return OwnedPetStore(self.path).list(account)
    def credits(self,account='alice'):return WalletStore(self.path).ensure(account).credits

    def travel(self,town,account='alice'):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO character_locations(account,town_id) VALUES (?,?) ON CONFLICT(account) DO UPDATE SET town_id=excluded.town_id',(account,town))

    def test_exactly_two_random_human_starters_only_at_fresh_creation_and_no_wallet_charge(self):
        self.create('alice');self.create('bob');before=self.credits()
        identities=grant_starters(self.path,'alice',self.template,created=True,rng=random.Random(17))
        self.assertEqual(identities,(2,3));self.assertEqual([i for i,_,_ in self.rows()],[1,2,3])
        names=[];looks=[]
        for identity,raw,inventory in self.rows()[1:]:
            pet=decode_pet_info(raw,human_equipment=True).fields
            self.assertIn(pet['0x8c446f'],(1,2));self.assertEqual(pet['0x8c4aef'],1)
            self.assertEqual(pet['0x8c4a07'],85);self.assertEqual(pet['0x8c4ab1'],85)
            self.assertEqual(pet['0x8c4b57'],1315)
            self.assertTrue(all(number(pet[SAVED[i]])==35 for i in HUMAN_SKILLS))
            names.append(pet['0x8c4489']);looks.append(pet['0x6d0203'])
            self.assertEqual(decode_item_list(inventory),(identity,(),0))
        self.assertEqual(len(set(names)),2);self.assertEqual(looks,[1,1]);self.assertEqual(self.credits(),before)
        self.assertEqual(len(self.rows('bob')),1)
        self.assertEqual(grant_starters(self.path,'alice',self.template,created=True),(2,3))
        self.assertEqual(len(self.rows()),3)

    def test_existing_saves_resume_and_dismissed_starters_never_receive_new_grants(self):
        self.create('alice');before=self.rows()
        self.assertEqual(grant_starters(self.path,'alice',self.template),());self.assertEqual(self.rows(),before)
        self.assertIsNone(tutorial_status(self.path,'alice'))
        grant_starters(self.path,'alice',self.template,created=True)
        self.store.dismiss('alice',2)
        self.assertEqual(grant_starters(self.path,'alice',self.template,created=True),(2,3))
        self.assertEqual([i for i,_,_ in self.rows()],[1,3])

    def test_starter_creation_second_insert_failure_rolls_back_entire_grant_and_tutorial(self):
        self.create('alice');before=(self.rows(),self.credits())
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER refuse_third BEFORE INSERT ON owned_pets WHEN NEW.pet_id=3 BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):grant_starters(self.path,'alice',self.template,created=True)
        self.assertEqual((self.rows(),self.credits()),before)
        self.assertIsNone(tutorial_status(self.path,'alice'))

    def test_city_offers_are_random_durable_isolated_and_cannot_reroll_or_revive_consumed_id(self):
        first=self.store.available('alice');bob=self.store.available('bob')
        self.assertNotEqual([c.name for c in first],[c.name for c in bob])
        reopened=RecruitmentStore(self.path,self.catalogs,self.template,rng=random.Random(99))
        self.assertEqual(reopened.available('alice'),first)
        self.assertEqual({c.price_credits for c in first if c.resource_type in (1,2)},{500})
        self.assertEqual({c.price_credits for c in first if c.resource_type in (3,4,5)},{2500})
        offer=next(c for c in first if c.resource_type==1);before=self.credits()
        raw,inventory,wallet=self.store.hire('alice',offer.candidate_id)
        pet=decode_pet_info(raw,human_equipment=True).fields
        self.assertEqual(pet['0x8c4489'],offer.name);self.assertEqual(wallet.credits,before-500)
        from tio.appearance import FIELDS
        self.assertEqual(bytes(pet[k] for k in FIELDS),offer.optional_bytes)
        self.assertEqual(self.store.available('bob'),bob)
        with self.assertRaises(ValueError):self.store.hire('alice',offer.candidate_id)
        replacement=next(c for c in self.store.available('alice') if c.resource_type==1)
        self.assertNotEqual(replacement.candidate_id,offer.candidate_id)
        self.assertNotEqual(replacement.name,offer.name)

    def test_wrong_city_or_miner_offer_cannot_charge_and_city_pools_stay_stable(self):
        original=self.store.available('alice');before=self.credits()
        self.travel(9);miners=self.store.available('alice')
        self.assertEqual([c.resource_type for c in miners],[6]);self.assertEqual(miners[0].price_credits,3500)
        with self.assertRaises(ValueError):self.store.hire('alice',original[0].candidate_id)
        self.assertEqual(self.credits(),before)
        self.travel(2);denver=self.store.available('alice')
        self.assertNotEqual([c.candidate_id for c in denver],[c.candidate_id for c in original])
        with self.assertRaises(ValueError):self.store.hire('alice',miners[0].candidate_id)
        self.travel(3);self.assertEqual(self.store.available('alice'),original)
        self.travel(10);self.assertEqual(self.store.available('alice'),())

    def test_simultaneous_hires_of_one_offer_grant_and_charge_once(self):
        offer=self.store.available('alice')[0];before=self.credits()
        def attempt(_):
            try:return self.store.hire('alice',offer.candidate_id)
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=4) as workers:results=list(workers.map(attempt,range(4)))
        self.assertEqual(sum(value is not None for value in results),1)
        self.assertEqual(len(self.rows()),1);self.assertEqual(self.credits(),before-500)

    def test_hire_failure_rolls_back_wallet_offer_and_actor(self):
        offer=self.store.available('alice')[0];before=(self.rows(),self.credits(),self.store.available('alice'))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("CREATE TRIGGER refuse_hire BEFORE INSERT ON hired_candidates BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.hire('alice',offer.candidate_id)
        self.assertEqual((self.rows(),self.credits(),self.store.available('alice')),before)

    def test_service_levels_unlock_fifteen_saved_fighters(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE wallets SET credits=300000 WHERE account=?', ('alice',))
        self.create('alice')
        for _ in range(6):
            self.store.hire('alice', self.store.available('alice')[0].candidate_id)
        with self.assertRaisesRegex(ValueError, 'Отряд заполнен'):
            self.store.hire('alice', self.store.available('alice')[0].candidate_id)
        prices = (2000, 5800, 11400, 18800, 28000, 39000, 51800, 66400)
        for level, cost in enumerate(prices, 1):
            request = Writer().u8(0xb1).u8(4).u8(0).u32(2).u8(level).u32(1).build()
            before = self.credits()
            services.purchase(self.path, 'alice', request)
            services.purchase(self.path, 'alice', request)
            self.assertEqual(self.credits(), before - cost)
            self.store.hire('alice', self.store.available('alice')[0].candidate_id)
            self.assertEqual(len(self.rows()), 7 + level)
            with self.assertRaisesRegex(ValueError, 'Отряд заполнен'):
                self.store.hire('alice', self.store.available('alice')[0].candidate_id)
        self.assertNotIn(2, [offer.unknown_u32 for offer in
                             decode_service_shop(services.catalog(self.path, 'alice'))])
        self.assertEqual(len(self.rows('bob')), 0)

    def test_tutorial_requires_real_owned_battle_and_server_observation_then_survives_resume(self):
        self.create('alice');self.create('bob');grant_starters(self.path,'alice',self.template,created=True)
        with self.assertRaises(ValueError):tutorial_begin(self.path,'bob','intro-bob')
        status=tutorial_begin(self.path,'alice','intro-alice');self.assertEqual(status['step'],0)
        with self.assertRaises(ValueError):tutorial_progress(self.path,'alice','intro-alice','move')
        with self.assertRaises(ValueError):tutorial_progress(self.path,'bob','intro-alice','move',observed=True)
        with self.assertRaises(ValueError):tutorial_begin(self.path,'alice','other-match')
        tutorial_progress(self.path,'alice','intro-alice','move',observed=True)
        tutorial_leave(self.path,'alice','intro-alice')
        status=tutorial_begin(self.path,'alice','intro-alice-resumed');self.assertEqual(status['step'],1)
        tutorial_progress(self.path,'alice','intro-alice-resumed','attack',observed=True)
        # A critical first shot may kill before ending a turn. Its observed
        # fact persists; completion must not wait for a second nonexistent kill.
        tutorial_progress(self.path,'alice','intro-alice-resumed','enemy_killed',observed=True)
        self.assertEqual(tutorial_status(self.path,'alice')['step'],2)
        status=tutorial_progress(self.path,'alice','intro-alice-resumed','end_turn',observed=True)
        self.assertTrue(status['completed']);self.assertIsNone(status['tip'])
        with self.assertRaises(ValueError):tutorial_begin(self.path,'alice','repeat')
        self.assertIsNone(tutorial_status(self.path,'bob'))


if __name__=='__main__':unittest.main()
