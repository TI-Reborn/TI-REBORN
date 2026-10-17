"""Execute complete original BA dispatcher, merge/delete and actual colour refresh.

Only managed-string storage, collection primitives and UI sinks are isolated.
Numeric readers, dispatcher86021C, full85FCC8/85FA88 name-based merge,
85FD00 ID removal and8723E4/872A4C colour refresh execute unchanged native code.
No process, GUI, authentication or hosted interaction.
"""
from pathlib import Path
import hashlib,json,sys
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import emulator,put,get,ret,run,DATA,ACTORS
from tools.verify_legacy_server_status_native import read_string
F=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-live-projection'
SOURCE=F.parent/'client-main-list-visibility/silver.dll'
SHA='e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80'

def consume(raw,base,case,level):
    u=emulator(raw,base);delta=base-0x400000;rows=[];iterators={};heap=DATA+0x5000;hits={};events=[];last=[]
    collection=DATA+0x1100;iterheap=DATA+0x1500;vtable=DATA+0x1400;dispose=DATA+0x1480
    put(u,DATA+0x1000,collection);put(u,0xac5fa0+delta,DATA+0x1000);put(u,0xacf398+delta,collection)
    put(u,vtable-4,dispose);u.mem_write(dispose,b'\xc3')
    for va,at,value in ((0xac55a4,0x3000,case['mode']),(0xac6184,0x3400,0xffffffff),(0xac5900,0x3100,0x3c)):
        put(u,va+delta,DATA+at);put(u,DATA+at,value)
    slots=DATA+0x3500;put(u,0xac618c+delta,slots);put(u,slots,ACTORS);u.mem_write(ACTORS+0x41,b'\1');put(u,ACTORS+0x5ffc,level)
    put(u,0xacf3a0+delta,DATA+0x4000);u.mem_write(DATA+0x4049,b'\0')
    before=bytes(u.mem_read(ACTORS,0x6100));own_room_before=get(u,DATA+0x3400)
    def alloc(uc,text=None,size=None):
        nonlocal heap
        at=heap;heap+=0x200;assert heap<DATA+0xf000
        if text is not None:
            at+=12;put(uc,at-4,len(text));uc.mem_write(at,text.encode('utf-16-le')+b'\0\0')
        return at
    def hook(uc,address,size,_):
        nonlocal iterheap
        va=address-delta;a,d,c=(uc.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX))
        last.append(hex(va));del last[:-16]
        if va in (0x86021c,0x85fcc8,0x85fa88,0x85fd00,0x8723e4,0x872a4c,0xc78200):hits[hex(va)]=hits.get(hex(va),0)+1
        if va in (0xa69ab0,0xa6a114):raise AssertionError('List update attempted to show/hide an owned window')
        if va==0x40ce98:uc.reg_write(UC_X86_REG_EAX,alloc(uc,size=a));ret(uc)
        elif va==0x605f1c:
            cursor=get(uc,a);name=bytes(uc.mem_read(cursor,256)).split(b'\0',1)[0];put(uc,a,cursor+len(name)+1)
            # New candidates retain the captain's original ASCII fixture Name.
            put(uc,d,alloc(uc,text=name.decode('ascii')));ret(uc)
        elif va==0x40b47c:put(uc,a,d);ret(uc)
        elif va==0x40c354:
            equal=read_string(uc,a)==read_string(uc,d);flags=uc.reg_read(UC_X86_REG_EFLAGS)
            uc.reg_write(UC_X86_REG_EFLAGS,(flags|0x40) if equal else (flags&~0x40));ret(uc)
        elif va==0x40cc38:uc.mem_write(a,bytes(uc.mem_read(d,0x30)));events.append('managed_record_copy');ret(uc)
        elif va in (0x40ceac,0x40b09c,0x68a094,0x9cfa38):ret(uc)
        elif va==0x87b43c:
            at=iterheap;iterheap+=0x10;assert iterheap<DATA+0x2000;put(uc,at,vtable);iterators[at]=-1;uc.reg_write(UC_X86_REG_EAX,at);ret(uc)
        elif va==0x87b4c0:
            iterators[a]+=1;uc.reg_write(UC_X86_REG_EAX,int(iterators[a]<len(rows)));ret(uc)
        elif va==0x87b450:uc.reg_write(UC_X86_REG_EAX,rows[iterators[a]]);ret(uc)
        elif va==0x87a980:rows.append(d);put(uc,collection+8,len(rows));events.append('add');ret(uc)
        elif va==0x87b1fc:uc.reg_write(UC_X86_REG_EAX,rows.index(d));ret(uc)
        elif va==0x87ae74:rows.pop(d);put(uc,collection+8,len(rows));events.append('delete');ret(uc)
        elif va in (0x876c44,0x87959c,0x8792e8,0x6d4e48):ret(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    states=[]
    for phase in ('create','join','leave','close'):
        packets=[bytes.fromhex(p) for p in case[phase+'_packets_hex'] if p[:4] in ('ba02','ba06')]
        assert packets
        for packet in packets:
            u.mem_write(DATA+0x2000,packet[1:]);u.reg_write(UC_X86_REG_EAX,0xba);u.reg_write(UC_X86_REG_EDX,DATA+0x2000)
            try:run(u,0x86021c,base)
            except Exception:
                print('BA dispatcher stopped',phase,hex(base),hex(u.reg_read(UC_X86_REG_EIP)-delta),last,file=sys.stderr);raise
        states.append(dict(phase=phase,rows=[dict(room_id=get(u,r),name=read_string(u,get(u,r+0x14)),members=u.mem_read(r+0x1d,1)[0],capacity=u.mem_read(r+0x1c,1)[0],colour=f'{get(u,r+0x24):08x}',blocked=u.mem_read(r+0x28,1)[0]) for r in rows]))
        if phase=='close':assert not rows
        else:
            assert len(rows)==1,'Full BA02 parser must merge the same Name rather than append duplicate rows'
            row=states[-1]['rows'][0];expected=2 if phase=='join' else 1
            assert (row['room_id'],row['members'],row['capacity'],row['name'])==(case['room_id'],expected,case['capacity'],'alice')
            colour=0xff6060ff if level==4 else (0xff606060 if expected>=case['capacity'] else 0xff50e070)
            assert row['colour']==f'{colour:08x}'
        assert u.mem_read(DATA+0x4049,1)==b'\0','Hidden browsing window was shown by unsolicited list update'
    assert bytes(u.mem_read(ACTORS,0x6100))==before and get(u,DATA+0x3400)==own_room_before
    assert hits['0x85fd00']==1 and hits['0x85fa88']==3 and hits['0x8723e4']==5
    return dict(base=hex(base),kind=case['kind'],mode=case['mode'],owned_level=level,states=states,
                original_dispatcher_hits=hits,managed_collection_events=events,numeric_readers_original=True,
                native_name_merge_and_ID_delete_executed=True,hidden_window_not_opened=True,owned_fighter_and_membership_unchanged=True)

def main():
    raw=SOURCE.read_bytes();assert hashlib.sha256(raw).hexdigest()==SHA
    report=json.loads((F/'live-tcp-cases.json').read_text());assert report['passed'] and len(report['cases'])==4
    cases=[consume(raw,base,case,level) for case in report['cases'] for base in (0x400000,0x10400000) for level in (1,4)]
    result=dict(passed=True,native_sha256=SHA,cases=cases,original_complete_BA02_and_BA06_dispatch_executed=True,
                isolated_calls='Managed strings/record storage, collection primitives, UI redraw/sort sinks/logging only',
                network_TCP_packets_from_exact_candidate=True,native_modified=False,hosted_modified=False,GUI_actions=0,authentication_calls=0)
    path=F/'native-live-projection-proof.json';assert not path.exists();path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(passed=True,native_sequences=len(cases),native_sha256=SHA)))
if __name__=='__main__':main()
