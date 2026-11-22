"""Solo admission and journaled boss loot on disposable real accounts."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from collections import Counter
import sqlite3
import unittest
from unittest.mock import patch

import test_contracts_combat as combat_fixture
from server.contracts_ui import execute, snapshot
from server.team_arena import TeamArena
from server.contracts_service import ContractsService
from server.battle_journal import BattleJournal
from tio.contract_loot import roll_upgrade, stage_boss_loot, UPGRADE_WEIGHTS
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.battle_position import BattlePositionRequest, encode_position_request
from tio.protocol.battle_loot import LootTransfer, encode_loot_transfer
from tio.protocol.item_list import decode_item_list
from tio.pve_contracts import validate_catalog


class ExpansionTests(unittest.TestCase):
    setUpClass = classmethod(combat_fixture.ContractsCombatTests.setUpClass.__func__)
    tearDownClass = classmethod(combat_fixture.ContractsCombatTests.tearDownClass.__func__)
    setUp = combat_fixture.ContractsCombatTests.setUp
    rows = combat_fixture.ContractsCombatTests.rows
    clear_enemies = combat_fixture.ContractsCombatTests.clear_enemies
    group = combat_fixture.ContractsCombatTests.group
    start = combat_fixture.ContractsCombatTests.start

    def collect_boss(self, battle, hub=None):
        hub = hub or self.hub
        with hub.journal.unit(battle):
            field = battle['field']
            stage_boss_loot(field)
            position = field.contract_metadata['boss_position']
            item, = field.loot.boxes[position]
            owner = min(battle['humans'])
            actor = field.actor(field.actor_ids(owner)[0])
            field._actors[actor.actor_id] = replace(actor, x=position[0], y=position[1], action_points=20)
            battle['arena']._turns[battle['room'].room_id] = (owner, frozenset((actor.actor_id,)), self.now+60)
            hub.perform_action(battle, owner, encode_position_request(BattlePositionRequest(actor.actor_id, *position)))
            hub.perform_action(battle, owner, encode_loot_transfer(LootTransfer(actor.actor_id, *position, (), ((item.instance_id, 1),))))

    def clear_and_collect(self, battle):
        self.clear_enemies(battle)
        self.collect_boss(battle)

    def solo(self, template='solo_dogs'):
        self.service.parties.create('alice', (1,))
        self.contract = self.service.contracts.accept(
            self.service.parties.info('alice'), 'alice', template, 'solo-request')
        self.service.parties.ready('alice', True)
        target = self.contract['target']
        import struct
        self.service.travel.travel('alice', struct.pack('<Bii', 0x1b, target['x'], target['y']))
        self.now = self.service.travel.route(self.contract['party_id'])[5] + .1
        self.assertTrue(self.service.travel.arrive('alice'))
        battle = self.hub.start_contract(self.sessions[0], self.service)
        self.hub.handle(self.sessions[0], b'\x36')
        self.hub.tick()
        return battle

    def test_solo_templates_admit_one_real_owner_and_native_species(self):
        for template, resource in (('solo_dogs', 103), ('solo_mutants', 100), ('solo_raiders', 1)):
            with self.subTest(template=template):
                battle = self.solo(template)
                self.assertEqual(battle['humans'], {self.owners[0]})
                self.assertEqual(set(battle['field'].combat.resources[i]
                    for i in battle['field'].contract_metadata['npc_roles']), {resource})
                self.hub.abort_contract(battle, 'fixture-finished')
                self.service.parties.disband('alice')

    def test_group_size_is_checked_against_template(self):
        self.service.parties.create('alice', (1,))
        with self.assertRaises(ValueError):
            self.service.contracts.accept(self.service.parties.info('alice'), 'alice', 'camp', 'no')
        invite = self.service.parties.invite('alice', 'bravo')
        self.service.parties.accept('bravo', invite['id'], (1,))
        with self.assertRaises(ValueError):
            self.service.contracts.accept(self.service.parties.info('alice'), 'alice', 'solo_dogs', 'no')
        record = self.service.contracts.accept(self.service.parties.info('alice'), 'alice', 'camp', 'yes')
        self.assertEqual(record['template']['reward'], dict(credits=1500, experience=600))

    def test_living_wounded_fighter_can_start_contract(self):
        from tio.protocol.pet_info import decode_pet_info, encode_pet_info
        self.group()
        with closing(sqlite3.connect(self.path)) as db, db:
            packet, = db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()
            pet = decode_pet_info(packet, human_equipment=True)
            pet.fields['0x8c4ab1'] -= 1
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1", (encode_pet_info(pet),))
        battle = self.hub.start_contract(self.sessions[0], self.service)
        actor = battle['field'].actor(battle['field'].actor_ids(self.owners[0])[0])
        self.assertLess(actor.health, actor.max_health)

    def test_solo_ui_creates_party_and_keeps_other_accounts_private(self):
        result = execute(self.service, self.sessions[0], dict(action='take', value='solo_dogs', request_id='a'*32))
        self.assertEqual(len(result['party']['members']), 1)
        self.assertTrue(result['permissions']['ready'])
        self.assertIsNone(snapshot(self.service, self.sessions[1])['contract'])
        self.assertEqual(execute(self.service, self.sessions[0], dict(action='take', value='solo_dogs', request_id='a'*32))['contract'], result['contract'])

    def test_boss_bag_blocks_finish_and_native_pickup_is_persistent_once(self):
        battle = self.solo()
        self.clear_enemies(battle)
        self.hub.tick()
        self.assertFalse(battle['finished'])
        field = battle['field']
        position = field.contract_metadata['boss_position']
        loot = field.loot.boxes[position]
        self.assertEqual(len(loot), 1)
        self.assertLessEqual(loot[0].unknown_bytes_02[0], 10)
        self.hub.tick()
        self.assertEqual(field.loot.boxes[position], loot)
        actor = field.actor(field.actor_ids(self.owners[0])[0])
        with self.hub.journal.unit(battle):
            field._actors[actor.actor_id] = replace(actor, x=position[0], y=position[1], action_points=20)
            battle['arena']._turns[battle['room'].room_id] = (self.owners[0], frozenset((actor.actor_id,)), self.now+60)
        opened = encode_position_request(BattlePositionRequest(actor.actor_id, *position))
        self.hub.handle(self.sessions[0], opened)
        packet = encode_loot_transfer(LootTransfer(actor.actor_id, *position, (), ((loot[0].instance_id, 1),)))
        self.hub.handle(self.sessions[0], packet)
        self.hub.handle(self.sessions[0], packet)
        saved = decode_item_list(next(inv for i, _, inv in OwnedPetStore(self.path).list('alice') if i == 1))[1]
        self.assertEqual(sum(i.instance_id == loot[0].instance_id for i in saved), 1)
        self.hub.tick()
        self.assertFalse(battle['finished'])  # The physical crates still contain supplies.
        self.hub.finish_contract(battle, abandon_loot=True)
        self.assertTrue(battle['finished'])

    def test_probability_table_has_exact_percentages_and_rejects_invalid_rolls(self):
        self.assertEqual(Counter(roll_upgrade(n) for n in range(10_000)), dict(enumerate(UPGRADE_WEIGHTS)))
        for roll in (-1, 10_000, True, 1.5):
            with self.assertRaises(ValueError):
                roll_upgrade(roll)

    def test_anti_experience_suppresses_fixed_and_combat_xp_for_contracts(self):
        import time
        from tio.premium import purchase, encode_purchase, OFFERS
        purchase(self.path, 'alice', encode_purchase(3, OFFERS[3][1]), now=int(time.time()))
        battle = self.start(selected=(1, 2))
        field = battle['field']
        owner = self.owners[0]
        with self.hub.journal.unit(battle):
            field.combat.experience.damage(field.combat, field.actor(field.actor_ids(owner)[0]),
                field.actor(field.actor_ids(next(iter(battle['bots'])))[0]), 10)
        self.clear_and_collect(battle)
        before = WalletStore(self.path).ensure('alice').credits
        self.hub.finish_contract(battle, abandon_loot=True)
        with closing(sqlite3.connect(self.path)) as db:
            gains = list(db.execute('SELECT gain FROM experience_battle_audit WHERE account=? AND match_id=?',
                                   ('alice', battle['match_id'])))
        self.assertEqual(gains, [(0,), (0,)])
        self.assertEqual(WalletStore(self.path).ensure('alice').credits - before, 1500)

    def test_pickup_and_checkpoint_failure_roll_back_together(self):
        battle = self.solo()
        self.clear_enemies(battle)
        self.hub.tick()
        before = self.rows('owned_pets')
        with patch('tio.battle_checkpoints.save', side_effect=RuntimeError('checkpoint failed')):
            with self.assertRaisesRegex(RuntimeError, 'checkpoint failed'):
                self.collect_boss(battle)
        self.assertEqual(self.rows('owned_pets'), before)
        self.assertFalse(battle['finished'])
        self.assertTrue(battle['field'].loot.boxes[battle['field'].contract_metadata['boss_position']])
        self.collect_boss(battle)
        self.hub.finish_contract(battle, abandon_loot=True)
        self.assertTrue(battle['finished'])

    def test_boss_death_during_live_turn_commits_backpack_before_other_enemies_die(self):
        from tio.battle_snapshot import loads
        battle = self.start()
        with self.hub.journal.unit(battle):
            field = battle['field']
            boss = field.contract_metadata['boss']
            field._actors[boss] = replace(field.actor(boss), health=0)
        self.hub.tick()
        self.assertGreater(len(field.living_sides()), 1)
        with closing(sqlite3.connect(self.path)) as db:
            payload, = db.execute('SELECT payload FROM battle_checkpoints WHERE match_id=?', (battle['match_id'],)).fetchone()
        saved = loads(payload)[0]['battle']['field']
        self.assertEqual(saved.contract_metadata['boss_item'], field.contract_metadata['boss_item'])

    def test_restart_retains_shared_bag_and_cannot_generate_or_claim_it_twice(self):
        battle = self.start()
        self.clear_enemies(battle)
        self.hub.tick()
        position = battle['field'].contract_metadata['boss_position']
        item, = battle['field'].loot.boxes[position]
        recovered = TeamArena(clock=self.clock)
        service = ContractsService(recovered, self.path, clock=self.clock)
        recovered.journal = BattleJournal(recovered, self.path, wall=self.clock)
        self.assertEqual(recovered.journal.recover(), [battle['match_id']])
        restored = recovered.battles[self.owners[0]]
        self.assertIs(restored, recovered.battles[self.owners[1]])
        self.assertEqual(restored['field'].loot.boxes[position], (item,))
        for session in self.sessions[:2]:
            self.assertTrue(recovered.resume(session))
            recovered.handle(session, b'\x36')
        self.collect_boss(restored, recovered)
        next_hub = TeamArena(clock=self.clock)
        next_hub.journal = BattleJournal(next_hub, self.path, wall=self.clock)
        self.assertEqual(next_hub.journal.recover(), [battle['match_id']])
        again = next_hub.battles[self.owners[0]]
        self.assertEqual(again['field'].loot.boxes[position], ())
        next_hub.finish_contract(again, abandon_loot=True)
        self.assertTrue(again['finished'])
        all_items = [i for account in ('alice', 'bravo') for _, _, raw in OwnedPetStore(self.path).list(account)
                     for i in decode_item_list(raw)[1]]
        self.assertEqual(sum(i.instance_id == item.instance_id for i in all_items), 1)


if __name__ == '__main__':
    unittest.main()
