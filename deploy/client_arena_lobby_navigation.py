"""Keep arena Team/Wall list navigation usable with an empty filtered roster.

The real mercenary-selector previously disabled all three tabs until an
eligible selected fighter existed. Only mode4 (arena entry) Team/Wall browsing
is enabled here. Survival, fighter selection and every battle request remain
original; the hosted server continues to enforce roster admission.
"""
from __future__ import annotations
import struct
import pefile
from .client_equipment_batch import Code
from .client_server_list_status import sha, call_bytes

BASE_SHA='853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1'
IMAGE_BASE=0x400000
APPEND_RVA=0x878000
APPEND_SIZE=0x1000
OPEN_HELPER=IMAGE_BASE+APPEND_RVA
EMPTY_HELPER=OPEN_HELPER+0x100
BA_COLOUR_HELPER=OPEN_HELPER+0x200
C8_COLOUR_HELPER=OPEN_HELPER+0x400
MODE=0xac4a84-IMAGE_BASE
TEAM=0xad0430-IMAGE_BASE
WALL=0xad042c-IMAGE_BASE
SIGNATURE=b'TIO-arena-Team-Wall-navigation-owned-roster-colours-v2'
GREEN=0xff50e070
GRAY=0xff606060
RELOCATIONS=((7566920,0x36df),(7568420,0x32e4),(7568422,0x32ed))


def endpoints(c, continuation):
    c.emit('c6462800 b8'); c.word(GREEN)
    c.emit('8a561d 3a561c'); c.branch('0f82','colour')
    c.emit('b8'); c.word(GRAY)
    c.label('colour'); c.emit('894624'); c.jump(continuation)


def ba_colour():
    c=Code(BA_COLOUR_HELPER)
    # BA02 carries no stake field. Scope precisely to Team/Wall categories.
    c.emit('807e1001'); c.branch('0f84','owned')
    c.emit('807e1004'); c.branch('0f84','owned')
    c.emit('0fb6461a 3b45fc'); c.branch('0f8f','red')
    c.emit('0fb6461b 3b45fc'); c.branch('0f8c','red')
    c.jump(0x872ab2)
    c.label('owned'); c.emit('9c60'); c.base()
    c.emit('8b93'); c.word(0xac618c-IMAGE_BASE)
    c.emit('b91f000000')
    c.label('slot'); c.emit('8b02 85c0'); c.branch('0f84','next')
    c.emit('80784100'); c.branch('0f84','next')
    c.emit('8b80fc5f0000 83f801'); c.branch('0f82','next')
    c.emit('83f814'); c.branch('0f87','next')
    c.emit('0fb65e1a 3bc3'); c.branch('0f82','next')
    c.emit('0fb65e1b 3bc3'); c.branch('0f86','eligible')
    c.label('next'); c.emit('83c204 49'); c.branch('0f85','slot')
    c.emit('619d'); c.jump(0x872aed)
    c.label('eligible'); c.emit('619d'); endpoints(c,0x872af8)
    c.label('red'); c.jump(0x872aed)
    return c.finish(0x200)


def c8_colour():
    c=Code(C8_COLOUR_HELPER)
    c.emit('807e1001'); c.branch('0f84','ordinary')
    c.emit('807e1004'); c.branch('0f85','stock')
    c.label('ordinary'); c.emit('837e2c00'); c.branch('0f85','stock')
    endpoints(c,0x872ca0)
    c.label('stock')
    c.emit('0fb6461b 2b45fc 8945ec 837dec05'); c.branch('0f8d','five')
    c.emit('8b45ec 8945e8'); c.branch('e9','blend')
    c.label('five'); c.emit('c745e805000000')
    c.label('blend'); c.emit('6b4de829 badbefb100 b8ff606000'); c.call(0xa897c8)
    c.emit('894624'); c.jump(0x872ca0)
    return c.finish(0x200)


def payload():
    c=Code(OPEN_HELPER); c.emit('9c60'); c.base()
    c.emit('8b44241c 8883'); c.word(MODE)  # Original completed selector mode write.
    c.emit('3c04'); c.branch('0f85','done')
    for field in (TEAM,WALL):
        c.emit('8b83'); c.word(field); c.emit('c6404a01')
    c.label('done'); c.emit('619d c3')
    result=c.finish(0x100)
    c=Code(EMPTY_HELPER); c.emit('9c 53 52'); c.base()
    c.emit('80bb'); c.word(MODE); c.emit('04 0f94c2')
    for field in (TEAM,WALL):
        c.emit('8b83'); c.word(field); c.emit('88504a')
    c.emit('5a 5b 9d'); c.jump(0x9442f5)
    return (result+c.finish(0x100)+ba_colour()+c8_colour()+SIGNATURE+b'\0').ljust(APPEND_SIZE,b'\0')


