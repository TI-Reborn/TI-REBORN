"""Execute the exact C# launcher payload in original ti.exe memory.

Checks collision before fog, adjacent surfaces after fog, original CanTrace,
deferred receiver states, stack/register preservation and scene bounds.
Rendering/audio are isolated; this is not a graphical-client acceptance test.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator,EXE_SHA
from verify_shot_geometry_native import NativeSight
from unicorn.x86_const import UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI

REPORT=Path(__import__('os').environ.get('TIO_DOOR_REPORT',ROOT/'reports/battle-screen-fixes-20261016'))

class Probe:
    def __init__(self):
        self.plan=json.loads((REPORT/'launcher-door-proof.json').read_text())
        self.u=u=exe_emulator();self.base=self.plan['allocation']
        u.mem_map(self.base,4096);u.mem_write(self.base,bytes.fromhex(self.plan['code']))
        for address,target in ((0x76e000,DATA+0x1000),(0x76e5f4,DATA+0x200),
                               (0x76dfac,DATA+0x300),(0x76e068,DATA+0x304),
                               (0x76e430,DATA+0x7000)):
            put32(u,address,target)
        put32(u,DATA+0x1000,DATA+0x1100);put32(u,DATA+0x11d0,DATA+0x1200)
        put32(u,DATA+0x1204,DATA+0x1300);put32(u,DATA+0x1208,2)
        put32(u,DATA+0x1300,DATA+0x9000);put32(u,DATA+0x1304,DATA+0xa000)
        put32(u,DATA+0x200,DATA+0x400);put32(u,DATA+0x424,8|(8<<16))
        put32(u,DATA+0x40c,DATA+0x2000);put32(u,DATA+0x41c,DATA+0x2100)
        for x in range(8):
            put32(u,DATA+0x2000+x*4,DATA+0x3000+x*0x100)
            put32(u,DATA+0x2100+x*4,DATA+0x5000+x*0x100)
        put32(u,DATA+0x300,7);put32(u,DATA+0x304,199)
        put32(u,DATA+0x7000,DATA+0x8000)
        self.actor(owner=7,hp=100,x=2,y=3)
        for door,x,y in ((0x9000,3,3),(0xa000,7,7)):
            put32(u,DATA+door+4,x);put32(u,DATA+door+8,y)
            u.mem_write(DATA+door+0x340,b'\x01');u.mem_write(DATA+door+0x411,b'\x02')
        self.runs=0
        def hook(uc,address,size,user):
            if address==0x6e40aa:
                # Native rendering internals isolated. Clear the fog exactly
                # where native tracing runs, between the adapter's two phases.
                assert self.cell(3,3)==(3 if self.state()==1 else 0)
                uc.mem_write(DATA+0x5000,bytes(0x800));self.runs+=1
                frame=uc.reg_read(UC_X86_REG_EBP)
                uc.reg_write(UC_X86_REG_ESP,frame)
                uc.reg_write(UC_X86_REG_EBP,get32(uc,frame))
                uc.reg_write(UC_X86_REG_ESP,frame+4);return_from_stub(uc)
            elif address==0x72dc96:uc.emu_stop()
        u.hook_add(UC_HOOK_CODE,hook)
        u.mem_write(0x6e40a4,bytes.fromhex(self.plan['fog_hook']))
        u.mem_write(0x72dc90,bytes.fromhex(self.plan['door_hook']))

    def actor(self,owner=7,hp=100,x=2,y=3):
        u=self.u;put32(u,DATA+0x8064,owner)
        u.mem_write(DATA+0x8008,struct.pack('<H',hp^199))
        put32(u,DATA+0x81bc,x&0xffffffff);put32(u,DATA+0x81c0,y&0xffffffff)

    def state(self,value=None,door=0x9000):
        if value is not None:self.u.mem_write(DATA+door+0x340,bytes((value,)))
        return self.u.mem_read(DATA+door+0x340,1)[0]

    def cell(self,x,y,value=None):
        a=DATA+0x3000+x*0x100+y*14
        if value is not None:self.u.mem_write(a,bytes((value,)))
        return self.u.mem_read(a,1)[0]

    def seen(self,x,y):return self.u.mem_read(DATA+0x5000+x*0x100+y*6,1)[0]

    def refresh(self):
        u=self.u;sp=STACK+0x8000;put32(u,sp,STOP)
        u.reg_write(UC_X86_REG_ESP,sp)
        registers={UC_X86_REG_EAX:DATA+0x400,UC_X86_REG_EBX:0x12345678,
                   UC_X86_REG_ESI:0x87654321,UC_X86_REG_EDI:0x23456789,UC_X86_REG_EBP:0x34567890}
        for r,value in registers.items():u.reg_write(r,value)
        u.emu_start(0x6e40a4,STOP,count=100000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        assert u.reg_read(UC_X86_REG_ESP)==sp+4
        for r,value in registers.items():assert u.reg_read(r)==value,(r,hex(u.reg_read(r)))

def main():
    p=Probe();cases=[];sight=NativeSight()
    for state in (1,2,1,2,1,3,4):
        p.state(state);p.refresh()
        expected=state-2 if state>2 else state
        assert p.state()==expected and p.cell(3,3)==(3 if expected==1 else 0)
        assert p.seen(3,3)==int(expected==1)
        assert p.seen(4,3)==p.seen(7,7)==0
        tiles=[p.cell(x,y) for y in range(8) for x in range(8)]
        sight.load(8,8,tiles)
        ray=sight.trace((1,3),(5,3))
        assert ray==(expected==2)
        cases.append(dict(state=state,stable=p.state(),collision=p.cell(3,3),original_ray_clear=ray))
    p.state(1)
    # The original click handler72e370 compares this rounded distance to1.
    # Its native math already accepts diagonals; only the surface was hidden.
    native_distances=[]
    for dx,dy in ((-1,-1),(-1,1),(1,-1),(1,1),(0,1),(1,0),(2,0),(2,2)):
        u=p.u;sp=STACK+0x8000;put32(u,sp,STOP)
        u.mem_write(sp+4,struct.pack('<ffff',3.,3.,float(3+dx),float(3+dy)))
        u.reg_write(UC_X86_REG_ESP,sp);u.emu_start(0x7493c8,STOP,count=1000)
        distance=u.reg_read(UC_X86_REG_EAX)&0xffff
        assert (distance<=1)==(max(abs(dx),abs(dy))==1)
        assert u.reg_read(UC_X86_REG_ESP)==sp+20
        native_distances.append(dict(offset=[dx,dy],distance=distance))
    for kwargs in (dict(hp=0),dict(owner=8),dict(x=0,y=0),dict(x=-1),dict(x=255)):
        p.actor(**kwargs);p.refresh();assert p.seen(3,3)==0
    neighbor_cases=0
    for dx in (-1,0,1):
        for dy in (-1,0,1):
            if not (dx or dy):continue
            p.actor(x=3+dx,y=3+dy)
            for a in (0,3):
                for b in (0,3):
                    if dx and dy:p.cell(3+dx,3,a);p.cell(3,3+dy,b)
                    p.refresh();assert p.seen(3,3)==1
                    assert all(p.seen(x,y)==0 for x in range(8) for y in range(8) if (x,y)!=(3,3))
                    neighbor_cases+=1
                    if dx and dy:p.cell(3+dx,3,0);p.cell(3,3+dy,0)
    # Receiver wrapper normalizes only door flag1, leaves crates unchanged.
    for flag in (0,1):
        for state in (1,2,3,4):
            u=p.u;sp=STACK+0x8000;put32(u,sp,STOP);put32(u,sp+4,flag);put32(u,sp+8,state)
            u.reg_write(UC_X86_REG_ESP,sp);u.reg_write(UC_X86_REG_EAX,DATA+0x9000)
            u.emu_start(0x72dc90,STOP,count=100)
            assert u.reg_read(UC_X86_REG_EIP)==0x72dc96,(flag,state,hex(u.reg_read(UC_X86_REG_EIP)))
            assert get32(u,sp+8)==(state-2 if flag==1 and state>=3 else state)
    # Empty/oversized scene never traverses invalid memory.
    for count in (0,10001):
        put32(p.u,DATA+0x1208,count);p.u.mem_write(DATA+0x5000,bytes(0x800))
        p.refresh();assert p.seen(3,3)==0
    result=dict(passed=True,exe_sha256=EXE_SHA,cases=cases,observer_limits=5,neighbor_cases=neighbor_cases,receiver_cases=8,native_click_distances=native_distances,
                stack_and_registers_preserved=True,original_ray_code_unstubbed=True,scope=__doc__)
    (REPORT/'launcher-native-doors.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Exact launcher native adapter, original sight, observer limits and receiver: PASS')

if __name__=='__main__':main()
