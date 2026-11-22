"""Unchanged original Silver numeric mail builders/readers in bounded Unicorn.

Managed strings, allocation and UI callbacks are explicit stubs. No GUI,
process, account, game socket or hosting data is touched by this proof.
"""
from functools import lru_cache
from hashlib import sha256
import json
import struct
import sys
from pathlib import Path

import pefile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_clan_warfare_native import ReaderProbe,emulator
from verify_auth_native import (
    ROOT,EXPECTED_SHA,DATA,STACK,STOP,put32,get32,return_from_stub,
    UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,
    UC_X86_REG_EBP,UC_X86_REG_EIP,
)
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EDI,UC_X86_REG_ESI
from tio.protocol import mail
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer


class MailReader(ReaderProbe):
    def __init__(self,body):
        super().__init__(body);self.consumed=None

    def hook(self,u,address,size,unused):
        a=u.reg_read(UC_X86_REG_EAX);d=u.reg_read(UC_X86_REG_EDX)
        if address in (0x6297ac,0x605df4,0x629860):
            pointer=get32(u,0xacd0e8) if address!=0x605df4 else get32(u,a)
            if address==0x6297ac:
                length=struct.unpack('<H',u.mem_read(pointer,2))[0]
                assert length<=16000
                raw=bytes(u.mem_read(pointer+2,length));pointer+=2+length
                put32(u,0xacd0e8,pointer)
            else:
                out=bytearray()
                while (word:=bytes(u.mem_read(pointer,2)))!=bytes(2):
                    out.extend(word);pointer+=2
                    assert len(out)<=16000
                raw=bytes(out);pointer+=2
                put32(u,0xacd0e8 if address==0x629860 else a,pointer)
            value=self.allocate();self.strings[value]=raw
            put32(u,value-4,len(raw));u.mem_write(value,raw+bytes(2));put32(u,d,value)
            return_from_stub(u)
        elif address==0x629abc:
            raw=self.strings[d];count=get32(u,0xacd0f0)
            u.mem_write(DATA+0x10000+count,struct.pack('<H',len(raw))+raw)
            put32(u,0xacd0f0,count+2+len(raw));return_from_stub(u)
        elif address==0x629a28:
            raw=self.strings[d]+bytes(2);count=get32(u,0xacd0f0)
            u.mem_write(DATA+0x10000+count,raw);put32(u,0xacd0f0,count+len(raw));return_from_stub(u)
        elif address in (0x40c048,0x40b4f0,0x40c05c):
            put32(u,a,d);return_from_stub(u)
        elif address in (0x644464,0x645a6c):
            assert d<=64
            base=0x44 if address==0x644464 else 0
            put32(u,a+base,self.allocate(d));put32(u,a+base+4,d);put32(u,a+base+8,self.allocate(d))
            return_from_stub(u)
        elif address in (0x7f0721,0x7efaba):
            self.consumed=get32(u,u.reg_read(UC_X86_REG_EBP)-(4 if address==0x7f0721 else 12))-DATA
        elif address in (0xa69d68,0x7da2f4):
            u.reg_write(UC_X86_REG_EAX,1);return_from_stub(u)
        elif address==0x7ef054:
            assert a&65535==1;return_from_stub(u)
        elif address in (0x7e27ec,0x702a58,0x40b15c,0x40b0e4):return_from_stub(u)
        else:super().hook(u,address,size,unused)


