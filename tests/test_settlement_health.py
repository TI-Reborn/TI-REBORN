"""Shared battle settlement retains wounds without saving temporary HP capacity."""
from dataclasses import replace
import unittest

import test_shared_team_arena as fixture
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info


class SettlementHealthTests(unittest.TestCase):
    setUp = fixture.SharedTeamTests.setUp
    paired = fixture.SharedTeamTests.paired
    create = fixture.SharedTeamTests.create
    send = fixture.SharedTeamTests.send

    def boosted(self, delta):
        owners, battle = self.paired()
        field = battle['field']
        identity = field.actor_ids(owners[0])[0]
        actor = field.actor(identity)
        base = actor.max_health
        from tio.combat_completion import initialize
        state = initialize(field.combat)
        state['health_capacity'][identity] = {'base': base, 'maximum': base + 20, 'expiry': 10}
        field._actors[identity] = replace(actor, max_health=base + 20, health=base + delta)
        return owners, battle, identity, base

    def health(self, index):
        packet = OwnedPetStore(self.path).list(self.sessions[index].account)[0][1]
        fields = decode_pet_info(packet, human_equipment=True).fields
        return fields['0x8c4ab1'], fields['0x8c4a07']

    def finish(self, battle, identity):
        field = battle['field']
        for key, actor in tuple(field._actors.items()):
            if key != identity:
                field._actors[key] = replace(actor, health=0)
        self.hub.finish(battle)

    def test_finish_caps_saved_health_at_permanent_maximum(self):
        _, battle, identity, base = self.boosted(10)
        self.finish(battle, identity)
        self.assertEqual(self.health(0), (base, base))

    def test_finish_preserves_real_wounds_below_permanent_maximum(self):
        _, battle, identity, base = self.boosted(-11)
        self.finish(battle, identity)
        self.assertEqual(self.health(0), (base - 11, base))

    def test_escape_caps_saved_health_without_changing_other_account(self):
        _, _, _, base = self.boosted(10)
        other = OwnedPetStore(self.path).list(self.sessions[1].account)
        self.send(0, b'\x2a\x01')
        self.assertEqual(self.health(0), (base, base))
        self.assertEqual(OwnedPetStore(self.path).list(self.sessions[1].account), other)


if __name__ == '__main__':
    unittest.main()
