"""Original XML loader and target_riflescope click/range branches, UI isolated."""
from verify_auth_native import *
from verify_mine_help_catalog_native import catalogue
from verify_mine_help_native import transport
import xml.etree.ElementTree as ET

OUT=ROOT/'reports/awp-scope-20261019'

def click(ap=15,distance=18,minimum=7,maximum=18):
    u=emulator();pet=DATA+0x5000;skills=DATA+0xc000;table=DATA+0x4000;metadata=DATA+0x4600
    put32(u,0xac618c,table);put32(u,table,pet)
    put32(u,pet+0x28,17);put32(u,pet+0x304,skills)
    put32(u,skills-4,1);put32(u,skills+8,9)
    u.mem_write(pet+0x6004,bytes((ap,)));u.mem_write(pet+0x6006,b'\1\0')
    put32(u,pet+0x603c,2);put32(u,pet+0x6040,2)
    u.mem_write(skills+0x326,b'\1\3');u.mem_write(skills+0x335,b'\1')
    u.mem_write(skills+0x337,b'\5\4')
    put32(u,0xac4960,0);u.mem_write(0xacfb9c,b'\5')
    for index,addr in enumerate((0xac5a30,0xac55a8,0xac5fe4,0xac57ac,0xac5d74,0xac587c,0xac5780)):
        put32(u,addr,DATA+0x4400+index*16)
    u.mem_write(DATA+0x4400,b'\6')
    put32(u,0xac637c,DATA+0x4500);put32(u,DATA+0x4500,metadata)
    u.mem_write(metadata+0x138,struct.pack('<HH',minimum,maximum))
    packets=transport(u,(0x95724c,0x43afc0,0xa88a78,0x40c9f4,0x40b09c,0x40b47c,0x4244b4,0x8b6f34))
    def hook(uc,address,size,user):
        values={0xa843d4:0,0xa83eb4:1,0xa843ac:1,0x9c04b8:1,0xa8907c:distance,0xa867e0:1,0xa7b030:0}
        if address in values:
            uc.reg_write(UC_X86_REG_EAX,values[address]);return_from_stub(uc)
            if address==0xa8907c:uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+16)
        elif address==0x9db7ac:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),20);put32(uc,uc.reg_read(UC_X86_REG_EDX),2)
            uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    try:u.emu_start(0x8b5a94,STOP,count=15000)
    except Exception as exc:raise RuntimeError(f'Native scope PC={u.reg_read(UC_X86_REG_EIP):x}') from exc
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
    expected=[encode_ability_cast(AbilityCast(9,17,0,20,2))] if ap>=3 and minimum<=distance<=maximum else []
    assert packets==expected,[p.hex() for p in packets]
    return dict(ap=ap,distance=distance,minimum=minimum,maximum=maximum,packets=[p.hex() for p in packets])

def main():
    xml=ET.Element('skills');xml.append(ET.parse(ROOT/'evidence/skills_diagnostic.xml').getroot().find("skill[@id='9']"))
    loaded=catalogue(ET.tostring(xml,encoding='unicode'))
    assert (loaded['target'],loaded['active'],loaded['ap'],loaded['splash_range'])==(5,1,3,1)
    cases=[click(ap,d,7,m) for ap,d,m in ((15,18,18),(3,7,18),(2,18,18),(15,6,18),(15,19,18),(15,17,16),(15,16,16))]
    report=dict(passed=True,binary_sha256=EXPECTED_SHA,loader=loaded,cases=cases,
        limitations='Original loader, selector and serializer; XML DOM, actor selection, distance math, UI and transport isolated. Separate graphical verification required.')
    (OUT/'native-regression.json').write_text(json.dumps(report,indent=2))
    print('Original sniper scope loader and 7 click/resource/range cases PASS')

if __name__=='__main__':main()
