"""Concurrent passive healing must not resend appearance/equipment profiles."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.battle_recovery import RecoveryStore,save_wounds,treat_updates
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.protocol.health import encode_health

ROOT=Path(__file__).resolve().parents[1]


class RecoveryRosterUpdateTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'state.sqlite3';self.now=[1000.]
        self.store=OwnedPetStore(self.path)
        raw=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        template=decode_pet_info(raw,human_equipment=True)
        for account in ('alice','bob'):
            for identity,maximum in ((1,115),(2,95),(3,85),(4,85)):
                pet=encode_pet_info(replace(template,fields={**template.fields,
                    '0x8c43eb':identity,'0x8c4489':('Fighter'+str(identity)).encode(),
                    '0x8c4a07':maximum,'0x8c4ab1':maximum,'0x8c4ac5':10*identity}))
                weapon=ItemRecord(1000+identity,301+identity,bytes(2),1,1,16,(300,)*3,bytes(4),None,bytes(3))
                self.store.ensure(account,pet,encode_item_list(identity,(weapon,)),human=True)
            with closing(sqlite3.connect(self.path)) as db,db:save_wounds(db,account,{2:26,4:26})
        self.recovery=RecoveryStore(self.path,clock=lambda:self.now[0])
        self.assertEqual(self.recovery.refresh('alice'),())
        self.assertEqual(self.recovery.refresh('bob'),())

    def snapshot(self,account):
        with closing(sqlite3.connect(self.path)) as db:
            return [(identity,decode_pet_info(raw,human_equipment=bool(human)).fields,inventory)
                    for identity,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,))]

    def test_two_healing_pets_emit_only_targeted_hp_and_preserve_every_other_field(self):
        before=self.snapshot('alice');other=self.snapshot('bob');self.now[0]+=10
        self.assertEqual(self.recovery.refresh('alice'),(encode_health(2,27),encode_health(4,27)))
        after=self.snapshot('alice')
        for (identity,old,inventory),(key,new,new_inventory) in zip(before,after):
            self.assertEqual(identity,key);self.assertEqual(inventory,new_inventory)
            expected={**old,'0x8c4ab1':27} if identity in (2,4) else old
            self.assertEqual(new,expected)
        self.assertEqual(self.snapshot('bob'),other)

    def test_two_sessions_cannot_duplicate_the_same_healing_tick(self):
        self.now[0]+=10
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies=list(pool.map(lambda _:RecoveryStore(self.path,clock=lambda:self.now[0]).refresh('alice'),range(2)))
        self.assertEqual(sorted(map(len,replies)),[0,2])
        self.assertEqual([p for group in replies for p in group], [encode_health(2,27),encode_health(4,27)])

    def test_shared_backend_keeps_two_accounts_recovery_separate(self):
        self.now[0]+=20
        for account in ('alice','bob'):
            self.assertEqual(self.recovery.refresh(account),(encode_health(2,28),encode_health(4,28)))
            self.assertEqual(self.recovery.refresh(account),())

    def test_paused_battle_does_not_emit_city_hp_or_rebuild_roster(self):
        before=self.snapshot('alice');self.now[0]+=3600
        self.assertEqual(self.recovery.refresh('alice',blocked=True),())
        self.assertEqual(self.snapshot('alice'),before)
        self.assertEqual(self.recovery.refresh('alice'),())
        self.now[0]+=10
        self.assertEqual(self.recovery.refresh('alice'),(encode_health(2,27),encode_health(4,27)))

    def test_paid_multi_treatment_updates_only_requested_hp_and_charges_once(self):
        from wallet_fixture import fund_wallet
        fund_wallet(self.path,'alice',credits=1000,gold=0)
        before=self.snapshot('alice');other=self.snapshot('bob')
        assets,cost,packets=treat_updates(self.path,'alice',(2,4))
        self.assertEqual((assets.credits,cost),(744,256))
        self.assertEqual(packets,(encode_health(2,95),encode_health(4,85)))
        for (identity,old,bag),(key,new,new_bag) in zip(before,self.snapshot('alice')):
            self.assertEqual(key,identity);self.assertEqual(bag,new_bag)
            self.assertEqual(new,{**old,'0x8c4ab1':old['0x8c4a07']} if identity in (2,4) else old)
        self.assertEqual(self.snapshot('bob'),other)
        self.assertEqual(treat_updates(self.path,'alice',(2,4))[:2],(assets,0))

    def test_failed_multi_treatment_rolls_back_hp_and_wallet(self):
        from wallet_fixture import fund_wallet
        from tio.wallets import WalletStore
        fund_wallet(self.path,'alice',credits=255,gold=0)
        before=self.snapshot('alice')
        for ids in ((2,4),(2,999)):
            with self.assertRaises(ValueError):treat_updates(self.path,'alice',ids)
            self.assertEqual(self.snapshot('alice'),before)
            self.assertEqual(WalletStore(self.path).ensure('alice').credits,255)

    def test_real_shared_battle_blocks_city_recovery_without_private_room(self):
        from types import SimpleNamespace
        from test_shared_team_arena import SharedTeamTests
        from tools.loopback_exchange import LoopbackExchange
        case=SharedTeamTests();case.setUp();self.addCleanup(case.doCleanups)
        owners,battle=case.open_battle()
        for index in (0,1,2):
            session=case.sessions[index];session.router=SimpleNamespace(team_arena=case.hub)
            self.assertFalse(session.arena.rooms.snapshot())
            self.assertEqual(LoopbackExchange.recovery_blocked(session,session.probe_character_id),index in (0,1))