def native_builder(entry,a=0,d=0,c=0,*,subject='',body='',recipient=b'Bob',items=(),money=0,setup=None,
                   silver=None):
    u=emulator(silver);obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    strings={};heap=DATA+0x4000
    def string(raw):
        nonlocal heap
        pointer=heap+8;heap+=len(raw)+32;put32(u,pointer-4,len(raw));u.mem_write(pointer,raw+bytes(2));strings[pointer]=raw
        return pointer
    name=string(recipient);title=string(subject.encode('utf-16le'));text=string(body.encode('utf-16le'))
    array=DATA+0x8000;put32(u,array-4,len(items))
    for index,(identity,count) in enumerate(items):
        put32(u,array+index*656+0x28,identity);put32(u,array+index*656+0x1c,count)
    if entry==0x7ee8c4:
        d=name;c=title
        for offset,value in ((4,money),(8,array),(12,text)):put32(u,STACK+0x8000+offset,value)
    elif entry==0x7eeb8c:a=name
    elif entry==0x7ef628:
        package, compose = DATA+0x12000, DATA+0x13000
        put32(u,0xace780,compose);put32(u,compose+0x2c8,array)
        for index in range(len(items)):
            put32(u,array+index*656+8,3)
    if setup:setup(u,string)
    def append(uc,eax,raw):
        size=get32(uc,eax+0x1004);uc.mem_write(eax+4+size,raw);put32(uc,eax+0x1004,size+len(raw))
        put32(uc,DATA+0x400,eax);uc.reg_write(UC_X86_REG_EAX,DATA+0x400)
    def hook(uc,address,size,unused):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif entry==0x7ef628 and address==0x4092ac:
            uc.reg_write(UC_X86_REG_EAX,package);return_from_stub(uc)
        elif entry==0x7ef628 and address==0x6747dc:
            put32(uc,package+0xc,money);return_from_stub(uc)
        elif address in (0x674aac,0x67493c):
            raw=strings.get(edx,b'');append(uc,eax,raw+(b'\0' if address==0x674aac else bytes(2)));return_from_stub(uc)
        elif address in (0x40c05c,0x40b47c):put32(uc,eax,edx);return_from_stub(uc)
        elif address==0x40c0d8:
            length=bytes(uc.mem_read(edx,1))[0];put32(uc,eax,string(bytes(uc.mem_read(edx+1,length))));return_from_stub(uc)
        elif address in (flush,0x40b180,0x40b09c,0x40b0fc,0x40b15c,0x40d6c8,0x91759c,
                         0x40eca8,0x40ec90,0x40d748):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    for reg,value in ((UC_X86_REG_EAX,a),(UC_X86_REG_EDX,d),(UC_X86_REG_ECX,c)):u.reg_write(reg,value)
    u.emu_start(entry,STOP,count=30000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))


def verify_compose_credits(silver: bytes) -> None:
    from server.mail_service import COMPOSE_PRICE_ID, COMPOSE_SEND_KIND, CREDITS_ID

    item = mail.ClaimItem(517, 3, 24)
    for amount, items in ((0, ()), (0, (item,)), (200, ()), (200, (item,))):
        expected = ((mail.ClaimItem(CREDITS_ID, 1, amount),) if amount else ()) + items
        selection = tuple((entry.identity, entry.count) for entry in items)
        quote = mail.decode_body_request(native_builder(0x7ef628, money=amount, items=selection,
                                                        silver=silver))
        assert quote == mail.BodyRequest(1, COMPOSE_PRICE_ID, items=expected), quote
        request = mail.decode_draft(native_builder(0x7ee8c4, a=COMPOSE_SEND_KIND,
                                                   money=amount, items=selection, silver=silver))
        assert request == mail.DraftRequest(COMPOSE_SEND_KIND, b'Bob', items=tuple(
            (entry.identity, entry.count) for entry in expected)), request


def reader_roundtrip(packet,reader,writer):
    probe=MailReader(packet[2:]);probe.run(reader)
    assert get32(probe.u,0xacd0e8)-DATA==len(packet)-2
    probe.run(writer)
    rebuilt=bytes(probe.u.mem_read(DATA+0x10000,get32(probe.u,0xacd0f0)))
    assert rebuilt==packet,(hex(reader),rebuilt.hex(),packet.hex())
    return dict(reader=hex(reader),writer=hex(writer),consumed=len(packet)-2,bytes=len(packet))


def list_reader(packet,rows):
    probe=MailReader(packet[2:]);probe.run(0x7f05e0,a=DATA)
    assert probe.consumed==len(packet)-2
    pointer=get32(probe.u,0xace784)
    for index,row in enumerate(rows):
        base=pointer+index*20
        assert get32(probe.u,base)==row.identity
        assert probe.strings[get32(probe.u,base+4)].decode('utf-16le')==row.sender
        assert probe.strings[get32(probe.u,base+8)].decode('utf-16le')==row.subject
        assert get32(probe.u,base+12)==row.created
        assert struct.unpack('<H',probe.u.mem_read(base+16,2))[0]==row.lifetime_days
        assert bytes(probe.u.mem_read(base+18,2))==bytes((int(row.unread),row.kind))
    return dict(reader='0x7f05e0',consumed=probe.consumed,rows=len(rows))


