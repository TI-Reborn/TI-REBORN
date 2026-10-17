"""Execute original rental dispatcher, numeric consumer and request writers in Unicorn."""
from verify_auth_native import *
from tio.protocol.rental import RentalOffer, encode_rental_catalog, decode_rental_request


def catalog_case(offers):
    packet = encode_rental_catalog(offers)
    u = emulator()
    wire=DATA+0x8000
    u.mem_write(wire, packet)
    window, listing, item = DATA+0x1100, DATA+0x1500, DATA+0x2000
    put32(u, 0xac563c, DATA+0x1000); put32(u, DATA+0x1000, window)
    put32(u, window+0x29c, listing); u.mem_write(window+0x2a0, b'\1')
    put32(u, 0xac637c, DATA+0x1800); put32(u, DATA+0x1800, DATA+0x4000)
    put32(u, 0xac5fe4, DATA+0x1900); put32(u, DATA+0x1900, 123000)
    captured=[]
    def hook(uc, addr, size, user):
        if addr == 0x40ce98:
            uc.reg_write(UC_X86_REG_EAX, item); return_from_stub(uc)
        elif addr == 0xa7b030:
            uc.reg_write(UC_X86_REG_EAX, 0); return_from_stub(uc)
        elif addr == 0x8e9fe4:
            captured.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX), 0x2a0)))
            return_from_stub(uc)
        elif addr == 0x8ebdca:
            assert get32(uc, uc.reg_read(UC_X86_REG_EBP)-4) == wire+len(packet)
        elif addr in (0x8e867c, 0x8e6690, 0x8e5564, 0x8e99ac):
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, 0xb4); u.reg_write(UC_X86_REG_EDX, wire+1)
    u.emu_start(0x8ebebc, STOP, count=1000000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP and len(captured)==len(offers)
    assert bytes(u.mem_read(window+0x2a0, 1)) == b'\0'
    for raw, o in zip(captured, offers):
        for offset, value in ((0x290,o.lot_id),(8,o.item_id),(0x38,o.credits),(0x3c,o.gold)):
            assert struct.unpack_from('<I',raw,offset)[0] == value
        assert raw[0x4e]==o.enhancement and raw[0x58]==255
        assert struct.unpack_from('<H',raw,0x29c)[0] == o.hours
    return {'offers':len(offers),'consumed':len(packet),'loading_cleared':True}


def request_case(currency=2):
    u=emulator(); obj=DATA+0x2000; pointer=DATA+0x1000; vtable=DATA+0x1100
    put32(u,0xac600c,pointer); put32(u,pointer,obj); put32(u,obj,vtable); put32(u,vtable,STOP-16)
    result=[]
    def hook(uc,addr,size,user):
        if addr==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,pointer); return_from_stub(uc)
        elif addr==STOP-16:
            result.append(bytes(uc.mem_read(obj+4,get32(uc,obj+0x1004))))
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    put32(u,STACK+0x8004,24)
    u.reg_write(UC_X86_REG_EAX,331420); u.reg_write(UC_X86_REG_EDX,7); u.reg_write(UC_X86_REG_ECX,currency)
    u.emu_start(0x8eb4b0,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert decode_rental_request(result[0])==(16,(331420,24,7,currency))
    return result[0].hex()


def timer_case():
    # Real ItemList decoder/getters, then the same TItem timer setter used by990a26.
    from tio.protocol.item_list import ItemRecord, encode_item_list
    item=ItemRecord(1234,314,bytes(2),1,0,0,(950,)*3,b'\x0a\0\0\1',10800,b'\x0a\0\0')
    body=encode_item_list(7,(item,))[10:]
    u=emulator(); u.mem_write(DATA,body); put32(u,0xacd0e8,DATA)
    obj=DATA+0x2000
    def hook(uc,addr,size,user):
        if addr==0x40b09c:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def run(entry,eax,edx=0):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000); put32(u,STACK+0x8000,STOP)
        u.reg_write(UC_X86_REG_EAX,eax); u.reg_write(UC_X86_REG_EDX,edx)
        u.emu_start(entry,STOP,count=5000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        return u.reg_read(UC_X86_REG_EAX)
    run(0x63bd38,obj)
    assert get32(u,0xacd0e8)==DATA+len(body)
    assert run(0x63ca78,obj)&255==1  # rented
    assert run(0x63cbb4,obj)&255==1  # time present
    seconds=run(0x63cb60,obj)
    assert seconds==10800
    put32(u,0xac5fe4,DATA+0x1800); put32(u,DATA+0x1800,123456000)
    run(0xa7be60,DATA+0x3000,seconds)
    assert get32(u,DATA+0x3000)==10800 and get32(u,DATA+0x325c)==123456
    return {'seconds_left':seconds,'receipt_tick_seconds':123456,'rented':True}


def category_cases(identities):
    """Original category predicates, with metadata supplied from delivered XML."""
    import xml.etree.ElementTree as ET
    from unicorn.x86_const import UC_X86_REG_EBX,UC_X86_REG_ESI
    items={int(n.get('id')):{v.get('key'):v.get('val') for v in n.findall('value')}
           for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()}
    kinds={'Melee':2,'Light':3,'Automatic':4,'Distance':5,'Heavy':6,'Throwing':7}
    names={4:'armor',5:'head',6:'body',7:'legs',8:'weapons',9:'melee',10:'light',11:'automatic',12:'distance',13:'heavy'}
    u=emulator();frame=STACK+0x7000;meta=frame-0x3a78
    buckets={name:[] for name in names.values()}
    for identity in identities:
        values=items[identity]
        u.mem_write(meta,bytes(0x3a78))
        u.mem_write(meta+0x120,struct.pack('<H',kinds.get(values.get('weaponType'),1)))
        u.mem_write(meta+0x12d,bytes([{'head':3,'chest':1,'legs':5,'complexarmor':9}.get(values.get('bodypart'),0)]))
        put32(u,meta+0x690,int(values.get('p_def',0)))
        for category,name in names.items():
            u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EBX,category)
            u.reg_write(UC_X86_REG_ESI,DATA+0x2000)
            u.emu_start(0x8e2f2a,0x8e31ca,count=100)
            assert u.reg_read(UC_X86_REG_EIP)==0x8e31ca
            if bytes(u.mem_read(frame-0x3a79,1))==b'\1':buckets[name].append(identity)
    assert all(buckets.values()),buckets
    assert 304 in buckets['automatic'] and 301 in buckets['light'] and 312 in buckets['distance']
    return buckets


def main():
    from tio.rental import RentalStore
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        store=RentalStore(Path(folder)/'rental.sqlite3')
        result={'catalog':[catalog_case(()),catalog_case(tuple(store.offers.values()))],
                'purchases':[request_case(1),request_case(2)],'inventory_timer':timer_case(),
                'category_predicates':category_cases(sorted({o.item_id for o in store.offers.values()}))}
    (ROOT/'evidence/rental_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,results=result),indent=2)+'\n')
    print('Original rental x86: empty/full catalogs and both purchase currencies PASS')


if __name__=='__main__':main()
