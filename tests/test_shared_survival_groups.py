"""Authoritative free-for-all scenes for three/four distinct saved accounts."""
from dataclasses import replace
import unittest

import test_shared_team_arena as shared_fixture
from tio.protocol.battle_turn import encode_end_turn


class SharedSurvivalDuelTests(unittest.TestCase):
    send = shared_fixture.SharedTeamTests.send

    def setUp(self):
        shared_fixture.SharedTeamTests.setUp(self)
        self.hub = shared_fixture.TeamArena(clock=lambda: self.now, survival_duels=True)

    def add_fighters(self, index: int, count: int) -> None:
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.item_list import encode_item_list
        from tio.protocol.pet_info import decode_pet_info, encode_pet_info
        account = self.sessions[index].account
        store = OwnedPetStore(self.path)
        first = decode_pet_info(store.list(account)[0][1], human_equipment=True)
        for slot in range(2, count + 1):
            fighter = replace(first, fields={**first.fields, '0x8c43eb': slot, '0x8c44a6': slot})
            store.ensure(account, encode_pet_info(fighter), encode_item_list(slot, ()), human=True)

    def test_two_owners_keep_all_three_fighters_in_authoritative_scene(self):
        self.add_fighters(0, 3)
        self.add_fighters(2, 3)
        self.add_fighters(3, 2)
        for index, count in ((0, 3), (1, 1), (3, 2)):
            self.send(index, bytes((0xba, 3, 0, count)))
        self.now = 100
        self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.send(2, bytes((0xba, 3, 0, 3)))
        owners = [self.hub.identities[self.sessions[i]] for i in (0, 2)]
        battle = self.hub.battles[owners[0]]
        self.assertIs(battle, self.hub.battles[owners[1]])
        self.assertEqual(battle['humans'], set(owners))
        self.assertFalse(battle['bots'])
        self.assertEqual([len(battle['field'].actor_ids(owner)) for owner in owners], [3, 3])
        self.assertEqual({len(ticket.actors) for ticket in self.hub.survival_queue.tickets.values()}, {1, 2})


