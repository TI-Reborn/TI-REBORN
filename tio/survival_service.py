"""Survival search admission and cancellation for the original BA UI.

BA03 category 0 is observed from the physical Survival tab. Search IDs are
local transient identifiers, distinct from combat rooms. Human searches remain queued until the shared server prepares a complete scene.
"""
from .matchmaking import SurvivalQueue
from .protocol.arena import ArenaMember, ArenaMemberPet, encode_member_list, decode_remove_request
from .protocol.pet_info import decode_pet_info
from .protocol.binary import Reader, Writer, PacketError


class SurvivalService:
    def __init__(self, **policy):
        self.queue = SurvivalQueue(**policy)
        self.search_ids = {}
        self._rosters = {}
        self.modes = {}
        self._next_id = 1

    def join(self, character_id, name, packet, roster):
        roster = tuple(roster)
        reader = Reader(packet)
        if reader.read(2) != b'\xba\x03':
            raise PacketError('Expected Arena search BA03')
        category, count = reader.u8(), reader.u8()
        reader.finish()
        if category not in (0,1,4):
            raise ValueError('This battle mode requires its own location menu')
        from .battle_modes import mode_rules, level_band
        mode_rules(category).validate(count)
        if character_id in self.modes and self.modes[character_id] != category:
            raise ValueError('Cancel the existing search before switching modes')
        # Validate the full request and serialization before changing the queue.
        candidate = SurvivalQueue(clock=self.queue.clock)
        ticket = candidate.join(character_id, roster, mode=category)
        if count != len(ticket.actors):
            raise ValueError('Search count does not match the saved squad')
        if len({level_band(level) for level in ticket.levels}) != 1:
            raise ValueError('Team fighters must belong to the same level range')
        search_id = self.search_ids.get(character_id, self._next_id)
        fields = {owner: decode_pet_info(p, human_equipment=int.from_bytes(p[5:9], 'little') in (1, 2, 6)).fields
                  for owner, p, _ in roster}
        # BA0B writes the same soldierInfo offsets as room25: level, NPC,
        # avatar, rank, military rank and points. Native BA0B rank is 1-based.
        # Remaining two integers and crest/avatar use local zero defaults.
        pets = tuple(ArenaMemberPet(fields[a]['0x8c4aef'], 1, 0,
                     (fields[a]['0x8c446f'], 0, max(1,fields[a]['0x8c4bbc']),
                      fields[a]['0x8c4bd0'], fields[a]['0x8c4bf6'], 0, 0), fields[a]['0x8c4489'])
                     for a in ticket.actors)
        reply = encode_member_list(search_id, 0, (ArenaMember(character_id, name, 0, max(ticket.levels), 1, pets),))
        self.queue.join(character_id, roster, mode=category)
        self._rosters[character_id] = roster
        self.modes[character_id] = category
        if character_id not in self.search_ids:
            self.search_ids[character_id] = search_id
            self._next_id += 1
        return reply

    def set_ready(self, character_id, packet):
        if packet not in (b'\xba\x07\0', b'\xba\x07\1'):
            raise PacketError('Expected Arena readiness BA07 boolean')
        if character_id not in self.search_ids:
            raise ValueError('Character is not searching')
        ready = packet[2]
        reply = (Writer().u8(0xba).u8(8).u32(self.search_ids[character_id])
                 .u32(character_id).u8(ready).build())
        if ready:
            self.queue.join(character_id, self._rosters[character_id], mode=self.modes[character_id])
        else:
            self.queue.cancel(character_id)
        return reply

    def cancel(self, character_id, packet):
        request = decode_remove_request(packet)
        if request.character_id != character_id or request.kick:
            raise ValueError('Only own search cancellation is supported')
        reply = encode_member_list(0xffffffff, 0, ())
        self.disconnected(character_id)
        return reply

    def disconnected(self, character_id):
        self.queue.cancel(character_id)
        self.search_ids.pop(character_id, None)
        self._rosters.pop(character_id, None)
        self.modes.pop(character_id, None)

    def searching(self, character_id):
        return character_id in self.search_ids
