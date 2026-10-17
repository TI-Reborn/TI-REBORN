"""Run original mining readers; isolate UI, allocation and collection adapters."""
from verify_auth_native import *
from tio.protocol.mining import occurrence,player_state,price


def run(packet,entry,stop,setup,stubs=()):
    u=emulator();u.mem_write(DATA,packet[2:]);setup(u)
    def hook(uc,a,size,user):
        if a in stubs:return_from_stub(uc)
        elif a==0x406a50:
            assert uc.reg_read(UC_X86_REG_EAX)==24
            uc.reg_write(UC_X86_REG_EAX,DATA+0x4000);return_from_stub(uc)
        elif a==0x43afc0:
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes(16));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(entry,stop,count=8000)
    assert u.reg_read(UC_X86_REG_EIP)==stop
    assert get32(u,u.reg_read(UC_X86_REG_EBP)-4)-DATA==len(packet)-2
    return u


def main():
    def setup(u):
        put32(u,0xac56fc,DATA+0x1000);put32(u,DATA+0x1000,DATA+0x2000)
    cases=[]
    for installed in (False,True):
        packet=occurrence(73,21,19,installed,500,300,200,50)
        u=run(packet,0x83481c,0x834a70,setup,(0x8197c0,0xa88a78))
        record=bytes(u.mem_read(DATA+0x4000,24))
        assert struct.unpack_from('<I',record)[0]==73
        assert record[4:7]==bytes((21,19,int(installed)))
        assert struct.unpack_from('<4I',record,8)==(500,300,200,50)
        cases.append(dict(packet=packet.hex(),record=record.hex()))
    def state_setup(u):
        put32(u,0xac64a0,DATA+0x1000);put32(u,0xac5f58,DATA+0x2000)
    u=run(player_state(miners=11,defenders=12,raiders=13,waiting_defenders=14,waiting_raiders=15),
          0x834aa4,0x834b3f,state_setup)
    assert [get32(u,DATA+0x2000+i) for i in (12,8,4,16,20)]==[11,12,13,14,15]
    # The recovered pointers bind flag1 to button_raid, flag2 to defense.
    for index,global_address in enumerate((0xacee5c,0xacee58,0xacee54,0xacee10)):
        put32(u,global_address,DATA+0x6000+index*0x400)
    def idle(uc,address,size,user):
        if address==0x8143ac:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,idle)
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
    u.emu_start(0x81541c,STOP,count=500)
    assert [bytes(u.mem_read(DATA+0x6000+i*0x400+0x4a,1))[0] for i in range(4)]==[1,0,1,0]
    def price_setup(u):
        put32(u,0xac5fb0,DATA+0x2000);put32(u,0xac5f3c,DATA+0x3000)
    u=run(price(1.25),0x834d9c,0x834dc5,price_setup)
    assert struct.unpack('<f',u.mem_read(DATA+0x2000,4))[0]==1.25
    (ROOT/'evidence/mining_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,cases=cases,
        readers=['83481c','834aa4','834d9c'],method=__doc__),indent=2)+'\n')
    print('Original occurrence, checkpoint state and price readers: PASS')


if __name__=='__main__':main()
