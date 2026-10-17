"""Offline x86 execution of the selected font adapter and original TI renderer.

Real TI font lookup, glyph quad, UV normalization, rotation, text measurement,
vertex construction and memory copy run unchanged. Only operating-system file/
protection/cache-flush APIs and the texture file decoder are explicit external
stubs. No game, renderer, network connection or hosted account is opened.
"""
from __future__ import annotations
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_ui_hd_fonts as hd

SOURCE=ROOT/'reports/ui-modernization/graphical/source'/hd.BASE_SHA/'silver.dll'
TI=ROOT/'reports/ui-modernization/baseline/ti.exe'
DATA=0x30000000; STACK=0x33000000; API=0x34000000; END=API+0xf00
FRAME=STACK+0xc000
REGS=(UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_ECX,UC_X86_REG_EDX,
      UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP)
VALUES=(0x11111111,0x22222222,0x33333333,0x44444444,0x55555555,0x66666666,FRAME)

def put(u,a,v):u.mem_write(a,struct.pack('<I',v&0xffffffff))
def get(u,a):return struct.unpack('<I',u.mem_read(a,4))[0]
def floats(u,a,n):return struct.unpack('<'+'f'*n,u.mem_read(a,n*4))
def signed(v):return v if v<0x80000000 else v-0x100000000
@lru_cache(maxsize=3)
def mapped(data,base):
    p=pefile.PE(data=data);p.relocate_image(base)
    return p.get_memory_mapped_image()

