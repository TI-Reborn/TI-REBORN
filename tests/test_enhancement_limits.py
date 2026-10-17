from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tio.enhancement_limits import enhancement_cap, required_level, project_inventory, project_owned_inventory
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.battle_attack import AttackRequest
from tio.owned_pets import OwnedPetStore
from tio.equipment import equip_primary_weapon, EquipmentRejected
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.warehouse import WarehouseStore
from test_combat import item
from test_weapon_proficiency import profile, change, setup


def upgraded(identity=10, template=252, level=20, slot=0, rented=False):
    return replace(item(identity,template,equipped=bool(slot)),location_raw=slot,
                   unknown_words=(400+level*65,)*3,unknown_bytes_02=bytes((level,0,0,int(rented))),
                   unknown_bytes_03=bytes((level,0,1)),optional_u32=10800 if rented else None)


class EnhancementLimitTests(unittest.TestCase):
    def test_bracket_boundaries_and_real_level_preservation(self):
        for level,cap in ((1,3),(3,3),(4,10),(6,10),(7,15),(10,15),(11,20),(15,20),(16,25),(26,25)):
            for upgrade in (0,3,10,15,19,20,25):
                source=upgraded(level=upgrade,rented=True)
                raw=encode_item_list(1,(source,))
                wire=project_inventory(raw,enhancement_cap(level))
                result=decode_item_list(wire)[1][0]
                self.assertEqual(result.unknown_bytes_02[0],min(upgrade,cap))
                self.assertEqual(replace(result,unknown_bytes_02=source.unknown_bytes_02),source)
                # Projecting a previously trimmed wire snapshot restores its original power.
                restored=decode_item_list(project_inventory(wire,25))[1][0]
                self.assertEqual(restored,source)
        for level in (0,-1,True,1.5):
            with self.assertRaises(ValueError):enhancement_cap(level)

    def test_non_equipment_fields_untouched_and_native_equip_requirements(self):
        source=upgraded(template=30)
        raw=encode_item_list(1,(source,))
        self.assertEqual(project_inventory(raw,3),raw)
        self.assertEqual([required_level(upgraded(level=n)) for n in (3,4,10,11,15,16,19,20,25)],
                         [1,4,4,7,7,11,11,1,1])

    def test_city_projection_warehouse_new_owner_and_level_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';store=OwnedPetStore(path)
            original=encode_item_list(1,(upgraded(rented=True),upgraded(11,level=10)))
            store.ensure('alice',profile(1),original,human=True)
            def wire(packet):return decode_item_list(project_owned_inventory(path,'alice',packet))[1]
            self.assertEqual([i.unknown_bytes_02[0] for i in wire(original)],[3,10])
            self.assertEqual(store.inventory('alice',1),original)
            self.assertEqual(project_owned_inventory(path,'bob',original),original)
            store.ensure('alice',change(profile(16),{'0x8c43eb':2}),encode_item_list(2,()),human=True)
            warehouse=WarehouseStore(path,capacity=100)
            warehouse.exchange('alice',1,deposits=((10,1),))
            self.assertEqual(warehouse.items('alice')[0].unknown_bytes_03[0],20)
            inventory,_=warehouse.exchange('alice',2,withdrawals=((10,1),))
            self.assertEqual(wire(inventory)[0].unknown_bytes_02[0],20)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE pet_id=2',(change(profile(7),{'0x8c43eb':2}),))
            self.assertEqual(wire(inventory)[0].unknown_bytes_02[0],15)
            self.assertEqual(wire(inventory)[0].optional_u32,10800)

    def test_city_enforces_sub20_equip_gate_but_allows_scaled20(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';store=OwnedPetStore(path)
            raw=encode_item_list(1,(upgraded(10,252,10),upgraded(20,252,20)))
            store.ensure('alice',profile(1),raw,human=True)
            action=lambda i:encode_item_action(ItemAction(1,i,255))
            with self.assertRaisesRegex(EquipmentRejected,'level 4'):equip_primary_weapon(path,'alice',action(10))
            self.assertEqual(store.inventory('alice',1),raw)
            result=equip_primary_weapon(path,'alice',action(20))
            projected=decode_item_list(project_owned_inventory(path,'alice',result))[1][-1]
            self.assertEqual((projected.equipped,projected.unknown_bytes_02[0],projected.unknown_bytes_03[0]),(1,3,20))

    def test_attack_scales_weapon_and_target_armor_and_preserves_cas(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';store=OwnedPetStore(path)
            field,combat=setup(packet=profile(1))
            owner,items,unknown=decode_item_list(combat.inventories[1])
            weapon=replace(upgraded(1,304,25,16),unknown_bytes_03=b'\x19\0\0')
            original=encode_item_list(owner,(weapon,*items[1:]),unknown)
            store.ensure('alice',profile(1),original,human=True)
            combat.register(1,original,human=True,path=path,account='alice',pet_packet=profile(1))
            armor=upgraded(3,252,20,4)
            combat.register(2,encode_item_list(2,(armor,)),human=True,pet_packet=change(profile(1),{'0x8c43eb':2}))
            replies=combat.attack(7,AttackRequest(1,5,1))
            # +3 gun at distance4: 54 -> 48 -> 40. +3 armor:85+3=88. Damage=floor(4000/188)=21.
            self.assertEqual(field.actor(2).health,979)
            wire=decode_item_list(next(p for p in replies if p[0]==0x30))[1]
            saved=decode_item_list(store.inventory('alice',1))[1]
            self.assertEqual((wire[0].unknown_bytes_02[0],wire[0].unknown_bytes_03[0]),(3,25))
            self.assertEqual(saved[0],replace(weapon,unknown_words=(2020,2025,2025)))
            self.assertEqual(saved[1].count,items[1].count-combat.catalog.weapons[304].bullets_count)
            # The next action must compare against saved full-power bytes, not projected UI bytes.
            combat.attack(7,AttackRequest(1,5,1))
            before=(dict(field._actors),dict(combat.inventories),dict(combat.proficiencies))
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE pet_id=1',(original,))
            with self.assertRaisesRegex(ValueError,'outside battle'):combat.attack(7,AttackRequest(1,5,1))
            self.assertEqual((dict(field._actors),dict(combat.inventories),dict(combat.proficiencies)),before)

    def test_high_level_restores_full_bonus_and_battle_reply(self):
        field,combat=setup(packet=profile(16))
        _,items,unknown=decode_item_list(combat.inventories[1])
        combat.inventories[1]=encode_item_list(1,(upgraded(1,304,25,16),*items[1:]),unknown)
        combat.attack(7,AttackRequest(1,5,1))
        self.assertEqual(field.actor(2).health,926)  # +25 at distance4: 98 -> 88 -> 74 at skill35.
        self.assertEqual(decode_item_list(combat.inventory_packet(1))[1][0].unknown_bytes_02[0],25)

    # Rank activity refreshes next_decay on roster reads. Freeze the clock so
    # this inventory-projection assertion does not fail at a second boundary.
    @patch('tio.ranks.time.time', lambda: 1700000000)
    def test_real_scene_scales_player_and_mirrored_bot_without_database_edits(self):
        from tio.abilities import AbilityCatalog
        from tio.matchmaking import SurvivalQueue
        from tio.arena_service import ArenaService
        from tools.survival_scene import prepare_survival
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';store=OwnedPetStore(path)
            p=change(profile(1),{'0x8c44a6':1})
            inv=encode_item_list(1,(upgraded(10,252,20,4),upgraded(11,304,25,16)))
            store.ensure('alice',p,inv,human=True)
            ticket=SurvivalQueue().join(7,store.list('alice'))
            with closing(sqlite3.connect(path)) as db:before='\n'.join(db.iterdump())
            scene=prepare_survival(path,'alice',ticket,AbilityCatalog(()))
            packets=[p for p in scene.packets if p[0]==0x30]
            self.assertEqual(len(packets),1)
            for actor in scene.field.combat.inventories:
                effective=decode_item_list(scene.field.combat.inventory_packet(actor))[1]
                self.assertEqual([i.unknown_bytes_02[0] for i in effective],[3,3])
                self.assertEqual([i.unknown_bytes_03[0] for i in effective],[20,25])
            arena=ArenaService();arena.start_survival(7,b'Test',scene)
            self.assertEqual(arena.inventory_packets(7,(1,)),tuple(packets))
            with closing(sqlite3.connect(path)) as db:self.assertEqual('\n'.join(db.iterdump()),before)


if __name__=='__main__':unittest.main()