def specifications():
    return (
        (0x9406de,bytes.fromhex('a2844aac00'),call_bytes(0x9406de,OPEN_HELPER),
         'After genuine selector setup, enable arena mode4 Team/Wall browsing even with zero eligible fighters'),
        (0x9442e3,bytes.fromhex('a13004ad00 c6404a00 a12c04ad00 c6404a00'),
         b'\xe9'+struct.pack('<i',EMPTY_HELPER-0x9442e3-5)+b'\x90'*13,
         'Empty-roster state keeps Team/Wall enabled only in arena selector mode4; Survival remains disabled'),
        (0x872aa0,bytes.fromhex('0fb6461a3b45fc7f440fb6461b3b45fc7c3b'),
         b'\xe9'+struct.pack('<i',BA_COLOUR_HELPER-0x872aa0-5)+b'\x90'*13,
         'Actual BA02 Team/Wall rows inspect all owned fighters, and show green/free, red/ineligible, gray/full'),
        (0x872c6b,bytes.fromhex('0fb6461b2b45fc8945ec837dec057d088b45ec8945e8eb07c745e8050000006b4de829badbefb100b8ff606000e82b6b2100894624'),
         b'\xe9'+struct.pack('<i',C8_COLOUR_HELPER-0x872c6b-5)+b'\x90'*48,
         'Typed C82C ordinary Team/Wall eligible rows use same clear green/free and gray/full endpoints'),
    )


def patch(data):
    if sha(data)!=BASE_SHA:
        raise ValueError('Arena navigation requires exact published status/freshness Silver')
    p=pefile.PE(data=data)
    try:
        last=p.sections[-1]
        if (len(p.sections)!=13 or p.OPTIONAL_HEADER.ImageBase!=IMAGE_BASE
                or p.OPTIONAL_HEADER.SizeOfImage!=APPEND_RVA
                or last.Name!=b'.tioscr\0' or last.VirtualAddress!=0x823000
                or last.Misc_VirtualSize!=0x55000 or last.SizeOfRawData!=0x55000
                or last.PointerToRawData!=0x76b200
                or last.PointerToRawData+last.SizeOfRawData!=len(data)):
            raise ValueError('Arena navigation PE geometry differs')
        result=bytearray(data)
        # Original absolute MOV operands are replaced by relative branches.
        # Retain the relocation block geometry and neutralize only those three
        # obsolete HIGHLOW entries; otherwise rebasing corrupts branch offsets.
        for offset,expected in RELOCATIONS:
            if struct.unpack_from('<H',data,offset)[0]!=expected:
                raise ValueError('Arena replaced operand relocation differs')
            struct.pack_into('<H',result,offset,expected&0xfff)
        for va,old,new,_ in specifications():
            if len(old)!=len(new) or p.get_data(va-IMAGE_BASE,len(old))!=old:
                raise ValueError('Arena selector native presentation differs: '+hex(va))
            at=p.get_offset_from_rva(va-IMAGE_BASE);result[at:at+len(new)]=new
        for field in ('Misc_VirtualSize','SizeOfRawData'):
            struct.pack_into('<I',result,last.get_field_absolute_offset(field),getattr(last,field)+APPEND_SIZE)
        struct.pack_into('<I',result,p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),APPEND_RVA+APPEND_SIZE)
        result.extend(payload());return bytes(result)
    finally:
        p.close()


def review(source,candidate):
    if patch(source)!=candidate:
        raise ValueError('Candidate differs from exact arena navigation transformer')
    p=pefile.PE(data=source)
    try:
        ranges=[(p.get_offset_from_rva(a-IMAGE_BASE),len(old),why) for a,old,_,why in specifications()]
        ranges += [(p.sections[-1].get_field_absolute_offset(f),4,'Extend final section for bounded native navigation helpers')
                   for f in ('Misc_VirtualSize','SizeOfRawData')]
        ranges += [(p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),4,'Map appended arena presentation helpers')]
        ranges += [(offset,2,'Neutralize obsolete absolute operand relocation replaced by PIC relative branch')
                   for offset,_ in RELOCATIONS]
        return dict(changes=[dict(offset=a,size=n,purpose=why,source_sha256=sha(source[a:a+n]),candidate_sha256=sha(candidate[a:a+n]))
                             for a,n,why in sorted(ranges)],appended_size=APPEND_SIZE,appended_sha256=sha(candidate[len(source):]))
    finally:
        p.close()


def metadata():
    return dict(source_sha256=BASE_SHA,selector_mode=4,team_enabled_field='ad0430+4a',wall_enabled_field='ad042c+4a',
                survival_field_unchanged='ad0428+4a',navigation_callbacks_original=['9443d0','944434'],
                roster_selection_unchanged=True,create_search_join_writers_unchanged=True,
                authoritative_admission='Original hosted healthy owned fighter level/roster checks',
                previous_authentication_status_availability_textures_preserved=True,published=False)
