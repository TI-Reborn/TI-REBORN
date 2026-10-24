"""Execute published party readers and invitation answer writer; UI/string allocation isolated."""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import *
from tio.protocol.ranked_party import invite,snapshot
RAW=(ROOT/'work/groza-20261019/gui/game-a/silver.dll').read_bytes()
assert hashlib.sha256(RAW).hexdigest()=='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'

def reader(base):
    u=emulator(RAW,base);a=lambda va:va+base-0x400000
    obj=DATA+0x1000;handle=DATA+0x3000;heap=DATA+0x4000;leader=[]
    put(u,a(0xac651c),handle);put(u,handle,obj)
    members=((1,b'Alice',4,0,0,2,1,((1,9,4,100,115,0,0),)),(0x4001,b'Bob',4,0,0,0,1,()))
    packet=snapshot(1,members,3);u.mem_write(DATA,packet[2:]);end=[]
    def hook(uc,address,size,_):
        nonlocal heap
        va=address-base+0x400000;eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if va==0x605f1c:
            ptr=get(uc,eax);raw=bytes(uc.mem_read(ptr,128)).split(b'\0',1)[0];put(uc,eax,ptr+len(raw)+1);put(uc,edx,heap);uc.mem_write(heap,bytes([len(raw)])+raw);heap+=0x100;ret(uc)
        elif va==0x40b47c:put(uc,eax,edx);ret(uc)
        elif va==0x40c06c:
            n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));ret(uc)
        elif va==0x7f597c:leader.append(eax);ret(uc)
        elif va==0xa8e4b0:uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
        elif va in (0x40c8cc,0xa01ef4,0xa0fba0,0x68a094,0xa017c8,0xa78afc):ret(uc)
        elif va==0x7f7d2d:
            ebp=uc.reg_read(UC_X86_REG_EBP);end.append(get(uc,ebp-0x1c4));uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    try:u.emu_start(a(0x7f78f8),STOP,count=40000)
    except Exception:
        print(dict(eip=hex(u.reg_read(UC_X86_REG_EIP)),eax=hex(u.reg_read(UC_X86_REG_EAX)),edx=hex(u.reg_read(UC_X86_REG_EDX)),esp=hex(u.reg_read(UC_X86_REG_ESP))))
        raise
    assert leader==[1] and end==[DATA+len(packet)-4],(leader,end,len(packet))
    assert get(u,obj+0x294)==1 and get(u,obj+100+0x294)==0x4001
    assert bytes(u.mem_read(obj+0x2f0,1))==b'\2' and bytes(u.mem_read(obj+0x29c,2))==b'\1\1'
    assert get(u,obj+0x2a0)==1 and get(u,obj+0x2a4)==9 and bytes(u.mem_read(obj+0x2a8,1))==b'\4'
    assert struct.unpack('<H',u.mem_read(obj+0x2aa,2))[0]==100 and struct.unpack('<H',u.mem_read(obj+0x2ac,2))[0]==115
    return dict(leader=leader[0],members=2,one_ready=True,allocated_slots=[1,1],soldier_hp=[100,115],bytes_consumed=len(packet)-4)

def answer(base,value):
    u=emulator(RAW,base);a=lambda va:va+base-0x400000
    obj=DATA+0x1000;handle=DATA+0x3000;vtable=DATA+0x3100;flush=DATA+0x3200
    put(u,a(0xac600c),handle);put(u,handle,obj);put(u,obj,vtable);put(u,vtable,flush);packets=[]
    def hook(uc,address,size,_):
        if address==a(0x6748b0):uc.reg_write(UC_X86_REG_EAX,handle);ret(uc)
        elif address==flush:packets.append(bytes(uc.mem_read(obj+4,get(uc,obj+0x1004))));ret(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,value);run(u,0x7f7350,base)
    assert packets==[b'\xc6\x37'+bytes([value])],packets
    return packets[0].hex()

if __name__=='__main__':
    result=dict(passed=True,graphical_clients=False,cases=[dict(base=hex(b),reader=reader(b),answers=[answer(b,v) for v in (0,1)]) for b in (0x400000,0x1400000)])
    (ROOT/'reports/trueskill-invite-20261019/native-party.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