class Fixture:
    def __init__(self,data,base,*,load_failure=None,protect_failure=0,flush_failure=0):
        self.base=base;self.u=Uc(UC_ARCH_X86,UC_MODE_32);u=self.u
        self.load_failure=load_failure;self.protect_failure=protect_failure;self.flush_failure=flush_failure
        self.protect=[];self.flush=[];self.loads=[];self.quads=[];self.native_quads=True;self.skip_d3d_flush=False
        self.string_next=DATA+0x1800000;self.cache_keys=[];self.loader_executed=set()
        self.u.mem_map(base,0x846000);u.mem_write(base,mapped(data,base))
        tiraw=TI.read_bytes();assert hd.sha(tiraw)==hd.TI_SHA
        image=mapped(tiraw,0x400000);u.mem_map(0x400000,(len(image)+0xfff)&~0xfff);u.mem_write(0x400000,image)
        u.mem_map(DATA,0x2000000);u.mem_map(STACK,0x10000);u.mem_map(API,0x1000)
        for stub in (0x10,0x20,0x30,0x40,0x50,0x60,0xf00):u.mem_write(API+stub,b'\xc3')
        u.mem_map(0,0x1000);put(u,0,0xffffffff)
        self.renderer=DATA+0x1000;self.batch=DATA+0x2000;self.vb=DATA+0x3000;self.vertices=DATA+0x4000
        self.manager=DATA+0x8000;array=DATA+0x9004;put(u,array-4,hd.FONT_COUNT);put(u,self.manager+4,array)
        self.fonts=[];self.oldtextures=[];self.textures={}
        self.manifest=hd.assets_manifest()
        for index,font in enumerate(self.manifest['fonts']):
            obj=DATA+0x100000+index*0x1d0000;self.fonts.append(obj);put(u,array+index*4,obj)
            kerning=DATA+0x60000+index*0x11000;listobj=DATA+0xd000+index*0x20
            put(u,obj+0x108,kerning);put(u,kerning+0x10004,listobj)
            # Populate actual native character records from the immutable XML.
            import xml.etree.ElementTree as ET
            xml=ROOT/'reports/ui-hd-assets/font-atlases/baseline-original'/f"{font['font']}.xml"
            tree=ET.parse(xml).getroot()
            put(u,obj+0x1c0324,int(tree.get('width')));put(u,obj+0x1c0328,int(tree.get('height')))
            u.mem_write(obj+0x1c032c,bytes((1,5,2)))
            for element in tree:
                if element.tag!='item':continue
                cp=int(element.get('ucode',element.get('ascii')));record=obj+0x10c+cp*28
                fields=[int(element.get(k)) for k in ('top','x','y','width','height','leading','trailing')]
                u.mem_write(record,struct.pack('<7i',*fields))
            tex=DATA+0x20000+index*0x100;self.oldtextures.append(tex)
            self.texture(tex,512,512);put(u,obj+0x1c010c,tex)
            global_va=hd.FONT_GLOBALS[index]
            if global_va:
                slot=DATA+0xa000+index*4;put(u,global_va,slot);put(u,slot,index)
            else:put(u,self.va(0xc17bf0),index)
            for density,atlas in enumerate(font['density_sets']):
                address=DATA+0x30000+(index*4+density)*0x100
                self.texture(address,atlas['width'],atlas['height'])
                self.textures[atlas['path'].replace('/','\\')]=address
        for global_va,obj in ((0x76de0c,self.renderer),(0x76df70,self.batch),(0x76e180,self.manager)):
            slot=DATA+0xb000+(global_va&0xff)*4;put(u,global_va,slot);put(u,slot,obj)
        group=DATA+0xc000;put(u,0x76e360,group);put(u,group,0x5a5a)
        put(u,self.renderer+0x299,3840);put(u,self.renderer+0x29d,2160)
        put(u,self.batch+4,self.renderer);put(u,self.batch+8,self.vb);put(u,self.vb+0x30,self.vertices)
        put(u,self.vb+0x18,0x104);put(u,self.vb+0x1c,28)
        self.scope(150)
        self.core(0x28,1)
        u.mem_write(0x6508be,b'\xe8'+struct.pack('<i',self.va(hd.CORE_UPLOAD)-0x6508c3))
        for iat,stub in ((0x77a090,0x10),(0x77a178,0x20),(0x77a170,0x30),(0x77a1b0,0x50),(0x77a190,0x60)):
            put(u,base+iat,API+stub)
        u.reg_write(UC_X86_REG_FPCW,0x37f)
        u.hook_add(UC_HOOK_CODE,self.hook)

    def va(self,a):return self.base+a-hd.BASE
    def st(self,off):return get(self.u,self.base+hd.STATE+off)
    def core(self,off,v):put(self.u,self.base+hd.CORE_STATE+off,v)
    def scope(self,percent=150,active=1,physical=(2560,1440)):
        self.core(0,percent);self.core(4,physical[0]);self.core(8,physical[1]);self.core(0x14,active)
        lw=physical[0]*100//percent;lh=physical[1]*100//percent
        self.core(0xc,lw);self.core(0x10,lh)
        self.u.mem_write(self.base+hd.CORE_STATE+0x1c,struct.pack('<2f',physical[0]/lw,physical[1]/lh))
    def texture(self,a,w,h):
        put(self.u,a+0xc,0x5abc0000+a%0x10000);put(self.u,a+0x14,w);put(self.u,a+0x18,h)
        self.u.mem_write(a+0x60,b'\0')  # Native managed PNG; one means render target.
    def ret(self,clean=0,result=None):
        u=self.u;s=u.reg_read(UC_X86_REG_ESP);r=get(u,s)
        if result is not None:u.reg_write(UC_X86_REG_EAX,result&0xffffffff)
        u.reg_write(UC_X86_REG_ESP,s+4+clean);u.reg_write(UC_X86_REG_EIP,r)
    def string(self,address,wide=True):
        result=[];size=2 if wide else 1
        for _ in range(200):
            raw=self.u.mem_read(address,size)
            if raw==b'\0'*size:break
            result.append(raw);address+=size
        return b''.join(result).decode('utf-16le' if wide else 'ascii')
    def unicode(self,text):
        p=self.string_next;self.string_next+=(len(text)*2+45)&~31
        self.u.mem_write(p,struct.pack('<HHiI',1200,2,-1,len(text))+text.encode('utf-16le')+b'\0\0')
        return p+12
    def utext(self,p):
        length=get(self.u,p-4);assert length<=256
        return bytes(self.u.mem_read(p,length*2)).decode('utf-16le')
    def hook(self,u,a,size,_):
        s=u.reg_read(UC_X86_REG_ESP)
        if a in (0x7404fc,0x7492cc,0x424d7c,0x42f698,0x42f7e4):self.loader_executed.add(hex(a))
        if a==END:u.emu_stop();return
        if a==API+0x10:
            page,count,new,out=(get(u,s+i) for i in (4,8,12,16));self.protect.append((page,count,new))
            assert page in (0x6fc000,0x650000) and count==4096
            failure=len(self.protect)==self.protect_failure
            if not failure:put(u,out,0x20)
            self.ret(16,int(not failure));return
        if a==API+0x20:
            assert self.string(get(u,s+4))=='kernel32.dll';self.ret(4,0x12345);return
        if a==API+0x30:
            assert get(u,s+4)==0x12345 and self.string(get(u,s+8),False)=='FlushInstructionCache'
            self.ret(8,API+0x40);return
        if a==API+0x40:
            process,page,count=(get(u,s+i) for i in (4,8,12));self.flush.append((process,page,count))
            assert process==0xffffffff and page in (0x6fc000,0x650000) and count==4096
            self.ret(12,int(len(self.flush)!=self.flush_failure));return
        if a==API+0x50:self.ret(0,0xffffffff);return
        if a==API+0x60:
            name=self.string(get(u,s+4));assert name in self.textures
            self.ret(4,0xffffffff if self.load_failure=='files' else 0x20);return
        if a==0x7404fc:
            nameptr=u.reg_read(UC_X86_REG_EAX);name=self.string(nameptr);assert name in self.textures
            assert get(u,nameptr-4)==len(name)  # Texture filename UnicodeString; text WideString is separate.
            assert u.reg_read(UC_X86_REG_EDX)==0 and u.reg_read(UC_X86_REG_ECX)==0
            assert [get(u,s+i) for i in (4,8,12)]==[0x5a5a,0,0]
            self.loads.append(name)
            return  # Execute the actual native loader and filename scanner.
        if a==0x40c16c:
            text=self.utext(u.reg_read(UC_X86_REG_EAX));start=u.reg_read(UC_X86_REG_EDX)-1;count=u.reg_read(UC_X86_REG_ECX)
            put(u,get(u,s+4),self.unicode(text[start:start+count]));self.ret(4);return
        if a==0x6b11f4:
            name=self.utext(u.reg_read(UC_X86_REG_EAX));key=self.utext(u.reg_read(UC_X86_REG_EDX))
            assert name in self.textures and key==name.rsplit('\\',1)[-1].rsplit('.',1)[0]
            self.cache_keys.append(key);texture=self.textures[name]
            if self.load_failure=='null':texture=0
            elif self.load_failure=='render-target':u.mem_write(texture+0x60,b'\x01')
            elif self.load_failure=='dimensions':put(u,texture+0x14,7)
            self.ret(0,texture);return
        if a==0x663834 and self.skip_d3d_flush:
            # Only the terminal GPU submission is external. Native text
            # traversal and its actual detoured callsite still execute.
            self.ret();return
        if a==hd.FONT_QUAD:
            row=(u.reg_read(UC_X86_REG_EAX),u.reg_read(UC_X86_REG_EDX),u.reg_read(UC_X86_REG_ECX),
                 *[get(u,s+i) for i in range(4,36,4)])
            self.quads.append(row)
            # Fixture models an already active native batch, avoiding a real
            # D3D flush. UV/position/rotation construction below runs natively.
            put(u,self.batch+0x10,row[0]);put(u,self.batch+0x14,0)
            if not self.native_quads:self.ret(32)

    def run(self,a,*,eax=None,edx=None,ecx=None,args=(),font=None,cp=65):
        u=self.u
        for reg,value in zip(REGS,VALUES):u.reg_write(reg,value)
        if font is not None:put(u,FRAME-4,font)
        put(u,FRAME-0x18,cp)
        for reg,value in ((UC_X86_REG_EAX,eax),(UC_X86_REG_EDX,edx),(UC_X86_REG_ECX,ecx)):
            if value is not None:u.reg_write(reg,value)
        start=STACK+0x8000;u.reg_write(UC_X86_REG_ESP,start);u.reg_write(UC_X86_REG_EFLAGS,0x202)
        u.mem_write(start,struct.pack('<'+'I'*(len(args)+1),END,*[v&0xffffffff for v in args]))
        try:u.emu_start(a,END+1,count=2500000)
        except Exception as e:raise AssertionError(f'x86 failed at {u.reg_read(UC_X86_REG_EIP):08x}, entry {a:08x}: {e}') from e
        assert u.reg_read(UC_X86_REG_EIP)==END
        assert u.reg_read(UC_X86_REG_ESP)==start+4+len(args)*4,(hex(a),hex(u.reg_read(UC_X86_REG_ESP)),args)
        assert [u.reg_read(r) for r in (UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP)]==[VALUES[i] for i in (1,4,5,6)]
        return tuple(u.reg_read(r) for r in REGS)

    def init(self):return self.run(self.va(hd.INIT))
    def draw(self,index=0,cp=65,rotation=0):
        return self.run(self.va(hd.DRAW),eax=self.oldtextures[index],edx=7,ecx=11,
                        args=(rotation,0xff887766,19,13,103,61,19,13),font=self.fonts[index],cp=cp)

