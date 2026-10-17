"""Original radio skill GUI, mining queue writers/readers and lobby state.

No server, hosted account or installed client is changed. Original scalar
builders/readers, skill selection branches and queue membership consumer run in
Unicorn. Allocation, transport, actor selection and UI/text helpers are explicit
stubs. Skill28's radio identity is supplied by original animation.xml; installed
skills.xml lacks28, so this proves the existing GUI path with a configured skill,
not that the current client already displays a radio button.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI,UC_X86_REG_EBX
import xml.etree.ElementTree as ET
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast


def transport(u,extras=(),results=None):
    obj,handle,vtable,flush=DATA+0x1000,DATA+0x3000,DATA+0x3100,DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    packets=[]
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==flush:
            packets.append(bytes(uc.mem_read(obj+4,get32(uc,obj+0x1004))))
            put32(uc,obj+0x1004,0);return_from_stub(uc)
        elif address in extras:
            if results is not None:results.append(hex(address))
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    return packets


def radio(actor=17,x=13,y=21,selection=0,allowed=1,target=0):
    u=emulator();pet=DATA+0x5000;skills=DATA+0xc000;slot=2
    put32(u,0xac618c,DATA+0x4000);put32(u,DATA+0x4000,pet)
    put32(u,pet+0x28,actor);put32(u,pet+0x304,skills)
    u.mem_write(pet+0x603c,bytes((x,)));u.mem_write(pet+0x6040,bytes((y,)))
    put32(u,skills+slot*0x348+8,28)
    u.mem_write(skills+slot*0x348+0x337,bytes((target,)))
    put32(u,0xac5a30,DATA+0x4100);put32(u,0xac5d74,DATA+0x4200)
    packets=transport(u,(0x95da50,))
    def hook(uc,address,size,user):
        value={0xa843d4:selection&0xffffffff,0xa843ac:allowed,0x8b4dd4:0}.get(address)
        if value is not None:uc.reg_write(UC_X86_REG_EAX,value);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,slot)
    u.emu_start(0x8b5424,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    expected=[] if selection<0 or not allowed or target==1 else [encode_ability_cast(AbilityCast(28,actor,0,x,y))]
    assert packets==expected,packets
    assert bytes(u.mem_read(DATA+0x4100,1))==bytes((6 if target==1 and selection>=0 and allowed else 0,))
    return dict(skill=28,actor=actor,position=[x,y],selected_actor_index=selection,allowed=allowed,
        target_type=target,packets=[p.hex()for p in packets],selection_mode=bytes(u.mem_read(DATA+0x4100,1))[0])


def role_request(entry,role,queued):
    u=emulator();calls=[];packets=transport(u,(0x814d64,),calls)
    put32(u,0xac4804,5 if queued else 0xffffffff)
    u.emu_start(entry,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    expected=([b'\xb0\x19']if queued else [])+[bytes((0xb0,0x14,role))]
    assert packets==expected,packets
    return dict(gui_callback=hex(entry),builder='0x8346fc',role=role,already_queued=queued,
        packets=[p.hex()for p in packets],gui_close_stubs=calls)


def queue_packet(rows):
    return b'\xb0\x18'+struct.pack('<I',len(rows))+b''.join(struct.pack('<IIiB',*row)for row in rows)


def queue_roundtrip(rows,own=17):
    u=emulator();obj=DATA+0x2000;array=DATA+0x4000;flags=DATA+0x4800;out=DATA+0x6000
    put32(u,obj,array);put32(u,obj+4,len(rows));put32(u,obj+8,flags)
    for index,(identity,role,order,ready) in enumerate(rows):
        base=array+index*16;put32(u,base,identity);u.mem_write(base+4,bytes((1,role,1)))
        put32(u,base+8,order&0xffffffff);u.mem_write(base+0xc,bytes((1,ready,1)))
        u.mem_write(flags+index,b'\1')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x65963c,STOP,count=3000)
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)));assert packet==queue_packet(rows)
    assert bytes(u.mem_read(0xab783e,10))==bytes.fromhex('c70568d2ac005e000000')
    put32(u,0xacd268,0x5e);u.mem_write(DATA,packet)
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EDX,DATA);u.reg_write(UC_X86_REG_ECX,len(packet))
    u.emu_start(0x65d034,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EAX)==0x5e and get32(u,0xacd0e8)==DATA+2
    allocations=[];calls=[]
    def hook(uc,address,size,user):
        if address==0x40d5a4:
            pointer=uc.reg_read(UC_X86_REG_EAX);length=get32(uc,uc.reg_read(UC_X86_REG_ESP)+4)
            assert length==len(rows)
            target=array if pointer==obj else flags
            assert pointer in (obj,obj+8)
            put32(uc,pointer,target);allocations.append((hex(pointer),length));return_from_stub(uc)
        elif address in (0x81541c,0x815484,0x814d64):
            calls.append(hex(address));return_from_stub(uc)
        elif address in (0x4244b4,0x40c244,0x40c06c,0xa88908,0x40b0fc):
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    put32(u,obj+4,0);put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x6595f0,STOP,count=5000)
    assert get32(u,0xacd0e8)==DATA+len(packet)
    observed=[]
    for index in range(len(rows)):
        base=array+index*16
        observed.append((get32(u,base),bytes(u.mem_read(base+5,1))[0],
            struct.unpack('<i',u.mem_read(base+8,4))[0],bytes(u.mem_read(base+0xd,1))[0]))
    assert observed==list(rows),observed
    values={0xac5a98:own,0xac5dc0:0xffffffff,0xac59d4:0,0xac5d28:0}
    for index,(global_address,value) in enumerate(values.items()):
        pointer=DATA+0x7000+index*16;put32(u,global_address,pointer);put32(u,pointer,value)
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x83558c,STOP,count=8000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    own_rows=[row for row in rows if row[0]==own]
    if own_rows:
        row=own_rows[-1]
        assert get32(u,DATA+0x7010)==row[2]&0xffffffff
        assert get32(u,DATA+0x7020)==row[1]
        assert get32(u,DATA+0x7030)==sum(other[1]==row[1]for other in rows)
        assert ('0x814d64' if row[2]<0 else '0x815484') in calls
    else:assert not calls,'Foreign queue update must not change own lobby'
    return dict(packet=packet.hex(),rows=observed,writer='0x65963c',reader='0x6595f0',consumer='0x83558c',
        consumed=len(packet)-2,own_order=struct.unpack('<i',u.mem_read(DATA+0x7010,4))[0],
        own_role=get32(u,DATA+0x7020),own_role_count=get32(u,DATA+0x7030),ui_calls=calls)


def legacy_queue(subcode,identity=17,progress=0.375,own=17):
    u=emulator();packet=bytes((0xb0,subcode))+struct.pack('<I',identity)
    if subcode==0x17:packet+=struct.pack('<fB',progress,2)
    u.mem_write(DATA,packet[2:])
    for index,address in enumerate((0xac64a0,0xac5a98,0xac5dc0,0xac5abc)):
        pointer=DATA+0x7000+index*16;put32(u,address,pointer)
    put32(u,DATA+0x7010,own);put32(u,DATA+0x7020,7)
    calls=[];consumed=[]
    def hook(uc,address,size,user):
        end=(0x834ba8 if identity==own else 0x834b8a)if subcode==0x17 else 0x834cdd
        if address==end:
            consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA)
        if address in (0x4244b4,0x40c1bc,0x40c06c,0xa88908,0x40b0fc,0x81541c):
            calls.append(hex(address));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x834b4c if subcode==0x17 else 0x834cc4,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert consumed==[len(packet)-2 if identity==own or subcode==0x1b else 4],consumed
    if subcode==0x17:assert get32(u,DATA+0x7030)==(round(progress*100)if identity==own else 0)
    else:assert get32(u,DATA+0x7020)==(0xffffffff if identity==own else 7)
    return dict(packet=packet.hex(),subcode=subcode,identity=identity,own=own,consumed=consumed,
        progress_percent=get32(u,DATA+0x7030),own_order=get32(u,DATA+0x7020),ui_calls=calls)


def main():
    root=BINARY.parent/'base';animations=ET.parse(root/'animation.xml').getroot()
    radio_animations=[node.attrib for node in animations.iter()if node.get('WeaponType')=='Skill28']
    assert radio_animations and all('radio' in node.get('Name','')for node in radio_animations)
    skills=ET.parse(root/'shared config/skills.xml').getroot()
    assert skills.find("skill[@id='28']")is None
    report=dict(sha256=EXPECTED_SHA,method=__doc__,radio_animations=radio_animations,
        installed_radio_skill_defined=False,
        radio=[radio(),radio(actor=0x40000002,x=255,y=1),radio(selection=-1),radio(allowed=0),radio(target=1)],
        role_requests=[role_request(entry,role,queued)for entry,role in ((0x815048,1),(0x815064,3),(0x815080,2))for queued in (False,True)],
        queue_roundtrips=[queue_roundtrip(rows)for rows in ((),((17,3,0,0),),((9,1,0,1),(11,2,0,1),(17,3,2,0),(18,3,3,1)),((17,2,-1,0),))],
        legacy_queue=[legacy_queue(subcode,identity)for subcode in (0x17,0x1b)for identity in (17,19)],
        wire_contract=dict(call='81 skill28 u32,actor u32,zero u32,x u8,y u8; generic configured target_self',
            join='B014 role1 mining/2 raid/3 defense',cancel='B019',rating='B028 role u8 (not call)',
            queue='B018 count u32; each playerId u32,teamType u32,order signed32,ready bool8',
            progress='B017 playerId u32,progress f32,trailing u8',removed='B01B playerId u32'),
        limits=['Skill28 is absent from installed skills catalogue; GUI needs a configured skill28 model.',
            'Radio/help identity derives from original animation resources; historical AP/cooldown values remain unspecified.',
            '7F01 is the established generic skill acknowledgement; no separate help-invitation S2C was established.'])
    (ROOT/'evidence/mine_help_native.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Original mine radio/role callbacks, B018 queue writer-reader-consumer, B017/B01B readers: PASS')


if __name__=='__main__':main()
