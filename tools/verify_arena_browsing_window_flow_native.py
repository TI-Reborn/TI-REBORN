"""Actual selector callback -> registry Show -> OnShow -> category event -> BA01.

Executes original window lookup/collection access, A69AB0 Show, A436E8,
A54980 event dispatch, 873E40 owned selected scan, complete 873AD0, 8723A0,
the actually bound 875630/8755BC category callbacks and BA01 encoding.
Only managed strings, an empty row iterator, terminal Visible property,
message/render/platform sinks and transport flush are isolated. No native
game process, GUI input, authentication, server or packet injection.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import emulator,put,get,ret,run,DATA,ACTORS
from tools.verify_legacy_server_status_native import read_string
from tools.verify_arena_browsing_visible_native import FOLDER,SOURCE
from deploy.client_server_list_status import sha


def flow(raw,base,category,roster,*,initial_mode=0,jailed=False,direct=False):
    u=emulator(raw,base);delta=base-0x400000;hits={};property_calls=[];messages=[]
    manager,collection,items,empty,vtable,setter=(DATA+x for x in (0x1000,0x1500,0x1600,0x1700,0x1800,0x1900))
    main,selector=(DATA+x for x in (0x2000,0x2500))
    # Original A436E8/0C call this terminal fixture Visible setter via vtable.
    put(u,vtable,setter);u.mem_write(setter,bytes.fromhex('885049c3'))
    put(u,manager+0x280,collection);put(u,manager+0x284,empty)
    put(u,collection+4,items);put(u,collection+8,2);put(u,items,main);put(u,items+4,selector)
    heap=DATA+0xb000
    def text(value):
        nonlocal heap
        at=heap+12;heap+=0x200;assert heap<DATA+0xf000
        u.mem_write(at-12,bytes.fromhex('b0040200')+(1).to_bytes(4,'little')+len(value).to_bytes(4,'little'))
        u.mem_write(at,value.encode('utf-16-le')+b'\0\0');return at
    for obj,name,visible in ((main,'window_serverlist',0),(selector,'window_mercenaries_selector',1)):
        put(u,obj,vtable);put(u,obj+0x2c,empty);put(u,obj+0x68,text(name));u.mem_write(obj+0x49,bytes((visible,)))
        put(u,obj+0x38,640);put(u,obj+0x3c,400)
    event_array=DATA+0x1a00;put(u,event_array-4,1);put(u,event_array,0x873e40+delta);put(u,main+0x310+0x10,event_array)
    put(u,0xb76650+delta,manager);put(u,0xac622c+delta,DATA+0x1b00);put(u,DATA+0x1b00,manager)
    for global_va,offset,value in ((0xac56e0,0x1c00,1280),(0xac5e60,0x1c04,960),(0xac5fe4,0x1c08,0),
                                  (0xac5900,0x1c0c,0),(0xac6490,0x1c10,int(jailed)),(0xac5dec,0x1c14,0),
                                  (0xac6248,0x1c20,0),(0xac5fa0,0x1c40,0)):
        put(u,global_va+delta,DATA+offset);put(u,DATA+offset,value)
    put(u,0xac48a0+delta,initial_mode);put(u,0xac489c+delta,0xffffffff)
    # Native event array exactly mirrors the actual category bindings.
    for global_va,offset,handler in ((0xacf3d0,0x3000,0),(0xacf3d8,0x3400,0x875630),(0xacf3d4,0x3800,0x8755bc)):
        control=DATA+offset;array=control+0x380;put(u,global_va+delta,control)
        if handler:put(u,array-4,1);put(u,array,handler+delta);put(u,control+0x2a0+0x10,array)
    for index,global_va in enumerate((0xacf3bc,0xacf3b8,0xacf3b0,0xacf3b4,0xacf3ac,0xacf3a8,0xacf3c0,0xacf3c4,0xacf3c8,0xacf3cc,0xacf39c)):
        control=DATA+0x4000+index*0x300;put(u,global_va+delta,control);put(u,control,vtable)
    put(u,0xacf394+delta,empty);put(u,0xacf398+delta,empty)
    slots=DATA+0x6800;put(u,0xac618c+delta,slots);before=[]
    for index,(level,selected) in enumerate(roster):
        actor=ACTORS+index*0x7000;put(u,slots+index*4,actor);u.mem_write(actor+0x41,b'\1')
        put(u,actor+0x5ffc,level);u.mem_write(actor+0x5ff1,bytes((selected,)))
        before.append((actor,bytes(u.mem_read(actor,0x6100))))
    obj,handle,tv,flush=(DATA+x for x in (0x8000,0x9200,0x9300,0x9400))
    put(u,handle,obj);put(u,obj,tv);put(u,tv,flush);put(u,0xac600c+delta,handle)
    watched=(0x9443d0,0x944434,0x873ad0,0xa69ab0,0xa6a114,0xa3fca8,0xa3f2a0,0xa5a528,
             0xa436e8,0xa4370c,0xa54980,0x873e40,0x873e7f,0x873e84,0x873ea7,0x873ed9,
             0x8731cc,0x8723a0,0x875630,0x8755bc,0x85f890)
    last=[]
    def hook(uc,address,size,_):
        va=address-delta;a,d=(uc.reg_read(r) for r in (UC_X86_REG_EAX,UC_X86_REG_EDX))
        last.append(hex(va));del last[:-20]
        if va in watched:hits[hex(va)]=hits.get(hex(va),0)+1
        if address==setter:property_calls.append(dict(object=hex(a),visible=d&255));return
        if va in (0x40b180,0x40b09c,0x40b0fc):ret(uc)
        elif va==0x423a54:put(uc,d,a);ret(uc)  # fixture names are already lowercase
        elif va==0x40b4c4:put(uc,a,d);ret(uc)
        elif va==0x40c354:
            equal=read_string(uc,a)==read_string(uc,d)
            flags=uc.reg_read(UC_X86_REG_EFLAGS);uc.reg_write(UC_X86_REG_EFLAGS,(flags|64) if equal else (flags&~64));ret(uc)
        elif va==0x6675e0:put(uc,d,a);ret(uc)
        elif va==0x689fb0:messages.append(read_string(uc,a));ret(uc)
        elif va in (0x9e3c88,0x8605b8,0x876c44):ret(uc)
        elif va in (0x87b43c,0x87b4c0):uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
        elif va==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);ret(uc)
        elif address==flush:ret(uc)
        elif va in (0xa089f0,0x85f954,0x85e488,0x85f9d4):raise AssertionError('Browsing invoked gameplay/admission')
    u.hook_add(UC_HOOK_CODE,hook)
    if direct:u.mem_write(main+0x49,b'\1');put(u,0xac48a0+delta,category)
    try:run(u,0x873e40 if direct else 0x9443d0 if category==1 else 0x944434,base,count=200000)
    except Exception:
        print('Window flow stopped',hex(u.reg_read(UC_X86_REG_EIP)-delta),last,file=sys.stderr);raise
    visible=u.mem_read(main+0x49,1)[0];selected=any(s for level,s in roster)
    patched=sha(raw)!=sha((FOLDER.parent/'client-empty-roster-navigation/silver.dll').read_bytes())
    expected=int(not jailed and (selected or (patched and category in (1,4))))
    assert visible==expected,(category,initial_mode,roster,jailed,direct,visible,expected)
    packet=bytes(u.mem_read(obj+4,get(u,obj+0x1004)))
    if direct:assert packet==b''
    else:
        assert packet==b'\xba\x01' and hits.get('0xa436e8')==1 and hits.get('0x873e40')==1
        assert hits.get('0x8731cc')==1 and hits.get(hex(0x875630 if category==1 else 0x8755bc))==1
        assert hits.get('0xa54980')==2 and get(u,0xac48a0+delta)==category
        assert u.mem_read(selector+0x49,1)==b'\0'
        # Re-run the actual OnShow empty-squad guard as a subsequent refresh.
        run(u,0x873e40,base);assert u.mem_read(main+0x49,1)[0]==expected
        assert bytes(u.mem_read(obj+4,get(u,obj+0x1004)))==packet
    for actor,snapshot in before:assert bytes(u.mem_read(actor,0x6100))==snapshot
    return dict(base=hex(base),category=category,initial_category=initial_mode,owned_roster=roster,jailed=jailed,
                direct_OnShow=direct,window_visible=bool(visible),expected_visible=bool(expected),
                original_native_hits=hits,actual_callback='875630' if category==1 else '8755bc',
                original_browse_request_hex=packet.hex(),selected_and_owned_fighters_unchanged=True,
                subsequent_OnShow_keeps_expected_visibility=not direct,terminal_property_calls=property_calls,
                admission_requests=0,messages=messages)


def main():
    raw=(FOLDER/'silver.dll').read_bytes();old=(FOLDER.parent/'client-empty-roster-navigation/silver.dll').read_bytes()
    cases=[];regressions=[];guards=[]
    for base in (0x400000,0x10400000):
        for category in (1,4):
            for roster in ([],[(4,0),(4,0)],[(1,1)],[(4,0),(1,0)]):
                cases.append(flow(raw,base,category,roster))
            regressions.append(flow(old,base,category,[(4,0),(4,0)],initial_mode=0))
            guards.append(flow(raw,base,category,[(4,0),(4,0)],jailed=True))
        for category in (0,2,3,8):
            guards.append(flow(raw,base,category,[],direct=True))
            guards.append(flow(old,base,category,[],direct=True))
    report=dict(passed=True,method=__doc__,source_sha256=sha(SOURCE.read_bytes()),candidate_sha256=sha(raw),
                previous8735_sha256=sha(old),first_entry_and_subsequent_OnShow_cases=cases,
                original_empty_squad_hide_regressions=regressions,other_categories_and_jail_guards=guards,
                original_owned_gui_trace='owned-d-main-transition-before-fix.json',
                original_owned_gui_trace_sha256=sha((FOLDER/'owned-d-main-transition-before-fix.json').read_bytes()),
                no_window_lookup_bypass=True,no_show_or_OnShow_or_event_dispatch_stubs=True,
                real_graphical_clients=0,hosted_modified=False,authentication_calls=0)
    path=FOLDER/'actual-native-window-flow-proof.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('PASS actual registry Show/OnShow/category callbacks: first entry and subsequent empty squad; other modes/jail unchanged')
if __name__=='__main__':main()
