"""Execute the published native barter writers/readers with explicit UI stubs."""
from pathlib import Path
import hashlib,json,struct,sys
import pefile
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_EIP
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
import verify_clan_warfare_native as base
from verify_auth_native import DATA,STACK,STOP,put32,get32,return_from_stub
from tio.protocol import player_trade as wire
from tio.protocol.warehouse import WarehouseItem
from verify_mail_native import native_builder

def run():
    binary=Path(r'C:\Users\jundu\AppData\Local\TIO-Online\silver.dll');raw=binary.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='d533d7ec2eaa5b6134c072be4a55ba3e04f8006a5279fabd645d03c5216c4748'
    mapped=pefile.PE(data=raw).get_memory_mapped_image()
    original=base.image()
    # Establish the exact original ABI before substituting the published image.
    for a,b in ((0x713f18,0x714068),(0x714368,0x7143a4),(0x71493c,0x714990),(0x641b28,0x641ea9),(0x642654,0x642700)):
        assert mapped[a-0x400000:b-0x400000]==original[a-0x400000:b-0x400000]
    base.image=lambda:mapped
    cases=[]
    for entry,a,d,packet in ((0x71402c,1,7,wire.answer_request(True,7)),(0x71402c,0,0,wire.answer_request(False,0)),
                             (0x714368,123,17,wire.offer_request(123,17)),(0x714368,wire.CREDITS_ID,123,wire.offer_request(wire.CREDITS_ID,123)),
                             (0x71493c,1,0,wire.confirm_request()),(0x71493c,0,0,wire.confirm_request(False))):
        result=native_builder(entry,a=a,d=d)
        assert result==packet,(hex(entry),result.hex(),packet.hex())
        cases.append(dict(kind='original request writer',entry=hex(entry),packet=packet.hex()))
    # Managed ANSI recipient and only the post-send UI callback are stubbed.
    def invite_setup(u,string):u.mem_write(0x72d32c,b'\xc3')
    packet=native_builder(0x713f18,a=DATA+0x4008,d=7,recipient=b'Bobby',setup=invite_setup)
    assert packet==wire.invite_request(b'Bobby',7)
    cases.append(dict(kind='original invitation writer',packet=packet.hex(),ui_stub='72D32C'))
    items=(WarehouseItem(123,3,17,1,2,3,4,5),wire.money(wire.CREDITS_ID,123),wire.money(wire.GOLD_ID,8))
    for item in items:
        packet=wire.record(item);probe=base.ReaderProbe(packet)
        probe.run(0x641b28)
        assert get32(probe.u,0xacd0e8)-DATA==len(packet)
        probe.run(0x641c74)
        assert bytes(probe.u.mem_read(DATA+0x10000,get32(probe.u,0xacd0f0)))==packet
        cases.append(dict(kind='original trade record roundtrip',template=item.template_id,bytes=len(packet)))
    packet=wire.start(items);probe=base.ReaderProbe(packet[1:]);probe.run(0x642654)
    assert get32(probe.u,0xacd0e8)-DATA==len(packet)-1
    probe.run(0x6426a0)
    assert bytes(probe.u.mem_read(DATA+0x10000,get32(probe.u,0xacd0f0)))==packet
    cases.append(dict(kind='original trade start list roundtrip',items=len(items),bytes=len(packet)))
    # Original 85 dispatch reads the complete ANSI name, then invokes its UI.
    probe=base.ReaderProbe(b'Alice\0');seen=[]
    def invitation(u,address,size,unused):
        if address in (0x7da2f4,0x67bf80):u.reg_write(UC_X86_REG_EAX,0);return_from_stub(u)
        if address==0x72d454:seen.append('invite');return_from_stub(u)
    probe.u.hook_add(UC_HOOK_CODE,invitation);probe.run(0x713fb0,a=DATA)
    assert seen==['invite']
    cases.append(dict(kind='original invitation reader',bytes=6))
    result=dict(passed=True,published_dll_sha256=hashlib.sha256(raw).hexdigest(),cases=cases,
                scope='Original x86 ABI; managed strings, allocator and UI callbacks are stubs. Not graphical acceptance.')
    path=ROOT/'reports/direct-trade-20261014/native-proof.json';path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(passed=True,cases=len(cases),report=str(path))))
if __name__=='__main__':run()
