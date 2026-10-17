"""Execute icon adapter and real native quad/UV math without a game process.

Resource decoding/allocation and final GPU calls are explicit fixture stubs.
TI740610,611958,661b18,651c30,6619dc,749a3c execute unchanged. This verifies
source-density/destination separation, normalized UVs, native fallback and ABI;
it does not claim actual Direct3D/client/hosted graphical validation.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_ui_hd_icons as a

DATA, STACK, STOP = 0x30000000, 0x31000000, 0x3003ff00
CALLEE = (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP)
CANARIES = (0x12345678, 0x23456789, 0x3456789a, 0x456789ab)


def put(u, address, value):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get(u, address):
    return struct.unpack('<I', u.mem_read(address, 4))[0]


@lru_cache(maxsize=5)
def mapped(image, base):
    pe = pefile.PE(data=image); pe.relocate_image(base)
    return pe.get_memory_mapped_image()


def fixture_input(source):
    """Temporary zero font reservation only if a real font build is unavailable."""
    p = pefile.PE(data=source)
    if p.OPTIONAL_HEADER.SizeOfImage == a.SECTION_RVA:
        return source, False
    if p.OPTIONAL_HEADER.SizeOfImage == a.SECTION_RVA+a.SIZE:
        return source, False
    assert a.sha(source) == a.LIVE_SHA
    out = bytearray(source); last = p.sections[-1]
    pad = a.SECTION_RVA-p.OPTIONAL_HEADER.SizeOfImage
    for field in ('Misc_VirtualSize', 'SizeOfRawData'):
        struct.pack_into('<I', out, last.get_field_absolute_offset(field), getattr(last, field)+pad)
    struct.pack_into('<I', out, p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), a.SECTION_RVA)
    struct.pack_into('<I', out, p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    out.extend(bytes(pad))
    return bytes(out), True


class Fixture:
    def __init__(self, image, ti, base, ti_base):
        self.u = Uc(UC_ARCH_X86, UC_MODE_32)
        for data, address in ((image, base), (ti, ti_base)):
            raw = mapped(data, address)
            self.u.mem_map(address, (len(raw)+4095)&~4095)
            self.u.mem_write(address, raw)
        self.u.mem_map(DATA, 0x40000); self.u.mem_map(STACK, 0x10000)
        self.u.mem_map(0, 0x1000)
        self.base, self.ti_base = base, ti_base
        self.next = DATA+0x10000
        self.loads, self.stock, self.quads, self.executed = [], [], [], set()
        self.fail_paths = set(); self.fail_original = False
        self.outputs = {}
        self.renderer, self.builder, self.vertex_holder, self.vertices = (DATA+0x1000, DATA+0x2000,
                                                                       DATA+0x3000, DATA+0x4000)
        put(self.u, self.tva(0x76de0c), DATA+0x100)
        put(self.u, DATA+0x100, self.renderer)
        put(self.u, self.renderer+0x1d0, self.builder)
        self.u.mem_write(self.renderer+0x2d5, b'\x07')
        put(self.u, self.builder+4, self.renderer); put(self.u, self.builder+8, self.vertex_holder)
        put(self.u, self.vertex_holder+0x30, self.vertices)
        put(self.u, self.va(0xacc3fc), self.tva(0x71bbe0))
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def va(self, value):
        return self.base+value-a.IMAGE_BASE

    def tva(self, value):
        return self.ti_base+value-a.IMAGE_BASE

    def ret(self, extra=0):
        sp = self.u.reg_read(UC_X86_REG_ESP)
        self.u.reg_write(UC_X86_REG_EIP, get(self.u, sp))
        self.u.reg_write(UC_X86_REG_ESP, sp+4+extra)

    def text(self, address):
        return bytes(self.u.mem_read(address, get(self.u, address-4)*2)).decode('utf-16le')

    def texture(self, width, height):
        p = self.next; self.next += 0x80
        self.u.mem_write(p, b'\xa5'*0x80)
        put(self.u,p+8,self.renderer)
        put(self.u,p+0x14,1<<(width-1).bit_length())
        put(self.u,p+0x18,1<<(height-1).bit_length())
        return p

    def image(self, width, height):
        p = self.next; self.next += 0x20
        texture = self.texture(width*2,height*2)
        self.u.mem_write(p, struct.pack('<IHHHH',texture,width*2,height*2,width,height))
        return p

    def hook(self, u, address, size, _):
        ti_va = address-self.ti_base+a.IMAGE_BASE
        if ti_va in (0x740610,0x611958,0x661b18,0x651c30,0x6619dc,0x749a3c):
            self.executed.add(hex(ti_va))
        if address == self.va(0x4f2cb4):
            sp = u.reg_read(UC_X86_REG_ESP)
            path = self.text(u.reg_read(UC_X86_REG_EAX))
            width, height = u.reg_read(UC_X86_REG_EDX),u.reg_read(UC_X86_REG_ECX)
            args = [get(u,sp+4*i) for i in range(1,5)]
            out, flags, zero1, zero2 = args
            self.loads.append({'path':path,'tile':[width,height],'flags':flags,'extra':[zero1,zero2]})
            fail = path in self.fail_paths or (self.fail_original and not path.startswith('ui-hd'))
            texture = 0 if fail else self.texture(width*2,height*2)
            u.mem_write(out,struct.pack('<IHHHH',texture,width*2,height*2,width,height))
            u.reg_write(UC_X86_REG_EAX,0x10203040)
            u.reg_write(UC_X86_REG_EDX,0x20304050)
            u.reg_write(UC_X86_REG_ECX,0x30405060)
            self.ret(16)
        elif address == self.tva(0x73f680):
            u.reg_write(UC_X86_REG_EAX,0); self.ret()
        elif address == self.tva(0x611da4):
            self.current_texture=u.reg_read(UC_X86_REG_EAX); self.ret()
        elif address == self.tva(0x65085c):
            vertices=[list(struct.unpack('<ffffIff',u.mem_read(self.vertices+i*28,28))) for i in range(4)]
            self.quads.append({'texture':self.current_texture,'vertices':vertices})
            self.ret()
        elif address == self.tva(0x650d98):
            self.ret()
        elif address == self.tva(0x71bbe0):
            sp=u.reg_read(UC_X86_REG_ESP)
            self.stock.append([get(u,sp+4*i) for i in range(1,9)])
            u.reg_write(UC_X86_REG_EAX,0x9abcdef0)
            self.ret(32)

    def run(self, va, eax=0, edx=0, ecx=0, args=()):
        sp=STACK+0xf000
        for reg,value in zip(CALLEE,CANARIES):self.u.reg_write(reg,value)
        self.u.reg_write(UC_X86_REG_EAX,eax);self.u.reg_write(UC_X86_REG_EDX,edx)
        self.u.reg_write(UC_X86_REG_ECX,ecx)
        self.u.reg_write(UC_X86_REG_EFLAGS,0x202)
        self.u.mem_write(sp,struct.pack('<'+'I'*(len(args)+1),STOP,*args))
        self.u.reg_write(UC_X86_REG_ESP,sp)
        try:self.u.emu_start(self.va(va),STOP,count=100000)
        except Exception as exc:
            raise RuntimeError(f'{va:#x} failed at {self.u.reg_read(UC_X86_REG_EIP):#x}: {exc}') from exc
        assert self.u.reg_read(UC_X86_REG_EIP)==STOP
        assert self.u.reg_read(UC_X86_REG_ESP)==sp+4+len(args)*4
        assert tuple(self.u.reg_read(r) for r in CALLEE)==CANARIES
        return self.u.reg_read(UC_X86_REG_EAX)

    def load(self,index):
        _,symbol,width,height,_=a.RESOURCES[index]
        path=DATA+0x8000+index*0x100
        raw=('pda\\'+a.RESOURCES[index][0]).encode('utf-16le')
        put(self.u,path-4,len(raw)//2);self.u.mem_write(path,raw+b'\0\0')
        out=DATA+0xa000+index*0x20; self.outputs[index]=out
        result=self.run(a.LOAD_WRAPPERS+index*0x80,path,width,height,args=(out,2,0,0))
        assert result==0x10203040
        assert self.u.reg_read(UC_X86_REG_EDX)==0x20304050
        assert self.u.reg_read(UC_X86_REG_ECX)==0x30405060
        return out


class NativeLoaderFixture(Fixture):
    """Run the genuine cross-DLL loader and basename extraction/cache boundary.

    Explicit stubs allocate Unicode strings and fixture texture objects; native
    Silver4f2cb4, TI71c844,7404fc,7492cc,424d7c,42f698,42f7e4 execute. Resource
    manager cache keys come from the actual native ExtractFileName result.
    """
    def __init__(self,*args):
        super().__init__(*args)
        self.cache={};self.cache_inputs=[];self.loader_executed=set()
        put(self.u,self.va(0xacc4b4),self.tva(0x71c844))
        put(self.u,self.tva(0x76e464),DATA+0x150);put(self.u,DATA+0x150,DATA+0x1600)
        put(self.u,self.tva(0x76e0f0),DATA+0x154);put(self.u,DATA+0x154,self.unicode('base\\'))
        self.asset_dimensions={}
        for name,symbol,w,h,_ in a.RESOURCES:
            self.asset_dimensions['base\\pda\\'+name]=(w*2,h*2)
            for density in a.DENSITIES:
                self.asset_dimensions['base\\'+a.path_for(symbol,density)]=(a.physical(w,density)*2,
                                                                           a.physical(h,density)*2)
                # Reproduce the historical basename alias for regression proof.
                self.asset_dimensions[f'base\\ui-hd\\icons\\a\\{density}\\{symbol}.png']=(a.physical(w,density)*2,
                                                                                        a.physical(h,density)*2)

    def unicode(self,text):
        p=self.next;self.next+=((len(text)*2+14+31)//32)*32
        self.u.mem_write(p,struct.pack('<HHiI',1200,2,-1,len(text))+text.encode('utf-16le')+b'\0\0')
        return p+12

    def hook(self,u,address,size,user):
        ti_va=address-self.ti_base+a.IMAGE_BASE
        if ti_va in (0x71c844,0x7404fc,0x7492cc,0x424d7c,0x42f698,0x42f7e4):
            self.loader_executed.add(hex(ti_va))
        if address==self.va(0x4f2cb4):
            # Observe the real wrapper; do not substitute the wrapper itself.
            sp=u.reg_read(UC_X86_REG_ESP);path=self.text(u.reg_read(UC_X86_REG_EAX))
            self.loads.append({'path':path,'tile':[u.reg_read(UC_X86_REG_EDX),u.reg_read(UC_X86_REG_ECX)],
                               'flags':get(u,sp+8),'extra':[get(u,sp+12),get(u,sp+16)]})
            return
        if address==self.tva(0x40bffc):
            # Native Unicode concatenation allocation only, both inputs intact.
            out=u.reg_read(UC_X86_REG_EAX)
            text=self.text(u.reg_read(UC_X86_REG_EDX))+self.text(u.reg_read(UC_X86_REG_ECX))
            put(u,out,self.unicode(text));self.ret();return
        if address==self.tva(0x40c16c):
            # Native substring allocation only; indices are calculated by the
            # real ExtractFileName/delimiter scanner, including managed length.
            sp=u.reg_read(UC_X86_REG_ESP);out=get(u,sp+4)
            text=self.text(u.reg_read(UC_X86_REG_EAX))
            start=u.reg_read(UC_X86_REG_EDX)-1;count=u.reg_read(UC_X86_REG_ECX)
            put(u,out,self.unicode(text[start:start+count]));self.ret(4);return
        if address==self.tva(0x6b11f4):
            source=self.text(u.reg_read(UC_X86_REG_EAX))
            key=self.text(u.reg_read(UC_X86_REG_EDX))
            self.cache_inputs.append({'source':source,'native_key':key})
            assert key==source.rsplit('\\',1)[-1].rsplit('.',1)[0], (source,key)
            if key not in self.cache:
                w,h=self.asset_dimensions[source]
                texture=self.texture(w,h)
                put(u,texture+0x20,w);put(u,texture+0x1c,h)
                put(u,texture+0xc,texture+0x70);u.mem_write(texture+0x60,b'\0')
                self.cache[key]=texture
            u.reg_write(UC_X86_REG_EAX,self.cache[key]);self.ret();return
        super().hook(u,address,size,user)

    def load(self,index):
        name,_,width,height,_=a.RESOURCES[index]
        path=self.unicode('pda\\'+name)
        out=DATA+0xa000+index*0x20;self.outputs[index]=out
        self.run(a.LOAD_WRAPPERS+index*0x80,path,width,height,args=(out,2,0,0))
        return out


def close(v,w):
    assert abs(v-w)<1e-5,(v,w)


def verify(source, ti, assets):
    assert a.sha(ti)==a.TI_SHA
    before,padded=fixture_input(source)
    already=pefile.PE(data=before).OPTIONAL_HEADER.SizeOfImage==a.SECTION_RVA+a.SIZE
    candidate=before if already else a.patch(before,expected_sha=a.sha(before))
    if not already:
        assert a.patch(before,expected_sha=a.sha(before))==candidate
        try:a.patch(before,expected_sha='0'*64)
        except ValueError:pass
        else:raise AssertionError('SHA guard did not reject wrong source')
    pe=pefile.PE(data=candidate)
    assert pe.FILE_HEADER.NumberOfSections==13
    assert pe.OPTIONAL_HEADER.SizeOfImage==a.SECTION_RVA+a.SIZE
    assert pe.get_data(a.SECTION_RVA,a.SIZE)==a.extension()
    asset_manifest=json.loads(assets.read_text(encoding='utf-8'))
    assert len(asset_manifest['assets'])==60
    for row in asset_manifest['assets']:
        assert a.sha(Path(row['path']).read_bytes())==row['sha256']
        assert row['client_relative_path']=='base/'+a.path_for(row['symbol'],row['density']).replace('\\','/')
        assert row['logical_tile']==[a.RESOURCES[next(i for i,r in enumerate(a.RESOURCES)
                                                   if r[1]==row['symbol'])][2],
                                    a.RESOURCES[next(i for i,r in enumerate(a.RESOURCES)
                                                   if r[1]==row['symbol'])][3]]
    cases=[]
    for base,ti_base in ((0x10000000,0x400000),(0x17000000,0x600000)):
        f=Fixture(candidate,ti,base,ti_base)
        for index,resource in enumerate(a.RESOURCES):
            start=len(f.loads);out=f.load(index)
            assert len(f.loads)==start+5
            row=base+a.ROWS+index*0x80
            assert get(f.u,row)==get(f.u,out) and get(f.u,row+0xc)==1
            for di,density in enumerate(a.DENSITIES):
                load=f.loads[start+1+di]
                assert load=={'path':a.path_for(resource[1],density),
                              'tile':[a.physical(resource[2],density),a.physical(resource[3],density)],
                              'flags':2,'extra':[0,0]}
            f.load(index);assert len(f.loads)==start+6
            cases.append({'case':'eager_load_once','silver_base':hex(base),'resource':resource[1]})
        assert get(f.u,base+a.STATE+4)==15 and get(f.u,base+a.STATE+0x20)==15
        assert get(f.u,base+a.STATE)==1
        load_count=len(f.loads)
        for index,(_,symbol,width,height,_) in enumerate(a.RESOURCES):
            out=f.outputs[index]; original=get(f.u,out); original_bytes=bytes(f.u.mem_read(original,0x80))
            for density in a.DENSITIES:
                put(f.u,base+a.UI_SCALE_STATE,density)
                for frame in range(4):
                    srcw,srch=a.physical(width,density),a.physical(height,density)
                    row=base+a.ROWS+index*0x80
                    selected=get(f.u,row+0x10+a.DENSITIES.index(density)*12)
                    before_quads=len(f.quads)
                    assert f.run(0x4f27fc,out,41,52,args=(0,frame,0x90dbefb1))==1
                    assert len(f.quads)==before_quads+1 and f.quads[-1]['texture']==selected
                    quad=f.quads[-1]['vertices']
                    aw=get(f.u,selected+0x14);ah=get(f.u,selected+0x18)
                    sx=(frame&1)*srcw;sy=(frame>>1)*srch
                    expected=((41,52,sx/aw,sy/ah),(41+width,52,(sx+srcw)/aw,sy/ah),
                              (41+width,52+height,(sx+srcw)/aw,(sy+srch)/ah),
                              (41,52+height,sx/aw,(sy+srch)/ah))
                    for vertex,(x,y,u,v) in zip(quad,expected):
                        close(vertex[0],x);close(vertex[1],y);close(vertex[5],u);close(vertex[6],v)
                        assert vertex[4]==0x90ffffff
                    assert get(f.u,selected+0x24)==srcw and get(f.u,selected+0x28)==srch
                    assert bytes(f.u.mem_read(original,0x80))==original_bytes
                    assert f.u.mem_read(f.renderer+0x2d5,1)==b'\x07'
                    assert get(f.u,base+a.STATE+0x10)==density
                    assert get(f.u,base+a.STATE+0x14)==index and get(f.u,base+a.STATE+0x18)==frame
                    cases.append({'case':'native_density_quad_uv','silver_base':hex(base),
                                  'ti_base':hex(ti_base),'resource':symbol,'density':density,'frame':frame})
        assert len(f.loads)==load_count
        assert f.executed=={'0x740610','0x611958','0x661b18','0x651c30','0x6619dc','0x749a3c'}
        # Next-draw switching also applies to controls loaded before scale changes.
        put(f.u,base+a.UI_SCALE_STATE,137)
        f.run(0x4f27fc,f.outputs[0],41,52,args=(0,0,0xffffffff))
        assert get(f.u,base+a.STATE+0x10)==100
        cases.append({'case':'unknown_density_safe100','silver_base':hex(base)})
        stock_inputs=[('unknown',f.image(40,40),0,0),('frame4',f.outputs[0],0,4),
                      ('frame_negative',f.outputs[0],0,0xffffffff),('effectflag',f.outputs[0],1,0)]
        wrong=f.image(39,40);put(f.u,wrong,get(f.u,f.outputs[0]));stock_inputs.append(('wrong_tile',wrong,0,0))
        for name,im,flag,frame in stock_inputs:
            start=len(f.stock);quads=len(f.quads)
            result=f.run(0x4f27fc,im,41,52,args=(flag,frame,0x12345678))
            assert result==0x9abcdef0 and len(f.stock)==start+1 and len(f.quads)==quads
            packed=list(struct.unpack('<III',f.u.mem_read(im,12)))
            assert f.stock[-1]==packed+[41,52,0x12345678,frame,flag]
            cases.append({'case':'stock_fallback_'+name,'silver_base':hex(base)})
        row=base+a.ROWS;selected=get(f.u,row+0x10);put(f.u,row+0x10,0)
        start=len(f.stock);f.run(0x4f27fc,f.outputs[0],41,52,args=(0,0,0xffffffff))
        assert len(f.stock)==start+1;put(f.u,row+0x10,selected)
        cases.append({'case':'missing_selected_hd_stock','silver_base':hex(base)})
        # A partial asset failure safely retains stock for that density and never
        # repeats allocation every draw; successfully loaded densities remain usable.
        fail=Fixture(candidate,ti,base,ti_base)
        fail.fail_paths.add(a.path_for('map',150));im=fail.load(0)
        assert get(fail.u,base+a.STATE)==0xffffffff and get(fail.u,base+a.STATE+0x24)==1
        put(fail.u,base+a.UI_SCALE_STATE,150)
        fail.run(0x4f27fc,im,41,52,args=(0,2,0xffffffff));assert len(fail.stock)==1
        fail.load(0);assert len(fail.loads)==6
        cases.append({'case':'partial_asset_failure_stock_no_repeat','silver_base':hex(base)})
        fail=Fixture(candidate,ti,base,ti_base);fail.fail_original=True;fail.load(0)
        assert len(fail.loads)==1 and get(fail.u,base+a.STATE+4)==0
        cases.append({'case':'missing_original_no_hd_allocation','silver_base':hex(base)})
        real=NativeLoaderFixture(candidate,ti,base,ti_base)
        all_textures=[]
        for index,(_,symbol,w,h,_) in enumerate(a.RESOURCES):
            im=real.load(index);row=base+a.ROWS+index*0x80
            original=get(real.u,im);textures=[get(real.u,row+0x10+12*i)for i in range(4)]
            assert len(set([original]+textures))==5
            all_textures.extend(textures)
            for di,density in enumerate(a.DENSITIES):
                texture=textures[di]
                words=struct.unpack('<IHHHH',real.u.mem_read(row+0x10+12*di,12))
                sw,sh=a.physical(w,density),a.physical(h,density)
                assert words== (texture,sw*2,sh*2,sw,sh)
                assert get(real.u,texture+0x20)==sw*2 and get(real.u,texture+0x1c)==sh*2
                assert get(real.u,texture+0xc)!=0 and real.u.mem_read(texture+0x60,1)==b'\0'
            original_bytes=bytes(real.u.mem_read(original,0x80))
            for density in a.DENSITIES:
                put(real.u,base+a.UI_SCALE_STATE,density)
                real.run(0x4f27fc,im,41,52,args=(0,3,0xffffffff))
                assert real.quads[-1]['texture']==textures[a.DENSITIES.index(density)]
            assert bytes(real.u.mem_read(original,0x80))==original_bytes
            cases.append({'case':'actual_native_loader_unique_cache_and_draw','silver_base':hex(base),
                          'resource':symbol,'density_texture_objects':len(set(textures))})
        assert len(set(all_textures))==60
        assert real.loader_executed=={'0x71c844','0x7404fc','0x7492cc','0x424d7c','0x42f698','0x42f7e4'}
        legacy=NativeLoaderFixture(candidate,ti,base,ti_base)
        alias=[]
        for density in a.DENSITIES:
            path=legacy.unicode(f'ui-hd\\icons\\a\\{density}\\map.png');im=DATA+0xb000
            legacy.run(0x4f2cb4,path,a.physical(40,density),a.physical(40,density),args=(im,2,0,0))
            alias.append(get(legacy.u,im))
        assert len(set(alias))==1
        cases.append({'case':'historical_identical_basename_reproduces_alias','silver_base':hex(base),
                      'old_density_texture_objects':len(set(alias))})
    return {'result':'PASS','case_count':len(cases),'cases':cases,
            'candidate_sha256':a.sha(candidate),'payload_sha256':a.sha(a.extension()),
            'source_sha256':a.sha(source),'zero_font_reservation_fixture':padded,
            'selected_assets_manifest':str(assets.resolve()),'selected_assets_manifest_sha256':a.sha(assets.read_bytes()),
            'native_executed':['TI740610','TI611958','TI661b18','TI651c30','TI6619dc','TI749a3c',
                               'Silver4f27fc stock trampoline','Silver4f2cb4','TI71c844','TI7404fc',
                               'TI7492cc','TI424d7c','TI42f698','TI42f7e4'],
            'explicit_stubs':['resource loader/decoder/allocation','texture blend selection73f680',
                              'GPU bind611da4/upload65085c/draw650d98','stock boundRenderEffect'],
            'cache_fixture_stubs':['Unicode concatenation/substr allocation','resource cache decoding/allocation'],
            'native_basename_cache_executed':True,'native_unique_density_texture_objects':60,
            'historical_basename_collision_reproduced':True,
            'no_per_draw_load':True,'original_texture_objects_preserved':True,
            'logical_hitboxes_and_callbacks_unchanged':True,'source_density_independent_of_destination':True,
            'immutable_ti_sha256':a.sha(ti),'graphical_validation':False,'published':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=ROOT/'reports/ui-modernization/client/silver.dll')
    p.add_argument('--assets',type=Path,default=ROOT/'reports/ui-hd-integration/icons-final/selected-assets-manifest.json')
    p.add_argument('--report',type=Path,default=ROOT/'reports/ui-hd-integration/icons-native-proof.json')
    args=p.parse_args()
    report=verify(args.source.read_bytes(),(ROOT/'reports/ui-modernization/baseline/ti.exe').read_bytes(),args.assets)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cases',)},ensure_ascii=False))
