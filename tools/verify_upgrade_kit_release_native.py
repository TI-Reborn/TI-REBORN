"""Execute final distributed kit visibility bytes in original x86 UI branches."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX
from deploy.client_upgrade_kit import patch,SITES


def main():
    final=patch(BINARY.read_bytes());pe=pefile.PE(data=final);u=emulator()
    for va,old,new in SITES:
        offset=pe.get_offset_from_rva(va-0x400000);u.mem_write(va,final[offset:offset+len(new)])
    panel,item=DATA+0x1000,DATA+0x2000;cases=[]
    gates=((0x9bc62a,0x9bc640,0x9bc98b),(0x9bcafd,0x9bcb0f,0x9bcb2d),
           (0x9bce56,0x9bce68,0x9bcee6),(0x9be89d,0x9be8b3,0x9bec4a),
           (0x9bee12,0x9bee28,0x9beecd),(0x9bf063,0x9bf079,0x9bf17e))
    for store,end in ((0x9a7f3a,0x9a7f41),(0x9ba21b,0x9ba222)):
        u.mem_write(panel+0x2a1,b'\x11\1\x22');u.reg_write(UC_X86_REG_EAX,panel)
        u.emu_start(store,end,count=10)
        assert bytes(u.mem_read(panel+0x2a1,3))==b'\x11\0\x22'
        for entry,visible,skipped in gates:
            for template in (30,19,301):
                put32(u,item+8,template);u.reg_write(UC_X86_REG_EAX,item);u.reg_write(UC_X86_REG_EBX,panel)
                u.reg_write(UC_X86_REG_ESP,STACK+0x8000);reached=[]
                def hook(uc,address,size,user):
                    if address in (visible,skipped):reached.append(address);uc.emu_stop()
                h=u.hook_add(UC_HOOK_CODE,hook);u.emu_start(entry,STOP,count=100);u.hook_del(h)
                assert reached==[visible]
                cases.append(dict(panel=hex(store),gate=hex(entry),template=template,visible=True))
    filters=[]
    for entry,end in ((0x9159ee,0x9159f9),(0x9171a9,0x9171b4)):
        for template in (30,19,301):
            for accepted in (0,1):
                put32(u,item+8,template);u.reg_write(UC_X86_REG_EAX,item);u.reg_write(UC_X86_REG_EBX,accepted)
                u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.emu_start(entry,end,count=100)
                assert u.reg_read(UC_X86_REG_EBX)==accepted
                filters.append(dict(entry=hex(entry),template=template,previous_filter=accepted,result=accepted))
    report=dict(passed=True,sha256=hashlib.sha256(final).hexdigest(),scope=__doc__,
        inventory=cases,warehouse=filters,limitations='Native branch execution with synthetic memory; no graphical UI or mouse automation.')
    (ROOT/'evidence/upgrade_kit_release_native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Final release: 36 inventory/render/layout/mouse branches, 12 warehouse filters, 2 constructors PASS')


if __name__=='__main__':main()
