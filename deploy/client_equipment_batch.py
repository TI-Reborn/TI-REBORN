"""Checked client release extension for emulator-only equipment F6/v1.

Native city/medical action33 stays intact. Only battle metadata types1/9
(weapon/armor) become private stage requests; native inventory OK explicitly
commits them before performing its original local close. patch() returns a
candidate PE and never edits an installed DLL or a published manifest.
"""
import hashlib
import struct
import pefile
from .client_battle_exchange import RVA

# Filled from the complete previous release chain, never just a marker check.
BASE_SHA='2d9e0f83b3ff94ef2c7ac5df2d396cd7b7a55a7ac03168c0ef252e977b75b359'
STAGE_HOOK=0x990500
OK_HOOK=0x9ba07e
INIT_HOOK=0x9ba0fd
HIDE_HOOK=0xa43b0e
STAGE_ENTRY=0x400000+RVA+0xc00
OK_ENTRY=0x400000+RVA+0xe00
INIT_ENTRY=0x400000+RVA+0x1000
HIDE_ENTRY=0x400000+RVA+0x1100
COUNTER=RVA+0xff0
ACTIVE=RVA+0xff4
WINDOW=RVA+0xff8
SIGNATURE=b'TIO-equipment-F6-v1'


class Code:
    def __init__(self,address):self.address=address;self.data=bytearray();self.labels={};self.fixups=[]
    def emit(self,value):self.data.extend(bytes.fromhex(value))
    def word(self,value):self.data.extend(struct.pack('<I',value&0xffffffff))
    def call(self,target):self.emit('e8');self.word(target-(self.address+len(self.data)+4))
    def jump(self,target):self.emit('e9');self.word(target-(self.address+len(self.data)+4))
    def branch(self,opcode,label):self.emit(opcode);self.fixups.append((len(self.data),label));self.word(0)
    def label(self,name):self.labels[name]=len(self.data)
    def base(self):
        self.emit('e800000000 5b 81eb');self.word(self.address+len(self.data)-3-0x400000)
    def finish(self,size):
        for at,label in self.fixups:struct.pack_into('<i',self.data,at,self.labels[label]-at-4)
        if len(self.data)>size:raise ValueError('Equipment client wrapper overflow')
        return bytes(self.data).ljust(size,b'\0')


def stage_code():
    c=Code(STAGE_ENTRY);c.emit('9c60');c.base()
    c.emit('8b93');c.word(0xac64a0-0x400000)
    c.emit('803a00');c.branch('0f84','stock')
    # The original frame copied the selected item to EBP-290. Reuse native
    # metadata indexing; neither city equipment nor consumed items is staged.
    c.emit('8d8570fdffff');c.call(0xa7b030)
    c.emit('69c04f070000 8b93');c.word(0xac637c-0x400000)
    c.emit('8b12 0fb784c218010000 83f801');c.branch('0f84','equipment')
    c.emit('83f809');c.branch('0f85','stock')
    c.label('equipment')
    c.emit('80bb');c.word(ACTIVE);c.emit('00');c.branch('0f85','write')
    c.emit('ff83');c.word(COUNTER)
    c.emit('83bb');c.word(COUNTER);c.emit('00');c.branch('0f85','nonzero')
    c.emit('ff83');c.word(COUNTER)
    c.label('nonzero');c.emit('c683');c.word(ACTIVE);c.emit('01')
    c.label('write')
    c.emit('8b74241c 89f0 b2f6');c.call(0x675bf8)
    c.emit('89f0 b201');c.call(0x675bf8)
    c.emit('89f0 31d2');c.call(0x675bf8)
    c.emit('89f0 8b93');c.word(COUNTER);c.call(0x6ac248)
    # The native writer returns a handle pointing at the transport object.
    # Preserve it for original990507; actor/item/option and flush stay native.
    c.emit('8944241c 619d');c.jump(0x990507)
    c.label('stock');c.emit('619d b233');c.call(0x675bf8);c.jump(0x990507)
    return c.finish(0x200)


