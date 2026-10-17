"""Execute original result selection and floating-text branch in silver.dll.

Unicorn runs native getters, result selection and text placement helper.
Localization, visibility, screen coordinates and final draw queue are explicit
stubs. This proves the client requests the original text, not rendered pixels.
"""
from verify_auth_native import *
from verify_attack_native import response
from unicorn.x86_const import UC_X86_REG_EBX
from tio.protocol.battle_attack import AttackResult,AttackHit


def consume(global_result,hit_result,skill_id=0):
    u=emulator();frame=STACK+0x7000;sp=frame-0x800
    slots=DATA+0x1000;metadata=DATA+0x5000;obj=DATA+0x8000;text=DATA+0x9000
    u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_ESP,sp)
    u.reg_write(UC_X86_REG_EBX,slots)
    put32(u,frame-0x24,obj);u.mem_write(obj+0x4d,bytes((global_result,1)))
    put32(u,frame-0x68,skill_id)
    u.mem_write(frame-0xe8+5,bytes((hit_result,1)))
    put32(u,frame-8,0);put32(u,frame-12,1);put32(u,frame-0x30,0)
    put32(u,slots,DATA+0x2000);put32(u,slots+4,DATA+0x3000)
    put32(u,0xac618c,slots)
    put32(u,0xac637c,DATA+0x4000);put32(u,DATA+0x4000,metadata)
    u.mem_write(metadata+0x12c,b'\1') # ordinary weapon; types4/8/13 suppress text
    put32(u,0xac6438,DATA+0x6000);put32(u,DATA+0x6000,DATA+0x7000)
    result={'global_result':global_result,'hit_result':hit_result,'skill_id':skill_id,
            'keys':[],'draws':[]}
    def hook(uc,address,size,user):
        if address==0x6675e0:
            key=bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EAX),8)).decode('utf-16le')
            result['keys'].append(key)
            put32(uc,uc.reg_read(UC_X86_REG_EDX),text)
            return_from_stub(uc)
        elif address in (0xa867e0,0xa867c0,0xa867d0):
            uc.reg_write(UC_X86_REG_EAX,{0xa867e0:0,0xa867c0:100,0xa867d0:200}[address])
            return_from_stub(uc)
        elif address==0x75f8bc:
            stack=uc.reg_read(UC_X86_REG_ESP)
            assert get32(uc,stack+8)==text
            result['draws'].append({'x':uc.reg_read(UC_X86_REG_EDX),
                                   'y':uc.reg_read(UC_X86_REG_ECX),
                                   'color':hex(get32(uc,stack+4)),
                                   'style':get32(uc,stack+12)})
            return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+12)
    u.hook_add(UC_HOOK_CODE,hook)
    for start,end in ((0x9603d3,0x9603de),(0x96058f,0x9605a3),(0x960694,0x9607f3)):
        u.emu_start(start,end,count=2000)
        assert u.reg_read(UC_X86_REG_EIP)==end
        assert u.reg_read(UC_X86_REG_ESP)==sp
    return result


if __name__=='__main__':
    cases=[]
    for top,hit,skill,key in ((2,0,0,'ch01'),(0,2,0,None),(0,0,0,None),
                              (0,2,22,'ch01'),(2,0,22,None),(4,4,0,'ch04')):
        row=consume(top,hit,skill)
        assert row['keys']==([] if key is None else [key]),row
        assert len(row['draws'])==(0 if key is None else 1),row
        cases.append(row)
    packets=[response(AttackResult(1,(4,1),(5,1),weapon,(AttackHit(2,0,100,flags=2),),flags=2))
             for weapon in (301,326,333)]
    language=Path(r'C:\Program Files (x86)\TIOnline\base\russian.lng').read_text(encoding='cp1251')
    labels=[line for line in language.splitlines() if line.startswith(('ch01=','ch04='))]
    assert 'ch01=*\u041f\u0440\u043e\u043c\u0430\u0445*' in labels,labels
    (ROOT/'evidence/miss_native.json').write_text(json.dumps({
        'sha256':EXPECTED_SHA,'method':__doc__,'labels':labels,'cases':cases,
        'native_writer_packets':packets},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Native miss selection/text queue:6 cases; original4B writer:3 cases PASS')
