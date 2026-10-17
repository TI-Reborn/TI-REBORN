"""Bounded original XML metadata loader proof for the approved item overlay.

Original metadata stores, class branches, variant comparison/string comparison,
integer conversion and Grenade/Throwing enum lookup execute in silver.dll.
XML DOM/property lookup, allocation/refcount and Unicode/ANSI conversion are
isolated. This is not a full filesystem loader or actual Windows GUI proof.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI
import xml.etree.ElementTree as ET

CATALOG = ROOT/'reports/gameplay-completion/stage3-items/client/candidate/items.xml'
CATALOG_SHA = '2efd1bca527c9f325737f7e1a0a6aad281a15a5cf71e67c6c876a58709751b40'
CLIENT = CATALOG.with_name('silver.dll')
CLIENT_SHA = '2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f'
_original_image=None
_candidate_image=None


def load_record(item):
    global _original_image,_candidate_image
    u=emulator();frame=STACK+0x7000;table=DATA+0x1000;node=DATA+0x6000;closure=node+0x100
    if _original_image is None:_original_image=pefile.PE(data=BINARY.read_bytes()).get_memory_mapped_image()
    if _candidate_image is None:
        raw=CLIENT.read_bytes();assert hashlib.sha256(raw).hexdigest()==CLIENT_SHA
        _candidate_image=pefile.PE(data=raw).get_memory_mapped_image()
    u.mem_map(0xc17000,0x6000);u.mem_write(0x400000,_candidate_image)
    put32(u,closure+0xc,0);put32(u,0xac637c,node+0x200);put32(u,node+0x200,table)
    put32(u,node+8,node+0x300);reads=[];strings={};arena=DATA+0x7000;executed=set()
    values={v.get('key'):v.get('val') for v in item.findall('value')}

    def string(pointer):
        if not pointer:return ''
        if pointer in strings:return strings[pointer]
        output=bytearray()
        for index in range(512):
            pair=bytes(u.mem_read(pointer+index*2,2))
            if pair==b'\0\0':return output.decode('utf-16le')
            output.extend(pair)
        raise AssertionError('Unterminated native key')

    def allocate(value):
        nonlocal arena
        if not value:return 0
        raw=value.encode('utf-16le');pointer=arena+8
        assert pointer+len(raw)+4<DATA+0x10000
        put32(u,pointer-8,0xffffffff);put32(u,pointer-4,len(value))
        u.mem_write(pointer,raw+b'\0\0\0\0');strings[pointer]=value
        arena=(pointer+len(raw)+4+3)&~3
        return pointer

    def hook(uc,address,size,user):
        # Every visited original instruction (including helper entrypoints)
        # must be byte-identical in this exact candidate, not just loader ranges.
        offset=address-0x400000
        assert 0<=offset and offset+size<=len(_original_image),hex(address)
        assert bytes(uc.mem_read(address,size))==_original_image[offset:offset+size],hex(address)
        executed.add(address)
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX);ecx=uc.reg_read(UC_X86_REG_ECX)
        if address==0x680770:
            key=string(edx);reads.append(('attribute',key))
            put32(uc,ecx,allocate(item.get(key,'')));return_from_stub(uc)
        elif address==0x6807d0:
            key=string(edx);reads.append(('value',key))
            sp=uc.reg_read(UC_X86_REG_ESP);put32(uc,get32(uc,sp+4),allocate(values.get(key,string(ecx))))
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8)
        elif address==0x681f48:
            key=string(edx);reads.append(('numeric/boolean value',key))
            value=values.get(key);put32(uc,ecx,allocate(value or ''))
            uc.reg_write(UC_X86_REG_EAX,int(value is not None));return_from_stub(uc)
        elif address==0x4237d0:
            put32(uc,edx,eax);return_from_stub(uc)
        elif address==0x40b09c:
            put32(uc,eax,0);return_from_stub(uc)
        elif address in (0x40b0fc,0x40b180):return_from_stub(uc)
        elif address==0x43b3f0:
            # Represent managed BSTR variant allocation; comparison itself runs.
            uc.mem_write(eax,b'\x08\0'+b'\0'*14);put32(uc,eax+8,edx);return_from_stub(uc)
        elif address==0x43a750:
            assert bytes(uc.mem_read(edx,2))==b'\x08\0'
            put32(uc,eax,get32(uc,edx+8));return_from_stub(uc)
        elif address==0x40b1ec:
            # Original shortstring length/copy 40c06c still executes after this
            # isolated managed UTF16 -> ANSI conversion of the ASCII catalog.
            value=string(ecx).encode('ascii');assert len(value)<=edx
            uc.mem_write(eax,value);uc.reg_write(UC_X86_REG_EAX,len(value))
            sp=uc.reg_read(UC_X86_REG_ESP);return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8)
        elif address==0x40b47c:
            put32(uc,eax,edx);return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE,hook)
    def region(start,end):
        u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EBX,closure);u.reg_write(UC_X86_REG_EDI,node)
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.emu_start(start,end,count=100000)
        assert u.reg_read(UC_X86_REG_EIP)==end,hex(u.reg_read(UC_X86_REG_EIP))
    region(0xa70286,0xa702f1)  # Original id/name attribute loader and metadata stores.
    region(0xa713cf,0xa71ba4)  # All itype/type/subtype class branches/comparisons.
    region(0xa71ba4,0xa72135)  # Native scalar/default parsing and icon/name storage.
    if item.get('id')=='5001':
        region(0xa70627,0xa70661)  # Original weaponType enum lookup ->metadata120.
        put32(u,frame-4,allocate(values['attackType']))
        region(0xa70757,0xa70775)  # Original attackType enum lookup ->metadata12c.
    word=lambda offset:int.from_bytes(u.mem_read(table+offset,2),'little')
    short=lambda offset:bytes(u.mem_read(table+offset+1,u.mem_read(table+offset,1)[0])).decode('ascii')
    actual=dict(id=word(0x116),name=short(0x16),kind=word(0x118),
        ap=word(0x13c),image=short(0x148),durability=word(0x65e),weight=word(0x65c),
        power=get32(u,table+0x650),radius=word(0x144),min_range=word(0x138),max_range=word(0x13a),spread=word(0x146))
    expected=dict(id=int(item.get('id')),name=item.get('name'),kind=1 if item.get('id')=='5001' else 2,
        ap=int(values.get('actionPoints',0)),image=values['image'],durability=int(values['durability']),
        weight=int(values['weight']),power=0,radius=int(values.get('radius',1)),
        min_range=int(values.get('minRange',0)),max_range=int(values.get('maxRange',0)),spread=int(values.get('spread',0)))
    assert actual==expected,(actual,expected)
    if item.get('id')=='5001':
        actual.update(attack_type=u.mem_read(table+0x12c,1)[0],weapon_type=word(0x120))
        assert actual['attack_type']==4 and actual['weapon_type']==7,actual
    actual['original_lookup_reads']=reads
    actual['candidate_executed_original_instruction_parity_count']=len(executed)
    return actual


def main():
    raw=CATALOG.read_bytes();assert hashlib.sha256(raw).hexdigest()==CATALOG_SHA
    root=ET.fromstring(raw);items={int(i.get('id')):i for i in root.findall('item')}
    assert len(items)==len(root.findall('item'))
    cases=[load_record(items[n]) for n in range(5001,5012)]
    report=dict(status='PASS',method=__doc__,silver_sha256=EXPECTED_SHA,candidate_sha256=CLIENT_SHA,catalog_sha256=CATALOG_SHA,
        candidate_execution='Exact candidate loaded and executed; every visited instruction compared byte-for-byte with original image, including native helpers and isolated helper entrypoints',
        runtime_catalog='base/shared config/items.xml; installed items.cfg is historical import/collision source',
        original_regions=['a70286..a702f1 id/name','a713cf..a71ba4 class','a71ba4..a72135 scalars/art',
            'a70627..a70661 weapon enum','a70757..a70775 attack enum'],
        original_comparison='43e840/43e850 ->43d0ac ->43cad4 ->43ca68 ->423820 ->43c95c; no comparison predicate stub',
        limitation='Controlled XML DOM/property values and managed allocation/conversion; no full filesystem load, art pixel, or live multiplayer GUI claim',
        cases=cases)
    (ROOT/'evidence/battle_item_catalog_native.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Approved XML overlay: all11 original metadata class/AP/name/icon/weight/durability stores PASS; Flare Grenade/Throwing enums PASS')


if __name__=='__main__':main()
