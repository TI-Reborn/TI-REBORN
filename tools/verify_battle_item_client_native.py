"""Execute candidate item GUI guards,33→target49, F7 parser and draw callback.

Native scalar writers, attack request49, UI-state/ownership/coordinate gates,
HP/AP checks and original SDK fill-rectangle forwarding execute. Managed UI,
network flush and final platform renderer remain explicit stubs. No installed
or published DLL is edited and this is not pixel validation in real clients.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI
from deploy import client_battle_items as extension
from tio.protocol.battle_item_visuals import encode_item_visuals, MAX_CELLS
from tio.protocol.battle_attack import AttackRequest, encode_attack_request
from tio.protocol.item_action import ItemAction, encode_item_action

SOURCE=ROOT/'reports/gameplay-completion/stage2-equipment/client/candidate/silver.dll'
DESTINATION=ROOT/'reports/gameplay-completion/stage3-items/client/candidate'
_candidate=None
_candidate_image=None
_external_images={}


def candidate():
    global _candidate
    if _candidate is None: _candidate=extension.patch(SOURCE.read_bytes())
    return _candidate


def runtime(client_data=None):
    global _candidate_image
    if _candidate_image is None: _candidate_image=pefile.PE(data=candidate()).get_memory_mapped_image()
    if client_data is None:image=_candidate_image
    else:
        digest=hashlib.sha256(client_data).hexdigest()
        if digest not in _external_images:_external_images[digest]=pefile.PE(data=client_data).get_memory_mapped_image()
        image=_external_images[digest]
    u=emulator();u.mem_map(0x400000+extension.RVA,(len(image)-extension.RVA+0xfff)&~0xfff)
    u.mem_write(0x400000,image)
    for index,(global_address,value) in enumerate(((0xac64a0,1),(0xac5a30,0),(0xac561c,38),
        (0xac5494,38),(0xac61b0,100),(0xac6068,200),(0xac5834,0),(0xac5940,0))):
        pointer=DATA+0x100+index*16;put32(u,global_address,pointer);put32(u,pointer,value)
    obj,handle,vtable,flush=DATA+0x1000,DATA+0x3000,DATA+0x3100,DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    put32(u,0xac618c,DATA+0x4000);put32(u,DATA+0x4000,DATA+0x5000)
    put32(u,DATA+0x5000+0x28,17);put32(u,0xac637c,DATA+0x4500);put32(u,DATA+0x4500,DATA+0xb000)
    return u,dict(packets=[],cursors=[],draws=[],calls=[],cell=(5,6),active_index=0,can_act=1)


def hooks(u,result):
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,DATA+0x3000);return_from_stub(uc)
        elif address==DATA+0x3200:
            result['packets'].append(bytes(uc.mem_read(DATA+0x1000+4,get32(uc,DATA+0x1000+0x1004))))
            put32(uc,DATA+0x1000+0x1004,0);return_from_stub(uc)
        elif address==0xa6a610:
            result['cursors'].append(uc.reg_read(UC_X86_REG_EAX));return_from_stub(uc)
        elif address==0xa843d4:uc.reg_write(UC_X86_REG_EAX,result['active_index']&0xffffffff);return_from_stub(uc)
        elif address==0xa843ac and not result.get('native_actor_guards'):
            uc.reg_write(UC_X86_REG_EAX,result['can_act']);return_from_stub(uc)
        elif address==0x9db7ac:
            x,y=result['cell'];put32(uc,uc.reg_read(UC_X86_REG_EAX),x&0xffffffff)
            put32(uc,uc.reg_read(UC_X86_REG_EDX),y&0xffffffff)
            uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
        elif address in (0x66754c,0x814608,0x72e668,0x9dc760) and not (address==0x66754c and result.get('native_actor_guards')):
            result['calls'].append(hex(address));uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
        elif address==0x87daa4:
            result['calls'].append('original_dispatch');uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0xa896f0:
            # Isolate only platform camera projection; native screen offsets
            # and SDK renderer argument forwarding below remain unmodified.
            return_from_stub(uc)
        elif address==DATA+0xf000:
            stack=uc.reg_read(UC_X86_REG_ESP)
            result['draws'].append(tuple(get32(uc,stack+i) for i in (4,8,12,16,20,24)))
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,stack+28)
    u.hook_add(UC_HOOK_CODE,hook)


def execute(u,entry,stop=STOP):
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.emu_start(entry,stop,count=100000)
    assert u.reg_read(UC_X86_REG_EIP)==stop,hex(u.reg_read(UC_X86_REG_EIP))


def select(u,result,*,template=24,actor=17,option=255,battle=1):
    frame=STACK+0x7000;put32(u,frame-0x288,template);put32(u,frame-0x294,actor);put32(u,frame+8,option)
    put32(u,get32(u,0xac64a0),battle);u.reg_write(UC_X86_REG_EBP,frame)
    execute(u,extension.SELECT_ENTRY)


def target_cases():
    cases=[]
    for change in ('normal','repeat','outside','no_actor','foreign_actor','dead_or_wrong_turn','cancel','city','other_item','explicit_option'):
        u,result=runtime();hooks(u,result)
        select(u,result,template=33 if change=='other_item' else 24,option=4 if change=='explicit_option' else 255,battle=0 if change=='city' else 1)
        if change=='outside':result['cell']=(38,6)
        if change=='no_actor':result['active_index']=-1
        if change=='foreign_actor':put32(u,DATA+0x5000+0x28,18)
        if change=='dead_or_wrong_turn':result['can_act']=0
        if change=='cancel':put32(u,get32(u,0xac5a30),0)
        execute(u,0x95db15,0x95db1a)
        if change=='repeat':execute(u,0x95db15,0x95db1a)
        assert result['packets']==([encode_attack_request(AttackRequest(17,5,6))] if change in ('normal','repeat') else [])
        assert bool(get32(u,0x400000+extension.SELECTED))==(change=='outside')
        cases.append(dict(change=change,packets_hex=[p.hex() for p in result['packets']],cursors=result['cursors']))
    return cases


def hp_cases():
    cases=[]
    # Enter the exact native medkit gate after its class=2 comparison. The
    # scoped thunk skips only the HP branch; original AP comparison executes.
    for template in (33,35,5002,5003,5011,5012):
        for ap in (0,10):
            u,result=runtime();hooks(u,result);closure=DATA+0x8000;put32(u,closure+0x18,template)
            u.mem_write(DATA+0x5000+0x6006,struct.pack('<HH',100,100));u.mem_write(DATA+0x5000+0x6004,bytes((ap,)))
            u.mem_write(DATA+0xb000+0x13c,struct.pack('<H',3));put32(u,DATA+0xb000+0x650,0)
            put32(u,0xac618c,DATA+0x4000);put32(u,DATA+0x4000,DATA+0x5000)
            u.reg_write(UC_X86_REG_EBX,closure);u.reg_write(UC_X86_REG_EDI,0);u.reg_write(UC_X86_REG_ESI,0)
            u.reg_write(UC_X86_REG_EBP,STACK+0x7000)
            reached=[]
            def gate(uc,address,size,user):
                if address in (0xa65925,0xa658da,0xa65974):reached.append(hex(address));uc.emu_stop()
            u.hook_add(UC_HOOK_CODE,gate);u.reg_write(UC_X86_REG_EAX,0);u.reg_write(UC_X86_REG_EDX,DATA+0xb000)
            u.mem_write(DATA+0xb000+0x118,struct.pack('<H',2));u.emu_start(0xa658a8,STOP,count=5000)
            special=template==35 or 5002<=template<=5011
            expected='0xa65974' if special and ap>=3 else '0xa65925' if special else '0xa658da'
            assert reached==[expected],(template,ap,reached)
            cases.append(dict(template=template,ap=ap,full_hp=True,branch=expected))
    return cases


def reader_cases():
    cases=[]
    valid=[encode_item_visuals(()),encode_item_visuals(((2,3,1),(4,5,2),(6,7,3))),
        encode_item_visuals(tuple((i%255,i//255,1) for i in range(MAX_CELLS)))]
    bad=[b'\xf7\x02\0\0',b'\xf7\x01\1\0',b'\xf7\x01\1\0\xff\2\1',
        b'\xf7\x01\1\0\1\2\4',b'\xf7\x01\1\0\1\2\1\0',b'\xf7\x01\x01\x10']
    for packet in [*valid,*bad,b'\x4e\0']:
        u,result=runtime();hooks(u,result);put32(u,0x400000+extension.COUNT,1)
        u.mem_write(DATA+0x6000,packet[1:]);u.reg_write(UC_X86_REG_EAX,packet[0])
        u.reg_write(UC_X86_REG_EDX,DATA+0x6000);u.reg_write(UC_X86_REG_ECX,len(packet))
        execute(u,extension.READER_ENTRY)
        count=get32(u,0x400000+extension.COUNT)
        expected=struct.unpack('<H',packet[2:4])[0] if packet in valid else 1 if packet[0]!=0xf7 else 0
        assert count==expected,(packet.hex(),count,expected)
        if packet in valid: assert bytes(u.mem_read(0x400000+extension.CELLS,count*3))==packet[4:]
        assert bool(u.reg_read(UC_X86_REG_EAX))==(packet[0]==0xf7)
        cases.append(dict(bytes=len(packet),valid=packet in valid,count=count,stock=packet[0]!=0xf7))
    return cases


def draw_case(battle=1):
    u,result=runtime();hooks(u,result);put32(u,get32(u,0xac64a0),battle)
    put32(u,0x400000+extension.COUNT,3);u.mem_write(0x400000+extension.CELLS,b'\2\3\1\4\5\2\6\7\3')
    put32(u,0xac5a00,DATA+0xf100);put32(u,DATA+0xf100,DATA+0xf000)
    execute(u,extension.DRAW_ENTRY)
    expected=[(172,307,16,10,0x60696969,0),(236,371,16,10,0x50ffe36b,0),(300,435,16,10,0x3052a8ff,0)] if battle else []
    assert result['draws']==expected,result['draws']
    put32(u,0x400000+extension.COUNT,0);before=len(result['draws']);execute(u,extension.DRAW_ENTRY)
    assert len(result['draws'])==before
    return dict(battle=battle,draws=result['draws'],empty_snapshot_clears=True)


def double_click_case(template, kind, ap=10, battle=1, *, client_data=None,
                      server_nvg_packet=None, actor=17, can_act=1, repeat=1, expected_packets=None,
                      native_actor_guards=False,actor_usable=True):
    """Actual original inventory double-click → a6516c →33, then map caller49."""
    u,result=runtime(client_data=client_data);hooks(u,result);put32(u,get32(u,0xac64a0),battle)
    put32(u,DATA+0x5000+0x28,actor);result['can_act']=can_act
    result['native_actor_guards']=native_actor_guards
    if native_actor_guards:
        # Actual a843ac uses actor+41 and the original 6a10f4 owner/turn
        # comparison. The cached ordinary-client privilege check stays false.
        u.mem_write(DATA+0x5000+0x41,bytes((int(actor_usable),)))
        put32(u,0xac5cd4,DATA+0x230);put32(u,DATA+0x230,1)
        put32(u,0xac5a98,DATA+0x234);put32(u,DATA+0x234,1 if can_act else 2)
        u.mem_write(0xac4500,b'\1');u.mem_write(0xacd294,b'\0')
        put32(u,0xb772dc,0);put32(u,0xb772d8,0)
    if server_nvg_packet is not None:
        u.mem_write(DATA+0x6000,server_nvg_packet[1:]);u.reg_write(UC_X86_REG_EAX,server_nvg_packet[0])
        u.reg_write(UC_X86_REG_EDX,DATA+0x6000);u.reg_write(UC_X86_REG_ECX,len(server_nvg_packet))
        # Execute the actual exported PacketHandler call site and receiver
        # chain, including F8/F7 fallback, rather than assigning cached state.
        execute(u,0x9f5563,0x9f5568)
    metadata_ap=5 if template==24 else 10 if template==35 else 3 if template==5002 else 0 if 5003<=template<=5011 else 2
    widget=DATA+0x7000;closure=DATA+0x8000;item=widget+0x288
    put32(u,item+8,template);put32(u,item+0x28,1001)
    put32(u,0xac64b4,DATA+0x200);put32(u,DATA+0x200,0)
    for address in (0xac62f8,0xac6118):put32(u,address,DATA+0x220)
    put32(u,DATA+0x5000+4,1)
    u.mem_write(DATA+0x5000+0x6006,struct.pack('<HH',100,100))
    u.mem_write(DATA+0x5000+0x6004,bytes((ap,)))
    u.mem_write(DATA+0xb000+0x118,struct.pack('<H',kind));u.mem_write(DATA+0xb000+0x68d,b'\1')
    u.mem_write(DATA+0xb000+0x13c,struct.pack('<H',metadata_ap));put32(u,DATA+0xb000+0x650,0)
    messages=[]
    def hook(uc,address,size,user):
        values={0x4092ac:closure,0xa93f70:0,0xa7b030:0,0x99f5d8:0,0xa93eec:1,0xa54980:0}
        if native_actor_guards:
            values.pop(0xa93f70);values.pop(0xa93eec)
        if address in values:uc.reg_write(UC_X86_REG_EAX,values[address]);return_from_stub(uc)
        elif address in (0xa42f18,0x40cb10,0x40b09c,0x40c9a4,0x40ec90,0x40b0fc,0xa68df4):return_from_stub(uc)
        elif address==0x40eca8:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX));return_from_stub(uc)
        elif address==0x40cc38:
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),0x290)));return_from_stub(uc)
        elif address==0x6675e0:
            put32(uc,uc.reg_read(UC_X86_REG_EDX),0);return_from_stub(uc)
        elif address==0x689fb0:messages.append(hex(address));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    for _ in range(repeat):
        u.reg_write(UC_X86_REG_EAX,widget);execute(u,0xa4dba0)
    allowed=(template!=33 and ap>=metadata_ap)
    expected=([encode_item_action(ItemAction(actor,1001,255))] if allowed and can_act else []) if expected_packets is None else expected_packets
    assert result['packets']==expected,(template,ap,result['packets'],expected)
    if expected_packets is None and can_act:assert bool(messages)==(not allowed)
    if allowed and template==24:
        execute(u,0x95db15,0x95db1a)
        assert result['packets'][-1]==encode_attack_request(AttackRequest(17,5,6))
    return dict(template=template,kind=kind,ap=ap,metadata_ap=metadata_ap,battle=battle,full_hp=True,allowed=bool(result['packets']),
        original_metadata_ap_would_allow=allowed,
        packets_hex=[p.hex() for p in result['packets']],
        gui_chain='a4dba0→a6516c→9903a4→33; binocular selection→95db15→49',
        actor=actor,can_act=can_act,repeat=repeat,ap_rejection_messages=len(messages),
        native_actor_guards=native_actor_guards,actor_usable=actor_usable,
        nvg_snapshot_hex=server_nvg_packet.hex() if server_nvg_packet is not None else None)


def main():
    source=SOURCE.read_bytes();raw=candidate();assert extension.patch(raw)==raw
    # A source with unapproved code must fail, even when its marker looks right.
    corrupted=bytearray(source);corrupted[0x1000]^=1
    try:extension.patch(bytes(corrupted))
    except ValueError:pass
    else:raise AssertionError('Unapproved client base accepted')
    report=dict(status='PASS',method=__doc__,preservation=extension.patch_plan(source,raw),
        namespace='F7/v1 and targeting state11 are explicit emulator extensions',
        hp_cases=hp_cases(),binocular_cases=target_cases(),reader_cases=reader_cases(),draw_cases=[draw_case(),draw_case(0)],
        double_click_cases=[double_click_case(t,k,a) for t,k,a in ((24,12,10),(35,2,10),(5002,2,10),(5003,2,10),(33,2,10),(35,2,0))])
    report['booster_city_double_click_cases']=[double_click_case(t,2,0,0) for t in range(5003,5012)]
    DESTINATION.mkdir(parents=True,exist_ok=True)
    (DESTINATION/'silver.dll').write_bytes(raw)
    (DESTINATION/'patch-plan.json').write_text(json.dumps(report['preservation'],indent=2)+'\n',encoding='utf-8')
    (ROOT/'evidence/battle_item_client_native.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Candidate item client: HP/AP12, binocular10, F7parser10, renderer2, original GUI doubleclick6 + booster city9 cases PASS; source bytes outside5 hooks+PE sizes preserved')


if __name__=='__main__':main()
