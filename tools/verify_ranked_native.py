"""Original x86 TrueSkill builder, score readers and flag-color callback.

Unicorn executes numeric readers and the engine's model lookup/color store.
Managed strings, allocations, UI and asynchronous event queuing are stubbed.
This does not validate rendered screens or actual game-client interaction.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator,EXE_SHA
from tio.protocol.ranked import decode_join,encode_info,encode_flags,encode_scores,encode_roster
from tio.control_points import ControlPoints
from tio.battle_state import BattleField,BattleActor
from types import SimpleNamespace
from tio.protocol.pet_info import decode_pet_info


def numeric(packet,entry,setup,stubs=(),until=None):
    u=emulator();u.mem_write(DATA,packet[2:]);setup(u);seen={}
    def hook(uc,a,size,user):
        if a==until:
            uc.reg_write(UC_X86_REG_EIP,STOP);uc.emu_stop()
        elif a==0x68a87c:
            seen['callback']=[uc.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX)]
            return_from_stub(uc)
        elif a in stubs:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(entry,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return u,seen


def main():
    results=[]
    def setup(u):
        put32(u,0xac5b7c,DATA+0x1000);put32(u,0xac5ac0,DATA+0x2000)
        put32(u,0xac643c,DATA+0x3000);put32(u,DATA+0x3000,DATA+0x4000)
        put32(u,0xac56b4,DATA+0x5000)
    packet=encode_info(173,2,5,9)
    u,_=numeric(packet,0x953038,setup,(0xa44c58,0x94f3ec))
    assert [get32(u,DATA+0x1000+offset) for offset in (0x260,0x264,0x268,0x26c)]==[173,2,5,9]
    results.append(dict(kind='rating reader',packet=packet.hex()))
    def token_setup(u):
        put32(u,0xac5b7c,DATA+0x1000);put32(u,0xac5fe4,DATA+0x2000);put32(u,DATA+0x2000,100)
    packet=b'\xc6\x24'+struct.pack('<IQ',5,123)
    u,_=numeric(packet,0x953fa4,token_setup,until=0x953ff5)
    assert [get32(u,DATA+0x1000+o) for o in (0x274,0x278,0x27c)]==[5,223,0]
    results.append(dict(kind='token count and relative subscription reader before UI',packet=packet.hex()))
    points=ControlPoints(((4,6),(20,25),(15,15)),[0,1,None],[995,990])
    packet=encode_scores(points)
    u,_=numeric(packet,0x953e5c,lambda u:None)
    assert [get32(u,base+offset) for base in (0xad04b0,0xad052c) for offset in (0,4)]==[995,5,990,5]
    results.append(dict(kind='score reader',packet=packet.hex()))
    for packet,position,side in zip(encode_flags(points),points.positions,(1,2,0)):
        u,seen=numeric(packet,0x953d30,lambda u:None)
        assert seen['callback']==[*position,side],seen
        # Execute the actual engine callback registered at71ba63/7224f4.
        exe=exe_emulator();handle=DATA+0x1000;scene=DATA+0x1100;collection=DATA+0x1200;model=DATA+0x2000
        put32(exe,0x76e000,handle);put32(exe,handle,scene);put32(exe,scene+0xd0,collection)
        put32(exe,collection+8,1);exe.mem_write(model+0x410,b'\x03')
        put32(exe,model+4,position[0]);put32(exe,model+8,position[1])
        for index,color in enumerate((0x888888,0x00ff00,0xff0000)):put32(exe,0x76dac4+index*4,color)
        def hook(uc,address,size,user):
            if address==0x4b1dec:uc.reg_write(UC_X86_REG_EAX,model);return_from_stub(uc)
            elif address==0x6d9c60:return_from_stub(uc)
        exe.hook_add(UC_HOOK_CODE,hook)
        exe.mem_write(STACK+0x8000,struct.pack('<4I',STOP,*seen['callback']))
        exe.emu_start(0x72db0c,STOP,count=500)
        # Native model+1c is written after the coordinate/type match.
        color_offset=0x1c
        assert get32(exe,model+color_offset)==(0x888888,0x00ff00,0xff0000)[side]
        results.append(dict(kind='flag reader and engine color store',packet=packet.hex(),callback=seen['callback']))
    u=emulator();obj=DATA+0x9000;handle=DATA+0x8000;vtable=DATA+0x8100;flush=DATA+0x8200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    slots=DATA+0x100;pet=DATA+0x1000
    put32(u,0xac618c,slots);put32(u,slots,pet);put32(u,pet+0x28,1);u.mem_write(pet+0x5ff1,b'\1')
    # Real, non-empty native selections exposed a reversed server decoder.
    for offset,template in ((0x31d8,208),(0x36f8,210),(0x3988,212),(0x3c18,301),(0x4138,302)):
        put32(u,pet+offset,template)
    for global_pointer in (0xac5974,0xac643c):
        put32(u,global_pointer,DATA+0x7400);put32(u,DATA+0x7400,DATA+0x7500)
    def builder_hook(uc,a,size,user):
        if a==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif a in (0xa83d3c,0xa86fe8):uc.reg_write(UC_X86_REG_EAX,2 if a==0xa86fe8 else 0);return_from_stub(uc)
        elif a==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,builder_hook);u.emu_start(0x952bfc,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert decode_join(packet)==((0,0),((1,((0,208),(2,210),(3,212),(4,301),(7,302)),2),)),packet.hex()
    results.append(dict(kind='original C6/21 builder',packet=packet.hex()))
    report=dict(silver_sha256=EXPECTED_SHA,exe_sha256=EXE_SHA,method=__doc__,passed=True,checks=results)
    (ROOT/'reports').mkdir(exist_ok=True)
    (ROOT/'reports/ranked-native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Native TrueSkill rating/score/flag callbacks: PASS')


if __name__=='__main__':main()
