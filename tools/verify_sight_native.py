"""Pin original sight packet readers, setter and HUD getter to the client hash."""
from verify_auth_native import *
import struct


if __name__ == '__main__':
    u=emulator()
    def call(site,target):
        assert bytes(u.mem_read(site,5))==b'\xe8'+struct.pack('<i',target-site-5)
    call(0x8c567f,0x605d68) # BattleSoldier3B: byte reader
    call(0x8c5689,0xa86df8) # setSight
    call(0x8c4a1b,0x605d68) # PetInfo66: same byte reader
    call(0x8c4a28,0xa86df8)
    call(0x9b521d,0xa86de4) # HUD obtains decoded sight
    call(0x9b5229,0x9b7a7c) # value sent to HUD field0
    assert bytes(u.mem_read(0x9b5227,2))==b'\x33\xd2'
    assert bytes(u.mem_read(0xa818c8,8))==b'getSight'
    assert bytes(u.mem_read(0xa81d9b,8))==b'setSight'
    result={'sha256':EXPECTED_SHA,'method':__doc__,
            'battle_3b_sight':'0x8c567f u8 ->0xa86df8 setSight',
            'city_66_sight':'0x8c4a1b u8 ->0xa86df8 setSight',
            'hud':'0x9b521d getSight ->0x9b5229 HUD field0',
            'human_radius':9,'human_basis':'User instruction; base/quest/tut_1000.xml:53 also says nine cells in tutorial',
            'dog_radius':12,'dog_basis':'Provisional local value; original per-species sight not established'}
    (ROOT/'evidence/sight_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original sight byte readers, setter and HUD getter: PASS')
