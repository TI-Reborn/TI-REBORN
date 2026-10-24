"""Animate server-visible F7 cells through original image/sound SDK bridges.

Patch only the two historical item extension entry points in the exact live
DLL, retaining the complete newer UI/authentication/client release chain.
"""
import hashlib
import struct
import pefile
from .client_equipment_batch import Code
from . import client_battle_items as old

BASE_SHA='e1d9435a8521881a6559dd3d724d9f5ca865a7aaa72d1707cf1669adaa3a4d80'
RVA=0x879000
SIZE=0x3000
DRAW=0x400000+RVA
READER=DRAW+0x800
LOAD=DRAW+0xc00
SOUND=DRAW+0xe00
ROWS=RVA+0x1000
STATE=RVA+0x1200
NAMES=RVA+0x1300
SIGNATURE=b'TIO-throwable-animation-v1'
RESOURCES=(('gfx\\tio-effects\\tio-smoke.png',64,64,1),
           ('gfx\\tio-effects\\tio-flare.png',128,192,32),
           ('gfx\\tio-effects\\tio-fire.png',64,128,32),
           ('gfx\\tio-effects\\tio-glow.png',192,192,1))


def load_code():
    c=Code(LOAD);c.emit('9c60');c.base()
    for i,(_,w,h,_) in enumerate(RESOURCES):
        c.emit('8db3');c.word(ROWS+i*64)
        c.emit('833e00');c.branch('0f85','loaded'+str(i))
        c.emit('6a00 6a00 6a02 56 8b4620 01d8 ba');c.word(w)
        c.emit('b9');c.word(h);c.call(0x4f2cb4)
        c.label('loaded'+str(i))
    c.emit('619d c3');return c.finish(0x200)


def reader_code():
    # Preserve the historical reader ABI, including version/length checks and
    # malformed-packet clearing. New kinds4/5 are fire and illuminated cells.
    raw=bytearray(old.reader_code())
    needle=bytes.fromhex('83f803');at=raw.index(needle);raw[at:at+3]=bytes.fromhex('83f805')
    # Relocate only the stock relative CALL; all EBX-relative data stay fixed.
    original=old.READER_ENTRY;dest=READER
    from capstone import Cs,CS_ARCH_X86,CS_MODE_32
    for ins in Cs(CS_ARCH_X86,CS_MODE_32).disasm(bytes(raw),original):
        if ins.mnemonic=='call' and ins.bytes[0]==0xe8:
            target=ins.address+5+struct.unpack('<i',ins.bytes[1:])[0]
            if original<=target<original+len(raw):target+=dest-original
            struct.pack_into('<i',raw,ins.address-original+1,target-(dest+ins.address-original+5))
    # base() contains its self-relative image-base subtraction.
    at=raw.index(bytes.fromhex('e8000000005b81eb'))
    struct.pack_into('<I',raw,at+8,dest+at+5-0x400000)
    return bytes(raw)


def sound_code():
    # Periodic finite samples use the original sound callback and obey its
    # player volume settings. No OS audio API or indefinitely looping channel.
    c=Code(SOUND);c.emit('9c60');c.base()
    c.emit('f783');c.word(STATE+4);c.word(2);c.branch('0f84','no_start')
    c.emit('f783');c.word(STATE+8);c.word(2);c.branch('0f85','no_start')
    c.emit('8b83');c.word(STATE);c.emit('8983');c.word(STATE+16)
    c.emit('8d83');c.word(NAMES+0x2c0);c.call(0x6a1090)
    c.label('no_start')
    for bit,nameoff,lastoff,period in ((1,0x280,24,1000),(2,0x200,16,1000),(8,0x240,20,1000)):
        c.emit('f783');c.word(STATE+4);c.word(bit);c.branch('0f84','silent'+str(bit))
        c.emit('8b83');c.word(STATE);c.emit('2b83');c.word(STATE+lastoff)
        c.emit('3d');c.word(period);c.branch('0f82','silent'+str(bit))
        c.emit('8b83');c.word(STATE);c.emit('8983');c.word(STATE+lastoff)
        c.emit('8d83');c.word(NAMES+nameoff);c.call(0x6a1090)
        c.label('silent'+str(bit))
    c.emit('8b83');c.word(STATE+4);c.emit('8983');c.word(STATE+8)
    c.emit('619d c3');return c.finish(0x200)


