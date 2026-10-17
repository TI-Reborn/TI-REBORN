"""Execute candidate PE equipment extension plus original33/OK paths.

Scalar packet writers, battle/metadata gates, nonce and original OK hide/event
flow execute in x86. UI bookkeeping and managed runtime helpers are isolated.
No installed DLL, client configuration or published manifest is modified.
"""
from verify_auth_native import *
from deploy.client_equipment_batch import (patch,RVA,COUNTER,ACTIVE,WINDOW,INIT_HOOK,
    STAGE_ENTRY,OK_ENTRY,INIT_ENTRY,HIDE_ENTRY,stage_code,ok_code,init_code,hide_code,sites,patch_plan)
from tio.protocol.equipment_batch import EquipmentBatchRequest,encode_equipment_batch,STAGE,COMMIT,CANCEL
from tio.protocol.item_action import ItemAction,encode_item_action

_candidate=None
PUBLISHED_BINARY=ROOT/'reports/gameplay-completion/stage2-equipment/client/source/silver.dll'


def candidate():
    global _candidate
    if _candidate is None:_candidate=patch(PUBLISHED_BINARY.read_bytes())
    return _candidate


def runtime(battle=1,kind=1):
    u=emulator();u.mem_map(0x400000+RVA,0x2000)
    u.mem_write(0x400000,pefile.PE(data=candidate()).get_memory_mapped_image())
    obj,handle,vtable,flush=DATA+0x1000,DATA+0x3000,DATA+0x3100,DATA+0x3200
    metadata=DATA+0x5000
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    put32(u,0xac637c,DATA+0x3300);put32(u,DATA+0x3300,metadata)
    u.mem_write(metadata+0x68d,b'\x01');u.mem_write(metadata+0x118,struct.pack('<H',kind))
    put32(u,0xac64a0,DATA+0x6000);u.mem_write(DATA+0x6000,bytes((battle,)))
    put32(u,0xac5fe4,DATA+0x6100)
    put32(u,DATA+0x8100+0xc,DATA+0x9000);put32(u,DATA+0x9000,0xa31a40)
    packets=[]
    def hook(uc,address,size,user):
        values={0x99f5d8:0,0xa7b030:0,0x66754c:1,0xa93eec:1,0x6748b0:handle}
        if address in values:uc.reg_write(UC_X86_REG_EAX,values[address]);return_from_stub(uc)
        elif address==flush:
            packets.append(bytes(uc.mem_read(obj+4,get32(uc,obj+0x1004))))
            put32(uc,obj+0x1004,0);return_from_stub(uc)
        elif address in (0x40cb10,0x40b09c,0x40c9a4,0x40b47c,0xa3ecfc,0xa3fc0c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    initialize_window(u)
    return u,packets


def initialize_window(u):
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,DATA+0x9000+0x68);u.reg_write(UC_X86_REG_EDX,0x9bb6d4)
    u.emu_start(INIT_HOOK,INIT_HOOK+5,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==INIT_HOOK+5
    assert get32(u,0x400000+WINDOW)==DATA+0x9000


def action(u,identity,item,option=255):
    put32(u,STACK+0x8000,STOP);put32(u,STACK+0x8004,option)
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,identity);u.reg_write(UC_X86_REG_EDX,item);u.reg_write(UC_X86_REG_ECX,DATA+0x4000)
    u.emu_start(0x9903a4,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP


def ok(u):
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.mem_write(DATA+0x9000+0x49,b'\x01')
    u.reg_write(UC_X86_REG_EAX,DATA+0x8100+0x2c)
    u.emu_start(0x9b90b7,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert bytes(u.mem_read(DATA+0x9000+0x49,1))==b'\0'


def staged(kind):
    u,packets=runtime(kind=kind)
    for identity,item,option in ((17,1001,255),(17,1002,4),(18,2001,255)):
        action(u,identity,item,option)
        assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(STAGE,1,ItemAction(identity,item,option)))
    ok(u);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(COMMIT,1))
    before=len(packets);ok(u);assert len(packets)==before
    action(u,17,1003,255);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(STAGE,2,ItemAction(17,1003,255)))
    ok(u);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(COMMIT,2))
    assert get32(u,0x400000+COUNTER)==2 and bytes(u.mem_read(0x400000+ACTIVE,1))==b'\0'
    return {'metadata_kind':kind,'packets_hex':[p.hex() for p in packets],'duplicate_ok_sent':False}


def unchanged(battle,kind):
    u,packets=runtime(battle=battle,kind=kind)
    action(u,17,1001,255)
    assert packets==[encode_item_action(ItemAction(17,1001,255))]
    ok(u);assert len(packets)==1
    return {'battle':battle,'metadata_kind':kind,'original_packet':packets[0].hex(),'commit_sent':False}


