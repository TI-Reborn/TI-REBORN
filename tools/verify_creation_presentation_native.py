"""Execute presentation detours and native model selection; renderer calls stubbed."""
from verify_auth_native import *
from deploy.client_character_onboarding import patch,STATE,BUTTON,CAPTION,RVA
from xml.etree import ElementTree


def presentation(raw,base):
    pe=pefile.PE(data=raw);pe.relocate_image(base)
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(base,pe.OPTIONAL_HEADER.SizeOfImage)
    u.mem_write(base,pe.get_memory_mapped_image());u.mem_map(DATA,0x10000);u.mem_map(STACK,0x10000)
    d=base-0x400000;calls=[]
    def hook(uc,address,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if address==0x40b4f0+d:
            put32(uc,eax,edx);return_from_stub(uc)
        elif address==0xa42b04+d:
            text=bytes(uc.mem_read(edx,get32(uc,edx-4))).decode('utf-16le') if edx else ''
            calls.append(('caption',text));return_from_stub(uc)
        elif address==0x6d0788+d:
            calls.append(('price',uc.reg_read(UC_X86_REG_ECX)));return_from_stub(uc)
        elif address in (0x6d0318+d,0x9e5908+d):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def execute(start,end):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.emu_start(start+d,end+d if end!=STOP else STOP,count=500)
        assert u.reg_read(UC_X86_REG_EIP)==(end+d if end!=STOP else STOP)
    original='Купить'.encode('utf-16le');put32(u,DATA,len(original));u.mem_write(DATA+4,original)
    u.reg_write(UC_X86_REG_EAX,DATA+0x100);u.reg_write(UC_X86_REG_EDX,DATA+4)
    execute(0x6d221f,0x6d2224)
    assert get32(u,base+BUTTON)==DATA+0x100
    for creation in (False,True,False):
        if creation:execute(0x400000+RVA+0x200,STOP)
        else:execute(0x6d06dd,0x6d06e2)
        assert bytes(u.mem_read(base+STATE,1))==bytes([creation])
        calls.clear();u.reg_write(UC_X86_REG_ECX,1234)
        execute(0x6d1069,0x6d106e)
        assert calls==[('price',0 if creation else 1234),('caption','Принять' if creation else 'Купить')],calls
    return {'base':hex(base),'free_and_paid_labels':True}


def model_selection():
    root=ElementTree.parse(ROOT/'evidence/customization_diagnostic.xml').getroot()
    models=BINARY.parent/'base/models';rows=[]
    for group in root:
        for v in group:
            for key,suffix in [('filename','.mdjx'),('texture',''),('mask','')]:
                if key in v.attrib:assert (models/(v.attrib[key]+suffix)).is_file(),v.attrib
            if group.attrib['type'] in ('HeadHairType','FacialHairType','HairColor'):
                rows.append(({'HeadHairType':1,'FacialHairType':2,'HairColor':3}[group.attrib['type']],int(v.attrib['id']),v.attrib))
    u=emulator();table=DATA+0x1004;put32(u,table-4,len(rows));put32(u,0xb772c8,table)
    for n,(kind,id,attrs) in enumerate(rows):
        at=table+n*56;put32(u,at,id);u.mem_write(at+4,bytes([kind]));put32(u,at+12,n+100)
    put32(u,0xac637c,DATA+0x3000);put32(u,DATA+0x3000,DATA+0x3100)
    u.mem_write(DATA+0x3100+0x666,b'\x01\x01')
    put32(u,0xac618c,DATA+0x7000);put32(u,DATA+0x7000,DATA+0x7100);put32(u,DATA+0x7128,42)
    loaded=[];attached=[]
    def hook(uc,address,size,user):
        if address==0xa78afc:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0xa8b468:
            loaded.append(rows[uc.reg_read(UC_X86_REG_EAX)]);return_from_stub(uc)
        elif address==0x68a724:
            attached.append(uc.reg_read(UC_X86_REG_EDX));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    checks=[]
    for hair,beard,color in [(5,1,3),(16,4,2),(12,0,4),(0,0,1)]:
        loaded.clear();attached.clear();u.mem_write(DATA,struct.pack('<6H',hair,beard,color,0,0,0))
        u.reg_write(UC_X86_REG_EAX,0);u.reg_write(UC_X86_REG_EDX,0);u.reg_write(UC_X86_REG_ECX,DATA)
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP);put32(u,STACK+0x8004,0)
        u.emu_start(0xa8b800,STOP,count=10000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        assert {(r[0],r[1]) for r in loaded}=={(1,hair),(2,beard),(3,color)},loaded
        assert len(attached)==2
        checks.append([r[2].get('filename',r[2].get('texture','none')) for r in loaded])
    return checks


if __name__=='__main__':
    raw=patch(BINARY.read_bytes())
    results={'presentation':[presentation(raw,b) for b in (0x400000,0x600000)],'models':model_selection()}
    (ROOT/'evidence/creation-presentation-native.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Native creation/paid captions, price, close and relocation; model/hair/color bindings PASS')
