"""Pin group1 RTTI field offsets/getter addresses to original numeric readers."""
from verify_auth_native import *

if __name__ == '__main__':
    u=emulator()
    fields=(('level',0x61c289,0,0x61c43f,0x64c64c),
            ('equipStatus',0x61c2b3,2,0x61c46d,0x64c6a8),
            ('injureStatus',0x61c2e9,4,0x61c4af,0x64c708),
            ('npcId',0x61c321,6,0x61c4de,0x64c768),
            ('avatarId',0x61c34b,8,0x61c516,0x64c7c8),
            ('rank',0x61c37b,0x10,0x61c553,0x64c824),
            ('militaryRank',0x61c3a3,0x18,0x61c594,0x64c880),
            ('pointsToNextRank',0x61c3db,0x20,0x61c5e1,0x64c8dc))
    results=[]
    for name,field,offset,method,getter in fields:
        expected=('f'+name).encode()
        assert bytes(u.mem_read(field,len(expected)))==expected
        assert get32(u,field-6)==offset
        assert get32(u,method-5)==getter
        expected=('get'+name[0].upper()+name[1:]).encode()
        assert bytes(u.mem_read(method,len(expected)))==expected
        results.append({'name':name,'native_offset':hex(offset),'getter':hex(getter)})
    (ROOT/'evidence/battle_member_rtti.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'fields':results},indent=2)+'\n')
    print('Original soldier RTTI: 8 field offsets/getter identities PASS')
