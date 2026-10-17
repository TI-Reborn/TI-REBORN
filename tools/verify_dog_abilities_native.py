"""Execute original door permission predicates and rejected-move recovery.

Resource classification, actor lookup, renderer/queue storage are isolated.
Permission scans, packet reads, path queue emission, UI reset writes and
queue-completion busy reset run as original x86. This is not a live UI test.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator,EXE_SHA
from tio.protocol.battle_move import BattleMove,encode_battle_move


def permission(address,kind,learned):
    u=emulator();actor=DATA;entries=DATA+0x1000
    put32(u,actor+4,3);put32(u,actor+0x304,entries);put32(u,entries-4,len(learned))
    for i,skill in enumerate(learned):put32(u,entries+i*0x348+8,skill)
    def hook(uc,a,size,user):
        if a==0xa93f9c:
            uc.reg_write(UC_X86_REG_EAX,kind);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,actor)
    u.emu_start(address,STOP,count=1000)
    return bool(u.reg_read(UC_X86_REG_EAX)&255)


def recovery(path,own=True):
    u=exe_emulator();actor=DATA+0x2000;context=DATA+0x3000
    put32(u,0x76e430,DATA+0x1000);put32(u,DATA+0x1000,actor)
    put32(u,0x76e17c,DATA+0x1100);put32(u,DATA+0x1100,context)
    put32(u,actor+0x1cc,2);put32(u,actor+0x1d0,3)
    put32(u,0x76dfac,DATA+0x1800);put32(u,DATA+0x1800,7)
    put32(u,actor+0x64,7 if own else 8)
    u.mem_write(0x76d9dc,b'\1');put32(u,0x78574c,42)
    u.mem_write(0x76daac,b'\1')
    packet=encode_battle_move(BattleMove(17,tuple(path)));u.mem_write(DATA,packet[1:])
    queued=[]
    def hook(uc,a,size,user):
        if a==0x7189b4:uc.reg_write(UC_X86_REG_EAX,0)
        elif a==0x72651c:uc.reg_write(UC_X86_REG_EAX,0)
        elif a in (0x6e40a4,0x725a3c):pass
        elif a==0x6dc920:uc.reg_write(UC_X86_REG_EIP,0x6dc9b8);return
        elif a==0x6f68a8:
            sp=uc.reg_read(UC_X86_REG_ESP)
            count=get32(uc,sp+4);p=uc.reg_read(UC_X86_REG_ECX)
            queued.append(bytes(uc.mem_read(p,count)))
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8);return
        elif a==0x6dc9f8:uc.emu_stop();return
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x6dc600,STOP,count=5000)
    assert len(queued)==max(0,len(path)-int(own))
    assert u.mem_read(0x76d9dc,1)==b'\0' and get32(u,0x78574c)==0xffffffff
    assert (get32(u,actor+0x1cc),get32(u,actor+0x1d0))==(2,3)
    corrected=None
    if queued:
        # Execute the queued scene correction from a mismatching prediction.
        # Do not replace ownership predicate723fa4 or positioning724b60.
        put32(u,actor+0x1bc,12);put32(u,actor+0x1c0,20)
        put32(u,0x76e5f4,DATA+0x4000);put32(u,DATA+0x4000,DATA+0x4100)
        record=DATA+0x5000;put32(u,record,0x3d);put32(u,record+12,DATA+0x5100)
        u.mem_write(DATA+0x5100,queued[-1])
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8004,DATA+0x6000)
        u.reg_write(UC_X86_REG_EAX,record)
        u.emu_start(0x6f57d0,0x6f598d,count=5000)
        corrected=(get32(u,actor+0x1bc),get32(u,actor+0x1c0))
        assert corrected==(2,3)
    if queued:
        frame=STACK+0x7000;put32(u,frame-4,context)
        put32(u,0x76e5f4,DATA+0x4000);put32(u,DATA+0x4000,DATA+0x4100)
        u.mem_write(context+0x18,b'\1');u.mem_write(context+0x21,b'\1')
        u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
        u.emu_start(0x6f65d3,0x6f6602,count=1000)
        assert u.mem_read(context+0x18,1)==b'\0'
        assert u.mem_read(context+0x21,1)==b'\0'
    busy=u.mem_read(0x76daac,1)[0]
    assert busy==int(not queued)
    return dict(packet=packet.hex(),own=own,queued=[p.hex() for p in queued],busy=busy,corrected_scene=corrected)


if __name__=='__main__':
    cases=[]
    for address,skill in ((0xa868cc,14),(0xa86b98,19)):
        for kind in (0,1):
            for learned in ((),(12,),(14,),(19,),(12,14,19)):
                result=permission(address,kind,learned)
                assert result==(kind==0 or skill in learned)
                cases.append(dict(function=hex(address),kind=kind,learned=learned,allowed=result))
    recovery_cases=[recovery(path,own) for own in (True,False)
                    for path in ([],[(2,3)],[(2,3),(2,3)])]
    from verify_attack_native import response
    from tio.protocol.battle_attack import AttackResult,AttackHit
    for skill in (12,23,26):
        response(AttackResult(17,(2,3),(2,3),333,skill_id=skill))
    response(AttackResult(17,(2,3),(2,3),333,(AttackHit(17,0,85,flags=2),),skill_id=12))
    # The original reaction selector chooses Evade action13 for result2.
    u=emulator();frame=STACK+0x7000;array=DATA+0x100;put32(u,array,DATA+0x1000)
    from unicorn.x86_const import UC_X86_REG_EBX
    u.reg_write(UC_X86_REG_EBX,array);u.reg_write(UC_X86_REG_EBP,frame)
    u.reg_write(UC_X86_REG_ESP,STACK+0x6000);put32(u,frame-0xc,0);put32(u,frame-8,0)
    u.mem_write(frame-0x6a,b'\2');u.emu_start(0x961286,0x9612f1,count=100)
    assert u.reg_read(UC_X86_REG_EDX)==13
    (ROOT/'evidence/dog_abilities_native.json').write_text(json.dumps(dict(
        method=__doc__,silver_sha256=EXPECTED_SHA,exe_sha256=EXE_SHA,
        permission_cases=cases,recovery_cases=recovery_cases,skill_packets=4,evade_action=13),indent=2)+'\n')
    print('Dog permissions20, rejection recovery6, skill packets4, evade selector1:31 cases PASS')
