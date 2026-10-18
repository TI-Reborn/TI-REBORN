"""Accurate Assault4 string framing against original native packet readers."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
from verify_clan_warfare_native import ReaderProbe
from verify_auth_native import DATA,put32,get32,return_from_stub,UC_X86_REG_EAX,UC_X86_REG_EDX
from tio.protocol import assault
class NativeStrings(ReaderProbe):
    def hook(self,u,address,size,unused):
        a=u.reg_read(UC_X86_REG_EAX);d=u.reg_read(UC_X86_REG_EDX)
        if address==0x6297ac:
            ptr=get32(u,0xacd0e8);n=int.from_bytes(u.mem_read(ptr,2),'little')
            assert n<=1024
            raw=bytes(u.mem_read(ptr+2,n));raw.decode('utf-8')
            put32(u,0xacd0e8,ptr+2+n);value=self.allocate();self.strings[value]=raw
            u.mem_write(value,bytes((min(n,255),))+raw);put32(u,d,value);return_from_stub(u)
        elif address==0x629abc:
            raw=self.strings[d];count=get32(u,0xacd0f0)
            u.mem_write(DATA+0x10000+count,struct.pack('<H',len(raw))+raw);put32(u,0xacd0f0,count+2+len(raw));return_from_stub(u)
        else:super().hook(u,address,size,unused)
def main():
    cases=[]
    name='Игрок Ёж'.encode('cp1251');petname='Боец'.encode('cp1251')
    pet=assault.RoomPet(4,1,0,petname,115,0,1,0,1)
    packet=assault.encode_room_info(19,(assault.RoomCell(1,name,4,0,1,(pet,),0),),0)
    cases.append(NativeStrings(packet[2:]).roundtrip(0x63a494,0x63a500,packet))
    assert name.decode('cp1251').encode('utf-8') in packet
    row=assault.RoomListItem(19,name,None,None,4,1,0)
    packet=assault.encode_room_list((row,));p=NativeStrings(packet[6:]);p.run(0x63aa10)
    assert get32(p.u,0xacd0e8)-DATA==len(packet)-6
    cases.append(dict(reader='0x63aa10',consumed=len(packet)-6))
    zone=assault.ZoneInfo(1,100,None,0,4,6,7,10,10,last_clan_owner=assault.ClanOwner(1,name,name,0))
    body=assault.encode_zone_body(zone);p=NativeStrings(body);p.run(0x649a44);assert get32(p.u,0xacd0e8)-DATA==len(body)
    p.run(0x649b34);assert bytes(p.u.mem_read(DATA+0x10000,get32(p.u,0xacd0f0)))==body
    cases.append(dict(reader='0x649a44',writer='0x649b34',consumed=len(body)))
    team=assault.TeamResult(1,4,0,(assault.PlayerResult(name,1,0,0),),(assault.ClanResult(name,0,0,0),))
    packet=assault.encode_battle_over(19,team,team)
    cases.append(NativeStrings(packet[2:]).roundtrip(0x64fb88,0x64fbbc,packet))
    result=dict(passed=True,cases=cases,encoding='Native6297ac/629abc: u16 bytes + UTF8 (TUTF8Encoding65001 at431eb0)',limitation='Managed allocation/Unicode conversion isolated; native full GUI acceptance is separate')
    (ROOT/'reports/training-base-20261018/native-strings.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
