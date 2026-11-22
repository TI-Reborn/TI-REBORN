"""Execute original6E writer plus released opening/AP/predicate hooks in Unicorn.

Transport, UI, allocator/refcount helpers are isolated; actual scalar writers,
opening eligibility, patched trampoline and transfer predicate execute.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI
from deploy.client_battle_exchange import patch,OPEN,PREDICATE,RVA,HOOK
from tio.protocol.battle_exchange import BattleExchange,encode_exchange


def runtime(patched=False):
    u=emulator()
    if patched:
        image=pefile.PE(data=patch(BINARY.read_bytes())).get_memory_mapped_image()
        u.mem_map(0x400000+RVA,0x1000);u.mem_write(0x400000,image)
    obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    def hook(uc,a,size,user):
        if a==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif a in (flush,0x40d748,0x40d6c8,0x40c9f4):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    return u,obj


def writer(deposits=(),withdrawals=()):
    u,obj=runtime()
    for address,rows in ((DATA+0x4000,deposits),(DATA+0x8000,withdrawals)):
        put32(u,address-4,len(rows))
        for n,(i,count) in enumerate(rows):put32(u,address+n*656+0x28,i);put32(u,address+n*656+0x1c,count)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,18);u.reg_write(UC_X86_REG_ECX,DATA+0x4000)
    put32(u,STACK+0x8004,DATA+0x8000)
    u.emu_start(0x98f478,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==encode_exchange(BattleExchange(17,18,withdrawals,deposits))
    return packet.hex()


def opening(ap):
    u,obj=runtime(True);u.mem_map(DATA+0x10000,0x20000)
    array=DATA+0x5000;actors=[DATA+0x10000,DATA+0x18000];windows=[]
    put32(u,0xac618c,array);put32(u,array,actors[0]);put32(u,array+4,actors[1]);put32(u,0xac4b04,1)
    for n,address in enumerate((0xac5a30,0xac55a8,0xac5fe4,0xac57e4,0xac56c4,0xac5a6c,0xac5c44,0xac5f18)):
        put32(u,address,DATA+0x6000+n*0x10)
    put32(u,DATA+0x6000,4)
    put32(u,0xac6008,DATA+0x6800);u.mem_write(DATA+0x6805,bytes((2,1)))
    for n,actor in enumerate(actors):
        put32(u,actor+0x28,17+n);put32(u,actor+0x6c,DATA+0x7000+n*0x100)
        u.mem_write(actor+0x6004,bytes((ap,0,100,0)))
        u.mem_write(actor+0x6029,b'\0')
    u.mem_write(0xac4afc,b'\0')
    def hook(uc,a,size,user):
        if a==0xa843d4:uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif a==0x9b1440:
            windows.append((uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX),uc.reg_read(UC_X86_REG_ECX)))
            return_from_stub(uc)
        elif a in (0x9b122c,0x9dcd0c,0x9b63dc):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x95ccc0,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    if ap:
        assert windows==[(0,DATA+0x7000,DATA+0x7100)]
        assert packet==encode_exchange(BattleExchange(17,18)),packet.hex()
    else:assert not packet and not windows
    return dict(ap=ap,opened=bool(windows),packet=packet.hex())


def predicates():
    from verify_battle_loot_client_native import run
    return run(client_patch=patch,own_exchange=True)


if __name__=='__main__':
    final=patch(BINARY.read_bytes());assert patch(final)==final
    cases=[writer(),writer(((501,3),),((601,7),(602,1))),opening(0),opening(1),opening(2)]
    result=dict(sha256=hashlib.sha256(final).hexdigest(),method=__doc__,cases=cases,predicates=predicates())
    (ROOT/'reports/battle-exchange/client-native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Native exchange6E writer, opening hook at1AP and own-merc predicate: PASS')
