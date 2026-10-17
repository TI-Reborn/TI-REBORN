"""Scoped FB rain presentation after the exact published throwable release."""
import hashlib,struct,pefile
from .client_equipment_batch import Code
from . import client_battle_items as old
from . import client_throwable_effects as fx
BASE_SHA='5f2eb65cede38dc146c0656a35d1ed27c45dec2175ba97c2c7d7ea2c3bbbbac9'
RVA=0x87c000;SIZE=0x4000
DRAW=0x400000+RVA;READER=DRAW+0x400;LOAD=DRAW+0x800;SOUND=DRAW+0xa00
CELLS=RVA+0x1000;COUNT=RVA+0x3000;THUNDER=COUNT+4;PREVIOUS=COUNT+8;LAST=COUNT+12;TICK=COUNT+16
ROW=RVA+0x3040;PATH=RVA+0x3100;LOOP=RVA+0x3180;RUMBLE=RVA+0x31c0


def reader():
    c=Code(READER);c.emit('3cfb');c.branch('0f85','stock');c.emit('9c60');c.base()
    c.emit('c783');c.word(COUNT);c.word(0)
    c.emit('83f909');c.branch('0f82','done');c.emit('803a01');c.branch('0f85','done')
    c.emit('807a0101');c.branch('0f87','done')
    c.emit('0fb77206 81fe00100000');c.branch('0f87','done')
    c.emit('8d0475 09000000 39c8');c.branch('0f85','done')
    c.emit('807a0100');c.branch('0f85','wet')
    c.emit('85f6');c.branch('0f85','done');c.emit('837a0200');c.branch('0f85','done')
    c.label('wet');c.emit('89f1 8d7a08 85c9');c.branch('0f84','copy')
    c.label('check');c.emit('803fff');c.branch('0f84','done');c.emit('807f01ff');c.branch('0f84','done')
    c.emit('83c702 49');c.branch('0f85','check')
    c.label('copy');c.emit('8b4202 8983');c.word(THUNDER);c.emit('89b3');c.word(COUNT)
    c.emit('8dbb');c.word(CELLS);c.emit('8d0c36 8d7208 fc f3a4')
    c.label('done');c.emit('c744241c01000000 619d c3')
    c.label('stock');c.call(0xc20200);c.emit('c3');return c.finish(0x400)


def load():
    c=Code(LOAD);c.emit('9c60');c.base();c.emit('83bb');c.word(ROW);c.emit('00');c.branch('0f85','done')
    c.emit('6a00 6a00 6a02 8d83');c.word(ROW);c.emit('50 b940000000 ba40000000 8d83');c.word(PATH);c.call(0x4f2cb4)
    c.label('done');c.emit('619d c3');return c.finish(0x200)


def sound():
    c=Code(SOUND);c.emit('9c60');c.base()
    c.emit('8b83');c.word(TICK);c.emit('2b83');c.word(LAST);c.emit('3de8030000');c.branch('0f82','thunder')
    c.emit('8b83');c.word(TICK);c.emit('8983');c.word(LAST);c.emit('8d83');c.word(LOOP);c.call(0x6a1090)
    c.label('thunder');c.emit('8b83');c.word(THUNDER);c.emit('3b83');c.word(PREVIOUS);c.branch('0f84','done')
    c.emit('8983');c.word(PREVIOUS);c.emit('85c0');c.branch('0f84','done')
    c.emit('8d83');c.word(RUMBLE);c.call(0x6a1090)
    c.label('done');c.emit('619d c3');return c.finish(0x200)


def draw():
    c=Code(DRAW);c.call(fx.DRAW);c.emit('9c60 83ec08');c.base()
    c.emit('8b83');c.word(0xac64a0-0x400000);c.emit('803800');c.branch('0f84','clear')
    c.emit('8bbb');c.word(COUNT);c.emit('85ff');c.branch('0f84','quiet')
    c.call(LOAD)
    c.emit('83bb');c.word(ROW);c.emit('00');c.branch('0f84','done')
    c.emit('ff93');c.word(0xb79b10-0x400000);c.emit('8983');c.word(TICK)
    c.emit('8db3');c.word(CELLS)
    c.label('loop');c.emit('0fb606 c1e005 83c010 890424 0fb64601 c1e005 83c010 89442404')
    c.emit('89e0 8d542404');c.call(0xa896f0)
    c.emit('8b83');c.word(TICK);c.emit('c1e803 0fb64e00 6bc91d 01c8 0fb64e01 6bc92f 01c8 83e03f 83e830 01442404')
    c.emit('8b93');c.word(0xac6068-0x400000);c.emit('8b12 03542404 83ea20')
    c.emit('8b83');c.word(0xac61b0-0x400000);c.emit('8b00 030424 83e804')
    # Native Image_RenderEffectScaled: record,x,y registers and five stack args.
    c.emit('6a08 6a20 6a00 68b0d0e080 6a00 89d1 89c2 8d83');c.word(ROW);c.call(0x4f2910)
    c.emit('83c602 4f');c.branch('0f85','loop');c.call(SOUND);c.branch('e9','done')
    c.label('clear');c.emit('c783');c.word(COUNT);c.word(0)
    c.label('quiet');c.emit('c783');c.word(PREVIOUS);c.word(0)
    c.label('done');c.emit('83c408 619d c3');return c.finish(0x400)


def patch(source):
    if hashlib.sha256(source).hexdigest()!=BASE_SHA:raise ValueError('Exact hosted rain base required')
    pe=pefile.PE(data=source);last=pe.sections[-1]
    if last.VirtualAddress+last.SizeOfRawData!=RVA or last.PointerToRawData+last.SizeOfRawData!=len(source):raise ValueError('Unsupported rain extension layout')
    data=bytearray(SIZE)
    for address,code in ((DRAW,draw()),(READER,reader()),(LOAD,load()),(SOUND,sound())):
        offset=address-0x400000-RVA;data[offset:offset+len(code)]=code
    for offset,name in ((PATH,'gfx\\rain.tga'),(LOOP,'tio_weather_rain'),(RUMBLE,'tio_weather_thunder')):
        at=offset-RVA;blob=name.encode();struct.pack_into('<ii',data,at-8,-1,len(blob));data[at:at+len(blob)+1]=blob+b'\0'
    data[-24:]=b'TIO-rain-only-FB-v1'.ljust(24,b'\0')
    result=bytearray(source)
    for at,before,target in ((0x9f40ae,old.DRAW_ENTRY,DRAW),(0x9f5563,0xc20200,READER)):
        off=pe.get_offset_from_rva(at-0x400000);assert result[off:off+5]==b'\xe8'+struct.pack('<i',before-at-5)
        result[off:off+5]=b'\xe8'+struct.pack('<i',target-at-5)
    result.extend(data)
    for field in (8,16):struct.pack_into('<I',result,last.get_file_offset()+field,last.SizeOfRawData+SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+SIZE)
    return bytes(result)
