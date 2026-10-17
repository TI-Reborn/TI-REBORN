"""Original corpse HP transition and owner elimination predicate; rendering isolated."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX


def death(old):
    u=emulator();actor=DATA+0x2000;table=DATA+0x100
    put32(u,0xac618c,table);put32(u,table,actor)
    put32(u,0xac64b4,DATA+0x200);put32(u,DATA+0x200,0xffffffff)
    u.mem_write(actor+0x6006,struct.pack('<H',old));u.mem_write(actor+0x40,b'\x01')
    calls=[]
    def hook(uc,address,size,user):
        if address==0xa93f70:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0xa86cd8:
            calls.append('DeathAnimation');return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+8)
        elif address in (0xa855ac,0x43afc0,0x68a774,0xa88a78):return_from_stub(uc)
        elif address==0x8c76a0:uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,4);u.reg_write(UC_X86_REG_ECX,0)
    u.emu_start(0x8c7320,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==0x8c76a0
    assert int.from_bytes(u.mem_read(actor+0x6006,2),'little')==0
    assert calls==(['DeathAnimation'] if old else [])
    assert u.mem_read(actor+0x40,1)[0]==(0 if old else 1)
    return dict(initial_hp=old,final_hp=0,death_calls=len(calls))


def eliminated(states,owner=8):
    u=emulator();table=DATA+0x100;put32(u,0xac618c,table)
    u.mem_map(0x4000000,0x30000)
    for index,(hp,removed,pos) in enumerate(states):
        actor=0x4000000+index*0x10000
        put32(u,table+index*4,actor);put32(u,actor+0x2c,owner)
        u.mem_write(actor+0x6006,struct.pack('<H',hp));u.mem_write(actor+0x20,bytes((removed,)))
        put32(u,actor+0x603c,pos);put32(u,actor+0x6040,pos)
    u.reg_write(UC_X86_REG_EAX,owner);u.emu_start(0x9c04bc,STOP,count=2000)
    return bool(u.reg_read(UC_X86_REG_EAX)&255)


def main():
    cases=[death(0),death(1)]
    assert eliminated([(0,0,5),(100,1,255)])
    assert not eliminated([(0,0,5),(1,0,255)])
    assert eliminated([(0,0,5),(0,0,255)])
    from trace_battle_soldier_native import trace
    from tio.protocol.battle_soldier import decode_battle_soldier,encode_battle_soldier
    fixtures=json.loads((ROOT/'evidence/battle_soldier_native_variants.json').read_text())
    base=next(c for c in fixtures if c['profile']['human'])
    soldier=decode_battle_soldier(b'\x3b'+bytes.fromhex(base['body_hex']),human_equipment=True)
    soldier.fields.update({'0x8c519b':255,'0x8c51af':255,'0x8c57bb':1})
    result=trace(body=encode_battle_soldier(soldier)[1:],human=True)
    assert result['model']['position']==[255,255] and result['model']['health']==1
    report=dict(sha256=EXPECTED_SHA,method=__doc__,death=cases,hidden_actor=result['model'],owner_predicate_cases=3)
    (ROOT/'evidence/corpse_visibility_native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Original HP transition, hidden snapshot and elimination predicate: 6 cases PASS')

if __name__=='__main__':main()
