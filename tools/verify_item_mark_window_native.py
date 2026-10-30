"""Original item-mark window builders (B8 01/02/03) and MarkedItems writer C829.

Builders 8a0e3c/8a0ec4/8a0f3c and writer 641740 run unchanged. Isolated: the
transport flush, RTL UStrToShortString (WideCharToMultiByte, modelled as ACP
1251) and oleaut32 SysAllocStringLen/SysFreeString. No UI, no gameplay.
"""
from verify_auth_native import *

ELEMENT_SIZE = 0x38  # 641797: index * 7 * 8


def unicode_string(u, address, text):
    """Delphi UnicodeString (codepage 1200, refcount -1); returns the data pointer."""
    u.mem_write(address, struct.pack('<HHiI', 1200, 2, -1, len(text)) + text.encode('utf-16le') + b'\0\0')
    return address + 12


def isolate_rtl(u):
    heap = [DATA+0xa000]

    def hook(uc, address, size, unused):
        if address == 0x40c06c:  # UStrToShortString(dest, source, limit)
            dest, source, limit = (uc.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
            text = bytes(uc.mem_read(source, get32(uc, source-4)*2)).decode('utf-16le') if source else ''
            raw = text.encode('cp1251')[:limit]
            uc.mem_write(dest, bytes([len(raw)])+raw); return_from_stub(uc)
        elif address == 0x404cfc:  # SysAllocStringLen(source, chars), stdcall
            sp = uc.reg_read(UC_X86_REG_ESP); source, chars = get32(uc, sp+4), get32(uc, sp+8)
            data = bytes(uc.mem_read(source, chars*2))
            uc.mem_write(heap[0], struct.pack('<I', len(data))+data+b'\0\0')
            uc.reg_write(UC_X86_REG_EAX, heap[0]+4); heap[0] += len(data)+8
            return_from_stub(uc); uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP)+8)
        elif address == 0x404d0c:  # SysFreeString(bstr), stdcall
            return_from_stub(uc); uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP)+4)
    u.hook_add(UC_HOOK_CODE, hook)


def request(function, expected, *, eax=0, edx=0, ecx=0, text_register=None, text=''):
    u = emulator(); obj = DATA+0x1000; handle = DATA+0x3000; vt = DATA+0x3100; flush = DATA+0x3200
    put32(u, handle, obj); put32(u, obj, vt); put32(u, vt, flush); put32(u, 0xac600c, handle)
    registers = {UC_X86_REG_EAX: eax, UC_X86_REG_EDX: edx, UC_X86_REG_ECX: ecx}
    if text_register is not None:
        registers[text_register] = unicode_string(u, DATA+0x5000, text)
    isolate_rtl(u)

    def hook(uc, address, size, unused):
        if address == 0x6748b0:
            uc.reg_write(UC_X86_REG_EAX, handle); return_from_stub(uc)
        elif address == flush:
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    for register, value in registers.items():
        u.reg_write(register, value)
    u.emu_start(function, STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    packet = bytes(u.mem_read(obj+4, get32(u, obj+0x1004)))
    assert packet == expected, (hex(function), packet.hex())
    return dict(builder=hex(function), packet=packet.hex())


def marked_items(rows, expected):
    """TANetMarkedItems: +0 elements, +4 count, +8 per-element isSet bytes."""
    u = emulator(); obj = DATA+0x6000; flags = DATA+0x6080; array = DATA+0x6100; out = DATA+0x8000
    put32(u, 0xacd0e0, out); put32(u, 0xacd0f0, 0)
    put32(u, obj, array); put32(u, obj+4, len(rows)); put32(u, obj+8, flags)
    u.mem_write(flags, b'\x01'*len(rows))
    for index, row in enumerate(rows):
        base = array + index*ELEMENT_SIZE
        u.mem_write(base, b'\x01'*ELEMENT_SIZE)  # every *_isSet byte
        u.mem_write(base, struct.pack('<I', row['object'])); u.mem_write(base+8, struct.pack('<I', row['template']))
        u.mem_write(base+0x10, struct.pack('<I', row['count']))
        u.mem_write(base+0x15, bytes([row['type1']])); u.mem_write(base+0x17, bytes([row['type2']]))
        u.mem_write(base+0x1a, struct.pack('<H', row['durability'])); u.mem_write(base+0x1e, struct.pack('<H', row['maximum']))
        u.mem_write(base+0x21, bytes([row['enhance']])); u.mem_write(base+0x23, bytes([row['damage']]))
        u.mem_write(base+0x25, bytes([row['se']])); u.mem_write(base+0x28, struct.pack('<I', row['seconds']))
        put32(u, base+0x30, unicode_string(u, DATA+0x7000+index*0x100, row['owner']))
    isolate_rtl(u)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x641740, STOP, count=50000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    packet = bytes(u.mem_read(out, get32(u, 0xacd0f0)))
    assert packet == expected, packet.hex()
    return dict(writer='641740', rows=len(rows), packet=packet.hex())


ROW = dict(object=0x11223344, template=301, count=1, type1=2, type2=3, durability=0x1a2b, maximum=0x3c4d,
           enhance=5, damage=6, se=1, seconds=86400, owner='Шрек')
# object, template, count u32; type1, type2 u8; durability, maximum u16; enhance, damage, se u8;
# seconds u32; owner UTF-16LE NUL-terminated.
ROW_WIRE = ('44332211' '2d010000' '01000000' '02' '03' '2b1a' '4d3c' '05' '06' '01' '80510100'
            '2804400435043a04' '0000')


if __name__ == '__main__':
    cases = [request(0x8a0e3c, bytes.fromhex('b801341200000000' '3438323100'), eax=0x1234,
                     text_register=UC_X86_REG_ECX, text='4821'),
             request(0x8a0e3c, bytes.fromhex('b801341200000700' '3438323100'), eax=0x1234, edx=7,
                     text_register=UC_X86_REG_ECX, text='4821'),
             request(0x8a0ec4, bytes.fromhex('b80234120000' '3438323100'), eax=0x1234,
                     text_register=UC_X86_REG_EDX, text='4821'),
             request(0x8a0f3c, bytes.fromhex('b8033412000001'), eax=0x1234, edx=1),
             marked_items([], bytes.fromhex('c82900000000')),
             marked_items([ROW], bytes.fromhex('c82901000000'+ROW_WIRE)),
             marked_items([ROW, dict(ROW, object=7, owner='Ab')],
                          bytes.fromhex('c82902000000'+ROW_WIRE+'07000000'+ROW_WIRE[8:-20]+'410062000000'))]
    (ROOT/'evidence/item_mark_window_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,
        method=__doc__, cases=cases), indent=2)+'\n')
    print(f'Original item-mark window builders and C829 writer: {len(cases)} cases PASS')
