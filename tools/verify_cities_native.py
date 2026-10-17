"""Original silver.dll ground reader consumes all generated city packets.

Allocation, strings and resource loading are isolated; this does not render maps.
"""
from verify_auth_native import *
from tio.map_generation import generate_map
from tio.protocol.battle_ground import encode_battle_ground


def run(profile,mode):
    scene=generate_map(profile,seed=7,mode=mode,deployment_size=6)
    p=scene.arena.ground;body=encode_battle_ground(p)[1:]
    u=emulator();u.mem_map(DATA+0x10000,0x10000);u.mem_write(DATA+0x18000,body)
    put32(u,0xac618c,DATA+0x1000);put32(u,0xac561c,DATA+0x1100)
    put32(u,0xac5494,DATA+0x1104);put32(u,0xac6498,DATA+0x1200)
    put32(u,DATA+0x1200,DATA+0x1300)
    for x in range(p.width):put32(u,DATA+0x1300+x*4,DATA+0x4000+x*0x400)
    names=[];consumed=[]
    def hook(uc,a,size,user):
        if a in (0x9dc14c,0x9596b8,0x95dd54,0x40b09c,0x40c9f4):return_from_stub(uc)
        elif a==0x605f1c:
            cursor=uc.reg_read(UC_X86_REG_EAX);start=get32(uc,cursor);end=start
            while uc.mem_read(end,1)!=b'\0':end+=1
            names.append(bytes(uc.mem_read(start,end-start)))
            put32(uc,cursor,end+1);return_from_stub(uc)
        elif a==0x95df1a:consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-(DATA+0x18000))
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+0x18000)
    u.emu_start(0x95dd78,STOP,count=500000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==[len(body)]
    assert names==[e.name for e in p.entries]
    grid=[get32(u,DATA+0x4000+x*0x400+y*8) for y in range(p.height) for x in range(p.width)]
    assert grid==list(p.second_layer)
    return dict(profile=profile,mode=mode,width=p.width,height=p.height,bytes_consumed=len(body),objects=len(names),passed=True)


if __name__=='__main__':
    cases=[run(p,m) for p in ('denver','new_york','military_zone') for m in (0,1,4)]
    folder=ROOT/'reports/cities';folder.mkdir(parents=True,exist_ok=True)
    (folder/'native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,cases=cases),indent=2)+'\n')
    print('Original city ground reader: 9 cases PASS')
