"""Original map writer1B, movement reader1D, hire62 and PetInfo66.

Network writer primitives are captured. Hire UI/allocation and PetInfo runtime
use the existing explicit probe stubs. Movement reader executes without stubs.
"""
from verify_auth_native import *
from verify_city_catalogs_native import run_case
from trace_pet_info_native import trace
from tio.locations import movement_packet
from tio.city_catalogs import CityCatalogs
from tio.hiring import HireStore
from tio.wallets import WalletStore
import tempfile


def main():
    u=emulator();out=bytearray()
    def hook(uc,addr,size,user):
        if addr in (0x65fec8,0x65fff4):
            value=uc.reg_read(UC_X86_REG_EDX)
            out.extend(bytes((value&255,)) if addr==0x65fec8 else struct.pack('<I',value))
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.mem_write(DATA,struct.pack('<IB3xIB3x',(-77)&0xffffffff,1,(-447)&0xffffffff,1))
    u.reg_write(UC_X86_REG_EAX,DATA);u.emu_start(0x6517f8,STOP,count=2000)
    assert bytes(out)==struct.pack('<Bii',0x1b,-77,-447)
    packet=movement_packet(42,-77,-447)
    u=emulator();u.mem_write(DATA,packet[1:])
    for addr,target in ((0xac5a98,DATA+0x1000),(0xac5b7c,DATA+0x2000),(0xac5a4c,DATA+0x3000),(0xac60a4,DATA+0x4000)):
        put32(u,addr,target)
    put32(u,DATA+0x1000,42)
    u.reg_write(UC_X86_REG_EAX,DATA);u.emu_start(0x88b130,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert struct.unpack('<iiii',u.mem_read(DATA+0x200c,16))==(-77,-447,-77,-447)
    assert struct.unpack('<ff',u.mem_read(DATA+0x201c,8))==(-77.,-447.)
    assert get32(u,DATA+0x2224)==0
    catalogs=CityCatalogs(ROOT/'config/city_catalogs.json')
    hire=run_case('pets',catalogs.pet_shop(9))
    row=bytes.fromhex(hire['records'][0])
    assert struct.unpack_from('<II',row,0x100)==(6,6)
    assert struct.unpack_from('<IBB2xIII',row,0x184)==(98,8,14,0,1000,3500)
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'state.db';WalletStore(path).ensure('native')
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        store=HireStore(path,catalogs,template)
        from tio.locations import LocationStore
        clock=[1000.]
        locations=LocationStore(path,clock=lambda:clock[0])
        locations.travel('native',bytes(out),42)
        clock[0]+=1000
        locations.refresh('native',42)
        pet,_,_=store.hire('native',6)
        result=trace(body=pet[1:],human=True,new_slot=True)
        assert result['consumed']==len(pet)-1
        assert result['native_health']=={'maximum':98,'current':98}
        assert result['native_max_weight']==1000
    (ROOT/'evidence/miner_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,
        'map_request':bytes(out).hex(),'movement_reply':packet.hex(),'hire':hire,'pet':result},indent=2)+'\n')
    print('Original map1B/1D, miner hire62 and saved PetInfo66: PASS')


if __name__=='__main__':main()