def draw_code():
    c=Code(DRAW);c.call(0x814608);c.emit('9c60 83ec10');c.base()
    c.emit('8b83');c.word(0xac64a0-0x400000);c.emit('803800');c.branch('0f84','clear')
    c.emit('8b83');c.word(0xac5a30-0x400000);c.emit('80380b');c.branch('0f85','resources')
    c.emit('b80e000000');c.call(0xa6a610)
    c.label('resources')
    c.call(LOAD)
    c.emit('ff93');c.word(0xb79b10-0x400000) # Existing relocated GetTickCount IAT.
    c.emit('8983');c.word(STATE)
    c.emit('c783');c.word(STATE+4);c.word(0)
    c.emit('8db3');c.word(old.CELLS);c.emit('8bbb');c.word(old.COUNT)
    c.emit('85ff');c.branch('0f84','clear')
    c.label('loop')
    c.emit('0fb606 c1e005 83c010 890424 0fb64601 c1e005 83c010 89442404')
    c.emit('89e0 8d542404');c.call(0xa896f0)
    c.emit('8b83');c.word(0xac61b0-0x400000);c.emit('8b00 030424 890424')
    c.emit('8b83');c.word(0xac6068-0x400000);c.emit('8b00 03442404 89442404')
    c.emit('0fb64602 83f803');c.branch('0f84','recon')
    c.emit('83f801');c.branch('0f84','smoke')
    c.emit('83f804');c.branch('0f84','fire')
    c.emit('83f802');c.branch('0f84','flare')
    c.emit('8dab');c.word(ROWS+192)
    c.emit('c74424082080ff40 c744240c00000000');c.branch('e9','glow')
    c.label('smoke');c.emit('838b');c.word(STATE+4);c.emit('01')
    c.emit('8dab');c.word(ROWS)
    c.emit('c744240870a0a0a0 c744240c00000000');c.branch('e9','puff')
    c.label('fire');c.emit('838b');c.word(STATE+4);c.emit('08')
    c.emit('8dab');c.word(ROWS+128);c.emit('c7442408ffffffff');c.branch('e9','animated')
    c.label('flare');c.emit('838b');c.word(STATE+4);c.emit('02')
    c.emit('8dab');c.word(ROWS+64);c.emit('c7442408ffffffff')
    c.label('animated');c.emit('8b83');c.word(STATE)
    c.emit('31d2 b941000000 f7f1 0fb64e00 01c8 0fb64e01 01c8 83e01f 8944240c')
    c.emit('b920000000 ba30000000 807e0204');c.branch('0f85','sprite')
    c.emit('ba40000000');c.branch('e9','sprite')
    c.label('glow');c.emit('b940000000 ba20000000');c.branch('e9','sprite')
    c.label('puff');c.emit('8b83');c.word(STATE)
    c.emit('c1e807 0fb64e00 01c8 0fb64e01 01c8 83e00f 89c1 d1e0 29442404')
    c.emit('b80f000000 29c8 6bc007 83c010 c1e018 0da0a0a000 89442408')
    c.emit('83c128 89ca')
    c.label('sprite');c.emit('837d0000');c.branch('0f84','next')
    # Original Image_RenderEffectScaled: image record, x/y registers,
    # stack width,height,frame,tint,flags. Ground anchor is the sprite's foot.
    c.emit('51 52 8b0424 2944240c 8b442404 d1f8 29442408')
    c.emit('ff742414 ff742414 6a00') # frame, tint, flags from original locals.
    c.emit('8b542414 8b4c2418 89e8')
    c.call(0x4f2910);c.branch('e9','next')
    c.label('recon');c.emit('8b0424 83e808 8b542404 83ea05')
    c.emit('6a0a 68ffa85230 6a00 b910000000');c.call(0x4f2864)
    c.label('next');c.emit('83c603 4f');c.branch('0f85','loop')
    c.call(SOUND);c.branch('e9','done')
    c.label('clear');c.emit('c783');c.word(STATE+4);c.word(0)
    c.emit('c783');c.word(STATE+8);c.word(0)
    c.emit('c783');c.word(STATE+16);c.word(0)
    c.emit('c783');c.word(STATE+20);c.word(0)
    c.emit('c783');c.word(STATE+24);c.word(0)
    c.label('done');c.emit('83c410 619d c3')
    return c.finish(0x800)


def extension():
    data=bytearray(SIZE)
    for address,code in ((DRAW,draw_code()),(READER,reader_code()),(LOAD,load_code()),(SOUND,sound_code())):
        off=address-0x400000-RVA;data[off:off+len(code)]=code
    at=NAMES-RVA
    for i,(path,w,h,count) in enumerate(RESOURCES):
        # Silver and the native SDK accept Delphi UnicodeString, not ANSI.
        blob=path.encode('utf-16le');struct.pack_into('<HHiI',data,at,1200,2,-1,len(path));at+=12
        data[at:at+len(blob)+2]=blob+b'\0\0'
        # The loader output record is12 bytes; path pointer at+32.
        struct.pack_into('<I',data,ROWS-RVA+i*64+32,NAMES+at-(NAMES-RVA))
        at=(at+len(blob)+5)&~3
    # Each row needs its own path field, outside the native output record.
    # Sound pointers occupy fixed strings beyond texture paths.
    for offset,name in ((0x200,'tio_fx_flare'),(0x240,'tio_fx_fire'),(0x280,'tio_fx_smoke'),(0x2c0,'tio_fx_flare_start')):
        at=NAMES-RVA+offset;blob=name.encode('utf-16le');struct.pack_into('<HHiI',data,at-12,1200,2,-1,len(name));data[at:at+len(blob)+2]=blob+b'\0\0'
    data[-len(SIGNATURE):]=SIGNATURE
    return bytes(data)


def patch(source):
    if hashlib.sha256(source).hexdigest()!=BASE_SHA:raise ValueError('Exact published throwable base required')
    pe=pefile.PE(data=source);last=pe.sections[-1]
    if last.VirtualAddress+last.SizeOfRawData!=RVA or last.PointerToRawData+last.SizeOfRawData!=len(source):raise ValueError('Unsupported extension layout')
    result=bytearray(source)
    for site,target in ((old.DRAW_ENTRY,DRAW),(old.READER_ENTRY,READER)):
        at=pe.get_offset_from_rva(site-0x400000)
        result[at:at+5]=b'\xe9'+struct.pack('<i',target-site-5)
    result.extend(extension())
    for field in (8,16):struct.pack_into('<I',result,last.get_file_offset()+field,last.SizeOfRawData+SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+SIZE)
    return bytes(result)
