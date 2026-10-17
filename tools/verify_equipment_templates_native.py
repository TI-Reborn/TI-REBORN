"""Execute original C5 builders and list/view readers, with UI/allocator stubs.

Primitive readers/writers and template records execute unchanged. Managed
string allocation/copy, UTF8 conversion and GUI updates are isolated, not a
claim of visual verification in a running client.
"""
from verify_auth_native import *
from dataclasses import asdict, replace
from tio.protocol.equipment_templates import *


def build(entry, first, second, template=None):
    u = emulator()
    obj, handle, vt, flush = DATA+0x1000, DATA+0x3000, DATA+0x3100, DATA+0x3200
    put32(u, handle, obj); put32(u, obj, vt); put32(u, vt, flush)
    put32(u, 0xac600c, handle)
    put32(u, 0xad039c, obj)
    if template is not None:
        name = template.name.encode('utf-16le')
        u.mem_write(DATA+0xa000, name+b'\0\0'); put32(u, DATA+0x9ffc, len(name))
        put32(u, 0xac4a14, DATA+0xa000)
        put32(u, 0xac4a20, template.level); put32(u, 0xac4a1c, template.npc_type)
        put32(u, 0xac4a3c, DATA+0x9000)
        u.mem_write(DATA+0x9280, bytes((template.remove_extra,)))
        for n, e in enumerate(template.elements):
            control = DATA+0x4000+0x400*n if n < 7 else DATA+0xb000
            setting = DATA+0x6000+0x400*n if n < 7 else DATA+0xb800
            if n < 7:
                put32(u, 0xad0364+n*4, control); put32(u, 0xad0380+n*4, setting)
            put32(u, control+0x2b0, e.object_id); put32(u, control+0x290, e.item_id)
            put32(u, control+0x2a4, e.count); u.mem_write(control+0x2d6, bytes((e.damage,)))
            u.mem_write(setting+0x2b0, struct.pack('<H',3)); put32(u, setting+0x2b8, e.setting & 0xffffffff)
        put32(u, 0xad0358, DATA+0x9400); put32(u, DATA+0x9408, len(template.elements)-7)
    def hook(uc, address, size, user):
        if address == 0x6748b0:
            uc.reg_write(UC_X86_REG_EAX, handle); return_from_stub(uc)
        elif address in (flush, 0x4244b4, 0x40c1bc, 0x43b31c, 0x9cfca0, 0x40b0fc, 0x435664):
            return_from_stub(uc)
        elif template is not None and address == 0x40c05c:
            put32(uc, uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX)); return_from_stub(uc)
        elif template is not None and address in (0x40b1a0,0x40b0e4,0x40b09c):
            return_from_stub(uc)
        elif template is not None and address in (0x932fb0,0x9340e8):
            assert uc.reg_read(UC_X86_REG_EDX) == 0
            uc.reg_write(UC_X86_REG_EAX, DATA+(0xb000 if address == 0x932fb0 else 0xb800)); return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, first); u.reg_write(UC_X86_REG_EDX, second)
    u.emu_start(entry, STOP, count=10000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    packet = bytes(u.mem_read(obj+4, get32(u, obj+0x1004)))
    return packet


def consume_view(t):
    u = emulator(); obj, array = DATA+0x3000, DATA+0x4000
    packet = encode_view(t)
    u.mem_write(DATA, packet)
    put32(u, 0xacd0e8, DATA+2)
    strings = {}
    def hook(uc, address, size, user):
        a, d = uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX)
        if address == 0x431a9c:  # UTF8 encoder object
            uc.reg_write(UC_X86_REG_EAX, DATA+0x8000); return_from_stub(uc)
        elif address == 0x431944:  # string allocation/conversion only
            sp = uc.reg_read(UC_X86_REG_ESP)
            dest, count = get32(uc, sp+4), get32(uc, sp+8)
            strings[DATA+0x9000] = bytes(uc.mem_read(d, count)).decode('utf-8')
            put32(uc, dest, DATA+0x9000)
            return_from_stub(uc); uc.reg_write(UC_X86_REG_ESP, sp+12)
        elif address == 0x40b47c:
            put32(uc, a, d); return_from_stub(uc)
        elif address == 0x646804:  # bounded managed array allocation
            assert d == len(t.elements)
            put32(uc, a+12, array); put32(uc, a+16, d); put32(uc, a+20, DATA+0x7000)
            return_from_stub(uc)
        elif address == 0x40b09c:
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x646260, STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert get32(u, 0xacd0e8) == DATA+len(packet)
    assert strings[get32(u, obj)] == t.name
    assert bytes(u.mem_read(obj+5, 6)) == bytes((t.level, 1, t.npc_type, 1, t.remove_extra, 1))
    for n, e in enumerate(t.elements):
        p = array+n*36
        actual = (get32(u,p), get32(u,p+8), get32(u,p+16),
                  *struct.unpack('<b', u.mem_read(p+21,1)),
                  *struct.unpack('<b', u.mem_read(p+23,1)),
                  u.mem_read(p+25,1)[0], *struct.unpack('<H',u.mem_read(p+28,2)),
                  *struct.unpack('<H',u.mem_read(p+32,2)))
        assert actual == tuple(asdict(e).values()), (actual, e)
        assert all(u.mem_read(p+offset,1)[0] == 1 for offset in (4,12,20,22,24,26,30,34))
    return {'packet_hex': packet.hex(), 'elements': len(t.elements), 'consumed': len(packet)-2}


