"""Execute original inventory/scrollbar geometry routines without a game client.

This proves the state-preserving native calls used by cached inventory reflow.
It does not verify a candidate reflow helper or graphical client behavior.
"""
import hashlib
import json
from pathlib import Path
import struct
import sys
from functools import lru_cache

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
DATA, STACK, STOP = 0x30000000, 0x31000000, 0x3004ff00
TABLE, SCROLL, PARENT, SOURCE, CELL, ARRAY = (DATA+x for x in (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x8000))
REGISTERS = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
CANARIES = (0x12345678, 0x23456789, 0x3456789a, 0x456789ab)


def put32(u, a, v):
    u.mem_write(a, struct.pack('<I', v & 0xffffffff))


def get32(u, a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def putf(u, a, v):
    u.mem_write(a, struct.pack('<f', v))


def getf(u, a):
    return struct.unpack('<f', u.mem_read(a, 4))[0]


@lru_cache(maxsize=2)
def mapped(image, base):
    pe = pefile.PE(data=image); pe.relocate_image(base)
    return pe.get_memory_mapped_image()


class Fixture:
    def __init__(self, image, base, mode, count, position):
        self.base = base
        memory = mapped(image, base)
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        self.u.mem_map(base, (len(memory)+4095)&~4095)
        self.u.mem_write(base, memory)
        self.u.mem_map(DATA, 0x50000); self.u.mem_map(STACK, 0x10000)
        self.u.mem_write(TABLE, b'\xa5'*0x400)
        self.u.mem_write(SCROLL, b'\x5a'*0x400)
        self.u.mem_write(PARENT, b'\0'*0x400)
        self.u.mem_write(ARRAY, bytes((i*37+11)&255 for i in range(count*0x290)))
        put32(self.u, self.va(0xac55cc), CELL); put32(self.u, CELL, SOURCE)
        put32(self.u, SOURCE+0xc, ARRAY if count else 0)
        put32(self.u, ARRAY-4, count)
        put32(self.u, PARENT+0x30, 146); put32(self.u, PARENT+0x4c, 0)
        put32(self.u, TABLE+0x4c, PARENT); put32(self.u, TABLE+0x280, SCROLL)
        self.u.mem_write(TABLE+0x30, struct.pack('<6I', 0, 20, 655, 372, 372, 655))
        put32(self.u, TABLE+0x284, 60)
        self.u.mem_write(TABLE+0x294, bytes([mode]))
        self.u.mem_write(SCROLL+0x30, struct.pack('<4I', 639, 0, 16, 372))
        put32(self.u, SCROLL+0x4c, TABLE)
        self.u.mem_write(SCROLL+0x2bc, b'\1')
        putf(self.u, SCROLL+0x2a4, position)
        putf(self.u, SCROLL+0x2a8, 0)
        putf(self.u, SCROLL+0x2ac, 20000)
        self.u.mem_write(self.va(0xb7665e), struct.pack('<H', 16))
        self.count, self.position, self.mode = count, position, mode
        self.calls = []
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def va(self, a):
        return self.base+a-0x400000

    def hook(self, u, address, size, _):
        if address == STOP:
            u.emu_stop(); return
        va = address-self.base+0x400000
        if va in (0x99efd4, 0xa4176c, 0xa417d0, 0xa41a58, 0x407438,
                  0x9bc9c4, 0x9bd118, 0xa7b030):
            self.calls.append(hex(va))

    def run(self, address, eax, edx=0, ecx=0):
        sp = STACK+0xf000
        put32(self.u, sp, STOP)
        self.u.reg_write(UC_X86_REG_ESP, sp)
        self.u.reg_write(UC_X86_REG_EAX, eax); self.u.reg_write(UC_X86_REG_EDX, edx)
        self.u.reg_write(UC_X86_REG_ECX, ecx)
        for r, value in zip(REGISTERS, CANARIES): self.u.reg_write(r, value)
        self.u.emu_start(self.va(address), STOP, count=100000)
        assert self.u.reg_read(UC_X86_REG_ESP) == sp+4
        assert self.u.reg_read(UC_X86_REG_EIP) == STOP
        for r, value in zip(REGISTERS, CANARIES): assert self.u.reg_read(r) == value

    def product_run(self, address, eax, edx=0, ecx=0):
        self.run(address,eax,edx,ecx)
        for r,value in ((UC_X86_REG_EAX,eax),(UC_X86_REG_EDX,edx),(UC_X86_REG_ECX,ecx)):
            assert self.u.reg_read(r) == value

    def verify_resize(self, width, height):
        before_table = bytes(self.u.mem_read(TABLE, 0x400))
        before_data = bytes(self.u.mem_read(ARRAY, self.count*0x290))
        # The display-owned helper supplies these pure constructor-derived
        # geometry writes; this fixture tests the original downstream routines.
        put32(self.u, TABLE+0x38, width); put32(self.u, TABLE+0x44, width)
        put32(self.u, TABLE+0x3c, height); put32(self.u, TABLE+0x40, height)
        put32(self.u, TABLE+0x288, height-32)
        put32(self.u, SCROLL+0x30, width-16)
        self.run(0xa4176c, SCROLL, height)
        self.run(0x99efc0, TABLE)
        content = (self.count*60 if not self.mode else
                   39*(1+self.count//((width-68)//71+1)))
        assert get32(self.u, TABLE+0x290) == content, (width, self.count, self.mode)
        assert getf(self.u, SCROLL+0x2ac) == max(0, content-height+4)
        assert getf(self.u, SCROLL+0x2a4) == min(self.position, max(0, content-height+4))
        assert get32(self.u, SCROLL+0x3c) == height
        assert get32(self.u, SCROLL+0x30) == width-16
        assert 16 <= get32(self.u, SCROLL+0x2a0) <= height-32
        assert bytes(self.u.mem_read(ARRAY, self.count*0x290)) == before_data
        after = bytes(self.u.mem_read(TABLE, 0x400))
        allowed = set()
        for offset in (0x38, 0x3c, 0x40, 0x44, 0x288, 0x290): allowed.update(range(offset, offset+4))
        assert all(a == b or i in allowed for i, (a,b) in enumerate(zip(before_table, after)))
        assert set(self.calls).issubset({'0x99efd4','0xa4176c','0xa417d0','0xa41a58','0x407438'})


class BagFixture(Fixture):
    def __init__(self, image, base, count, position, hidden):
        super().__init__(image, base, 0, count, position)
        config = DATA+0x40000
        self.u.mem_write(config, b'\0'*0x3a78)
        self.u.mem_write(config+0x116, struct.pack('<H', 40))
        put32(self.u, config-4, 1)
        put32(self.u, self.va(0xac637c), CELL+4); put32(self.u, CELL+4, config)
        self.hidden = hidden
        for i in range(count):
            item = ARRAY+i*0x290
            put32(self.u, item+4, 0); put32(self.u, item+8, 40)
            self.u.mem_write(item+0x30, bytes([int(hidden and i%3 == 0)]))
        put32(self.u, TABLE+0x278, 0)
        put32(self.u, TABLE+0x298, SCROLL)
        put32(self.u, TABLE+0x2c8, ARRAY if count else 0)
        put32(self.u, TABLE+0x294, 0x1234abcd)
        for offset in (0x29c,0x29d,0x2a1,0x2a3,0x2a4,0x2a2):
            self.u.mem_write(TABLE+offset, b'\1')

    def verify_resize(self, width, height):
        before = bytes(self.u.mem_read(TABLE, 0x400))
        before_data = bytes(self.u.mem_read(ARRAY, self.count*0x290))
        put32(self.u, TABLE+0x38, width); put32(self.u, TABLE+0x44, width)
        put32(self.u, TABLE+0x3c, height); put32(self.u, TABLE+0x40, height)
        put32(self.u, TABLE+0x2ac, height//16)
        put32(self.u, SCROLL+0x30, width-16)
        self.run(0xa4176c, SCROLL, height)
        self.run(0x9bc9c4, TABLE)
        self.run(0x9bd118, TABLE)
        visible = self.count-((self.count+2)//3 if self.hidden else 0)
        columns = (width-68)//64+1
        content = 3+37*((visible+columns-1)//columns)
        assert get32(self.u, TABLE+0x28c) == content
        assert getf(self.u, SCROLL+0x2ac) == max(0, content-height)
        assert getf(self.u, SCROLL+0x2a4) == min(self.position, max(0, content-height))
        assert get32(self.u, TABLE+0x2b0) == int(getf(self.u, SCROLL+0x2a4))
        assert get32(self.u, TABLE+0x294) == 0x1234abcd
        assert get32(self.u, SCROLL+0x3c) == height
        assert bytes(self.u.mem_read(ARRAY, self.count*0x290)) == before_data
        after = bytes(self.u.mem_read(TABLE, 0x400))
        allowed = set()
        for offset in (0x38,0x3c,0x40,0x44,0x28c,0x2ac,0x2b0): allowed.update(range(offset,offset+4))
        assert all(a == b or i in allowed for i,(a,b) in enumerate(zip(before,after)))


def product_helpers(image):
    """Verify core's exact helpers against original native geometry routines."""
    from deploy import client_ui_scale as core
    core_image = core.patch(image)
    cases = []
    for base in (0x400000,0x10400000):
        for width,height in ((655,372),(655,800),(785,140),(222,108)):
            for mode in (0,1):
                for count in (0,1,30,200):
                    for position in (0,1250):
                        reference = Fixture(image,base,mode,count,position)
                        reference.verify_resize(width,height)
                        f = Fixture(core_image,base,mode,count,position)
                        original = bytes(f.u.mem_read(ARRAY,count*0x290))
                        f.product_run(core.INVENTORY_VIEW,TABLE,width,height)
                        assert bytes(f.u.mem_read(TABLE,0x400)) == bytes(reference.u.mem_read(TABLE,0x400))
                        assert bytes(f.u.mem_read(SCROLL,0x400)) == bytes(reference.u.mem_read(SCROLL,0x400))
                        assert bytes(f.u.mem_read(ARRAY,count*0x290)) == original
                        cases.append(dict(kind='core-inventory',base=hex(base),width=width,height=height,
                                          mode=mode,count=count,initial_scroll=position))
        for height in (108,140,372,700,800):
            for count in (0,1,30,200):
                for position in (0,1250):
                    f = BagFixture(core_image,base,count,position,False)
                    f.run(0x9bc9c4,TABLE); f.run(0x9bd118,TABLE)
                    content = get32(f.u,TABLE+0x28c)
                    for i in range(count): put32(f.u,ARRAY+i*0x290+4,0xdeadbeef)
                    before_data = bytes(f.u.mem_read(ARRAY,count*0x290))
                    before = bytes(f.u.mem_read(TABLE,0x400))
                    old_height = get32(f.u,TABLE+0x3c)
                    weight, sibling, children, pointers = (DATA+x for x in (0x3200,0x3600,0x6000,0x7000))
                    f.u.mem_write(weight,b'\xa3'*0x400); f.u.mem_write(sibling,b'\xa4'*0x400)
                    put32(f.u,weight,f.va(0x9b0b10)); put32(f.u,sibling,f.va(0xa2c1b0))
                    put32(f.u,weight+0x34,old_height+196)
                    put32(f.u,PARENT+0x2c,children);put32(f.u,children+4,pointers);put32(f.u,children+8,2)
                    put32(f.u,pointers,weight);put32(f.u,pointers+4,sibling)
                    before_weight = bytes(f.u.mem_read(weight,0x400));before_sibling=bytes(f.u.mem_read(sibling,0x400))
                    f.product_run(core.ITEMS_VIEW,TABLE,height)
                    assert get32(f.u,TABLE+0x3c) == height
                    assert get32(f.u,TABLE+0x40) == height
                    assert get32(f.u,TABLE+0x2ac) == height//16
                    assert get32(f.u,TABLE+0x28c) == content
                    assert getf(f.u,SCROLL+0x2ac) == max(0,content-height)
                    assert get32(f.u,TABLE+0x2b0) == int(getf(f.u,SCROLL+0x2a4))
                    assert bytes(f.u.mem_read(ARRAY,count*0x290)) == before_data
                    assert bytes(f.u.mem_read(sibling,0x400)) == before_sibling
                    assert get32(f.u,weight+0x34) == height+196
                    after_weight=bytes(f.u.mem_read(weight,0x400))
                    assert before_weight[:0x34] == after_weight[:0x34]
                    assert before_weight[0x38:] == after_weight[0x38:]
                    allowed = set()
                    for offset in (0x3c,0x40,0x2ac,0x2b0): allowed.update(range(offset,offset+4))
                    after = bytes(f.u.mem_read(TABLE,0x400))
                    assert all(a == b or i in allowed for i,(a,b) in enumerate(zip(before,after)))
                    cases.append(dict(kind='core-items',base=hex(base),height=height,count=count,
                                      initial_scroll=position,invalid_index_canary=True,
                                      unrelated_sibling_preserved=True,weight_footer_delta=height-old_height))
        f = Fixture(core_image,base,0,0,0)
        put32(f.u,TABLE+0x280,0)
        old_content=get32(f.u,TABLE+0x290)
        f.product_run(core.INVENTORY_VIEW,TABLE,655,700)
        assert get32(f.u,TABLE+0x38) == 655 and get32(f.u,TABLE+0x3c) == 700
        assert get32(f.u,TABLE+0x288) == 668 and get32(f.u,TABLE+0x290) == old_content
        cases.append(dict(kind='core-inventory-missing-scrollbar',base=hex(base)))
        f = BagFixture(core_image,base,0,0,False)
        put32(f.u,TABLE+0x298,0)
        put32(f.u,PARENT+0x2c,DATA+0x6000)
        put32(f.u,DATA+0x6000+8,0)
        old_content=get32(f.u,TABLE+0x28c)
        f.product_run(core.ITEMS_VIEW,TABLE,700)
        assert get32(f.u,TABLE+0x3c) == 700 and get32(f.u,TABLE+0x40) == 700
        assert get32(f.u,TABLE+0x2ac) == 43 and get32(f.u,TABLE+0x28c) == old_content
        cases.append(dict(kind='core-items-missing-scrollbar',base=hex(base)))
    return cases,hashlib.sha256(core_image).hexdigest()


def main():
    source = ROOT/'reports/ui-modernization/baseline/silver.dll'
    image = source.read_bytes()
    rows = []
    for base in (0x400000, 0x10400000):
        for width, height in ((655, 372), (655, 800), (785, 140), (222, 108)):
            for mode in (0, 1):
                for count in (0, 1, 30, 200):
                    for position in (0, 1250):
                        f = Fixture(image, base, mode, count, position)
                        f.verify_resize(width, height)
                        rows.append(dict(kind='inventory-list', base=hex(base), width=width, height=height,
                                         mode=mode, count=count, initial_scroll=position,
                                         content_height=get32(f.u, TABLE+0x290),
                                         scroll=getf(f.u, SCROLL+0x2a4), calls=f.calls))
        for width, height in ((222,108),(222,700),(655,140),(655,800)):
            for count in (0,1,30,200):
                for position in (0,1250):
                    for hidden in (False, True):
                        f = BagFixture(image, base, count, position, hidden)
                        f.verify_resize(width,height)
                        rows.append(dict(kind='inventory-bag', base=hex(base), width=width,height=height,
                                         count=count,initial_scroll=position,hidden_third=hidden,
                                         content_height=get32(f.u,TABLE+0x28c),
                                         scroll=getf(f.u,SCROLL+0x2a4),calls=f.calls))
    products, core_sha = product_helpers(image)
    report = dict(result='PASS', cases=len(rows)+len(products), native_cases=len(rows),
                  product_helper_cases=len(products),core_candidate_sha256=core_sha,
                  source_sha256=hashlib.sha256(image).hexdigest(),
                  native_routines_executed=['99efc0','99efd4','a4176c','a417d0','a41a58','407438','a4211c',
                                           '9bc9c4','9bd118','9bd10c','a7b030','a7b41c','a7b524',
                                           'a7b3f0','a7b5f0','a7b8d0'],
                  stubs=[], preservation=['inventory bytes','all table fields except geometry/content extent',
                                          'bag selection and filter flags; valid resource-index caches',
                                          'scroll position unless native range clamp is required',
                                          'EBX/ESI/EDI/EBP and stack'],
                  candidate_helper_verified=True, graphical_validation=False, published=False,
                  rows=rows, product_rows=products)
    output = ROOT/'reports/ui-modernization/inventory-scrollbar-native-proof.json'
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('rows','product_rows')}))


if __name__ == '__main__': main()
