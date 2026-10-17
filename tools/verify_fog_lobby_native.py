"""Original x86 fog reset/reveal and F0 Unicode argument parsing.

Runs ti.exe UpdateFog with an open-map LOS stub and actor getter stubs;
distance, reset loop and reveal writes are original. Rendering is not tested.
Runs silver.dll F0 and UTF16 readers with Delphi string allocation isolated.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator, EXE_SHA
from tio.protocol.system_message import encode_shop_error


def fog(persistent):
    u=exe_emulator();settings=DATA+0x100;scene=DATA+0x200
    field=DATA+0x1000;columns=DATA+0x2000;actor=DATA+0x3000
    for address,pointer in ((0x76e330,settings),(0x76e17c,DATA+0x300),
                            (0x76ddf8,DATA+0x400),(0x76dee4,DATA+0x404),
                            (0x76dcf8,DATA+0x408),(0x76dc08,DATA+0x40c),
                            (0x76e430,DATA+0x500),(0x76e314,DATA+0x410)):
        put32(u,address,pointer)
    put32(u,DATA+0x300,scene)
    put32(u,DATA+0x408,32);put32(u,DATA+0x40c,32)
    put32(u,DATA+0x500,actor)
    u.mem_write(settings+6,bytes((persistent,)))
    put32(u,field+0x1c,columns);put32(u,field+4,DATA+0x600)
    for x in range(32):put32(u,columns+x*4,DATA+0x4000+x*0x100)
    def visible(x,y):return u.mem_read(DATA+0x4000+x*0x100+y*6,1)[0]
    def hook(uc,address,size,user):
        if address in (0x724a0c,0x724050,0x7265cc):
            uc.reg_write(UC_X86_REG_EAX,{0x724a0c:1,0x724050:100,0x7265cc:3}[address])
            return_from_stub(uc)
        elif address==0x6e1c88:
            sp=uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP,sp+12)
        elif address==0x6e442f:uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    def update(x,y):
        put32(u,actor+0x1bc,x);put32(u,actor+0x1c0,y)
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
        u.reg_write(UC_X86_REG_EAX,field)
        u.emu_start(0x6e40a4,STOP,count=200000)
        assert u.reg_read(UC_X86_REG_EIP)==0x6e442f
    update(5,5)
    assert visible(5,5)==1 and visible(22,22)==0
    update(22,22)
    assert visible(22,22)==1 and visible(5,5)==persistent
    assert visible(0,31)==0
    return {'persistent':persistent,'old_position_visible':visible(5,5),
            'new_position_visible':visible(22,22),'unexplored_visible':visible(0,31)}


def message(text):
    u=emulator();packet=encode_shop_error(text);u.mem_write(DATA,packet)
    strings={0:''};heap=DATA+0x2000;result={}
    def save(destination,value):
        nonlocal heap
        heap+=8;strings[heap]=value;put32(u,destination,heap)
    def hook(uc,address,size,user):
        a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX)
        if address in (0x40c048,0x40c05c,0x40b4f0,0x40b4c4):
            save(a,strings[d]);return_from_stub(uc)
        elif address==0x40bf90:
            save(a,chr(d&65535));return_from_stub(uc)
        elif address==0x40c164:
            save(a,strings[get32(uc,a)]+strings[d]);return_from_stub(uc)
        elif address in (0x40b09c,0x40b0e4):
            put32(uc,a,0);return_from_stub(uc)
        elif address==0x40c900:
            uc.mem_write(a,bytes(24));return_from_stub(uc)
        elif address==0x7d1afc:
            bp=uc.reg_read(UC_X86_REG_EBP)
            result.update(command=a,argument=strings[get32(uc,bp-0x18)],
                          type=get32(uc,bp-0x3c),consumed=get32(uc,bp-0x1c)-DATA)
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+1)
    u.emu_start(0x7d0980,STOP,count=200000)
    assert result==dict(command=394,argument=text,type=5,consumed=len(packet)),result
    return result


if __name__=='__main__':
    from verify_battle_ground_scene_native import run as read_ground
    report={'scope':__doc__,'ti_exe_sha256':EXE_SHA,'silver_sha256':EXPECTED_SHA,
            'ground_reader_flags':[read_ground(8,8,v)['persistent_fog'] for v in (0,1,2)],
            'fog':[fog(1),fog(0)],
            'messages':[message('Recruit 1: здоровье 21/105. Вылечите бойца в казарме.'),
                        message('Боец Ёж: здоровье 1/120. Дождитесь восстановления.') ]}
    (ROOT/'evidence/fog_lobby_native.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Original fog: persistent bug reproduced, moving sight refogs with flag0; original F0 UTF16 parser: PASS')
