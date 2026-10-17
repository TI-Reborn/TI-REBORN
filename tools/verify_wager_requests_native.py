"""Execute pinned silver.dll main-room join/kick/team builders with real writers."""
from verify_arena_requests_native import run
from verify_auth_native import (ROOT, EXPECTED_SHA, emulator, put32, get32, DATA, STOP,
    return_from_stub, UC_HOOK_CODE, UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_EIP)
from tio.protocol.wagers import WagerRoomRecord,encode_room_list
import json


def read_list_item(record):
    """Real647450 numeric readers; managed string storage explicitly isolated."""
    packet = encode_room_list((record,))
    u = emulator(); u.mem_write(DATA,packet[6:]); cursor=DATA; obj=DATA+0x4000
    put32(u,0xacd0e8,cursor)
    def hook(uc,address,size,unused):
        a,d=uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)
        if address==0x6297ac:
            pointer=get32(uc,0xacd0e8)
            length=int.from_bytes(uc.mem_read(pointer,2),'little')
            raw=bytes(uc.mem_read(pointer+2,length)); assert raw==record.creator_name
            put32(uc,0xacd0e8,pointer+2+length); put32(uc,d,DATA+0x6000); return_from_stub(uc)
        elif address==0x40b47c:
            put32(uc,a,d); return_from_stub(uc)
        elif address==0x40b09c: return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook); u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x647450,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,0xacd0e8)-cursor==len(packet)-6
    actual=(get32(u,obj),bytes(u.mem_read(obj+0xd,1))[0],bytes(u.mem_read(obj+0xf,1))[0],
            bytes(u.mem_read(obj+0x11,1))[0],bytes(u.mem_read(obj+0x13,1))[0],
            bytes(u.mem_read(obj+0x15,1))[0],bytes(u.mem_read(obj+0x17,1))[0],
            bytes(u.mem_read(obj+0x19,1))[0],bytes(u.mem_read(obj+0x1b,1))[0],
            get32(u,obj+0x20),get32(u,obj+0x28))
    expected=(record.identity,record.creator_level,record.mode,record.capacity,record.members,
              record.status,record.soldiers,record.map_size,record.level_delta,record.crest_id,record.stake)
    assert actual==expected,(actual,expected)
    assert bytes(u.mem_read(obj+0x4c,1))==b'\0'
    return dict(packet_hex=packet.hex(),consumed=len(packet)-6,fields=actual,
                strings='managed storage isolated; u16 prefix derived from original6297ac')


if __name__ == '__main__':
    cases = []
    for entry, identity, side, expected in (
        (0xa089f0,42,0,'292a000000'),
        (0xa08a50,0x12345678,0,'2b78563412'),
        (0xa08ae4,42,0,'2d2a00000000'),
        (0xa08ae4,42,1,'2d2a00000001')):
        packet = run(entry,identity,side)
        assert packet.hex() == expected, (hex(entry),packet.hex())
        cases.append(dict(entry=hex(entry),identity=identity,side=side,packet_hex=packet.hex()))
    (ROOT/'evidence/wager_requests_native.json').write_text(json.dumps(
        dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases,
             list_items=[read_list_item(WagerRoomRecord(42,b'Alice',3,mode,players,1,0,soldiers,2,1,0,100))
                         for mode,players,soldiers in ((0,3,2),(1,4,3),(4,8,1))],
             team_arrow_callers=['8200f9: member.team-1, member.characterID',
                                 '8201b4: member.team+1, member.characterID']),indent=2)+'\n',encoding='utf-8')
    print('Original wager main-room request builders: 4 cases PASS')