def wrapped_nonce():
    u,packets=runtime();put32(u,0x400000+COUNTER,0xffffffff)
    action(u,17,1001,255)
    assert packets==[encode_equipment_batch(EquipmentBatchRequest(STAGE,1,ItemAction(17,1001,255)))]
    return {'initial_nonce':0xffffffff,'next_nonce':1}


def hide(u,window=DATA+0x9000):
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    put32(u,window,0xa31a40);u.mem_write(window+0x49,b'\x01')
    u.reg_write(UC_X86_REG_EAX,window)
    u.emu_start(0xa4370c,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and bytes(u.mem_read(window+0x49,1))==b'\0'


def hide_cancel():
    u,packets=runtime();action(u,17,1001)
    hide(u,DATA+0xa000);assert len(packets)==1
    hide(u);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(CANCEL,1))
    before=len(packets);hide(u);assert len(packets)==before
    action(u,17,1002);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(STAGE,2,ItemAction(17,1002,255)))
    ok(u);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(COMMIT,2))
    return {'packets_hex':[p.hex() for p in packets],'foreign_window_cancelled':False,'duplicate_hide_sent':False}


def reconstructed_cancel():
    u,packets=runtime();action(u,17,1001)
    initialize_window(u);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(CANCEL,1))
    action(u,17,1002);assert packets[-1]==encode_equipment_batch(EquipmentBatchRequest(STAGE,2,ItemAction(17,1002,255)))
    return {'packets_hex':[p.hex() for p in packets]}


def verify():
    raw=candidate();assert patch(raw)==raw
    original=BINARY.read_bytes();pe=pefile.PE(data=original)
    writers=[]
    for section in pe.sections:
        if not section.Characteristics&0x20000000:continue
        data=section.get_data()
        for offset in range(len(data)-6):
            if data[offset:offset+3]==b'\xb2\xf6\xe8':
                address=0x400000+section.VirtualAddress+offset
                target=address+7+struct.unpack_from('<i',data,offset+3)[0]
                if target==0x675bf8:writers.append(hex(address))
    assert not writers
    published=PUBLISHED_BINARY.read_bytes()
    result={'original_sha256':EXPECTED_SHA,'published_source_sha256':hashlib.sha256(published).hexdigest(),
            'published_source_bytes':len(published),
            'candidate_sha256':hashlib.sha256(raw).hexdigest(),'method':__doc__,
            'preservation':patch_plan(published,raw),
            'namespace':'F6/v1 is an explicit TIO emulator extension, not historical native protocol',
            'collision_audit':{'scope':'Executable original PE sections: MOV DL,F6 + direct CALL native u8 writer675BF8',
                               'native_writers_found':writers,
                               'limitation':'This establishes no original writer using that recovered scalar-call pattern; it is not a complete historical server protocol specification.'},
            'hooks':[{'va':hex(va),'before':before.hex(),'after':after.hex()} for va,before,after in sites()],
            'stage_cases':[staged(1),staged(9)],
            'unchanged_cases':[unchanged(0,1),unchanged(0,9),unchanged(1,2),unchanged(1,3),unchanged(1,12)],
            'wrap_case':wrapped_nonce(),'hide_cancel':hide_cancel(),'reconstructed_cancel':reconstructed_cancel()}
    return result


if __name__=='__main__':
    result=verify()
    (ROOT/'evidence/equipment_batch_client_native.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    from capstone import Cs,CS_ARCH_X86,CS_MODE_32
    disassembler=Cs(CS_ARCH_X86,CS_MODE_32);lines=[f'; candidate SHA256 {result["candidate_sha256"]}',
        '; F6/v1 explicitly extends TIO emulator protocol; original confirmation not established.']
    for name,address,data in (('stage',STAGE_ENTRY,stage_code()),('OK',OK_ENTRY,ok_code()),
                              ('inventory capture',INIT_ENTRY,init_code()),('guarded OnHide cancel',HIDE_ENTRY,hide_code())):
        lines.append(f'; {name} at {address:08x}')
        for instruction in disassembler.disasm(data,address):
            if instruction.bytes==b'\0\0':break
            lines.append(f'{instruction.address:08x} {instruction.mnemonic} {instruction.op_str}')
    (ROOT/'evidence/equipment_batch_client_native.asm').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Candidate x86 equipment batch: stage/OK/CANCEL/foreign hide/reopen/wrap + unchanged city/medical/booster/binocular stock33 PASS')
