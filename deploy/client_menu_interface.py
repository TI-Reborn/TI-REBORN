"""A bounded native presentation patch against the published October 7 client.

The original controls, localization, callbacks, authorization and transport are
retained. Verified zero padding in the existing writable .tiochar section hosts
PIC presentation thunks; no section/file growth is needed. A separate doubled
font is selected only around marked menu calls, then the native slot is restored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile

BASE_SHA = '7137403658a66f8c9ee571960f29203bf6049d2722fa9719526049aec01670c1'
IMAGE_BASE = 0x400000
SECTION_RVA = 0x817000
RESOURCE_RVA = SECTION_RVA + 0xbd0
FRAME_RVA = SECTION_RVA + 0xbe0
FONT_RVA = SECTION_RVA + 0xbf0
CLIENT_BASE_RVA = SECTION_RVA + 0xbf4
NAME_RVA = SECTION_RVA + 0xb0c
FRAME_NAME_RVA = SECTION_RVA + 0xb4c
FONT_INDEX = 3
TAG = 0x43525553
ENTRIES = {name: IMAGE_BASE + SECTION_RVA + offset for name, offset in {
    'initialize':0x850, 'construct':0x920, 'caption':0x950,
    'measure':0x970, 'draw':0x39c, 'title':0x400, 'font_swap':0x470,
    'logo':0x66a, 'position':0x750, 'frame':0x780}.items()}


class Assembler:
    def __init__(self, address: int):
        self.address=address
        self.data=bytearray()
        self.labels={}
        self.fixups=[]

    def emit(self, hexadecimal: str):
        self.data.extend(bytes.fromhex(hexadecimal))

    def word(self, value: int):
        self.data.extend(struct.pack('<I',value & 0xffffffff))

    def relative(self, opcode: str, target: int):
        self.emit(opcode)
        self.word(target-(self.address+len(self.data)+4))

    def branch(self, opcode: str, label: str):
        self.emit(opcode)
        self.fixups.append((len(self.data),label))
        self.word(0)

    def label(self, name: str):
        self.labels[name]=len(self.data)

    def base(self):
        self.emit('e8 00000000 5b 81eb')
        self.word(self.address+len(self.data)-3-IMAGE_BASE)

    def finish(self):
        for at,label in self.fixups:
            struct.pack_into('<i',self.data,at,self.labels[label]-at-4)
        return bytes(self.data)


def thunks() -> dict[int, bytes]:
    result={}
    a=Assembler(ENTRIES['initialize'])
    a.emit('9c60');a.base()
    # Preserve all registers and the existing following resource-loader stack.
    a.emit('6a00 6a00 6a02 8d83');a.word(RESOURCE_RVA);a.emit('50')
    a.emit('b932000000 ba32000000 8d83');a.word(NAME_RVA)
    a.relative('e8',0x4f2cb4)
    a.emit('6a00 6a00 6a02 8d83');a.word(FRAME_RVA);a.emit('50')
    a.emit('b920000000 ba20000000 8d83');a.word(FRAME_NAME_RVA)
    a.relative('e8',0x4f2cb4)
    # The registered TextOut callback belongs to the immutable native ti.exe.
    # Derive its load base rather than assuming where Windows mapped it.
    a.emit('8bb300586c00 8b36 81ee94be3100 89b3');a.word(CLIENT_BASE_RVA)
    a.emit('8b8680e13600 8b00 8d93');a.word(SECTION_RVA+0xb80)
    a.emit('8d8b');a.word(SECTION_RVA+0xba0)
    a.emit('8dbec8ec2f00 ffd7 8983');a.word(FONT_RVA)
    a.emit('619d 6a00 6a00 6a02')
    a.relative('e9',0xa62db5)
    result[ENTRIES['initialize']]=a.finish()

    a=Assembler(ENTRIES['construct'])
    a.emit('53');a.base();a.emit('8d8b');a.word(RESOURCE_RVA);a.emit('5b')
    # Tail-call: native constructor still receives the original parent argument.
    a.relative('e9',0xa4517c)
    result[ENTRIES['construct']]=a.finish()

    a=Assembler(ENTRIES['caption'])
    a.relative('e8',0xa42b04)
    # CaptionX is unused because CaptionOffsets is false on these five controls.
    a.emit('c783d0020000');a.word(TAG);a.emit('c3')
    result[ENTRIES['caption']]=a.finish()

    a=Assembler(ENTRIES['measure'])
    a.emit('50 8b03 81b8d0020000');a.word(TAG)
    a.branch('0f85','normal');a.emit('58')
    a.relative('e8',ENTRIES['font_swap']);a.emit('b103 ff742404')
    a.relative('e8',0x675578);a.relative('e8',ENTRIES['font_swap']);a.emit('c20400')
    a.label('normal');a.emit('58')
    a.relative('e9',0x675578)
    result[ENTRIES['measure']]=a.finish()

    a=Assembler(ENTRIES['draw'])
    a.emit('52 8b13 81bad0020000');a.word(TAG)
    a.branch('0f85','normal');a.emit('5a')
    a.relative('e8',ENTRIES['font_swap']);a.emit('b003 ff742408 ff742408')
    a.relative('e8',0x4f2a0c);a.relative('e8',ENTRIES['font_swap']);a.emit('c20800')
    a.label('normal');a.emit('5a')
    a.relative('e9',0x4f2a0c)
    result[ENTRIES['draw']]=a.finish()

    a=Assembler(ENTRIES['title'])
    # The separately loaded texture identifies this menu even if an ingame
    # dialog happens to have the same dimensions. Preserve call registers.
    a.emit('50 52 53');a.base();a.emit('8b0424 8b93');a.word(FRAME_RVA)
    a.emit('399038030000 5b 5a 58');a.branch('0f85','normal')
    a.relative('e8',ENTRIES['font_swap'])
    a.emit('8b4b30 81c1c0000000 50 8b4334 83c016 8944240c 58')
    a.emit('b003 ff742408 ff742408')
    a.relative('e8',0x4f2a0c);a.relative('e8',ENTRIES['font_swap']);a.emit('c20800')
    a.label('normal');a.relative('e9',0x4f29a8)
    result[ENTRIES['title']]=a.finish()

    a=Assembler(ENTRIES['font_swap'])
    a.emit('60');a.base()
    a.emit('8b83');a.word(FONT_RVA);a.emit('83f8ff');a.branch('0f84','done')
    a.emit('8b93');a.word(CLIENT_BASE_RVA)
    a.emit('8b9288e63600 8702 8983');a.word(FONT_RVA)
    a.label('done');a.emit('61 c3');result[ENTRIES['font_swap']]=a.finish()

    a=Assembler(ENTRIES['logo'])
    a.emit('53 56 57 89c6');a.base()
    a.emit('8bbb');a.word(0x6c56e0);a.emit('8b3f 6bcf0f c1e905 81f980020000')
    a.branch('0f8e','width');a.emit('b980020000');a.label('width')
    a.emit('51 89c8 0fb75606 0fafc2 0fb74e04 31d2 f7f1 59')
    a.emit('51 50 6a00 6a00 89fa 29ca d1fa b914000000 89f0')
    a.relative('e8',0x4f28d4);a.emit('5f 5e 5b c20800')
    result[ENTRIES['logo']]=a.finish()

    a=Assembler(ENTRIES['position'])
    a.emit('81f9c2010000');a.branch('0f8d','normal')
    # On the native 800x600 option keep a sixteen-pixel bottom margin too.
    # ECX initially contains half the framebuffer height; preserve X in EDX.
    a.emit('52 8d940910ffffff 83c160 39d1');a.branch('0f8e','fits')
    a.emit('89d1');a.label('fits');a.emit('5a')
    a.label('normal');a.relative('e9',0xa69d7c);result[ENTRIES['position']]=a.finish()

    a=Assembler(ENTRIES['frame'])
    a.relative('e8',0xa4341c);a.emit('53');a.base()
    a.emit('8b93');a.word(FRAME_RVA);a.emit('899038030000')
    a.emit('8b93');a.word(FRAME_RVA+4);a.emit('89903c030000')
    a.emit('8b93');a.word(FRAME_RVA+8);a.emit('899040030000 5b c3')
    result[ENTRIES['frame']]=a.finish()
    return result


def edit_specifications() -> list[tuple[int,bytes,bytes,str]]:
    out=[]
    def change(va,old,new,reason):
        if len(old)!=len(new):raise ValueError('Presentation changes must retain length')
        out.append((va,old,new,reason))
    def call(va,target,new,reason):
        change(va,b'\xe8'+struct.pack('<i',target-va-5),b'\xe8'+struct.pack('<i',new-va-5),reason)
    def scalar(va,old,new,reason):
        change(va,struct.pack('<I',old),struct.pack('<I',new),reason)
    for va,code in thunks().items():
        change(va,bytes(len(code)),code,'Presentation thunk in verified .tiochar padding')
    name='pda\\menubutton.png'
    constant=struct.pack('<III',0x000204b0,0xffffffff,len(name))+name.encode('utf-16le')+b'\0\0'
    change(IMAGE_BASE+SECTION_RVA+0xb00,bytes(len(constant)),constant,'Native Unicode texture constant')
    name='pda\\menuframe.png'
    constant=struct.pack('<III',0x000204b0,0xffffffff,len(name))+name.encode('utf-16le')+b'\0\0'
    change(IMAGE_BASE+SECTION_RVA+0xb40,bytes(len(constant)),constant,'Separate main-menu frame texture constant')
    for offset,name in ((0xb80,'base/fonts/menu.xml'),(0xba0,'base/fonts/menu.png')):
        constant=bytes([len(name)])+name.encode('ascii')+b'\0'
        change(IMAGE_BASE+SECTION_RVA+offset,bytes(len(constant)),constant,'Native ShortString filename for scoped font')
    # The resource struct is deliberately kept zero until native initialization.
    change(0xa62daf,bytes.fromhex('6a006a006a02'),b'\xe9'+struct.pack('<i',ENTRIES['initialize']-0xa62daf-5)+b'\x90','Load the separate 50px main-menu button atlas')
    scalar(0x8890d9,176,384,'Main-menu window width')
    scalar(0x8890de,288,448,'Main-menu window height')
    call(0x8890c4,0xa4341c,ENTRIES['frame'],'Separate thick frame on main menu only')
    call(0x888f37,0xa69d7c,ENTRIES['position'],'Keep the main menu below the logo at smaller viewport heights')
    call(0x9de662,0x4f2788,ENTRIES['logo'],'Scale the title to at most 46.875 percent of viewport width, capped at640px')
    for va in (0x88917e,0x8891f4,0x88926a,0x8892e0,0x889356):
        scalar(va,125,300,'Main-menu live button width')
    for va,old,new in ((0x88919e,32,64),(0x889214,80,136),(0x88928a,128,208),(0x889300,176,280),(0x889376,224,352)):
        scalar(va,old,new,'Main-menu live button vertical position')
    for va in (0x889154,0x8891ca,0x889240,0x8892b6,0x88932c):
        call(va,0xa4517c,ENTRIES['construct'],'Use separate 50px main-menu resource while retaining the constructor')
    for va in (0x889178,0x8891ee,0x889264,0x8892da,0x889350):
        call(va,0xa42b04,ENTRIES['caption'],'Mark only the five main-menu controls for nice-font rendering')
    call(0xa4564f,0x675578,ENTRIES['measure'],'Measure marked captions using separate doubled font and restore native slot')
    call(0xa456d5,0x4f2a0c,ENTRIES['draw'],'Draw marked enabled captions using separate doubled font and restore native slot')
    call(0xa45742,0x4f2a0c,ENTRIES['draw'],'Draw marked disabled captions using separate doubled font and restore native slot')
    call(0xa438c0,0x4f29a8,ENTRIES['title'],'Center enlarged title on the main menu only')
    change(0xa4389e,b'\x03',b'\x09','Shared native titles sit below the eight-pixel decorative border')
    # Keep both existing relocation locations intact, avoiding stale relocations
    # on padding. Height is the whole framebuffer rather than an old sub-rect.
    change(0x9de543,bytes.fromhex('a14c5aac008b400c8b154c5aac002b4204'),
           bytes.fromhex('a1605eac008b00908b15605eac00909090'),
           'Cover the complete viewport at 4:3 and 16:9')
    return sorted(out,key=lambda item:item[0])


def patch(data: bytes) -> bytes:
    # Exact reverse verification makes a future full release idempotent while
    # refusing arbitrary later binaries. Older recognized clients compose the
    # already-published appearance, inventory and own-merc exchange patches.
    if hashlib.sha256(data).hexdigest()!=BASE_SHA:
        candidate=bytearray(data)
        pe=pefile.PE(data=data)
        try:
            for va,old,new,_ in edit_specifications():
                offset=pe.get_offset_from_rva(va-IMAGE_BASE)
                if data[offset:offset+len(new)]!=new:
                    raise ValueError('Not this complete native interface patch')
                candidate[offset:offset+len(old)]=old
            if hashlib.sha256(candidate).hexdigest()==BASE_SHA:
                return data
        except (ValueError,pefile.PEFormatError):
            pass
        from .client_battle_exchange import patch as previous
        try:
            data=previous(data)
        except (AssertionError,ValueError,pefile.PEFormatError) as error:
            raise ValueError('Expected the exact published 2026.10.07.3 silver.dll') from error
        if hashlib.sha256(data).hexdigest()!=BASE_SHA:
            raise ValueError('Expected the exact published 2026.10.07.3 silver.dll')
    pe=pefile.PE(data=data)
    section=pe.sections[-1]
    if (section.Name.rstrip(b'\0')!=b'.tiochar' or section.VirtualAddress!=SECTION_RVA
            or section.SizeOfRawData!=0xc00 or section.Characteristics & 0xe0000000!=0xe0000000):
        raise ValueError('Unexpected client presentation section')
    result=bytearray(data)
    end=-1
    for va,old,new,_ in edit_specifications():
        offset=pe.get_offset_from_rva(va-IMAGE_BASE)
        if offset<end:raise ValueError('Overlapping patch sites')
        if data[offset:offset+len(old)]!=old:
            raise ValueError('Unexpected native presentation bytes at '+hex(va))
        result[offset:offset+len(new)]=new
        end=offset+len(new)
    return bytes(result)


def patch_plan(previous: bytes, updated: bytes) -> dict:
    if patch(previous)!=updated:raise ValueError('Updated binary does not match bounded presentation patch')
    pe=pefile.PE(data=previous)
    changes=[]
    for va,old,new,reason in edit_specifications():
        changes.append(dict(offset=pe.get_offset_from_rva(va-IMAGE_BASE),previous_hex=old.hex(),updated_hex=new.hex(),native_va=hex(va),reason=reason))
    changes.sort(key=lambda row:row['offset'])
    return dict(path='silver.dll',previous_sha256=BASE_SHA,updated_sha256=hashlib.sha256(updated).hexdigest(),changes=changes,
                retained_native_callbacks=[hex(x) for x in (0x888fa4,0x88903c,0x888fdc,0x883130,0x888fb4)],
                new_textures=['base/pda/menubutton.png','base/pda/menuframe.png'],
                font_scope='Dedicated doubled menu font selected only around marked menu/title callbacks; original slot immediately restored')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    args=parser.parse_args()
    previous=args.source.read_bytes();updated=patch(previous)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_bytes(updated)
    args.plan.parent.mkdir(parents=True,exist_ok=True)
    args.plan.write_text(json.dumps(patch_plan(previous,updated),indent=2)+'\n',encoding='utf-8')
    print(hashlib.sha256(updated).hexdigest())
