"""Execute the reviewed F8 extension and original SC filter/UI callbacks.

The entire custom packet bounds validator, model writes, original605df4 string
reader and original89a514 tab filtering execute. Delphi heap/managed-string
primitives, window collection/painting and transport handles are isolated,
explicit stubs. Numeric BD writers execute unchanged. This is native x86 model
and callback proof, not a rendered GUI or hosted acceptance test.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EFLAGS
from deploy import client_sc_auction as client
from tio.protocol import sc_auction_view as wire
from tio.protocol.item_list import encode_item_list
from tio.sc_auction import prize, policy

BASE_CLIENT = ROOT / 'reports/gameplay-completion/stage3-items/client/candidate/silver.dll'


def sample_lot(ident=1, *, state='active', name='Alice', enhanced=False):
    offer = dict(policy()['offers'][0], enhance=10 if enhanced else 0)
    lot = dict(id=ident, currency='credits', item_packet=encode_item_list(1,(prize(offer),)),
        state=state, start_price=100, price=101, fee=5, step=1, started=1791446400,
        ends=1791446700, duration=300, extension=10, automatic=1)
    return wire.lot_view(lot, bidder_name=name, notes='SC '+str(ident), personal=name=='Alice',now=1791446410)


class NativeScene:
    def __init__(self, *, base=0x400000, candidate=None):
        data=client.patch(BASE_CLIENT.read_bytes()) if candidate is None else candidate
        pe=pefile.PE(data=data)
        if base != 0x400000: pe.relocate_image(base)
        image=pe.get_memory_mapped_image()
        self.base=base; self.delta=base-0x400000
        self.u=Uc(UC_ARCH_X86,UC_MODE_32); self.u.mem_map(0,0x1000)
        self.u.mem_map(base,(len(image)+4095)&~4095); self.u.mem_write(base,image)
        self.u.mem_map(DATA,0x800000); self.u.mem_map(STACK,0x10000)
        self.next=DATA+0x10000; self.calls=[]; self.stubs=set(); self.arrays={}; self.windows=[]
        self.u.hook_add(UC_HOOK_CODE,self.hook)
        # Real original widget fields used by filtering and history scroll calculations.
        for address in (0xacf424,0xacf428,0xacf42c,0xacf430,0xacf434,0xac4910,0xac4914,
                        0xacf740,0xacf744,0xacf748):
            obj=self.allocate(0x400); self.set(address,obj)
            if address in (0xac4910,0xac4914):
                put32(self.u,obj+0x280,self.allocate(0x400)); put32(self.u,obj+0x288,16)
        self.u.mem_write(self.get(0xacf424)+0x280,b'\1')
        own=self.allocate(0x200); self.set(0xac5b7c,own)
        self.u.mem_write(own+0x24,b'\5Alice')
        clock=self.allocate(4); self.set(0xac5fe4,clock); put32(self.u,clock,123456)
        self.transport=self.allocate(0x2000); self.handle=self.allocate(4)
        put32(self.u,self.handle,self.transport); vmt=self.allocate(4); put32(self.u,self.transport,vmt)
        self.flush=DATA+0x700000; put32(self.u,vmt,self.flush); self.set(0xac600c,self.handle)

    def allocate(self,n):
        address=self.next; self.next=(address+n+15)&~15
        if self.next>=DATA+0x600000: raise AssertionError('Native test heap exhausted')
        self.u.mem_write(address,bytes(n)); return address

    def set(self,address,value): put32(self.u,address+self.delta,value)
    def get(self,address): return get32(self.u,address+self.delta)

    def string(self,value):
        if not value:return 0
        data=value.encode('utf-16le'); head=self.allocate(12+len(data)+2)
        self.u.mem_write(head,struct.pack('<HHii',1200,2,1,len(value))+data+b'\0\0'); return head+12

    def text(self,pointer):
        if not pointer:return ''
        n=get32(self.u,pointer-4)
        return bytes(self.u.mem_read(pointer,n*2)).decode('utf-16le')

    def ret(self,pop=0):
        sp=self.u.reg_read(UC_X86_REG_ESP); self.u.reg_write(UC_X86_REG_EIP,get32(self.u,sp))
        self.u.reg_write(UC_X86_REG_ESP,sp+4+pop)

    def hook(self,u,address,size,user):
        at=address-self.delta; a=u.reg_read(UC_X86_REG_EAX); d=u.reg_read(UC_X86_REG_EDX)
        c=u.reg_read(UC_X86_REG_ECX); sp=u.reg_read(UC_X86_REG_ESP)
        if address==STOP: u.emu_stop(); return
        if at in (client.READER_ENTRY,0x89a514,0x89a88c,0x605df4,0x89b2d8,
                  0x891444,0x891458,0x899a94,0x89430c,0x894410): self.calls.append(hex(at))
        if at==0x40d5a4:
            count=get32(u,sp+4); types={self.get(0x88c7a8):88,self.get(0x88c7d4):24,self.get(0x88c474):12}
            width=types[d]; old=get32(u,a); prev=get32(u,old-4) if old else 0
            ptr=self.allocate(8+count*width)+8; put32(u,ptr-8,1);put32(u,ptr-4,count)
            if old and prev: u.mem_write(ptr,bytes(u.mem_read(old,min(prev,count)*width)))
            put32(u,a,ptr if count else 0);self.arrays[ptr]=(count,width); self.ret()
        elif at==0x40d6c8: put32(u,a,0); self.ret()
        elif at==0x40cc38: u.mem_write(a,bytes(u.mem_read(d,88))); self.ret()
        elif at in (0x40b47c,0x40b4c4,0x40b4f0,0x40c05c,0x40c048): put32(u,a,d); self.ret()
        elif at==0x40c0d8:
            n=bytes(u.mem_read(d,1))[0];put32(u,a,self.string(bytes(u.mem_read(d+1,n)).decode('cp1251')));self.ret()
        elif at==0x40bf90: put32(u,a,self.string(chr(d)));self.ret()
        elif at==0x40c164: put32(u,a,self.string(self.text(get32(u,a))+self.text(d)));self.ret()
        elif at==0x40c354:
            first,second=self.text(a),self.text(d); flags=u.reg_read(UC_X86_REG_EFLAGS)&~0x41
            u.reg_write(UC_X86_REG_EFLAGS,flags|(0x40 if first==second else 1 if first<second else 0));self.ret()
        elif at==0x40b09c:put32(u,a,0);self.ret()
        elif at in (0x40b180,0x40b0fc,0x40b0e4):self.ret()
        elif at==0x4244b4:put32(u,d,self.string(str(a)));self.ret()
        elif at==0x424724:u.reg_write(UC_X86_REG_EAX,int(self.text(a)));self.ret()
        elif at==0xa46b10:
            # Original setter executes its managed assignment; paint/event callbacks isolated.
            pass
        elif at in (0xa45c0c,0xa54980):self.ret()
        elif at==0x675578:u.reg_write(UC_X86_REG_EAX,16);self.ret(4)
        elif at==0x6675e0:put32(u,d,self.string('Get lot'));self.ret()
        elif at==0x675528:u.reg_write(UC_X86_REG_EAX,70);self.ret()
        elif at in (0xa417d0,0xa416c8):self.ret(4)
        elif at in (0xa69cd0,0xa6a114):
            self.windows.append((hex(at),self.text(a)));self.ret()
        elif at==0x6748b0:u.reg_write(UC_X86_REG_EAX,self.handle);self.ret()
        elif address==self.flush:self.ret()
        else:return
        if at != 0xa46b10:self.stubs.add(hex(at))

    def run(self,entry,*,eax=0,edx=0,ecx=0,stack=(),count=500000):
        sp=STACK+0x8000;put32(self.u,sp,STOP)
        for i,value in enumerate(stack,1):put32(self.u,sp+i*4,value)
        self.u.reg_write(UC_X86_REG_ESP,sp);self.u.reg_write(UC_X86_REG_EAX,eax)
        self.u.reg_write(UC_X86_REG_EDX,edx);self.u.reg_write(UC_X86_REG_ECX,ecx)
        try:self.u.emu_start(entry+self.delta,STOP,count=count)
        except Exception as error:raise AssertionError(f'Native execution failed at {self.u.reg_read(UC_X86_REG_EIP):x}; calls {self.calls[-10:]}') from error
        assert self.u.reg_read(UC_X86_REG_EIP)==STOP,hex(self.u.reg_read(UC_X86_REG_EIP))

    def receive(self,packet):
        packet=bytes(packet)
        self.u.mem_write(DATA,packet[1:]); before=self.next
        self.run(client.READER_ENTRY,eax=packet[0],edx=DATA,ecx=len(packet))
        assert self.u.reg_read(UC_X86_REG_EAX)==1
        return self.next-before

    def dispatch(self,packet):
        self.u.mem_write(DATA,packet);self.set(0xac5834,DATA+0x8000)
        self.run(0x9f5548,stack=(packet[0],DATA,len(packet),0))
        assert self.u.reg_read(UC_X86_REG_EAX)==1

    def rows(self,address,width):
        ptr=self.get(address);n=get32(self.u,ptr-4) if ptr else 0
        return tuple(bytes(self.u.mem_read(ptr+i*width,width)) for i in range(n))

    def tab(self,index):
        for j,address in enumerate((0xacf424,0xacf428,0xacf42c,0xacf430)):
            self.u.mem_write(self.get(address)+0x280,bytes((int(index==j),)))
        self.run(0x89a514,eax=self.get(0xac4910))
        return tuple(struct.unpack_from('<I',raw)[0] for raw in self.rows(0xacf41c,88))

    def request(self,entry):
        put32(self.u,self.transport+0x1004,0);self.run(entry)
        return bytes(self.u.mem_read(self.transport+4,get32(self.u,self.transport+0x1004)))

    def click(self,*,bot=False):
        """Original ordinary GUI hit test and builder, no click/rectangle stub.

        Tooltip89739c m739(Place bid) rectangle x19d-54 corresponds to
        click899e3b ->BD06. Tooltip8974ad m796(Autobid) rectangle x19d-7e
        corresponds to click899e9b ->BD14/0. Not the admin delete callback.
        """
        frame=STACK+0x7000;x=0x19d-(0x7e if bot else 0x54)+21
        for offset,value in ((-8,x),(-0xc,0),(-0x14,0),(8,46)):put32(self.u,frame+offset,value)
        self.u.reg_write(UC_X86_REG_EBP,frame);self.u.reg_write(UC_X86_REG_EDI,self.get(0xac4910))
        self.u.reg_write(UC_X86_REG_ESI,0);self.u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
        put32(self.u,self.transport+0x1004,0)
        self.u.emu_start((0x899e9b if bot else 0x899e3b)+self.delta,
                        (0x899f09 if bot else 0x899e9b)+self.delta,count=10000)
        return bytes(self.u.mem_read(self.transport+4,get32(self.u,self.transport+0x1004)))

    def click_claim(self,index=0):
        # Entire original closed/own/unbought gate, text width, rectangle hit
        # test and BD07 builder; localization/font width are explicit stubs.
        frame=STACK+0x7000
        for offset,value in ((-8,0x29e),(-0xc,0),(-0x14,0),(8,62)):put32(self.u,frame+offset,value)
        self.u.reg_write(UC_X86_REG_EBP,frame);self.u.reg_write(UC_X86_REG_EDI,self.get(0xac4910))
        self.u.reg_write(UC_X86_REG_ESI,index);self.u.reg_write(UC_X86_REG_EAX,index*11)
        self.u.reg_write(UC_X86_REG_EDX,self.get(0xacf41c));self.u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
        put32(self.u,self.transport+0x1004,0)
        self.u.emu_start(0x899cfc+self.delta,0x899dcd+self.delta,count=10000)
        return bytes(self.u.mem_read(self.transport+4,get32(self.u,self.transport+0x1004)))

    def remaining(self,index=0):
        # Execute the original renderer's entire 64-bit countdown and clamp.
        frame=STACK+0x7000;self.u.reg_write(UC_X86_REG_EBP,frame)
        self.u.reg_write(UC_X86_REG_EBX,index);self.u.reg_write(UC_X86_REG_ESP,STACK+0x6000)
        self.u.emu_start(0x896b42+self.delta,0x896c1f+self.delta,count=1000)
        return get32(self.u,frame-0x2d0)


def main():
    original=BASE_CLIENT.read_bytes();updated=client.patch(original);plan=client.patch_plan(original,updated)
    language=Path(r'C:\Program Files (x86)\TIOnline\base\russian.lng')
    labels=dict(line.split('=',1) for line in language.read_text(encoding='cp1251').splitlines() if line.startswith(('m727=','m739=','m796=')))
    assert labels['m739']=='Сделать ставку' and labels['m796']=='Автоставка'
    assert 'удалить лот' in labels['m727']
    findings=[]
    for base in (0x400000,0x500000):
        scene=NativeScene(base=base,candidate=updated)
        views=(sample_lot(1),sample_lot(2,enhanced=True),sample_lot(3,state='won'),sample_lot(4,state='won',name='Bob'))
        packet=wire.encode_catalogue(views);scene.dispatch(packet)
        rows=scene.rows(0xacf418,88);assert len(rows)==4
        tabs=[scene.tab(i) for i in range(4)];assert tabs==[(1,),(2,),(3,4),(3,)],tabs
        scene.tab(0);assert scene.remaining()==290000
        put32(scene.u,scene.get(0xac5fe4),124456);assert scene.remaining()==289000
        assert scene.click().hex()=='bd0601000000'
        assert scene.click(bot=True).hex()=='bd140001000000'
        scene.tab(2);assert scene.click_claim(0).hex()=='bd0703000000'
        assert scene.click_claim(1)==b''  # Another character's won lot.
        scene.tab(0)
        row=rows[0];assert scene.text(struct.unpack_from('<I',row,56)[0])=='Alice'
        prizes=struct.unpack_from('<I',row,80)[0];assert get32(scene.u,prizes)==9 and get32(scene.u,prizes+4)==5
        history=wire.encode_history(3,(dict(date=wire.datetime_days(1791446500),action=4,name='Алиса',amount=5,automatic=True,currency=0),),page=2,pages=3,remaining_ms=10000)
        scene.receive(history);assert len(scene.rows(0xacf420,24))==1
        assert scene.get(0xac491c)==3 and scene.get(0xac4928)==2 and scene.get(0xac492c)==3
        assert scene.get(0xac4924)==134456
        scene.receive(wire.encode_bot(1,5,100,200,7))
        assert tuple(scene.text(get32(scene.u,scene.get(a)+0x58)) for a in (0xacf740,0xacf748,0xacf744))==('100','200','7')
        # Original GUI callback pushes N then TO; builder writes FROM,N,TO.
        assert scene.request(0x89430c).hex()=='bd1401010000006400000007000000c8000000'
        assert scene.request(0x894410).hex()=='bd140201000000'
        # Negative control: BD05/3 is administrator delete-lot confirmation,
        # m727("Do you want to delete lot?") gated by ac490c and paused auction.
        scene.set(0xac4918,1);assert scene.request(0x899a94).hex()=='bd05030100000000'
        from tio.protocol.sc_auction import decode as request_decoder
        try:request_decoder(scene.request(0x899a94))
        except ValueError:pass
        else:raise AssertionError('Administrative SC delete admitted as ordinary gameplay')
        scene.receive(wire.encode_claim(3,101,0,1792051300,can_pay=True))
        assert scene.get(0xacf444)==3 and scene.get(0xacf44c)==101
        assert scene.request(0x891444).hex()=='bd090300000001'
        assert scene.request(0x891458).hex()=='bd090300000000'
        # Full replacement, malformed snapshots preserve last complete models;
        # clear on reconnect drops both models and original selection globals.
        scene.receive(wire.encode_catalogue((views[0],)));assert len(scene.rows(0xacf418,88))==1
        saved=scene.get(0xacf418)
        malformed=(packet[:-1],packet+b'\0',b'\xf8\2\0',b'\xf8\1\1\xc9\0')
        for bad in malformed:assert scene.receive(bad)==0 and scene.get(0xacf418)==saved
        scene.receive(wire.encode_clear());assert all(scene.get(a)==0 for a in (0xacf418,0xacf41c,0xacf420,0xac491c,0xacf444))
        findings.append(dict(image_base=hex(base),tabs=tabs,catalogue_rows=4,history_name='Алиса',
            native_callbacks=['bid BD06','open bot BD14/0','own won lot BD07','bot BD14/1 FROM,N,TO','delete bot BD14/2','claim BD09/1','defer BD09/0'],
            original_hit_tests=True,foreign_won_lot_claim_rejected=True,
            admin_BD05_3_rejected=True,
            malformed_rejected=len(malformed),clear_reconnect=True,exported_PacketHandler_dispatch=True,
            original_countdown_ms=[290000,289000],original_calls=sorted(set(scene.calls)),
            isolated_helpers=sorted(scene.stubs),window_calls=scene.windows))
    report=dict(status='PASS',method=__doc__,base_sha256=client.BASE_SHA,patch_plan=plan,
                original_button_labels=labels,language_sha256=hashlib.sha256(language.read_bytes()).hexdigest(),
                proof=findings,limitations='No installed-file modification, renderer pixels, graphical game client or hosted acceptance. Clock/date UTC projection requires server-authoritative dates and native global clock; authoritative money/expiry stays backend.')
    (ROOT/'evidence/sc_view_native.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('F8 native SC models/filter/bid/bot/claim callbacks, base and ASLR, malformed/clear/reconnect: PASS')


if __name__=='__main__':main()
