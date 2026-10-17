"""City-session services proven against this TI build.

70 is emitted by6d4b03;9E dispatch6d4c08 calls6d4b44, which reads no
payload and updates the reply flag and elapsed time. Catalog requests61,73,
B102 use configured browsing data; unsupported transactions remain unhandled.
"""
from .binary import PacketError
from .arena import encode_room_list


def city_service_reply(packet: bytes, catalogs=None) -> bytes | None:
    if not packet:
        raise PacketError('Empty application packet')
    if packet[0] == 0x70:
        if packet != b'\x70':
            raise PacketError('Ping has no payload')
        return b'\x9e'
    if packet[:2] == b'\xba\x01':
        if len(packet) != 2:
            raise PacketError('Arena list request has no payload')
        # No arena rooms exist yet. Do not fabricate entries or acknowledge joins.
        return encode_room_list()
    if catalogs is not None:
        if packet[0] == 0x61:
            if packet != b'\x61':
                raise PacketError('Pet shop request has no payload')
            return catalogs.pet_shop()
        if packet[0] == 0x73:
            if len(packet) != 2:
                raise PacketError('Item shop request has one category byte')
            return catalogs.item_shop(packet[1])
        if packet[0] == 0x76:
            from .premium_shop import decode_premium_request
            return catalogs.premium_shop(decode_premium_request(packet))
        if packet == b'\xb1\x02':
            return catalogs.service_shop()
    return None