def ok_code():
    c=Code(OK_ENTRY);c.emit('9c60');c.base()
    c.emit('8b93');c.word(0xac64a0-0x400000)
    c.emit('803a00');c.branch('0f84','clear')
    c.emit('80bb');c.word(ACTIVE);c.emit('00');c.branch('0f84','close')
    c.emit('8b83');c.word(0xac600c-0x400000)
    c.emit('8b00');c.call(0x6748b0);c.emit('8b30 89f0 b2f6');c.call(0x675bf8)
    c.emit('89f0 b201');c.call(0x675bf8)
    c.emit('89f0 b201');c.call(0x675bf8)
    c.emit('89f0 8b93');c.word(COUNTER);c.call(0x6ac248)
    c.emit('89f0 8b10 ff12')  # Same native transport Flush virtual call.
    c.label('clear');c.emit('c683');c.word(ACTIVE);c.emit('00')
    c.label('close');c.emit('619d');c.call(0xa4370c);c.emit('c3')
    return c.finish(0x1c0)


def cancel_write(c):
    c.emit('8b93');c.word(0xac64a0-0x400000)
    c.emit('803a00');c.branch('0f84','clear')
    c.emit('8b83');c.word(0xac600c-0x400000)
    c.emit('8b00');c.call(0x6748b0);c.emit('8b30 89f0 b2f6');c.call(0x675bf8)
    c.emit('89f0 b201');c.call(0x675bf8)
    c.emit('89f0 b202');c.call(0x675bf8)
    c.emit('89f0 8b93');c.word(COUNTER);c.call(0x6ac248)
    c.emit('89f0 8b10 ff12')


def init_code():
    # This exact constructor call writes window_inventory's name at +68.
    # Store the concrete object so generic OnHide cannot affect another UI.
    c=Code(INIT_ENTRY);c.emit('9c60');c.base()
    c.emit('8b44241c 83e868 8983');c.word(WINDOW)
    # An inventory reconstructed while its predecessor has pending choices
    # abandons that lease explicitly, including nonce reset after reconnect.
    c.emit('80bb');c.word(ACTIVE);c.emit('00');c.branch('0f84','close')
    cancel_write(c)
    c.label('clear');c.emit('c683');c.word(ACTIVE);c.emit('00')
    c.label('close');c.emit('619d');c.call(0x40b47c);c.emit('c3')
    return c.finish(0x100)


def hide_code():
    c=Code(HIDE_ENTRY);c.emit('9c60');c.base()
    # Original OnHide receives &window.event (+2E8). A hide from Escape,
    # window close or another modal cancels only this inventory's lease.
    c.emit('8b44241c 2de8020000 3b83');c.word(WINDOW)
    c.branch('0f85','close')
    c.emit('80bb');c.word(ACTIVE);c.emit('00');c.branch('0f84','close')
    cancel_write(c)
    c.label('clear');c.emit('c683');c.word(ACTIVE);c.emit('00')
    c.label('close');c.emit('619d');c.call(0xa54980);c.emit('c3')
    return c.finish(0x100)


def extension():
    result=stage_code()+ok_code()+SIGNATURE
    return result.ljust(0x400,b'\0')+init_code()+hide_code()+b'\0'*0x200


def sites():
    return ((STAGE_HOOK,b'\xb2\x33\xe8'+struct.pack('<i',0x675bf8-0x990502-5),
             b'\xe9'+struct.pack('<i',STAGE_ENTRY-STAGE_HOOK-5)+b'\x90\x90'),
            (OK_HOOK,b'\xe8'+struct.pack('<i',0xa4370c-OK_HOOK-5),
             b'\xe8'+struct.pack('<i',OK_ENTRY-OK_HOOK-5)),
            (INIT_HOOK,b'\xe8'+struct.pack('<i',0x40b47c-INIT_HOOK-5),
             b'\xe8'+struct.pack('<i',INIT_ENTRY-INIT_HOOK-5)),
            (HIDE_HOOK,b'\xe8'+struct.pack('<i',0xa54980-HIDE_HOOK-5),
             b'\xe8'+struct.pack('<i',HIDE_ENTRY-HIDE_HOOK-5)))


