"""Execute actual legacy list06 decoder, complete row renderer and formatter.

Production x86 runs at preferred and relocated bases. GUI draw sinks, native
collection enumeration, localization, allocation and cleanup are isolated;
numeric parsing, availability branches, actual integer-to-Unicode conversion,
new name/header wrappers and managed Unicode assignment execute unchanged.
This offline proof makes no graphical-client or live-service claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_legacy_lobbies_native import emulator, put, get, ret, restart, DATA, STOP, STACK
from deploy import client_server_list_status as patcher
from tio.protocol.server_list import ServerList, ServerEntry, encode_server_list


def read_string(u, pointer):
    if not pointer:
        return ''
    length = get(u, pointer-4)
    assert length < 1024
    return bytes(u.mem_read(pointer, length*2)).decode('utf-16-le')


def run_case(raw, base, count, available, *, selected=False, server_id=1, exercise=None):
    u = emulator(raw, base); delta = base-patcher.IMAGE_BASE
    record = DATA+0x4000; control = DATA+0x1000; parent = DATA+0x2000
    collection = DATA+0x3000; vtable = DATA+0x3100; heap = DATA+0x6000
    allocation = heap
    captured = dict(draws=[], integer_formatter_inputs=[], stubs=set())
    clock = dict(now=0)
    put(u, 0xb79b10+delta, DATA+0x3600); u.mem_write(DATA+0x3600, b'\xc3')
    packet = encode_server_list(ServerList(0, (ServerEntry(server_id, b'\x7f\0\0\1', 28513, count, 15, int(available)),)))
    u.mem_write(DATA, packet)
    put(u, 0xac5d24+delta, collection); put(u, 0xac5b7c+delta, parent)
    put(u, 0xacdd9c+delta, collection)
    put(u, control+0x4c, parent); put(u, control+0x38, 350); put(u, control+0x3c, 120)
    put(u, control+0x280, 0 if selected else 0xffffffff)
    put(u, control+0x284, 18); put(u, control+0x288, 2)
    put(u, control+0x2b8, collection); put(u, collection, vtable)
    put(u, vtable+0x14, DATA+0x3500); u.mem_write(DATA+0x3500, b'\xc3')
    iterator = DATA+0x3200; iterator_calls = 0; parsing = True
    put(u, iterator, vtable); put(u, vtable-4, DATA+0x3500)

    def reset_iteration():
        nonlocal iterator_calls
        iterator_calls = 0

    def allocate(uc, text=None, length=None):
        nonlocal allocation
        if text is not None:
            length = len(text)
        target = allocation+12; allocation += 0x100
        assert allocation < DATA+0xf000
        uc.mem_write(target-12, struct.pack('<HHii', 1200, 2, 1, length))
        uc.mem_write(target, ((text.encode('utf-16-le') if text is not None else bytes(2*length))+b'\0\0'))
        return target

    def hook(uc, address, size, unused):
        nonlocal iterator_calls
        original = address-delta
        a, d, c = (uc.reg_read(reg) for reg in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        if original == 0x4244b4:
            captured['integer_formatter_inputs'].append(a)  # Observe; execute actual numeric formatter.
            return
        if address == DATA+0x3600:
            uc.reg_write(UC_X86_REG_EAX, clock['now']); ret(uc)
        elif original == 0x40c0e4:
            put(uc, a, allocate(uc, length=d)); ret(uc)
        elif original == 0x40bf68:
            uc.reg_write(UC_X86_REG_EAX, a); ret(uc)
        elif original == 0x40c1bc:
            put(uc, a, allocate(uc, read_string(uc, d)+read_string(uc, c))); ret(uc)
        elif original == 0x40c244:
            sp=uc.reg_read(UC_X86_REG_ESP)
            text=''.join(read_string(uc, get(uc, sp+4+i*4)) for i in reversed(range(d)))
            put(uc, a, allocate(uc, text)); ret(uc, d*4)
        elif original == 0x40ce98:
            uc.reg_write(UC_X86_REG_EAX, record); ret(uc)
        elif original == 0x71fea0:
            captured['record_hex']=bytes(uc.mem_read(d, 16)).hex(); ret(uc)
        elif original == 0x605ca4:
            assert bytes(uc.mem_read(a, 1)) == b'\0'; put(uc, d, 0); ret(uc)
        elif original == 0x6675e0:
            put(uc, d, allocate(uc, read_string(uc, a))); ret(uc)
        elif original in (0xa4211c, 0xa42140):
            uc.reg_write(UC_X86_REG_EAX, 0); ret(uc)
        elif original == 0x72095c:
            uc.reg_write(UC_X86_REG_EAX, iterator); ret(uc)
        elif original == 0x720970:
            uc.reg_write(UC_X86_REG_EAX, record); ret(uc)
        elif original == 0x72071c:
            uc.reg_write(UC_X86_REG_EAX, 0); ret(uc)
        elif original == 0x7209e0:
            uc.reg_write(UC_X86_REG_EAX, int(iterator_calls == 0)); iterator_calls += 1; ret(uc)
        elif address == DATA+0x3500:
            uc.reg_write(UC_X86_REG_EAX, 0); ret(uc)
        elif original == 0x4f26f4:
            put(uc, d, 0); ret(uc)
        elif original == 0x424f2c:
            uc.reg_write(UC_X86_REG_EAX, 0); ret(uc)
        elif original == 0x4a53c4:
            ret(uc, 8)
        elif original == 0x4f29a8:
            sp=uc.reg_read(UC_X86_REG_ESP)
            captured['draws'].append(dict(text=read_string(uc, d), colour=hex(get(uc, sp+4)), x=c, y=get(uc, sp+8), font=a))
            ret(uc, 8)
        elif original == 0x4f2ba8:
            uc.reg_write(UC_X86_REG_EAX, len(read_string(uc, d))*8); ret(uc)
        elif original == 0x4f2888:
            ret(uc, 16)
        elif original == 0x4f2950:
            ret(uc, 20)
        elif original == 0x4f2978:
            ret(uc, 16)
        elif original == 0x4f27fc:
            ret(uc, 12)
        elif original == 0x40c06c and a >= STACK:
            return  # Execute actual short-string writer in original packet05.
        elif original == 0x40b1ec:
            # Isolate the platform codepage conversion, retaining the original
            # Unicode-to-short-string wrapper and all packet writing code.
            length=get(uc,uc.reg_read(UC_X86_REG_ESP)+4)
            value=bytes(uc.mem_read(c,length*2)).decode('utf-16-le').encode('cp1251')
            assert len(value) <= d
            uc.mem_write(a,value); uc.reg_write(UC_X86_REG_EAX,len(value)); ret(uc,4)
        elif original in (0xa69aa0, 0x71e8ec, 0x71e594, 0xa53b08, 0x40b09c, 0x40b0fc,
                          0x40c06c, 0x4f2eb4, 0x4f2ee8):
            ret(uc)
        else:
            return
        captured['stubs'].add(hex(original) if address != DATA+0x3500 else 'localized-name collection count')

    token=u.hook_add(UC_HOOK_CODE, hook)
    restart(u)
    u.reg_write(UC_X86_REG_EAX, 6); u.reg_write(UC_X86_REG_EDX, DATA+1); u.reg_write(UC_X86_REG_ECX, len(packet))
    u.emu_start(0x87daa4+delta, STOP, count=100000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    raw_record=bytes.fromhex(captured['record_hex'])
    assert struct.unpack_from('<3H',raw_record,8)==(28513,count,15)
    assert raw_record[14] == int(available)
    parser_formatter_inputs=captured['integer_formatter_inputs'][:]
    captured['integer_formatter_inputs'].clear(); parsing=False
    # The 16-byte native record is untouched; render it through the real vtable method.
    before=bytes(u.mem_read(record,16))
    restart(u); u.reg_write(UC_X86_REG_EAX,control)
    try:
        u.emu_start(0x71f010+delta, STOP, count=100000)
    except Exception:
        print('Renderer stopped at '+hex(u.reg_read(UC_X86_REG_EIP)-delta)+', stack '+hex(u.reg_read(UC_X86_REG_ESP)))
        raise
    assert u.reg_read(UC_X86_REG_EIP)==STOP, hex(u.reg_read(UC_X86_REG_EIP))
    assert u.reg_read(UC_X86_REG_ESP)==0x3008004, 'Renderer stack ABI changed'
    assert bytes(u.mem_read(record,16)) == before, 'Rendering mutated list06 state'
    expected_colour=hex(0xffb1efdb if available else 0xff606060)
    name='TI-REBORN' if server_id==1 else 'Server '+str(server_id)
    assert any(d['text']==name for d in captured['draws']), captured['draws']
    name_draw=next(d for d in captured['draws'] if d['text']==name)
    count_draw=next(d for d in captured['draws'] if d['text']==str(count))
    assert name_draw['colour']==expected_colour and count_draw['colour']==expected_colour, captured['draws']
    assert any(d['text']=='Онлайн' for d in captured['draws'])
    assert not any('%' in d['text'] for d in captured['draws'])
    assert count in captured['integer_formatter_inputs']
    if exercise is not None:
        exercise(u, dict(base=base, delta=delta, record=record, control=control,
                         parent=parent, collection=collection, clock=clock,
                         captured=captured, reset_iterator=reset_iteration))
    captured['stubs']=sorted(captured['stubs']); captured['packet_hex']=packet.hex()
    captured.update(base=hex(base),online=count,available=available,selected=selected,server_id=server_id,
                    parser_formatter_inputs=parser_formatter_inputs,native_record_unchanged=True)
    u.hook_del(token)
    return captured



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'reports/gameplay-completion/legacy-lobbies-20261011/client/silver.dll')
    parser.add_argument('--candidate',type=Path,default=ROOT/'reports/gameplay-completion/legacy-status-20261011/client/silver.dll')
    parser.add_argument('--report',type=Path,default=ROOT/'reports/gameplay-completion/legacy-status-20261011/native-server-status.json')
    args=parser.parse_args(); source=args.source.read_bytes(); raw=args.candidate.read_bytes()
    review=patcher.review(source,raw)
    cases=[run_case(raw,base,count,available,selected=selected)
           for base in (0x400000,0x10400000) for count in (0,1,2,50,999,65535)
           for available in (False,True) for selected in (False,True)]
    cases.extend(run_case(raw,base,2,True,server_id=2) for base in (0x400000,0x10400000))
    report=dict(status='PASS',scope=__doc__,source_sha256=patcher.sha(source),candidate_sha256=patcher.sha(raw),
                case_count=len(cases),cases=cases,review=review,metadata=patcher.metadata(),real_graphical_clients=0)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: '+str(len(cases))+' real native list06/render/formatter cases at preferred and relocated bases')


if __name__=='__main__':
    main()
