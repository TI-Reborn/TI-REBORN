"""Run ti.exe's original AJPG decrypt loop; retain original masks and header fields."""
from verify_battle_loaded_native import exe_emulator, EXE_SHA
from verify_auth_native import *


def decrypt(raw):
    u=exe_emulator()
    frame=STACK+0x9000
    source_ref,source,dest,svt,dvt=DATA+0x1000,DATA+0x1100,DATA+0x1200,DATA+0x1300,DATA+0x1400
    read,write=DATA+0x5100,DATA+0x5200
    put32(u,source_ref,source);put32(u,source,svt);put32(u,dest,dvt)
    put32(u,svt+0xc,read);put32(u,dvt+0x10,write)
    put32(u,frame-4,source_ref);put32(u,frame-0x14,dest)
    u.mem_write(frame-6,struct.pack('<H',100))
    cursor=0;plain=bytearray()
    def hook(uc,address,size,user):
        nonlocal cursor
        if address==read:
            assert uc.reg_read(UC_X86_REG_ECX)==1 and cursor<len(raw)
            uc.mem_write(uc.reg_read(UC_X86_REG_EDX),raw[cursor:cursor+1]);cursor+=1
            uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
        elif address==write:
            assert uc.reg_read(UC_X86_REG_ECX)==1
            plain.extend(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),1))
            uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EBP,frame)
    u.reg_write(UC_X86_REG_ESP,frame-0x100)
    u.reg_write(UC_X86_REG_EAX,len(raw))
    u.emu_start(0x66609a,0x6660f4,count=len(raw)*40+100)
    assert u.reg_read(UC_X86_REG_EIP)==0x6660f4 and cursor==len(raw)==len(plain)
    assert plain[:8]==b'\x07AJPG_EX'
    color_size,mask_size=struct.unpack_from('<QQ',plain,39)
    assert 55+color_size+mask_size==len(plain)
    return bytes(plain),bytes(plain[55+color_size:])


def main():
    root=ROOT/'reports/equipment-textures';rows=[]
    for name in ('base/items/itm_repair3.png','base/items/jacket0b.tga'):
        old=(root/'source'/name).read_bytes();new=(root/'client'/name).read_bytes()
        original,old_mask=decrypt(old);exported,new_mask=decrypt(new)
        assert original[:39]==exported[:39] and original[47:55]==exported[47:55]
        assert old_mask==new_mask and old!=new
        rows.append(dict(path=name,source_sha256=hashlib.sha256(old).hexdigest(),
                         output_sha256=hashlib.sha256(new).hexdigest(),
                         original_mask_sha256=hashlib.sha256(old_mask).hexdigest(),
                         output_mask_sha256=hashlib.sha256(new_mask).hexdigest(),
                         native_header_preserved=True,native_mask_preserved=True))
    report=dict(passed=True,exe_sha256=EXE_SHA,original_loop='66609a..6660f4',
                stream_io_stubbed=True,graphical_game_client=False,cases=rows)
    (root/'native-ajpg.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Original AJPG decrypt code: two source/export pairs, exact native masks and headers PASS')


if __name__=='__main__':main()
