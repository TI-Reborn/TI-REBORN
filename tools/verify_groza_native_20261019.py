"""Execute original Groza selector and coordinate cast; DOM/UI/transport isolated."""
from verify_auth_native import *
from verify_mine_help_catalog_native import catalogue
from verify_mine_help_native import transport
import xml.etree.ElementTree as ET


def descriptor(path):
    root=ET.Element('skills')
    root.append(ET.parse(path).getroot().find("skill[@id='27']"))
    return ET.tostring(root,encoding='unicode')


def ground_click(target_type,ap=15,distance=5):
    u=emulator();pet=DATA+0x5000;skills=DATA+0xc000;table=DATA+0x4000
    put32(u,0xac618c,table);put32(u,table,pet)
    put32(u,pet+0x28,17);put32(u,pet+0x304,skills)
    put32(u,skills-4,1);put32(u,skills+8,27)
    u.mem_write(pet+0x6004,bytes((ap,)));u.mem_write(pet+0x6006,b'\x01\x00')
    put32(u,pet+0x603c,2);put32(u,pet+0x6040,2)
    u.mem_write(skills+0x326,b'\x01\x06')
    u.mem_write(skills+0x332,b'\x0a\x04')
    u.mem_write(skills+0x337,bytes((target_type,4)))
    put32(u,0xac4960,0);u.mem_write(0xacfb9c,bytes((target_type,)))
    for index,addr in enumerate((0xac5a30,0xac55a8,0xac5fe4,0xac57ac,0xac5d74,0xac587c,0xac5780)):
        put32(u,addr,DATA+0x4400+index*16)
    u.mem_write(DATA+0x4400,b'\x06')
    put32(u,0xac637c,DATA+0x4500);put32(u,DATA+0x4500,DATA+0x4600)
    packets=transport(u,(0x95724c,0x43afc0,0xa88a78,0x40c9f4,0x40b09c,0x40b47c,0x4244b4,0x8b6f34))
    def hook(uc,address,size,user):
        values={0xa843d4:0,0xa83eb4:1,0xa843ac:1,0x9c04b8:1,0xa8907c:distance,0xa867e0:1}
        if address in values:
            uc.reg_write(UC_X86_REG_EAX,values[address]);return_from_stub(uc)
            if address==0xa8907c:uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+16)
        elif address==0x9db7ac:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),7);put32(uc,uc.reg_read(UC_X86_REG_EDX),2)
            uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    try:u.emu_start(0x8b5a94,STOP,count=15000)
    except Exception as exc:raise RuntimeError(f'Native type{target_type} PC={u.reg_read(UC_X86_REG_EIP):x} SP={u.reg_read(UC_X86_REG_ESP):x}') from exc
    assert u.reg_read(UC_X86_REG_EIP)==STOP,hex(u.reg_read(UC_X86_REG_EIP))
    from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
    expected=[encode_ability_cast(AbilityCast(27,17,0,7,2))] if target_type==4 and ap>=6 and 4<=distance<=10 else []
    assert packets==expected,[p.hex() for p in packets]
    return dict(target_type=target_type,ap=ap,distance=distance,packets=[p.hex() for p in packets])


def main():
    work=ROOT/'work/groza-20261019';out=ROOT/'reports/groza-20261019'
    before=catalogue(descriptor(work/'skills.xml'))
    after=catalogue(descriptor(work/'skills-candidate.xml'))
    assert before['target']==1 and after['target']==4
    assert (after['active'],after['ap'],after['range'],after['minimum_range'],after['splash_range'])==(1,6,10,4,2)
    assert any(x['key']=='itemConsumeId' and x['configured'] for x in after['lookups'])
    cases=[ground_click(t,ap,d) for t,ap,d in ((1,15,5),(4,15,5),(4,6,4),(4,6,10),(4,5,5),(4,15,3),(4,15,11))]
    report=dict(passed=True,binary_sha256=EXPECTED_SHA,before=before,after=after,cases=cases,
        limitations='Original x86 loader and cast control flow executed; XML DOM, selection, distance helper, UI previews and transport stubbed. GUI tested separately.')
    (out/'native-regression.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Native Groza loader/ground click and resource/range controls: 7 cases PASS')


if __name__=='__main__':main()
