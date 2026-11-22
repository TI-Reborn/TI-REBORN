"""Real saved account selections, frozen policies and native PvE packets."""
from copy import deepcopy
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.contract_scene import BOT_OWNER, freeze_policy, prepare
from tio.matchmaking import SearchTicket
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_ground import decode_battle_ground
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.pve_contracts import load_catalog

ROOT = Path(__file__).resolve().parents[1]


class ContractSceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'real-accounts.db'
        self.store = OwnedPetStore(self.path)
        raw = bytes.fromhex(json.loads((ROOT / 'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        base = decode_pet_info(raw, human_equipment=True)
        self.accounts = ('alice', 'bob', 'carol', 'dave')
        for index, account in enumerate(self.accounts):
            for identity in (1, 2, 3):
                fields = {**base.fields, '0x8c43eb': identity, '0x8c44a6': identity if identity < 3 else 0,
                          '0x8c4489': (account + str(identity)).encode(),
                          '0x8c4ab1': base.fields['0x8c4a07']}
                first = 10000 * (index + 1) + identity * 10
                choices = ((301, 1, 16), (229, 1, 4), (3, 60, 0))
                items = tuple(ItemRecord(first + offset, template, b'\0\0', count, int(slot != 0),
                                         slot, (300, 300, 300), b'\0' * 4, None, b'\0' * 3)
                              for offset, (template, count, slot) in enumerate(choices))
                self.store.ensure(account, encode_pet_info(replace(base, fields=fields)),
                                  encode_item_list(identity, items), human=True)
            self.store.list(account)  # Normalize real saved projections before comparison.
        self.templates = {t['id']: t for t in load_catalog()['templates']}

    def record(self, name='camp', seed=901):
        template = deepcopy(self.templates[name])
        template['scene_policy'] = freeze_policy(template)
        return dict(id='scene-test-' + name, seed=seed, template=template)

    def seats(self, count=2, selected=(2, 1)):
        result = []
        for index, account in enumerate(self.accounts[:count]):
            saved = {i: p for i, p, _ in self.store.list(account)}
            owner = 42 + index
            levels = tuple(decode_pet_info(saved[i], human_equipment=True).fields['0x8c4aef'] for i in selected)
            result.append((owner, 0, self.path, account, SearchTicket(owner, selected, levels, 0, 7), False))
        return result

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT account,pet_id,human,pet_packet,inventory_packet FROM owned_pets ORDER BY account,pet_id').fetchall()

    def test_four_real_accounts_eight_selected_actors_share_one_field_without_save_mirrors(self):
        seats = self.seats(4)
        before = self.rows()
        field, views, ground, skills, bot = prepare(seats, self.record())
        self.assertEqual(self.rows(), before)
        self.assertEqual(set(views), {42, 43, 44, 45})
        self.assertEqual(bot, BOT_OWNER)
        self.assertEqual(len(field._actors), 13)
        self.assertEqual(len(field.combat.persistence), 8)
        for owner, _, path, account, ticket, _ in seats:
            actors = field.actor_ids(owner)
            self.assertEqual(tuple(field.combat.storage_ids[i] for i in actors), ticket.actors)
            self.assertTrue(all(field.allied(owner, other[0]) for other in seats))
            self.assertFalse(field.allied(owner, bot))
            for actor in actors:
                self.assertEqual(field.combat.persistence[actor], (path, account))
                local = field.combat.storage_ids[actor]
                saved = {i: inv for i, _, inv in self.store.list(account)}
                self.assertEqual(decode_item_list(field.combat.inventories[actor])[1], decode_item_list(saved[local])[1])
                self.assertIsInstance(skills[actor], bytes)
        self.assertEqual(field.living_sides(), {('team', 0), ('team', 1)})
        self.assertEqual((decode_battle_ground(ground).width, decode_battle_ground(ground).height), (38, 38))
        self.assertTrue(field.loot.boxes)

    def test_npcs_have_native_existing_models_equipment_and_no_persistent_account(self):
        record = self.record('checkpoint')
        field, views, _, skills, bot = prepare(self.seats(), record)
        expected = {'scout': 2, 'rifleman': 3, 'heavy': 1}
        counts = {role: 0 for role in expected}
        for actor_id in field.actor_ids(bot):
            role_name = field.contract_metadata['npc_roles'][actor_id]
            role = record['template']['scene_policy']['roles'][role_name]
            counts[role_name] += 1
            actor = field.actor(actor_id)
            if actor_id == field.contract_metadata['boss']:
                role = {**role, 'health': role['health'] * 2, 'name': role['name'] + ' — босс'}
            self.assertEqual((actor.health, actor.max_health, actor.action_points, actor.sight_radius),
                             (role['health'], role['health'], role['action_points'], role['sight_radius']))
            packet = views[42].snapshot(actor_id)
            decoded = decode_battle_soldier(packet, human_equipment=True)
            self.assertEqual(decoded.fields['0x8c50fb'], role['resource_id'])
            self.assertEqual(decoded.fields['0x8c52cf'], role['weapon_id'])
            self.assertEqual(decoded.fields['0x8c5187'], 1)
            self.assertEqual(decoded.fields['0x8c5116'].decode('cp1251'), role['name'])
            inventory = decode_item_list(field.combat.inventories[actor_id])[1]
            self.assertEqual({i.template_id for i in inventory if i.equipped}, {role['weapon_id'], *role['armor_ids']})
            ammo = field.combat.catalog.weapons[role['weapon_id']].ammo_id
            self.assertEqual(next(i.count for i in inventory if i.template_id == ammo), role['ammunition'])
            self.assertNotIn(actor_id, field.combat.persistence)
            self.assertNotIn(actor_id, field.combat.storage_ids)
            self.assertTrue({i.instance_id for i in inventory}.issubset(field.contract_transient_items))
            self.assertTrue({i.instance_id for i in inventory}.isdisjoint(field.combat.temporary_items))
            self.assertIsInstance(skills[actor_id], bytes)
        self.assertEqual(counts, expected)
        self.assertEqual({row[0] for row in self.rows()}, set(self.accounts))

    def test_npc_equipment_does_not_turn_into_transferable_death_loot(self):
        field, _, _, _, bot = prepare(self.seats(), self.record())
        before = self.rows()
        crates = dict(field.loot.boxes)
        states = {identity: replace(field.actor(identity), health=0) for identity in field.actor_ids(bot)}
        changes = {}
        boxes, ground = field.loot.stage_deaths(states, changes)
        self.assertFalse(boxes)
        self.assertFalse(ground)
        self.assertFalse(changes)
        self.assertEqual(field.loot.boxes, crates)
        self.assertEqual(self.rows(), before)

    def test_maps_reproduce_their_seed_and_keep_native_footprints(self):
        for name in self.templates:
            with self.subTest(name=name):
                record = self.record(name)
                first = prepare(self.seats(), record)
                second = prepare(self.seats(), record)
                field = first[0]
                self.assertEqual(first[2], second[2])
                self.assertEqual(field.contract_metadata, second[0].contract_metadata)
                self.assertEqual(field._actors, second[0]._actors)
                self.assertEqual(field.scene_metadata['objects'], second[0].scene_metadata['objects'])
                self.assertTrue(field.scene_metadata['objects'])
                from collections import deque
                start = next(iter(field._actors.values()))
                reached, pending = {(start.x, start.y)}, deque([(start.x, start.y)])
                while pending:
                    x, y = pending.popleft()
                    for point in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                        if field.inside(*point) and point not in field.blocked and point not in reached:
                            reached.add(point); pending.append(point)
                self.assertTrue(all((a.x, a.y) in reached for a in field._actors.values()))
                self.assertTrue(field.loot.boxes)
                self.assertEqual(field.loot.boxes, second[0].loot.boxes)
                for actor_id in field._actors:
                    self.assertNotIn((field.actor(actor_id).x, field.actor(actor_id).y), field.doors.states)
                changed = prepare(self.seats(), self.record(name, seed=902))
                self.assertNotEqual(first[2], changed[2])

    def test_frozen_policy_ignores_later_mutable_role_and_map_config(self):
        policy = json.loads((ROOT / 'config/contracts_map_profiles.json').read_text(encoding='utf-8'))
        source = Path(self.temp.name) / 'custom-policy.json'
        source.write_text(json.dumps(policy), encoding='utf-8')
        record = self.record()
        record['template']['scene_policy'] = freeze_policy(record['template'], policy_path=source)
        policy['roles']['scout']['health'] = 999
        policy['profiles']['contract_camp']['width'] = 64
        source.write_text(json.dumps(policy), encoding='utf-8')
        field, _, _, _, bot = prepare(self.seats(), record)
        self.assertEqual(field.width, 38)
        scouts = [i for i in field.actor_ids(bot) if field.contract_metadata['npc_roles'][i] == 'scout']
        self.assertTrue(all(field.actor(i).health == 45 for i in scouts))

    def test_invalid_or_changed_snapshot_and_excess_selection_rejected_before_save_mutation(self):
        before = self.rows()
        invalid = self.record()
        invalid['template']['scene_policy']['roles']['scout']['health'] += 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            prepare(self.seats(), invalid)
        invalid = self.record()
        del invalid['template']['scene_policy']
        with self.assertRaisesRegex(ValueError, 'Frozen'):
            prepare(self.seats(), invalid)
        with self.assertRaisesRegex(ValueError, 'eight'):
            prepare(self.seats(4, (1, 2, 3)), self.record())
        seats = self.seats()
        with self.assertRaisesRegex(ValueError, 'real account'):
            prepare([seats[0], seats[0]], self.record())
        with self.assertRaisesRegex(ValueError, 'real account'):
            prepare([(*seats[0][:-1], True)], self.record())
        self.assertEqual(self.rows(), before)

    def test_changed_real_selection_rejected(self):
        seat = self.seats(1)[0]
        owner, side, path, account, ticket, bot = seat
        with self.assertRaisesRegex(ValueError, 'no longer owned'):
            prepare([(owner, side, path, account, replace(ticket, actors=(999, 1)), bot)], self.record())

    def test_wounded_selection_retains_saved_health(self):
        seat = self.seats(1)[0]
        account = seat[3]
        with closing(sqlite3.connect(self.path)) as db, db:
            packet = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=2', (account,)).fetchone()[0]
            pet = decode_pet_info(packet, human_equipment=True)
            hurt = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4ab1': 1}))
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=2', (hurt, account))
        field, _, _, _, _ = prepare([seat], self.record())
        identity = next(i for i in field.actor_ids(seat[0]) if field.combat.storage_ids[i] == 2)
        self.assertEqual(field.actor(identity).health, 1)


if __name__ == '__main__':
    unittest.main()
