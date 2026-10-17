"""Original x86 ground brush selection and item quantity gates; renderer stubbed."""
from verify_battle_loaded_native import exe_emulator
from verify_auth_native import *
from verify_item_stacking_native import check

def brush(identity,layer):
    u=exe_emulator();parent=DATA+0x1000;array=DATA+0x2000;object_=DATA+0x6000;selected=[]
    put32(u,parent-4,array);put32(u,array-4,3)
    for index,(kind,rank) in enumerate(((0,layer),(identity,0),(identity,1))):
        entry=array+index*0x72c;u.mem_write(entry,struct.pack('<H',kind));put32(u,entry+8,rank)
        put32(u,entry+0xc,1000+kind*10+rank)
    for indirect,value in ((0x76dcf8,40),(0x76dc08,40)):
        p=DATA+(0x100 if indirect==0x76dcf8 else 0x200);put32(u,indirect,p);put32(u,p,value)
    root,columns,grid=DATA+0x300,DATA+0x400,DATA+0x5000
    put32(u,0x76e5f4,root);put32(u,root,root+0x30);put32(u,root+0x30+0xc,columns);put32(u,columns+5*4,grid)
    u.mem_write(grid+6*14+8,bytes((identity,)))
    put32(u,0x76e000,DATA+0x600);put32(u,DATA+0x600,DATA+0x700)
    put32(u,DATA+0x700+0xd4,DATA+0x800)
    def hook(uc,address,size,user):
        if address==0x406f80:uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0x40cc78:uc.reg_write(UC_X86_REG_EAX,object_);return_from_stub(uc)
        elif address==0x40ca18:
            dst,src=uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)
            uc.mem_write(dst,bytes(uc.mem_read(src,0x720)));return_from_stub(uc)
        elif address==0x4b1c08:
            selected.append(dict(marker=get32(uc,object_),x=get32(uc,object_+4),y=get32(uc,object_+8)));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);put32(u,STACK+0x8004,parent)
    u.reg_write(UC_X86_REG_EAX,layer);u.reg_write(UC_X86_REG_EDX,5);u.reg_write(UC_X86_REG_ECX,6)
    u.emu_start(0x7173cc,STOP,count=1000)
    assert selected==[dict(marker=1000+identity*10+layer,x=5,y=6)],selected
    return dict(brush=identity,layer=layer,selected=selected)

if __name__=='__main__':
    result=dict(passed=True,method=__doc__,ground=[brush(i,l) for i in (7,8,9) for l in (0,1)],
                materials=[check(65487,2,1),check(65488,4,1)],graphical_client=False)
    (ROOT/'reports/forest-biomes/native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original biome ground selection + material stack/warehouse gates PASS')