class SharedSurvivalGroupsTests(unittest.TestCase):
    send=shared_fixture.SharedTeamTests.send

    def setUp(self):
        shared_fixture.SharedTeamTests.setUp(self)
        self.hub.survival_queue.group_wait=3

    def join(self,count):
        for index in range(count):self.send(index,b'\xba\x03\0\1')
        return [self.hub.identities[s] for s in self.sessions[:count]]

    def test_four_distinct_accounts_share_a_free_for_all_and_complete_turn_circle(self):
        owners=self.join(4)
        battle=self.hub.battles[owners[0]];field=battle['field']
        self.assertEqual(battle['humans'],set(owners))
        self.assertFalse(battle['bots'])
        self.assertEqual(len(field.living_sides()),4)
        self.assertFalse(any(field.allied(a,b) for a in owners for b in owners if a!=b))
        cells=[(a.x,a.y) for a in field._actors.values()]
        self.assertEqual(len(set(cells)),4)
        self.assertTrue(all(field.inside(*p) and p not in field.blocked for p in cells))
        self.assertGreater(min(max(abs(a[0]-b[0]),abs(a[1]-b[1]))
                               for a in cells for b in cells if a!=b),4)
        for index in range(3):self.send(index,b'\x36');self.hub.tick()
        self.assertFalse(battle['arena']._turns)
        self.send(3,b'\x36');self.hub.tick()
        visited=[]
        for _ in owners:
            turn=battle['arena']._turns[battle['room'].room_id][0]
            visited.append(turn)
            index=owners.index(turn)
            self.send(index,encode_end_turn());self.hub.tick()
        self.assertEqual(set(visited),set(owners))
        self.assertEqual(len(visited),4)
        # Losing one owner cannot finish a four-way match prematurely.
        gone=owners[0]
        for identity in field.actor_ids(gone):field._actors[identity]=replace(field.actor(identity),health=0)
        self.hub.tick()
        self.assertFalse(battle['finished'])
        self.assertEqual(len(field.living_sides()),3)

    def test_three_players_wait_for_deadline_and_need_all_three_loads(self):
        owners=self.join(3)
        self.assertFalse(self.hub.battles)
        self.now=2.99;self.hub.tick();self.assertFalse(self.hub.battles)
        self.now=3;self.hub.tick()
        battle=self.hub.battles[owners[0]]
        self.assertEqual(len(battle['field'].living_sides()),3)
        self.assertFalse(self.hub.survival_queue.tickets)
        self.send(0,b'\x36');self.send(1,b'\x36');self.hub.tick()
        self.assertFalse(battle['arena']._turns)
        self.send(2,b'\x36');self.hub.tick()
        self.assertTrue(battle['arena']._turns)

    def test_cancelled_fourth_player_is_not_in_three_player_scene(self):
        owners=self.join(3)
        self.send(2,b'\xba\x07\0')
        self.send(3,b'\xba\x03\0\1')
        self.now=3;self.hub.tick()
        battle=self.hub.battles[owners[0]]
        self.assertNotIn(owners[2],battle['humans'])
        self.assertEqual(len(battle['humans']),3)
        self.assertTrue(self.hub.busy(self.sessions[2]))

    def test_duplicate_human_accounts_cannot_supply_two_survival_seats(self):
        self.sessions[1].account=self.sessions[0].account
        self.join(2);self.now=3;self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.assertEqual(len(self.hub.survival_queue.tickets),2)

    def test_lone_player_gets_transient_naked_bot_at_sixty_seconds_and_can_start(self):
        from tio.protocol.item_list import decode_item_list
        from tio.protocol.battle_turn import encode_end_turn
        owners=self.join(1)
        self.now=59.999;self.hub.tick();self.assertFalse(self.hub.battles)
        self.now=60;self.hub.tick()
        battle=self.hub.battles[owners[0]];field=battle['field']
        self.assertEqual(battle['humans'],set(owners))
        self.assertEqual(len(battle['bots']),1)
        self.assertEqual(len(field.living_sides()),2)
        bot=next(iter(battle['bots']))
        for identity in field.actor_ids(bot):
            self.assertFalse(decode_item_list(field.combat.inventories[identity])[1])
            self.assertNotIn(identity,field.combat.persistence)
        self.assertFalse(self.hub.survival_queue.tickets)
        self.send(0,b'\x36');self.hub.tick()
        self.assertTrue(battle['arena']._turns)
        self.send(0,encode_end_turn());self.hub.tick()
        self.assertFalse(battle.get('faulted'))
        self.assertTrue(any(field.bot_crates.values()) or any(
            field.actor(i).action_points==0 for i in field.actor_ids(bot)))

    def test_unready_player_does_not_get_bot_and_readiness_restarts_minute(self):
        owners=self.join(1)
        self.now=30;self.send(0,b'\xba\x07\0')
        self.now=100;self.hub.tick();self.assertFalse(self.hub.battles)
        self.send(0,b'\xba\x07\1')
        self.now=159.99;self.hub.tick();self.assertFalse(self.hub.battles)
        self.now=160;self.hub.tick();self.assertIn(owners[0],self.hub.battles)

    def test_human_at_bot_deadline_takes_precedence(self):
        owners=self.join(1)
        self.now=60;self.send(1,b'\xba\x03\0\1')
        battle=self.hub.battles[owners[0]]
        self.assertEqual(len(battle['humans']),2)
        self.assertFalse(battle['bots'])

    def test_bot_cannot_inherit_captains_equipment_or_modify_its_saved_inventory(self):
        from contextlib import closing
        import sqlite3
        from test_tactical_bot import item
        from tio.protocol.item_list import encode_item_list,decode_item_list
        bag=encode_item_list(1,(item(10,301,equipped=True,slot=16),item(11,3,40)))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(bag,self.sessions[0].account))
        owners=self.join(1);self.now=60;self.hub.tick()
        battle=self.hub.battles[owners[0]];field=battle['field']
        human=field.actor_ids(owners[0])[0];bot=field.actor_ids(next(iter(battle['bots'])))[0]
        self.assertEqual(len(decode_item_list(field.combat.inventories[human])[1]),2)
        self.assertFalse(decode_item_list(field.combat.inventories[bot])[1])
        self.assertIn(bot,field.combat.weight_capacities)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(self.sessions[0].account,)).fetchone()[0],bag)


if __name__=='__main__':unittest.main()
