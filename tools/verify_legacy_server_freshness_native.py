"""Execute native server-list refresh, response recovery and stale rendering.

Runs the real 06 decoder, complete original renderer, actual formatter, appended
helpers and original 05 builder/primitive/CString writers. Only clock, platform
codepage conversion, GUI/collection sinks and transport Flush are isolated.
No game windows are opened and no hosted service is contacted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_server_list_freshness as patcher
from tools.verify_legacy_server_status_native import run_case, read_string
from tools.verify_legacy_lobbies_native import put, get, ret, restart, DATA, ACTORS, STOP, STACK
from tio.protocol.server_list import ServerList, ServerEntry, encode_server_list


def exercise(scenario):
    def check(u, ctx):
        delta = ctx['delta']; clock = ctx['clock']; record = ctx['record']
        control, parent, captured = ctx['control'], ctx['parent'], ctx['captured']
        transport = ACTORS+0x20000; wrapper = ACTORS+0x100; vtable = ACTORS+0x300
        token = ACTORS+0x200; login = ACTORS+0x204; text = ACTORS+0x100c
        put(u, 0xac600c+delta, wrapper); put(u, wrapper, transport)
        put(u, transport, vtable); put(u, vtable, DATA+0x3700); u.mem_write(DATA+0x3700, b'\xc3')
        put(u, 0xac553c+delta, token); put(u, token, 0x12345678)
        put(u, 0xac5bac+delta, login); put(u, login, text)
        login_text = 'owned-qa-list-token'
        u.mem_write(text-12, struct.pack('<HHii',1200,2,-1,len(login_text)))
        u.mem_write(text,login_text.encode('utf-16-le')+b'\0\0')
        u.mem_write(parent+0x49,b'\x01')
        sent=[]; trace=[]; original05_calls=0; selected07_calls=[]

        def hook(uc,address,size,unused):
            nonlocal original05_calls
            original=address-delta
            if original == 0x87c76c:
                original05_calls += 1  # Observe; execute original builder.
            elif address == DATA+0x3700:
                size=get(uc,transport+0x1004)
                sent.append(dict(at=clock['now'],packet_hex=bytes(uc.mem_read(transport+4,size)).hex()))
                ret(uc)
            elif original == 0xa6a114:
                assert read_string(uc,uc.reg_read(UC_X86_REG_EAX)) == 'window_servers_list'
                uc.mem_write(parent+0x49,b'\0'); ret(uc)
            elif original == 0x688420:
                ret(uc,12)
            elif original == 0x71fa5c:
                uc.reg_write(UC_X86_REG_EAX,record); ret(uc)
            elif address == DATA+0x3800:
                put(uc,uc.reg_read(UC_X86_REG_ECX),0); ret(uc)
            elif original == 0x87c7b4:
                selected07_calls.append(dict(server_id=uc.reg_read(UC_X86_REG_EAX),
                                              port=uc.reg_read(UC_X86_REG_ECX),at=clock['now']))
                ret(uc,4)  # Isolated server handoff transport, original click executes.
            elif original == 0x6d311c:
                ret(uc)

        hook_id=u.hook_add(UC_HOOK_CODE,hook)
        current_count=0; current_available=True

        def state():
            return dict(active=u.mem_read(ctx['base']+patcher.ACTIVE,1)[0],
                        pending=u.mem_read(ctx['base']+patcher.PENDING,1)[0],
                        stale=u.mem_read(ctx['base']+patcher.STALE,1)[0],
                        last_send=get(u,ctx['base']+patcher.LAST_SEND),
                        last_reply=get(u,ctx['base']+patcher.LAST_REPLY))

        def run(entry):
            try:
                u.emu_start(entry+delta,STOP,count=200000)
            except Exception:
                print('Native '+scenario+' stopped at '+hex(u.reg_read(UC_X86_REG_EIP)-delta))
                raise
            assert u.reg_read(UC_X86_REG_EIP)==STOP
            assert u.reg_read(UC_X86_REG_ESP)==STACK+0x8004

        def render(now, *, colour=None, sends=None):
            clock['now']=now&0xffffffff; ctx['reset_iterator']()
            captured['draws'].clear(); before=bytes(u.mem_read(record,16))
            restart(u); u.reg_write(UC_X86_REG_EAX,control); run(0x71f010)
            assert bytes(u.mem_read(record,16))==before
            name=next(d for d in captured['draws'] if d['text']=='TI-REBORN')
            count=next(d for d in captured['draws'] if d['text']==str(current_count))
            assert name['colour']==count['colour']
            if colour is not None:
                assert name['colour']==colour,(now,name,state())
            if sends is not None:
                assert len(sent)==sends,(now,sent,state())
            trace.append(dict(action='render',at=clock['now'],online=current_count,
                              available=current_available,colour=name['colour'],
                              sent=len(sent),visible=u.mem_read(parent+0x49,1)[0],state=state()))

        def response(now, online, available=True):
            nonlocal current_count,current_available
            clock['now']=now&0xffffffff
            packet=encode_server_list(ServerList(0,(ServerEntry(1,b'\x7f\0\0\1',28513,online,15,int(available)),)))
            u.mem_write(DATA,packet); restart(u)
            u.reg_write(UC_X86_REG_EAX,6); u.reg_write(UC_X86_REG_EDX,DATA+1); u.reg_write(UC_X86_REG_ECX,len(packet))
            run(0x87daa4)
            current_count=online; current_available=available
            assert get(u,ctx['base']+patcher.LAST_REPLY)==clock['now']
            assert state()['active']==1 and state()['pending']==0 and state()['stale']==0
            assert struct.unpack_from('<3H',bytes(u.mem_read(record,16)),8)==(28513,online,15)
            assert u.mem_read(record+14,1)[0]==int(available)
            trace.append(dict(action='actual06',at=clock['now'],online=online,available=available,state=state()))

        green,gray='0xffb1efdb','0xff606060'
        if scenario == 'online_0_1_2':
            render(4999,colour=green,sends=0); render(5000,colour=green,sends=1)
            render(5001,colour=green,sends=1)
            response(5010,1); render(5010,colour=green,sends=1)
            render(10010,colour=green,sends=2)
            response(10020,2); render(10020,colour=green,sends=2)
        elif scenario == 'timeout_and_recovery':
            render(5000,colour=green,sends=1); render(7999,colour=green,sends=1)
            render(8000,colour=gray,sends=1); render(15000,colour=gray,sends=1)
            assert state()['active']==0 and state()['pending']==0 and state()['stale']==1
            response(15010,2); render(15010,colour=green,sends=1)
            render(20010,colour=green,sends=2)
        elif scenario == 'native_offline_flag':
            response(10,65535,False); render(10,colour=gray,sends=0)
            render(5010,colour=gray,sends=1)
            response(5020,1,True); render(5020,colour=green,sends=1)
        elif scenario == 'hidden_and_original_selection':
            u.mem_write(parent+0x49,b'\0'); render(10000,colour=green,sends=0)
            u.mem_write(parent+0x49,b'\x01'); render(10001,colour=green,sends=1)
            response(10010,1); render(10010,colour=green,sends=1)
            # Execute unchanged original selected-row callback; only GUI hide,
            # configuration collection and final handoff are isolated.
            put(u,0xacdda0+delta,control); put(u,control+0x280,0)
            put(u,get(u,ctx['collection'])+0xc,DATA+0x3800); u.mem_write(DATA+0x3800,b'\xc3')
            put(u,0xac5818+delta,login)
            restart(u); run(0x71e998)
            assert u.mem_read(parent+0x49,1)==b'\0'
            assert selected07_calls == [dict(server_id=1,port=28513,at=10010)]
            render(60000,colour=green,sends=1)
            trace.append(dict(action='original07',window_hidden=True,selected=selected07_calls))
        elif scenario == 'clock_wrap':
            response(0xffffff00,0)
            render((0xffffff00+4999)&0xffffffff,colour=green,sends=0)
            render((0xffffff00+5000)&0xffffffff,colour=green,sends=1)
            render((0xffffff00+8000)&0xffffffff,colour=gray,sends=1)
            response((0xffffff00+8010)&0xffffffff,2); render((0xffffff00+8010)&0xffffffff,colour=green,sends=1)
        elif scenario == 'not_authenticated_no_poll':
            u.mem_write(ctx['base']+patcher.ACTIVE,b'\0')
            render(60000,colour=green,sends=0)
        else:
            raise AssertionError(scenario)
        expected=b'\x05\0'+struct.pack('<I',0x12345678)+login_text.encode('cp1251')+b'\0'
        assert all(s['packet_hex']==expected.hex() for s in sent),sent
        assert original05_calls == len(sent)
        assert get(u,token)==0x12345678 and get(u,login)==text
        assert bytes(u.mem_read(text,len(login_text)*2))==login_text.encode('utf-16-le')
        captured['freshness']=dict(scenario=scenario,trace=trace,original05_calls=original05_calls,
                                   sent=sent,original_request_token_unchanged=True,
                                   original_request_string_unchanged=True,
                                   original05_primitive_and_cstring_writers_executed=True,
                                   selected07_calls=selected07_calls)
        u.hook_del(hook_id)
    return check


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'reports/gameplay-completion/legacy-status-20261011/client/silver.dll')
    parser.add_argument('--candidate',type=Path,default=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-freshness/silver.dll')
    parser.add_argument('--report',type=Path,default=ROOT/'reports/gameplay-completion/legacy-status-20261011/native-server-freshness.json')
    args=parser.parse_args(); source=args.source.read_bytes(); raw=args.candidate.read_bytes()
    review=patcher.review(source,raw)
    cases=[run_case(raw,base,count,available,selected=selected)
           for base in (0x400000,0x10400000) for count in (0,1,2,50,999,65535)
           for available in (False,True) for selected in (False,True)]
    cases.extend(run_case(raw,base,2,True,server_id=2) for base in (0x400000,0x10400000))
    scenarios=('online_0_1_2','timeout_and_recovery','native_offline_flag',
               'hidden_and_original_selection','clock_wrap','not_authenticated_no_poll')
    temporal=[run_case(raw,base,0,True,exercise=exercise(scenario))
              for base in (0x400000,0x10400000) for scenario in scenarios]
    report=dict(status='PASS',scope=__doc__,source_sha256=patcher.sha(source),candidate_sha256=patcher.sha(raw),
                row_case_count=len(cases),temporal_case_count=len(temporal),cases=cases,temporal=temporal,
                review=review,metadata=patcher.metadata(),real_graphical_clients=0)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PASS: '+str(len(cases))+' full native row cases, '+str(len(temporal))+' clock/05/06/visibility/selection cases')


if __name__=='__main__':
    main()