def notification_reader(has_items):
    packet=mail.encode_notification('Отправитель','Тема',has_items)
    probe=MailReader(packet[2:]);probe.run(0x7ef998,a=DATA)
    assert probe.consumed==len(packet)-2
    assert bytes(probe.u.mem_read(0xac477b,1))==b'\1'
    assert sorted(raw.decode('utf-16le') for raw in probe.strings.values())==['Отправитель','Тема']
    return dict(reader='0x7ef998',consumed=probe.consumed,auto_page_query=1,unread_notification=True)


def mail_warehouse_drag(entry):
    """Original widget type17 chooses mail warehouse3 and actor-owned arrays."""
    u=emulator();context=DATA+0x1000;widget=DATA+0x2000;table=DATA+0x3000;actor=DATA+0x4000;array=DATA+0x5000
    put32(u,context+16,widget);put32(u,widget+0x278,17)
    put32(u,0xac64b4,DATA+0x6000);put32(u,0xac618c,table);put32(u,table,actor);put32(u,actor+0x28,1)
    put32(u,DATA+0x6100,widget)
    put32(u,0xb768e0+0x28,1001);put32(u,0xb768e0+0x1c,3)
    observed=[]
    def hook(uc,address,size,unused):
        if address==0x40d5a4:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),array);put32(uc,array-4,1);return_from_stub(uc)
        elif address==0x40d6c8:put32(uc,uc.reg_read(UC_X86_REG_EAX),0);return_from_stub(uc)
        elif address==0x40cc38:
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX),656)));return_from_stub(uc)
        elif address==0x992294:
            first=uc.reg_read(UC_X86_REG_ECX);second=get32(uc,uc.reg_read(UC_X86_REG_ESP)+4)
            observed.append(WarehouseTransfer(uc.reg_read(UC_X86_REG_EAX)&255,uc.reg_read(UC_X86_REG_EDX),
                () if not first else ((get32(uc,first+0x28),get32(uc,first+0x1c)),),
                () if not second else ((get32(uc,second+0x28),get32(uc,second+0x1c)),)))
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EDI,context);u.reg_write(UC_X86_REG_ESI,DATA+0x6100)
    u.emu_start(entry,STOP,count=1000)
    expected=WarehouseTransfer(3,1,((1001,3),) if entry==0xa66645 else (),((1001,3),) if entry==0xa667b2 else ())
    assert observed==[expected],observed
    # Execute the unchanged complete numeric6B writer separately with this exact call ABI.
    def setup(uc,string):
        put32(uc,0xac5940,DATA+0x9000);put32(uc,0xac55cc,DATA+0x9100)
        if expected.first_items:put32(uc,STACK+0x8004,0)
        else:put32(uc,STACK+0x8004,DATA+0x8000)
    # Both directions have one array. Managed refcount/reset is stubbed.
    packet=native_builder(0x992294,a=3,d=1,c=DATA+0x8000 if expected.first_items else 0,items=((1001,3),),setup=setup)
    assert packet==encode_warehouse_transfer(expected),(packet.hex(),encode_warehouse_transfer(expected).hex())
    return dict(ui_entry=hex(entry),widget_type=17,warehouse_type=3,packet_hex=packet.hex())


