"""Run the original 3600-frame watchdog and 9E reset; UI/transport stubbed.

This is a native-code regression, not graphical-client validation.
"""
from verify_auth_native import *
import pefile


def run(heartbeat):
    u=emulator();disconnect=[]
    put32(u,0xac5dec,DATA+0x1000)
    put32(u,0xac5fe4,DATA+0x1100)
    u.mem_write(0xac48b0,b'\1')
    def hook(uc,address,size,user):
        if address==0x87b594:
            disconnect.append(uc.reg_read(UC_X86_REG_EAX));return_from_stub(uc)
        elif address in (0x43afc0,0xa88a78,0x40c9f4):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def invoke(entry):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.emu_start(entry,STOP,count=3000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
    for frame in range(1,6001):
        put32(u,DATA+0x1100,frame*10)
        if heartbeat and frame%1000==0:
            u.reg_write(UC_X86_REG_EAX,0x9e);u.reg_write(UC_X86_REG_EDX,DATA)
            invoke(0x6d4c08)
            assert get32(u,0xac48b4)==0
        invoke(0x87b984)
    assert bool(disconnect)==(not heartbeat)
    return dict(frames=6000,heartbeat_every_frames=1000 if heartbeat else None,
                disconnect_calls=disconnect,final_watchdog_frames=get32(u,0xac48b4))


if __name__=='__main__':
    live=Path.home()/'AppData/Local/TIO-Online/silver.dll'
    original=pefile.PE(str(BINARY)).get_memory_mapped_image()
    patched=pefile.PE(str(live)).get_memory_mapped_image()
    for start,end in ((0x87b984,0x87ba24),(0x6d4ae8,0x6d4c22)):
        assert original[start-0x400000:end-0x400000]==patched[start-0x400000:end-0x400000]
    result=dict(method=__doc__,original_sha256=EXPECTED_SHA,
                installed_sha256=hashlib.sha256(live.read_bytes()).hexdigest(),
                installed_watchdog_parity=True,cases=[run(False),run(True)])
    (ROOT/'reports/wall-disconnect/native.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
