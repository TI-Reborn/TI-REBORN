"""Execute original 83 reader -> clan row draw -> weekly badge sprite choice.

No installed DLL edit, network, game process or graphical acceptance. Delphi
allocation/string and graphics callbacks are explicit bounded test stubs. The
numeric reader and original clan UI's row+0x220 fetch/sprite selection execute.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))

from tio.protocol.clan_ratings import ClanRating, encode_ratings
from verify_auth_native import BINARY, DATA, STACK, get32, put32, return_from_stub
from verify_clan_warfare_native import ReaderProbe
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX,
                              UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_EBX,
                              UC_X86_REG_ESI, UC_X86_REG_EDI)


def proof():
    published=ROOT/'reports/gameplay-completion/stage6-economy/client/candidate/silver.dll'
    published_raw=published.read_bytes()
    published_sha=hashlib.sha256(published_raw).hexdigest()
    if published_sha!='7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b':
        raise RuntimeError('Expected exact DLL published with client2026.10.08.5')
    original_image=pefile.PE(data=BINARY.read_bytes()).get_memory_mapped_image()
    published_image=pefile.PE(data=published_raw).get_memory_mapped_image()
    unchanged=[]
    for start,end in ((0x6e6ef0,0x6e70df),(0x841aed,0x841b1e),(0x6e7a48,0x6e7aab),
                      (0x605d68,0x605df4)):
        before=original_image[start-0x400000:end-0x400000]
        assert before==published_image[start-0x400000:end-0x400000]
        unchanged.append(dict(start=hex(start),end_exclusive=hex(end),sha256=hashlib.sha256(before).hexdigest()))
    cases = []
    for place, sprite in ((0,None),(1,3),(2,2),(5,2),(6,1),(10,1),(11,0),(20,0),(21,None)):
        record = ClanRating(17,b'Clan A',b'Alice',3,10,1,901,
                            crest_id=29, alliance_crest_id=31,
                            unknown_u32_3=place, unknown_u32_4=77)
        packet = encode_ratings(0,0,(record,))
        p = ReaderProbe(packet[1:])
        handle = DATA+0x18000
        put32(p.u,0xac6580,handle)
        p.run(0x6e6ef0,a=DATA)
        pointer = get32(p.u,handle)
        assert get32(p.u,pointer+0x220) == place
        assert get32(p.u,pointer+0x224) == 77
        assert pointer != 0
        frame,obj,array_handle = DATA+0x1b000,DATA+0x12000,DATA+0x16000
        put32(p.u,frame-8,obj);put32(p.u,obj+0x2ac,array_handle);put32(p.u,array_handle,pointer)
        put32(p.u,frame-4,100);put32(p.u,frame-12,200)
        for reg,value in ((UC_X86_REG_EBP,frame),(UC_X86_REG_EBX,0),
                          (UC_X86_REG_ESI,0),(UC_X86_REG_EDI,0)):
            p.u.reg_write(reg,value)
        rendered=[]
        def graphics(uc,address,size,unused):
            if address == 0x674ea4:
                stack=uc.reg_read(UC_X86_REG_ESP)
                raw=bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EAX),64))
                end=next(i for i in range(0,64,2) if raw[i:i+2]==b'\0\0')
                asset=raw[:end].decode('utf-16-le')
                rendered.append(dict(asset=asset,sprite=get32(uc,stack+8),
                                     x=uc.reg_read(UC_X86_REG_EDX),y=uc.reg_read(UC_X86_REG_ECX)))
                return_from_stub(uc)
                uc.reg_write(UC_X86_REG_ESP,stack+12)
        p.u.hook_add(UC_HOOK_CODE,graphics)
        p.stop_at=0x841b1e
        p.run(0x841aed)
        expected=[] if sprite is None else [dict(asset='assault_medal_small',sprite=sprite,x=416,y=228)]
        assert rendered == expected, (place,rendered,expected)
        cases.append(dict(place=place,packet_hex=packet.hex(),reader_field_offset='0x220',
                          unchanged_unknown_field_offset='0x224',graphics_callback=rendered))
    return dict(passed=True,original_binary_sha256=hashlib.sha256(BINARY.read_bytes()).hexdigest(),
                published_client_version='2026.10.08.5',published_binary_sha256=published_sha,
                original_code_parity_with_published_dll=unchanged,
                scope='unchanged original 83 reader and clan rating UI row badge draw instructions',
                reader='0x6e6ef0',row_place_store='0x6e7070',row_place_offset='0x220',
                ui_place_load='0x841afb',ui_badge_call='0x841b19',sprite_selector='0x6e7a48',
                confirmed_wire_field='ClanRating.unknown_u32_3 is weekly assault clan place (1..20)',
                remaining_unknown_field='unknown_u32_4 at native record+0x224',cases=cases,
                limitations=['No graphical game client launched','Graphics callbacks stubbed; existing original asset keys retained',
                             'Does not prove a weekly standings request opcode or permanent player medal fields'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/gameplay-followup/stage1-interfaces/weekly-ui/native-badge.json')
    args=parser.parse_args();result=proof()
    result['probe_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],cases=len(result['cases']),confirmed_wire_field=result['confirmed_wire_field']),ensure_ascii=False))


if __name__ == '__main__':
    main()
