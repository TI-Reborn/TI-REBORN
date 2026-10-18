"""Execute original C8/39 reader/consumer; prove resource semantics via RTTI."""
from verify_auth_native import *
from tio.protocol.asset_count import AssetCount,encode_asset_count

OUT=ROOT/'reports/warehouse-counters-20261018'


def main():
    raw=BINARY.read_bytes();pe=pefile.PE(data=raw);data=pe.get_memory_mapped_image()
    for address,name,pointer in ((0x90f1a0,b'SetRepairPowerAvailable',0x91453c),
                                 (0x90f1e6,b'SetUpgradesCountAvailable',0x914540)):
        offset=address-0x400000
        assert data[offset:offset+len(name)]==name
        assert struct.unpack_from('<I',data,offset-5)[0]==pointer
    value=AssetCount(12345,0,7,6,3,4,5,201,101)
    packet=encode_asset_count(value)
    u=emulator();obj=DATA+0x2000;character=DATA+0x4000;warehouse=DATA+0x8000
    u.mem_write(DATA,packet[2:]);put32(u,0xacd0e8,DATA)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x65802c,STOP,count=5000)
    assert get32(u,0xacd0e8)-DATA==len(packet)-2
    put32(u,0xac5b7c,character);put32(u,0xac55cc,DATA+0x6000);put32(u,DATA+0x6000,warehouse)
    put32(u,0xac618c,DATA+0x7000);u.mem_write(0xac4754,b'\0')
    def hook(uc,address,size,unused):
        if address==0x7d8acc:uc.reg_write(UC_X86_REG_EAX,0xffffffff);return_from_stub(uc)
        elif address in (0x974730,0x70a78c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x7d4c28,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert (get32(u,warehouse+0x34),get32(u,warehouse+0x38))==(201,101)
    assert [get32(u,character+n) for n in (0x238,0x23c,0x240,0x244,0x248)]==[7,6,3,4,5]
    result=dict(passed=True,original_sha256=EXPECTED_SHA,reader='65802c',consumer='7d4c28',
        resource_setters={'repair_points':'91453c','upgrade_kits':'914540'},
        native_rtti_names_verified=True,packet=packet.hex(),
        seven_icons_left_to_right=['Upgrade Kit count','remaining repair points','Spectra Crystals Stock','Spectra Crystals Bonds','Spectra Crystals','yellow range tokens','daily blue range token'],
        graphical_validation=False,ui_callbacks_stubbed=True,
        correction='Former clan-treasury interpretation of fields8/9 was incorrect; these are available warehouse resource fields.')
    (OUT/'native-protocol.json').write_text(json.dumps(result,indent=2));print('Original warehouse resource fields and RTTI: PASS')


if __name__=='__main__':main()
