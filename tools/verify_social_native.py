"""Execute original B502 with name-based self/clan/foreign branch selection.

String conversion/comparison stubs use the actual supplied names. Numeric
readers, row layouts, prize branches, and cursors run unmodified original x86.
Allocation and GUI are stubbed; this does not verify a rendered client screen.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EFLAGS
from verify_clans_native import builder
from tio.achievements import catalog
from tio.protocol.achievements import encode_list


def consume(name, own, clan, *, private):
    records=[{**r,'earned':r['id']%2,'counter':r['goal']//2} for r in catalog()]
    u=emulator();packet=encode_list(0,name,records,private=private)
    u.mem_write(DATA,packet);character=DATA+0x1100
    put32(u,0xac63f8,DATA+0x1000);put32(u,0xac64a0,DATA+0x1001)
    put32(u,0xac5b7c,character);put32(u,0xac6148,DATA+0x1500);put32(u,0xac596c,DATA+0x1504)
    strings={character+0x24:own.encode('cp1251'),character+0x284:clan.encode('cp1251')}
    cursor=DATA+0x2000;rows=[];prizes={};end=[];compared=[];branches=[]
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
            strings[start]=bytes(uc.mem_read(start,p-start))
            put32(uc,a,p+1);put32(uc,d,start);return_from_stub(uc)
        elif address==0x40c0d8:
            assert d in strings
            put32(uc,a,d);return_from_stub(uc)
        elif address==0x40c354:
            equal=strings[a]==strings[d];compared.append(dict(left=strings[a].decode('cp1251'),right=strings[d].decode('cp1251'),equal=equal))
            flags=uc.reg_read(UC_X86_REG_EFLAGS)
            uc.reg_write(UC_X86_REG_EFLAGS,(flags|64) if equal else (flags&~64));return_from_stub(uc)
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
        elif address==0x9638e5:branches.append('private')
        elif address==0x963a16:branches.append('public_end')
        elif address==0x963a96:end.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-8))
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+2)
    u.emu_start(0x9637bc,STOP,count=200000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and end==[DATA+len(packet)]
    assert len(rows)==len(records)
    assert branches.count('private')==(len(records) if private else 0)
    for actual,expected in zip(rows,records):
        assert (actual['id'],actual['level'],actual['earned'])==(expected['id'],expected['level'],expected['earned'])
        if private:
            assert (actual['counter'],actual['goal'])==(expected['counter'],expected['goal'])
            assert len(actual['prizes'])==len(expected['prizes'])
            for a,e in zip(actual['prizes'],expected['prizes']):
                if e['kind']==1:assert abs(a['value']-e['value'])<0.00001
                else:assert a==e
        else:assert actual['counter']==actual['goal']==0 and not actual['prizes']
    return dict(query=name,viewer=own,viewer_clan=clan,private=private,records=len(rows),bytes=len(packet),
                consumed=end[0]-DATA,first_comparisons=compared[:2],private_rows=branches.count('private'))


def run():
    cases=[consume('Alice','Alice','Alpha',private=True),consume('Bob','Alice','Alpha',private=False),
           consume('Alpha','Alice','Alpha',private=True),consume('Bob','Alice','',private=False)]
    built=[]
    for entry,a,string,wanted in ((0x963708,0,b'Bob',b'\xb5\x01\0Bob\0'),(0x6e11b0,0,b'',b'\xaf\x0c')):
        packet=builder(entry,a=a,string=string);assert packet==wanted,(hex(entry),packet.hex())
        built.append(dict(address=hex(entry),packet_hex=packet.hex()))
    report=dict(status='PASS',binary_sha256=EXPECTED_SHA,method=__doc__,reader='9637bc',
                comparisons=['96381e','96383f','9638b9','9638da'],private_counter_reads=['9638e8','9638f3'],
                cases=cases,builders=built,collision_rule='A foreign character equal to the viewer clan name must be rejected before public encoding.',
                real_game_clients_used=False,gui_verified=False)
    folder=ROOT/'reports/gameplay-followup/stage3-social'
    (folder/'native-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Original B502 real-name branches: 4 cases,58 rows each; B501/AF0C builders PASS')


if __name__=='__main__':run()