def patch(data):
    try:pe=pefile.PE(data=data)
    except pefile.PEFormatError as error:raise ValueError('Unsupported equipment client PE') from error
    if SIGNATURE in data:
        section=pe.sections[-1];original=bytearray(data)
        if (section.VirtualAddress!=RVA or section.SizeOfRawData!=0x1400 or section.Misc_VirtualSize!=0x1400
                or pe.OPTIONAL_HEADER.SizeOfImage!=RVA+0x2000 or section.PointerToRawData+0x1400!=len(data)):
            raise ValueError('Unknown equipment extension section')
        if data[section.PointerToRawData+0xc00:]!=extension():raise ValueError('Equipment extension bytes changed')
        for address,before,after in sites():
            offset=pe.get_offset_from_rva(address-0x400000)
            if data[offset:offset+len(after)]!=after:raise ValueError('Equipment hook bytes changed')
            original[offset:offset+len(before)]=before
        del original[section.PointerToRawData+0xc00:]
        for field in (8,16):struct.pack_into('<I',original,section.get_file_offset()+field,0xc00)
        struct.pack_into('<I',original,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x1000)
        if hashlib.sha256(original).hexdigest()!=BASE_SHA:raise ValueError('Unknown equipment base release')
        return data
    base=data
    if hashlib.sha256(base).hexdigest()!=BASE_SHA:
        raise ValueError('Expected exact published 2026.10.07.4 equipment base release')
    pe=pefile.PE(data=base);section=pe.sections[-1];result=bytearray(base)
    if section.VirtualAddress!=RVA or section.SizeOfRawData!=0xc00 or section.PointerToRawData+0xc00!=len(base):
        raise ValueError('Unexpected equipment section layout')
    for address,before,after in sites():
        offset=pe.get_offset_from_rva(address-0x400000)
        if base[offset:offset+len(before)]!=before:raise ValueError('Unknown original equipment hook')
        result[offset:offset+len(after)]=after
    result.extend(extension())
    for field in (8,16):struct.pack_into('<I',result,section.get_file_offset()+field,0x1400)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x2000)
    return bytes(result)


def patch_plan(previous,updated):
    """Prove every source byte outside the four hooks and PE sizes survives."""
    if patch(previous)!=updated:raise ValueError('Equipment candidate differs from checked patch')
    pe=pefile.PE(data=previous);section=pe.sections[-1]
    changes=[{'offset':pe.get_offset_from_rva(address-0x400000),
              'before_hex':before.hex(),'after_hex':after.hex(),'native_va':hex(address)}
             for address,before,after in sites()]
    for offset in (section.get_file_offset()+8,section.get_file_offset()+16,
                   pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage')):
        changes.append({'offset':offset,'before_hex':previous[offset:offset+4].hex(),
                        'after_hex':updated[offset:offset+4].hex(),'reason':'PE appended section size'})
    allowed={at for change in changes for at in range(change['offset'],change['offset']+len(bytes.fromhex(change['before_hex'])))}
    if any(a!=b and offset not in allowed for offset,(a,b) in enumerate(zip(previous,updated))):
        raise ValueError('Unexpected edit outside bounded equipment hooks and PE sizes')
    if updated[len(previous):]!=extension():raise ValueError('Unexpected appended equipment code')
    return {'previous_sha256':hashlib.sha256(previous).hexdigest(),'updated_sha256':hashlib.sha256(updated).hexdigest(),
            'previous_bytes':len(previous),'updated_bytes':len(updated),'changes':changes,
            'appended_bytes':len(extension()),'all_other_published_bytes_preserved':True,
            'namespace':'Explicit TIO emulator equipment F6/v1'}