def close(actual,expected):
    assert abs(actual-expected)<0.0001,(actual,expected)

def verify():
    source=SOURCE.read_bytes();candidate=hd.patch(source);manifest=hd.assets_manifest();checks=[]
    def ok(name):checks.append(name)
    p=pefile.PE(data=candidate);old=pefile.PE(data=source)
    assert len(p.sections)==len(old.sections)==13 and p.OPTIONAL_HEADER.SizeOfImage==hd.RVA+hd.SIZE
    assert hd.patch(source)==candidate
    # All original bytes except PE size/checksum fields and the exact startup
    # hook stay identical, including screen/scale/portrait predecessor payloads.
    allowed=set(range(old.get_offset_from_rva(hd.HOOK-hd.BASE),old.get_offset_from_rva(hd.HOOK-hd.BASE)+6))
    for field in ('Misc_VirtualSize','SizeOfRawData'):
        a=old.sections[-1].get_field_absolute_offset(field);allowed.update(range(a,a+4))
    for field in ('SizeOfImage','CheckSum'):
        a=old.OPTIONAL_HEADER.get_field_absolute_offset(field);allowed.update(range(a,a+4))
    assert all(a==b or i in allowed for i,(a,b) in enumerate(zip(source,candidate)))
    ok('immutable predecessor spans; deterministic append; 13 sections')
    for base in (0x10000000,0x14000000):
        f=Fixture(candidate,base);u=f.u;baseline=[bytes(u.mem_read(a,0x1c0330)) for a in f.fonts]
        f.init();assert f.st(0)==1 and f.st(8)==36 and f.st(0xc)==1 and len(f.loads)==36
        assert len(f.cache_keys)==36 and len(set(f.cache_keys))==36
        assert f.loader_executed=={'0x7404fc','0x7492cc','0x424d7c','0x42f698','0x42f7e4'}
        assert f.st(4)==0 and f.st(0x60)==0
        for va,_ in hd.FONT_CALLS:assert va+5+signed(get(u,va+1))==f.va(hd.DRAW)
        assert hd.TI_UPLOAD_CALL+5+signed(get(u,hd.TI_UPLOAD_CALL+1))==f.va(hd.UPLOAD)
        f.init();assert len(f.loads)==36 and f.st(0x64)==2
        ok(f'{base:x}: real lookup/Unicode filename loader,36 unique native basename keys,transactional install/no repeat')
        for index,font in enumerate(manifest['fonts']):
            for density,percent in enumerate(hd.PERCENTS):
                for cp in (65,ord('Ж'),ord('я')):
                    glyph=next(g for g in font['glyphs'] if g['codepoint']==cp)
                    dx,dy,w,h=glyph['visual_logical_box'];sx,sy,sw,sh=glyph['source_rects'][density]
                    for rotation in (0,90,-90):
                        f.scope(percent);f.draw(index,cp,rotation);q=f.quads[-1]
                        tx=f.textures[font['density_sets'][density]['path'].replace('/','\\')]
                        x=61+dx if rotation==0 else 61-dy if rotation==90 else 61+dy
                        y=103+dy if rotation==0 else 103+dx if rotation==90 else 103-dx
                        assert q==(tx,sx,sy,rotation&0xffffffff,0xff887766,h,w,y,x,sh,sw),q
                        vs=[floats(u,f.vertices+n*28,7) for n in range(6)]
                        bounds=(x,y,x+w,y+h) if rotation==0 else (x-h,y,x,y+w) if rotation==90 else (x,y-w,x+h,y)
                        for observed,expected in zip((min(v[0] for v in vs),min(v[1] for v in vs),max(v[0] for v in vs),max(v[1] for v in vs)),bounds):close(observed,expected)
                        aw=font['density_sets'][density]['width'];ah=font['density_sets'][density]['height']
                        for observed,expected in zip((min(v[5] for v in vs),min(v[6] for v in vs),max(v[5] for v in vs),max(v[6] for v in vs)),((sx+.5)/aw,(sy+.5)/ah,(sx+sw+.5)/aw,(sy+sh+.5)/ah)):close(observed,expected)
                        assert get(u,f.batch+0x14)==6 and f.st(0x6c)==0
                        ok(f'{base:x}: {font["font"]}/{percent}/U+{cp:04X}/{rotation} real source-UV/destination/rotation')
        assert [bytes(u.mem_read(a,0x1c0330)) for a in f.fonts]==baseline
        assert len(f.loads)==36;ok(f'{base:x}: all original glyph metrics/font identities retained, hot selection has no loads')
        # Execute each original native text loop through the installed CALL,
        # proving that its actual EBP self/codepoint slots match the adapter.
        f.skip_d3d_flush=True
        looptext=DATA+0xe00;raw='AЖя42'.encode('utf-16le')
        u.mem_write(looptext-12,struct.pack('<HHiI',1200,2,-1,len(raw)));u.mem_write(looptext,raw+b'\0\0')
        position=DATA+0xf80;put(u,position,40);put(u,position+4,80)
        for index,obj in enumerate(f.fonts):
            put(u,obj+0x1c0190,1);put(u,obj+0x1c0110,0xff887766)
            for percent in hd.PERCENTS:
                for entry in (0x6fcd84,0x6fca84,0x6fcc04):
                    f.scope(percent);before=f.st(0x20);start=len(f.quads)
                    f.run(entry,eax=obj,edx=position,ecx=looptext)
                    qs=f.quads[start:];assert len(qs)==5 and f.st(0x20)==before+5,(index,percent,hex(entry),len(qs),f.st(0x20)-before)
                    assert f.st(0x30)==index and f.st(0x34)==ord('2') and f.st(0x6c)==0
                    assert len({q[3] for q in qs})==1 and signed(qs[0][3]) in (0,90,-90)
                    ok(f'{base:x}: original native text loop {entry:x}/{index}/{percent} detours actual self/codepoint frame')
        f.skip_d3d_flush=False
        # Real text measurement uses retained font records and native kerning,
        # format parsing, UTF16 length and rounding. No text/font API stubs.
        text=DATA+0xe00;raw='AЖя 42'.encode('utf-16le');u.mem_write(text-12,struct.pack('<HHiI',1200,2,-1,len(raw)));u.mem_write(text,raw+b'\0\0')
        out=DATA+0xf00
        for obj in f.fonts:
            results=[]
            for percent in hd.PERCENTS:
                f.scope(percent);f.run(0x6fdcb4,eax=obj,edx=text,ecx=out);results.append(bytes(u.mem_read(out,8)))
            assert len(set(results))==1;ok(f'{base:x}: real native text width/height unchanged at four densities')
        # Exact stock fallback arguments, including invalid rotations and
        # live device-reset unavailability; no mutation before tail fallback.
        for reason in ('world','small-viewport','unknownfont','unicode','missing','render-target','nullD3D','dimensions','invalidscale','rotation'):
            f.scope(150);index=0;cp=65;rot=0;header=base+hd.TABLE
            address=get(u,header+0x20);saved=bytes(u.mem_read(address,0x64))
            font_obj=f.fonts[0]
            if reason=='world':f.core(0x14,0)
            elif reason=='small-viewport':put(u,f.renderer+0x299,512)
            elif reason=='unknownfont':f.fonts[0]=DATA+0xf000
            elif reason=='unicode':cp=0x2603
            elif reason=='missing':put(u,header+0x20,0)
            elif reason=='render-target':u.mem_write(address+0x60,b'\x01')
            elif reason=='nullD3D':put(u,address+0xc,0)
            elif reason=='dimensions':put(u,address+0x14,7)
            elif reason=='invalidscale':f.core(0,175)
            elif reason=='rotation':rot=45
            f.draw(index,cp,rot);assert f.quads[-1]==(f.oldtextures[0],7,11,rot&0xffffffff,0xff887766,19,13,103,61,19,13)
            f.fonts[0]=font_obj;put(u,header+0x20,address);u.mem_write(address,saved);put(u,f.renderer+0x299,3840)
            ok(f'{base:x}: untouched stock fallback {reason}')
        f.scope(150);f.draw();assert f.st(0x6c)==0;ok(f'{base:x}: restored native resource resumes without reload/retry')
        # Original GPU copy + predecessor scope scaling runs before the new
        # font-only pixel snap; CPU vertices, UV, tint, Z/RHW and x87 CW persist.
        for percent in hd.PERCENTS:
            for own,scope,valid in ((True,1,True),(False,1,True),(True,0,True),(True,1,False)):
                f.scope(percent,scope);f.core(0x14,scope)
                texture=get(u,base+hd.TABLE+0x18+hd.PERCENTS.index(percent)*4) if own else f.oldtextures[0]
                put(u,f.batch+0x10,texture);put(u,FRAME-4,f.vb);put(u,f.vb+0x18,0x104 if valid else 0x102)
                sourcebuf=DATA+0x50000;dest=DATA+0x51000
                vertex=struct.pack('<4fI2f',12.3,27.7,1.,1.,0xff887766,.2,.8);raw=vertex*6
                u.mem_write(sourcebuf,raw);u.mem_write(dest-4,b'ABCD'+b'\0'*len(raw)+b'EFGH')
                u.reg_write(UC_X86_REG_FPCW,0x77f)
                f.run(f.va(hd.UPLOAD),eax=sourcebuf,edx=dest,ecx=len(raw))
                assert u.reg_read(UC_X86_REG_FPCW)==0x77f and bytes(u.mem_read(sourcebuf,len(raw)))==raw
                assert bytes(u.mem_read(dest-4,4))==b'ABCD' and bytes(u.mem_read(dest+len(raw),4))==b'EFGH'
                result=bytes(u.mem_read(dest,len(raw)))
                for n in range(6):
                    observed=floats(u,dest+n*28,2)
                    sx,sy=floats(u,base+hd.CORE_STATE+0x1c,2)
                    expected=(round(12.3*sx),round(27.7*sy)) if scope and valid and own else (12.3*sx,27.7*sy) if scope and valid else (12.3,27.7)
                    for a,b in zip(observed,expected):close(a,b)
                    assert result[n*28+8:n*28+28]==raw[n*28+8:n*28+28]
                ok(f'{base:x}: real copy/scoped GPU pixels {percent}/{own}/{scope}/{valid}')
        # Failure transactions are checked independently with the original
        # native code bytes and explicit API failure responses.
        for failure in ('files','null','render-target','dimensions'):
            x=Fixture(candidate,base,load_failure=failure);x.init();assert x.st(0)==0xffffffff and x.st(8)==0 and x.st(0xc)==0
            counts=(len(x.loads),len(x.protect),len(x.flush));x.init();assert counts==(len(x.loads),len(x.protect),len(x.flush))
            ok(f'{base:x}: resource failure {failure}, untouched calls/no retry')
        for protect_failure,flush_failure in ((1,0),(2,0),(0,1),(0,2),(3,0),(4,0)):
            x=Fixture(candidate,base,protect_failure=protect_failure,flush_failure=flush_failure);x.init()
            if protect_failure<=2 and protect_failure or flush_failure:
                assert x.st(0xc)==0xffffffff
                for va,raw in hd.FONT_CALLS:assert bytes(x.u.mem_read(va,5))==raw
                assert 0x6508c3+signed(get(x.u,0x6508bf))==x.va(hd.CORE_UPLOAD)
            else:assert x.st(0xc)==1 and x.st(4)==4
            counts=(len(x.loads),len(x.protect),len(x.flush));x.run(x.va(hd.INSTALL));assert counts==(len(x.loads),len(x.protect),len(x.flush))
            ok(f'{base:x}: guarded protection/flush failure {protect_failure}/{flush_failure}, no install loop')
        for reason in ('manager','core','call','prologue'):
            x=Fixture(candidate,base)
            if reason=='manager':put(x.u,get(x.u,0x76e180),0)
            elif reason=='core':x.core(0x28,0)
            elif reason=='call':x.u.mem_write(hd.FONT_CALLS[0][0],b'\x90')
            elif reason=='prologue':x.u.mem_write(0x65085c,b'\x90')
            x.init();assert x.st(0xc) in (0,0xffffffff) and not x.protect
            ok(f'{base:x}: exact startup/installer guard {reason}')
    return candidate,{'result':'PASS','candidate_sha256':hd.sha(candidate),'source_sha256':hd.BASE_SHA,
        'ti_sha256':hd.TI_SHA,'asset_manifest_sha256':hd.ASSET_MANIFEST_SHA,'checks':len(checks),'cases':checks,
        'native_code':['6fe910 font object lookup','7404fc Unicode filename loader','7492cc basename/extension normalization','424d7c/42f698/42f7e4 actual filename scanner','7406a8 glyph quad','66462c vertex batch','664408 UV normalization','664544 rotation','651c30 vertex construction','6fcd84/6fca84/6fcc04 actual native text loops','6fdcb4 text measurement and its native dependencies','406cdc memory copy','existing c25a00 scoped UI GPU scaling'],
        'external_stubs':['GetFileAttributesW','Unicode substring allocation40c16c','resource cache texture decode/allocation6b11f4','terminal D3D batch submission663834 for integrated native text-loop cases','VirtualProtect','GetModuleHandleW','GetProcAddress','GetCurrentProcess','FlushInstructionCache'],
        'native_unique_font_density_cache_keys':36,'native_basename_cache_executed':True,
        'bases':['0x10000000','0x14000000'],'installed_client_modified':False,'graphical_validation':False,'hosted_validation':False,
        'source_file_sha256':hd.sha(Path(hd.__file__).read_bytes())}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path,default=ROOT/'reports/ui-hd-assets/native-fonts/native-unicode-loader-proof.json');parser.add_argument('--candidate',type=Path,default=ROOT/'reports/ui-hd-assets/native-fonts/silver.dll');args=parser.parse_args()
    candidate,report=verify();args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');args.candidate.parent.mkdir(parents=True,exist_ok=True);args.candidate.write_bytes(candidate)
    print(json.dumps({k:report[k] for k in ('result','checks','candidate_sha256','source_file_sha256')}))
if __name__=='__main__':main()
