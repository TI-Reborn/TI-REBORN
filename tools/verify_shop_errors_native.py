"""Original F0 wait reset and command47 numeric argument parsing."""
from verify_auth_native import *


def main():
    u=emulator()
    u.mem_write(0xac4c58,b'\x01')
    u.emu_start(0x7d1d91,0x7d1d98,count=30)
    assert bytes(u.mem_read(0xac4c58,1))==b'\0'
    # Command47 explicitly parses the argument as an integer before item-name lookup.
    frame=DATA+0x5000;array=DATA+0x2000;string=DATA+0x1000
    put32(u,string-4,1);u.mem_write(string,'1\0'.encode('utf-16le'))
    put32(u,array,string);put32(u,frame-8,array)
    u.reg_write(UC_X86_REG_EBP,frame)
    u.emu_start(0x7d2d12,0x7d2d26,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==0x7d2d26
    assert u.reg_read(UC_X86_REG_EAX)==1
    (ROOT/'evidence/shop_errors_native.json').write_text(json.dumps({
        'sha256':EXPECTED_SHA,'waiting_before':1,'waiting_after':0,
        'command47_argument':1,'scope':'Original instruction ranges; no UI emulation'},indent=2)+'\n')
    print('F0 wait reset and numeric currency argument: PASS')


if __name__=='__main__':main()
