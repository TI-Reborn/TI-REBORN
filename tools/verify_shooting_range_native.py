"""Execute original mode16 entry/start builders. Only transport/UI are stubbed."""
from verify_auth_native import *
from verify_arena_requests_native import run
from tio.shooting_range import CREATE_REQUEST


def native_request(selection=None):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vtable=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush)
    put32(u,0xac600c,handle);put32(u,0xac63b4,DATA+0x3300)
    if selection is not None:
        u.mem_write(0xac4815,b'\x01')
        put32(u,0xac481c,selection)
        put32(u,0xac6008,DATA+0x4000)
        u.mem_write(DATA+0x4019,b'\x10')
    def hook(uc,addr,size,user):
        if addr==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif addr in (0x81dd88,0xa03344,flush):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x6e8f50 if selection is None else 0x81db34,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))


if __name__=='__main__':
    packet=native_request();assert packet==CREATE_REQUEST,(packet.hex(),CREATE_REQUEST.hex())
    cases=[dict(entry='6e8f50',packet=packet.hex())]
    for selection in range(4):
        packet=native_request(selection)
        assert packet==bytes((0x2e,(0,0,1,2)[selection]))
        cases.append(dict(entry='81db34',ui_selection=selection,packet=packet.hex()))
    from tests.test_shooting_range import RangeTests
    from tio.protocol.battle_soldier import encode_battle_soldier
    from trace_battle_soldier_native import trace
    fixture=RangeTests();fixture.setUp()
    try:
        fixture.start()
        target=min(fixture.field.practice.targets)
        packet=encode_battle_soldier(fixture.scene.visibility.templates[target])
        result=trace(human=False,equipment_class=2,body=packet[1:])
        assert result['body_hex']==packet[1:].hex()
        assert result['model']['health']==result['model']['max_health']==200
        cases.append(dict(entry='8c5044',equipment_class=2,model=result['model'],packet=packet.hex()))
    finally:fixture.doCleanups()
    (ROOT/'evidence/shooting_range_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n')
    print('Original Shooting Range entry and four payment builders: PASS')
