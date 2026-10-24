"""Original enum lookup and original HUD frame routing, no GUI rendering claims."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX,UC_X86_REG_EDI
OUT=ROOT/'reports/rpg-action-icon-20261019';WORK=ROOT/'work/rpg-action-icon-20261019'

def enum(value):
    u=emulator();p=DATA+0x100;raw=value.encode('utf-16le');put32(u,p-8,0xffffffff);put32(u,p-4,len(value));u.mem_write(p,raw+b'\0\0')
    def hook(uc,address,size,user):
        if address in (0x40b180,0x40b0fc):return_from_stub(uc)
        elif address==0x4237d0:
            put32(uc,uc.reg_read(UC_X86_REG_EDX),uc.reg_read(UC_X86_REG_EAX));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,p)
    u.emu_start(0xa75d38,STOP,count=10000);assert u.reg_read(UC_X86_REG_EIP)==STOP
    return u.reg_read(UC_X86_REG_EAX)

def routing(attack_type):
    u=emulator();frame=STACK+0x7000;actor=DATA+0x2000
    put32(u,0xac618c,DATA+0x1000);put32(u,DATA+0x1000,actor);put32(u,frame-8,0)
    def hook(uc,a,size,user):
        if a==0xa75e98:uc.reg_write(UC_X86_REG_EAX,attack_type);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EDI,0);u.reg_write(UC_X86_REG_EBP,frame)
    u.emu_start(0x9c178b,0x9c185d,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==0x9c185d
    return get32(u,0xad11ec),get32(u,0xad11f0)

def main():
    raw=(WORK/'silver.dll').read_bytes();current=pefile.PE(data=raw).get_memory_mapped_image()
    old=pefile.PE(data=BINARY.read_bytes()).get_memory_mapped_image()
    for va,n in ((0xa75d38,141),(0xa75e98,137),(0x9c178b,210),(0x9c2e27,58)):
        assert current[va-0x400000:va-0x400000+n]==old[va-0x400000:va-0x400000+n]
    cases=[]
    for name in ('None','Bullet','Rocket','Grenade','Mine','Flash','Minigun','Suicide','Bow','Distance','Subgrenade','Light','StunGrenade','GasMine'):
        attack=enum(name);frame,action=routing(attack)
        assert (frame==4)==(name=='Rocket')
        if name=='Rocket':assert attack==3 and action==0xfffffff3
        cases.append(dict(attack=name,native_enum=attack,frame=frame,action=hex(action)))
    import xml.etree.ElementTree as ET
    item=ET.parse(WORK/'items.xml').getroot().find("item[@id='316']")
    fields={n.get('key'):n.get('val') for n in item.findall('value')}
    assert fields['attackType']==fields['weaponAttack']=='Rocket'
    result=dict(passed=True,method=__doc__,silver_sha256=hashlib.sha256(raw).hexdigest(),
        native_spans_match=True,cases=cases,rpg_template=316,rpg_frame=4,other_weapons_preserved=True,
        allocated_strings_and_metadata_accessor_isolated=True,graphical_client=False)
    (OUT/'native-icon-routing.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