def run():
    cases=[]
    for kind in (0,1):
        request=mail.DraftRequest(kind,b'Bob','Тема','Проверка',( (17,3),(19,4)))
        packet=native_builder(0x7ee8c4,a=kind,subject=request.subject,body=request.body,items=request.items)
        assert packet==mail.encode_draft(request),(packet.hex(),mail.encode_draft(request).hex())
        cases.append(dict(builder='0x7ee8c4',kind=kind,packet_hex=packet.hex()))
    for entry,a,d,packet in ((0x7eead0,1,0,mail.encode_recalculate()),
        (0x7ef054,3,0,mail.encode_page(3)),
        (0x7ef08c,77,0,mail.encode_body_request(mail.BodyRequest(0,77))),
        (0x7ef0d4,77,0,mail.encode_body_request(mail.BodyRequest(2,77)))):
        result=native_builder(entry,a=a,d=d);assert result==packet,(hex(entry),result.hex(),packet.hex())
        cases.append(dict(builder=hex(entry),packet_hex=result.hex()))
    for calculate in (True,False):
        def setup_money(u,string):put32(u,0xac4784,string(b'Bob'));put32(u,0xac4788,10)
        packet=native_builder(0x7eeb8c,d=10,c=not calculate,setup=setup_money)
        assert packet==mail.encode_money(mail.MoneyRequest(b'Bob',10,calculate))
        cases.append(dict(builder='0x7eeb8c',calculate=calculate,packet_hex=packet.hex()))
    packet=native_builder(0x7eeb1c);assert packet==b'\xb7\x0b'
    cases.append(dict(builder='0x7eeb1c',packet_hex=packet.hex()))
    def setup_query(u,string):put32(u,0xac55cc,DATA+0x9000)
    packet=native_builder(0x9921a8,a=3,d=1,setup=setup_query);assert packet==b'\x69\x03'
    cases.append(dict(builder='0x9921a8',packet_hex=packet.hex()))
    request=mail.BodyRequest(1,0,'Тема','Письмо')
    def draft_setup(u,string):put32(u,0xac4794,string(request.subject.encode('utf-16le')));put32(u,0xac479c,string(request.body.encode('utf-16le')))
    packet=native_builder(0x7ef130,a=0,setup=draft_setup);assert packet==mail.encode_body_request(request)
    cases.append(dict(builder='0x7ef130',packet_hex=packet.hex()))
    request=mail.BodyRequest(1,77,'Тема','Письмо',0,(mail.ClaimItem(17,1,10),mail.ClaimItem(19,101,3,(20,30,40),2,b'Alice',123)))
    def claim_setup(u,string):
        put32(u,0xac4794,string(request.subject.encode('utf-16le')));put32(u,0xac479c,string(request.body.encode('utf-16le')))
        put32(u,0xac47a4,10);put32(u,0xacea74,DATA+0x9000);put32(u,DATA+0x9000+0x2c8,DATA+0x8000)
        for index,item in enumerate(request.items):
            base=DATA+0x8000+index*656
            put32(u,base+8,item.template)
            for offset,value in zip((0x48,0x4c,0x4a),item.durability):u.mem_write(base+offset,struct.pack('<H',value))
            u.mem_write(base+0x4e,bytes((item.enhance,)))
            if item.marker:
                put32(u,base,item.mark_time);u.mem_write(base+0x58,bytes((1,len(item.marker)))+item.marker)
    packet=native_builder(0x7ef1f4,a=77,items=((17,10),(19,3)),setup=claim_setup)
    assert packet==mail.encode_body_request(request),(packet.hex(),mail.encode_body_request(request).hex())
    cases.append(dict(builder='0x7ef1f4',semantics='take money with full package echo',packet_hex=packet.hex()))
    rows=(mail.MailSummary(77,'Отправитель','Проверка',1800000000,2,True,0),mail.MailSummary(78,'Bob','',1800000001,0,False,1))
    cases.append(list_reader(mail.encode_list(rows,pages=3,page=2),rows))
    for marked in (False,True):
        item=mail.PostItem(17,101,3,(20,30,40),2,1,True,False,'Маркер' if marked else None,123 if marked else 0)
        row=mail.MailBody(77,'Alice','Тема',1800000000,10,False,True,'Текст',100,(item,))
        cases.append(reader_roundtrip(mail.encode_body(row),0x643f50,0x644008))
        warehouse=(mail.PostWarehouseItem(77,'Alice','Тема',1800000000,item),)
        cases.append(reader_roundtrip(mail.encode_post_warehouse(warehouse),0x645840,0x64588c))
    cases.extend(mail_warehouse_drag(entry) for entry in (0xa66645,0xa667b2))
    cases.extend(notification_reader(has_items) for has_items in (False,True))
    return dict(dll_sha256=EXPECTED_SHA,scope=__doc__,cases=cases)


if __name__=='__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--compose':
        image_path, report_path = map(Path, sys.argv[2:])
        raw = image_path.read_bytes()
        report = json.loads(report_path.read_bytes())
        assert report['sha256'] == sha256(raw).hexdigest() and report['mailCredits']
        with pefile.PE(data=raw) as image:
            mapped = bytearray(image.get_memory_mapped_image())
        for patch in report['mailPatches']:
            start = patch['rva']
            payload = bytes.fromhex(patch['bytes'])
            mapped[start:start + len(payload)] = payload
        verify_compose_credits(bytes(mapped))
        print('Eight native mail compose packet cases passed')
        sys.exit(0)
    result=run();output=ROOT/'reports/stage7/mail-native.json'
    output.write_text(json.dumps(result,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=True,cases=len(result['cases']),output=str(output))))
