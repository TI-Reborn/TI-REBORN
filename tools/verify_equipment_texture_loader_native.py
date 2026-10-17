"""Execute the original memory-texture loader's D3DX argument assembly in Unicorn."""
from verify_battle_loaded_native import exe_emulator, EXE_SHA
from verify_auth_native import *


def verify():
    u=exe_emulator()
    obj,renderer=DATA+0x1000,DATA+0x2000
    frame=STACK+0x9000
    put32(u,obj+8,renderer)
    put32(u,renderer+0x44,0x12345678)
    put32(u,renderer+0x1c4,1) # D3DPOOL_MANAGED
    put32(u,obj+0x2c,0)
    put32(u,frame-4,obj)
    put32(u,frame-8,DATA+0x3000)
    put32(u,frame-0xc,123456)
    put32(u,frame-0x10,0)
    put32(u,frame+8,0) # D3DFMT_UNKNOWN
    put32(u,frame+0xc,1) # existing mip-level parameter
    u.reg_write(UC_X86_REG_EBP,frame)
    u.reg_write(UC_X86_REG_ESP,frame-0x100)
    def hook(uc,address,size,user):
        if address==0x40ea64:
            uc.reg_write(UC_X86_REG_EAX,obj+0xc)
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x6107cc,0x5f585c,count=200)
    assert u.reg_read(UC_X86_REG_EIP)==0x5f585c
    at=u.reg_read(UC_X86_REG_ESP)+4
    args=[get32(u,at+4*i) for i in range(15)]
    assert args[:10]==[0x12345678,DATA+0x3000,123456,0,0,1,0,0,1,1],args
    assert args[10:13]==[1,0,frame-0x50] and args[13:]==[0,obj+0xc],args
    result=dict(exe_sha256=EXE_SHA,original_loader='6107cc..610818',
                d3dx_import='5f585c',width_parameter=0,height_parameter=0,
                dimensions_from_texture_file=True,d3dx_stubbed=True,
                graphical_game_client=False,args=args,
                documentation='https://learn.microsoft.com/en-us/windows/win32/direct3d9/d3dxcreatetexturefromfileinmemoryex')
    path=ROOT/'reports/equipment-textures/native-loader.json'
    path.write_text(json.dumps(result,indent=2)+'\n')
    print('Original texture loader: source dimensions passed to D3DX9; no fixed 128/256 clamp PASS')


if __name__=='__main__':verify()
