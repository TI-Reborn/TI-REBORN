"""Execute F9 snapshot and original inventory/AP/native33 paths in x86.

This proves model/packet behavior, including ASLR, conservative malformed
state and repeated-click handling. Managed widgets, network flush, camera and
platform renderer are the same explicit stubs as the existing F6/F7/F8 probes.
No installed DLL, publication, remote service or player database is changed.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_ESI
from deploy import client_battle_items as client
from verify_sc_view_native import NativeScene, sample_lot
from tio.protocol import sc_auction_view as sc_wire
from tio.protocol.battle_item_visuals import encode_item_visuals
from tio.protocol.item_action import ItemAction, encode_item_action
import verify_battle_item_client_native as items
import verify_equipment_batch_native as equipment

FOLDER=ROOT/'reports/gameplay-followup/stage1-interfaces/nvg'
SOURCE=FOLDER/'source/silver.dll'
_images={}
_original_image=None


def cached_original_emulator():
    """Map the pinned original PE identically to verify_auth_native.emulator."""
    global _original_image
    original=BINARY.read_bytes()
    assert hashlib.sha256(original).hexdigest()==EXPECTED_SHA
    if _original_image is None:_original_image=pefile.PE(data=original).get_memory_mapped_image()
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0,0x1000)
    u.mem_map(0x400000,(len(_original_image)+0xfff)&~0xfff);u.mem_write(0x400000,_original_image)
    u.mem_map(DATA,0x10000);u.mem_map(STACK,0x10000)
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    return u


def scene_for(raw,base):
    """Cache the fully parsed/relocated real PE image, not executed code."""
    key=(hashlib.sha256(raw).hexdigest(),base)
    if key not in _images:
        pe=pefile.PE(data=raw)
        if base!=0x400000:pe.relocate_image(base)
        _images[key]=pe.get_memory_mapped_image()
    # NativeScene's constructor only uses these two PE-image operations.
    # Avoid parsing the same 7 MB DLL for every independent Unicorn machine.
    # Each case still maps and executes the complete real image itself.
    class CachedImage:
        def relocate_image(self,address):assert address==base
        def get_memory_mapped_image(self):return _images[key]
    original=pefile.PE
    try:
        pefile.PE=lambda *,data:CachedImage()
        return NativeScene(candidate=raw,base=base)
    finally:pefile.PE=original


def candidate():return client.patch_nvg(SOURCE.read_bytes())


def snapshot(ids):
    """Literal approved F9/v1 format, independent of the native validator."""
    return bytes((0xf9,1))+struct.pack('<H',len(ids))+b''.join(struct.pack('<I',i) for i in ids)


def stored(scene):
    count=scene.get(0x400000+client.NVG_COUNT)
    address=scene.base+client.NVG_ACTORS
    return tuple(struct.unpack('<I',scene.u.mem_read(address+4*i,4))[0] for i in range(count))


def receiver_cases(raw,base=0x400000):
    scene=scene_for(raw,base);rows=[]
    valid=((),(17,),(1,17,2147483647),tuple(range(1,65)))
    for ids in valid:
        packet=snapshot(ids);scene.dispatch(packet)
        assert stored(scene)==ids,(base,ids,stored(scene))
        rows.append(dict(ids=list(ids),packet_bytes=len(packet),valid=True))
    malformed=[b'\xf9',b'\xf9\1',b'\xf9\2\0\0',snapshot((0,)),snapshot((0x80000000,)),
               snapshot((17,17)),snapshot((18,17)),snapshot(tuple(range(1,66))),snapshot((17,))+b'\0']
    good=snapshot((1,17,99))
    malformed.extend(good[:i] for i in range(1,len(good)))
    for packet in malformed:
        scene.dispatch(snapshot((17,)));scene.dispatch(packet)
        assert stored(scene)==(),(packet.hex(),stored(scene))
        rows.append(dict(packet_hex=packet.hex(),valid=False,eligibility_cleared=True))
    scene.dispatch(snapshot((17,)));scene.dispatch(snapshot((18,)))
    assert stored(scene)==(18,)
    scene.dispatch(snapshot(()));assert stored(scene)==()
    return dict(image_base=hex(base),cases=rows,full_replacement=True,empty_clears=True,
                original_exported_PacketHandler=True)


def gate_case(raw,*,base=0x400000,ap=0,ids=(17,),template=5002,actor=17,battle=1,repeat=1):
    scene=scene_for(raw,base);scene.dispatch(snapshot(ids))
    actor_pointer=DATA+0x9000;closure=DATA+0x8000;array=DATA+0xa000;metadata=DATA+0xb000
    battle_pointer=DATA+0xc000
    scene.set(0xac64a0,battle_pointer);put32(scene.u,battle_pointer,battle)
    scene.set(0xac618c,array);put32(scene.u,array,actor_pointer);put32(scene.u,actor_pointer+0x28,actor)
    scene.u.mem_write(actor_pointer+0x6004,bytes((ap,)))
    scene.set(0xac637c,DATA+0xd000);put32(scene.u,DATA+0xd000,metadata)
    scene.u.mem_write(metadata+0x13c,struct.pack('<H',3));put32(scene.u,metadata+0x650,0)
    put32(scene.u,closure+0x18,template)
    reached=[]
    def stop(uc,address,size,user):
        if address in (0xa65925+scene.delta,0xa65974+scene.delta):
            reached.append(hex(address-scene.delta));uc.emu_stop()
    scene.u.hook_add(UC_HOOK_CODE,stop)
    for index in range(repeat):
        scene.u.reg_write(UC_X86_REG_EAX,actor_pointer);scene.u.reg_write(UC_X86_REG_EBX,closure)
        scene.u.reg_write(UC_X86_REG_EDI,0);scene.u.reg_write(UC_X86_REG_ESI,0)
        scene.u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
        scene.u.emu_start(client.NVG_GATE_HOOK+scene.delta,STOP,count=10000)
        eligible=(index==0 and battle and template==5002 and actor in ids)
        expected='0xa65974' if ap>=3 or eligible else '0xa65925'
        assert reached[-1]==expected,(base,ap,ids,template,actor,battle,index,reached)
        assert scene.u.reg_read(UC_X86_REG_EBX)==closure
    if ap<3 and battle and template==5002 and actor in ids:
        assert actor not in stored(scene),'A rapid second click could attempt free activation'
        scene.dispatch(snapshot((actor,)));assert stored(scene)==(actor,),'Server full snapshot must restore eligibility'
    return dict(image_base=hex(base),ap=ap,ids=list(ids),template=template,actor=actor,battle=battle,
                branches=reached,repeat=repeat,shortcut_only_active_nvg=True)


def inventory_cases(raw):
    packet=encode_item_action(ItemAction(17,1001,255));cases=[]
    def click(*args,**kwargs):return items.double_click_case(*args,native_actor_guards=True,**kwargs)
    for ap in range(3):
        cases.append(click(5002,2,ap,client_data=raw,server_nvg_packet=snapshot((17,)),expected_packets=[packet]))
        cases.append(click(5002,2,ap,client_data=raw,server_nvg_packet=snapshot((17,)),repeat=2,expected_packets=[packet]))
        for ids in ((),(18,)):
            cases.append(click(5002,2,ap,client_data=raw,server_nvg_packet=snapshot(ids),expected_packets=[]))
    for ap in (3,10):
        cases.append(click(5002,2,ap,client_data=raw,server_nvg_packet=snapshot(()),expected_packets=[packet]))
    for template in (35,5003,5011,5012):
        cases.append(click(template,2,0,client_data=raw,server_nvg_packet=snapshot((17,))))
    for ap in range(3):
        cases.append(click(5002,2,ap,client_data=raw,server_nvg_packet=snapshot((17,)),can_act=0,expected_packets=[]))
        cases.append(click(5002,2,ap,client_data=raw,server_nvg_packet=snapshot((17,)),actor_usable=False,expected_packets=[]))
    cases.append(click(5002,2,0,client_data=raw,server_nvg_packet=b'\xf9\2\0\0',expected_packets=[]))
    return cases


def prior_item_cases(raw):
    previous=(items._candidate,items._candidate_image)
    try:
        items._candidate=raw;items._candidate_image=pefile.PE(data=raw).get_memory_mapped_image()
        return dict(hp=items.hp_cases(),binocular=items.target_cases(),f7=items.reader_cases(),
                    renderer=[items.draw_case(),items.draw_case(0)],
                    city_boosters=[items.double_click_case(t,2,0,0) for t in range(5003,5012)])
    finally:items._candidate,items._candidate_image=previous


def prior_equipment_cases(raw):
    previous=(equipment._candidate,equipment.emulator)
    def expanded():
        u=cached_original_emulator();u.mem_map(0x400000+client.RVA+0x2000,0x7000);return u
    try:
        equipment._candidate=raw;equipment.emulator=expanded
        return dict(stage=[equipment.staged(1),equipment.staged(9)],
                    unchanged=[equipment.unchanged(b,k) for b,k in ((0,1),(0,9),(1,2),(1,3),(1,12))],
                    wrap=equipment.wrapped_nonce(),hide=equipment.hide_cancel(),reconstruction=equipment.reconstructed_cancel())
    finally:equipment._candidate,equipment.emulator=previous


def prior_sc_cases(raw,base=0x400000):
    scene=scene_for(raw,base)
    views=(sample_lot(1),sample_lot(2,enhanced=True),sample_lot(3,state='won'),sample_lot(4,state='won',name='Bob'))
    scene.dispatch(sc_wire.encode_catalogue(views));tabs=[scene.tab(i) for i in range(4)]
    assert tabs==[(1,),(2,),(3,4),(3,)]
    scene.tab(0);assert scene.remaining()==290000
    assert scene.click().hex()=='bd0601000000';assert scene.click(bot=True).hex()=='bd140001000000'
    scene.tab(2);assert scene.click_claim(0).hex()=='bd0703000000';assert scene.click_claim(1)==b''
    scene.receive(sc_wire.encode_bot(1,5,100,200,7))
    assert scene.request(0x89430c).hex()=='bd1401010000006400000007000000c8000000'
    assert scene.request(0x894410).hex()=='bd140201000000'
    history=sc_wire.encode_history(3,(dict(date=sc_wire.datetime_days(1791446500),action=4,name='Алиса',amount=5,automatic=True,currency=0),),page=2,pages=3,remaining_ms=10000)
    scene.receive(history);assert len(scene.rows(0xacf420,24))==1
    scene.receive(sc_wire.encode_claim(3,101,0,1792051300,can_pay=True));assert scene.request(0x891444).hex()=='bd090300000001'
    scene.dispatch(snapshot((17,)));assert stored(scene)==(17,)
    # Receiving F7 and F8 must leave authoritative NVG state alone.
    scene.dispatch(encode_item_visuals(((2,3,1),)));assert stored(scene)==(17,)
    scene.dispatch(sc_wire.encode_clear());assert stored(scene)==(17,)
    assert all(scene.get(a)==0 for a in (0xacf418,0xacf41c,0xacf420,0xac491c,0xacf444))
    return dict(image_base=hex(base),tabs=tabs,original_bd_callbacks=True,history_unicode=True,
                f7_f8_chain_preserved=True,nvg_unaffected_by_unrelated_packets=True)


def verify():
    before=SOURCE.read_bytes();raw=client.patch_nvg(before)
    assert client.patch_nvg(raw)==raw
    gates=[]
    for base in (0x400000,0x500000):
        for ap in (0,1,2,3,10):
            for ids in ((),(17,),(18,)):
                gates.append(gate_case(raw,base=base,ap=ap,ids=ids,repeat=2))
        for template in (35,5003,5011,5012):gates.append(gate_case(raw,base=base,template=template))
        gates.append(gate_case(raw,base=base,actor=18,ids=(17,)))
        gates.append(gate_case(raw,base=base,battle=0))
    previous_emulator=items.emulator
    try:
        items.emulator=cached_original_emulator
        inventory=inventory_cases(raw);f7=prior_item_cases(raw)
    finally:items.emulator=previous_emulator
    return dict(passed=True,status='PASS',method=__doc__,
                preservation=client.nvg_patch_plan(before,raw),
                receiver=[receiver_cases(raw,base) for base in (0x400000,0x500000)],
                gate=gates,inventory=inventory,
                f6=prior_equipment_cases(raw),f7=f7,
                f8=[prior_sc_cases(raw,base) for base in (0x400000,0x500000)],
                server_protocol_required='F9/v1 full owner-only active living NVG IDs after state transitions/start/reconnect; empty clears',
                limits='Original x86 and scalar writers execute; managed UI/network/camera/platform rendering stubbed. No graphical acceptance or hosted mutation.')


def main():
    report=verify();raw=candidate();destination=FOLDER/'candidate';destination.mkdir(parents=True,exist_ok=True)
    (destination/'silver.dll').write_bytes(raw)
    (destination/'patch-plan.json').write_text(json.dumps(report['preservation'],indent=2)+'\n',encoding='utf-8')
    report['source_sha256']={str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (ROOT/'deploy/client_battle_items.py',ROOT/'tools/verify_battle_item_client_native.py',Path(__file__),ROOT/'tests/test_nvg_client_native.py')}
    manifest=(FOLDER/'source/manifest.json').read_bytes();manifest_data=json.loads(manifest)
    assert manifest_data['version']=='2026.10.08.5'
    assert next(row for row in manifest_data['files'] if row['path']=='silver.dll')['sha256']==client.NVG_BASE_SHA
    report['published_source']=dict(version=manifest_data['version'],manifest_sha256=hashlib.sha256(manifest).hexdigest(),
                                    base_url='https://185.184.42.88/updates/',read_only_download=True)
    (FOLDER/'native-proof.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(f"NVG original-x86 PASS: receiver {sum(len(r['cases']) for r in report['receiver'])}, gate {len(report['gate'])}, full inventory {len(report['inventory'])}; F6/F7/F8 preserved; candidate {hashlib.sha256(raw).hexdigest()}")


if __name__=='__main__':main()
