from contextlib import closing
import sqlite3
import struct
import unittest

import test_multi_account
from tio.implants import SLOTS
from tio.level_progression import FLOORS
from tio.owned_pets import OwnedPetStore
from tio.protocol.abilities import encode_ability_request
from tio.protocol.item_action import ItemAction, encode_item_action, item_target_option
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info


class ImplantSlotTests(unittest.TestCase):
    def test_cybernetics_refreshes_each_slot_and_installed_implant(self):
        game = test_multi_account.MultiAccountTests()
        game.setUp()
        self.addCleanup(game.doCleanups)
        game.start()
        path = game.config.database
        for owner, name in (('alice', 'Alice'), ('bob', 'Bob')):
            peer = game.handoff(game.begin(owner))
            game.enter(peer, name)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('UPDATE wallets SET credits=? WHERE account=?', (100_000, owner))
                raw, = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',
                                  (owner,)).fetchone()
                pet = decode_pet_info(raw, human_equipment=True)
                pet.fields.update({'0x8c4aef': 7, '0x8c4b05': FLOORS[6]})
                items = tuple(ItemRecord(i, template, bytes(2), 1, 0, 0, (500,)*3,
                                         bytes(4), None, bytes(3))
                              for i, template in enumerate((6100, 6101, 6102, 6103, 6120), 1))
                db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? '
                           'WHERE account=? AND pet_id=1',
                           (encode_pet_info(pet), encode_item_list(1, items), owner))
            if owner == 'alice':
                alice = peer
        pets = OwnedPetStore(path)
        other = pets.inventory('bob', 1)
        alice.send(struct.pack('<Bii', 0x1b, -154, -318))
        game.ping(alice)

        def command(packet):
            alice.send(packet)
            alice.send(b'\x70')
            replies = []
            for _ in range(1024):
                reply = alice.receive()
                if reply == b'\x9e':
                    return replies
                replies.append(reply)
            self.fail('Missing ping response')

        def check_refresh(replies, rank, active):
            self.assertTrue(any(packet[0] == 0x66 for packet in replies),
                            (rank, [packet.hex()[:64] for packet in replies]))
            profile = next(i for i, packet in enumerate(replies) if packet[0] == 0x66)
            inventory, = (i for i, packet in enumerate(replies) if packet[0] == 0x30)
            self.assertLess(profile, inventory)
            self.assertEqual(decode_pet_info(replies[profile], human_equipment=True).fields['0x8c4a42'], rank)
            self.assertEqual([item.unknown_bytes_02[1] for item in decode_item_list(replies[inventory])[1]
                              if item.equipped], active)

        command(b'\xa9\x01\x00\x00\x00')
        learn = encode_ability_request(1, 35)
        for rank, slot in enumerate(SLOTS, 1):
            wear = encode_item_action(ItemAction(1, rank, item_target_option(slot)))
            previous = pets.inventory('alice', 1)
            self.assertTrue(any(packet[0] == 0xf0 for packet in command(wear)))
            self.assertEqual(pets.inventory('alice', 1), previous)
            check_refresh(command(learn), rank, [1]*(rank-1))
            command(wear)
            self.assertEqual(tuple(item.slot for item in decode_item_list(pets.inventory('alice', 1))[1]
                                   if item.equipped), SLOTS[:rank])
        check_refresh(command(encode_ability_request(1, 35, opcode=0x90)), 0, [0]*4)
        check_refresh(command(learn), 1, [1, 0, 0, 0])
        self.assertEqual(pets.inventory('bob', 1), other)
