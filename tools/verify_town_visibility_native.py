"""Original C82D decoder, enabled assignment and map visibility gate.

Runs native code fragments with a supplied town table; does not render the UI.
Also checks the F0/98 direct ID-minus-one lookup against the shipped XML.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI
from dataclasses import replace
import xml.etree.ElementTree as ET
from tio.locations import TOWNS, town_packets
from tio.protocol.town_info import decode_town_info, encode_town_info


def main():
    u=emulator();obj=DATA+0x1000;table=DATA+0x3000;indirect=DATA+0x2000
    put32(u,0xac63bc,indirect);put32(u,indirect,table)
    rows=ET.parse(ROOT/'evidence/zones_diagnostic.xml').getroot().findall('town')
    assert [int(t.get('id')) for t in rows]==list(range(1,len(rows)+1))
    put32(u,table-4,len(rows))
    for index,t in enumerate(rows):
        record=DATA+0x4000+index*0x400
        put32(u,table+index*4,record);put32(u,record+8,int(t.get('id')))
    put32(u,0xac5d58,DATA+0x2100)
    def hook(uc,addr,size,user):
        if addr==0x40b0fc:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def run(start,end=STOP):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.emu_start(start,end,count=10000)
        assert u.reg_read(UC_X86_REG_EIP)==end
    results=[]
    for town in TOWNS:
        index=town-1;record=get32(u,table+index*4)
        put32(u,DATA+0x2100,town)
        run(0x7d2ea4,0x7d2eb7)
        assert get32(u,u.reg_read(UC_X86_REG_EAX)+8)==town
        for enabled in (0,1):
            info=replace(decode_town_info(town_packets(town)[0]),final_bool=enabled)
            body=encode_town_info(info)[2:]
            u.mem_write(DATA,body);put32(u,0xacd0e8,DATA)
            u.reg_write(UC_X86_REG_EAX,obj);run(0x64a3fc)
            assert get32(u,0xacd0e8)-DATA==len(body)
            u.reg_write(UC_X86_REG_EDI,obj);u.reg_write(UC_X86_REG_EBX,index)
            run(0x7cfb41,0x7cfb59)
            assert u.mem_read(record+4,1)[0]==enabled
            u.reg_write(UC_X86_REG_EDI,index)
            run(0x9e8ed6,0x9e8eef if enabled else 0x9e969b)
            results.append(dict(town=town,enabled=enabled,map_gate_passed=bool(enabled)))
    (ROOT/'evidence/town_visibility_native.json').write_text(json.dumps(
        dict(method=__doc__,sha256=EXPECTED_SHA,cases=results),indent=2)+'\n')
    print('Original town enabled flag, map gate and ID lookup: PASS')


if __name__=='__main__':main()
