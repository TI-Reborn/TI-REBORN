"""Run original B502/B503 readers, stubbing allocation, strings and GUI only.

Primitive numeric readers, all prize branches, grouping and complete flags
execute from the unmodified silver.dll. This is not live visual verification.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EFLAGS
from tio.achievements import catalog
from tio.protocol.achievements import encode_list,encode_awards


def consume(records,notification=False,private=True):
    u=emulator()
    packet=encode_awards(records) if notification else encode_list(0,'ProbeNew' if private else 'Other',records,private=private)
    u.mem_write(DATA,packet)
    put32(u,0xac63f8,DATA+0x1000);put32(u,0xac64a0,DATA+0x1001)
    put32(u,0xac5b7c,DATA+0x1100);put32(u,0xac6148,DATA+0x1200);put32(u,0xac596c,DATA+0x1204)
    cursor=DATA+0x2000;rows=[];prizes={};end=[]
    def allocate(size):
        nonlocal cursor
        address=cursor;cursor+=(size+15)&~15
        assert cursor<DATA+0xf000
        return address
    def hook(uc,address,size,user):
        a,d=uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)
        if address==0x605f1c:
            start=get32(uc,a);p=start
            while uc.mem_read(p,1)!=b'\0':p+=1
            put32(uc,a,p+1);put32(uc,d,start);return_from_stub(uc)
        elif address==0x40c0d8:
            put32(uc,a,DATA+3);return_from_stub(uc)
        elif address==0x40c354:
            flags=uc.reg_read(UC_X86_REG_EFLAGS)
            uc.reg_write(UC_X86_REG_EFLAGS,(flags|64) if private else (flags&~64));return_from_stub(uc)
        elif address==0x6b940c:
            obj=allocate(0x38);put32(uc,obj+0x30,allocate(16));uc.reg_write(UC_X86_REG_EAX,obj);return_from_stub(uc)
        elif address==0x40ce98:
            uc.reg_write(UC_X86_REG_EAX,allocate(a));return_from_stub(uc)
        elif address==0x6ba274:
            kind=uc.mem_read(d,1)[0]
            if kind==0:p=dict(kind=kind,item_id=get32(uc,d+8),count=get32(uc,d+12),enhancement=uc.mem_read(d+16,1)[0])
            else:p=dict(kind=kind,value=struct.unpack('<f',uc.mem_read(d+4,4))[0] if kind==1 else get32(uc,d+12))
            prizes.setdefault(a,[]).append(p);return_from_stub(uc)
        elif address in (0x6c10b4,0x6bdbc8,0x6bde3c):
            obj=d if address==0x6c10b4 else a
            rows.append(dict(id=get32(uc,obj+12),level=uc.mem_read(obj+25,1)[0],earned=get32(uc,obj+28),
                             counter=get32(uc,obj+32),goal=get32(uc,obj+36),prizes=prizes.get(get32(uc,obj+48),[])))
            return_from_stub(uc)
        elif address in (0x6be028,0x6b9744,0x40b0fc,0x40b09c):return_from_stub(uc)
        elif address in (0x963a96,0x963c00):
            end.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-(4 if notification else 8)))
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,DATA+2)
    u.emu_start(0x963ac8 if notification else 0x9637bc,STOP,count=200000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert end==[DATA+len(packet)],(end,len(packet))
    assert len(rows)==len(records)
    for actual,expected in zip(rows,records):
        assert (actual['id'],actual['level'],actual['earned'])==(expected['id'],expected['level'],1 if notification else expected['earned'])
        if not notification and private:assert (actual['counter'],actual['goal'])==(expected['counter'],expected['goal'])
        wanted=expected['prizes'] if private or notification else []
        assert len(actual['prizes'])==len(wanted)
        for a,e in zip(actual['prizes'],wanted):
            if e['kind']==1:assert abs(a['value']-e['value'])<0.00001
            else:assert a==e,(a,e)
    return dict(notification=notification,private=private,records=len(rows),bytes=len(packet),consumed=end[0]-DATA-2)


if __name__=='__main__':
    records=[{**r,'earned':r['id']%2,'counter':r['goal']//2} for r in catalog()]
    records.append(dict(id=100,level=2,earned=1,counter=2,goal=5,prizes=[dict(kind=2,value=123)]))
    results=[consume([]),consume(records),consume(records,private=False),consume([],True),consume(records,True)]
    (ROOT/'evidence/achievements_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,results=results),indent=2)+'\n')
    print('Original B502/B503: 5 cases, all four prize kinds, exact consumption PASS')