def consume_list(entries):
    u = emulator(); packet = encode_list(entries); u.mem_write(DATA, packet)
    strings = {0: ''}; cursor = DATA+0x5000; rows = []; end_pointer = []
    def allocate(uc, value):
        nonlocal cursor
        cursor += 512; strings[cursor] = value
        return cursor
    def hook(uc, address, size, user):
        a, d = uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX)
        if address in (0x40c048, 0x40c05c, 0x40b4f0):
            put32(uc, a, d); return_from_stub(uc)
        elif address == 0x40bf90:
            put32(uc, a, allocate(uc, chr(d & 65535))); return_from_stub(uc)
        elif address == 0x40c164:
            put32(uc, a, allocate(uc, strings[get32(uc,a)]+strings[d])); return_from_stub(uc)
        elif address == 0x40c8cc or address == 0x92eb28:
            uc.mem_write(a, bytes(12)); return_from_stub(uc)
        elif address == 0x931f6c:
            rows.append((get32(uc,d), strings[get32(uc,d+4)], *uc.mem_read(d+8,2)))
            return_from_stub(uc)
        elif address == 0x92f519:
            end_pointer.append(get32(uc, uc.reg_read(UC_X86_REG_EBP)-16))
        elif address in (0x932994, 0x40c9a4, 0x40b09c, 0x40b0e4, 0x40b0fc,
                         0x40c1bc, 0x43b31c, 0x9cfca0, 0x435664):
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, DATA+2)
    u.emu_start(0x92f4b8, STOP, count=40000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert end_pointer == [DATA+len(packet)]
    assert rows == [(i,t.name,t.level,t.npc_type) for i,t in entries], rows
    assert bytes(u.mem_read(0xac4a04,1)) == b'\1'
    return {'packet_hex':packet.hex(), 'records':rows, 'loaded_flag':1}


if __name__ == '__main__':
    t = Template('Комплект', 7, 6, 1, tuple(Element(1000+n, 200+n, 40+n, n%4, 10+n, n%3, 101+n, 200+n) for n in range(8)))
    builders = []
    for entry, action in ((0x92ec28,None), (0x92ec5c,2), (0x92ec9c,0), (0x92edec,4), (0x92eda0,5)):
        packet = build(entry, 41, 6)
        result = decode_request(packet)
        assert result[:3] == ((None,0,0) if action is None else (action,41,0 if action == 2 else 6)), result
        builders.append({'entry':hex(entry),'packet_hex':packet.hex()})
    for action, identity in ((3,0),(1,41)):
        packet = build(0x92ee38, action, identity, t)
        result = decode_request(packet)
        assert result[:3] == (action,identity,0)
        expected = replace(t,elements=tuple(Element(object_id=e.object_id,setting=e.setting)
                    if n in GEAR_SLOTS else Element(item_id=e.item_id,count=e.count,damage=e.damage,setting=e.setting)
                    for n,e in enumerate(t.elements)))
        assert result[3] == expected,(result[3], expected)
        builders.append({'entry':'0x92ee38','action':action,'packet_hex':packet.hex()})
    report = {'sha256':EXPECTED_SHA, 'method':__doc__, 'builders':builders,
              'lists':[consume_list(()), consume_list(((41,t), (42,replace(t,name='Dog',npc_type=1))))],
              'views':[consume_view(t), consume_view(replace(t,elements=(Element(),)*7))]}
    (ROOT/'evidence/equipment_templates_native.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Original C5: 7 builders, 2 list readers and 2 view readers PASS')
