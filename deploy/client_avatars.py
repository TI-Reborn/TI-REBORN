"""FC assignment receiver wrapping the exact published rain release."""
import hashlib,struct,pefile
from .client_equipment_batch import Code
from .client_rain_weather import READER as PREVIOUS
BASE_SHA='a2adfba38fb591151720e64ba9c27c7721a18a939fa9f6855b1262a35cd1c525'
RVA=0x880000;SIZE=0x1000;ENTRY=0x400000+RVA


def code(*, max_avatar=10003):
    c=Code(ENTRY);c.emit('3cfc');c.branch('0f85','stock');c.emit('9c60');c.base()
    c.emit('83f904');c.branch('0f82','done');c.emit('803a01');c.branch('0f85','done')
    c.emit('0fb77201 83fe1f');c.branch('0f87','done')
    c.emit('8d04f5 04000000 39c8');c.branch('0f85','done')
    c.emit('83c203 85f6');c.branch('0f84','done')
    # Validate all records before mutating any native actor.
    c.emit('89d7 89f1');c.label('check');c.emit('833f00');c.branch('0f84','done')
    c.emit('8b4704 85c0');c.branch('0f84','valid');c.emit('3d11270000');c.branch('0f82','done');c.emit('3d');c.word(max_avatar);c.branch('0f87','done')
    c.label('valid');c.emit('83c708 49');c.branch('0f85','check')
    c.label('record');c.emit('8b02 8bbb');c.word(0xac618c-0x400000);c.emit('b91f000000')
    c.label('slot');c.emit('8b2f 85ed');c.branch('0f84','next');c.emit('394528');c.branch('0f85','next')
    c.emit('8b4204 898578020000');c.branch('e9','advance')
    c.label('next');c.emit('83c704 49');c.branch('0f85','slot')
    c.label('advance');c.emit('83c208 4e');c.branch('0f85','record')
    c.label('done');c.emit('c744241c01000000 619d c3')
    c.label('stock');c.call(PREVIOUS);c.emit('c3');return c.finish(0x400)


def patch(source):
    if hashlib.sha256(source).hexdigest()!=BASE_SHA:raise ValueError('Exact hosted avatar base required')
    p=pefile.PE(data=source);s=p.sections[-1]
    if s.VirtualAddress+s.SizeOfRawData!=RVA or s.PointerToRawData+s.SizeOfRawData!=len(source):raise ValueError('Unsupported avatar extension layout')
    result=bytearray(source);at=0x9f5563;offset=p.get_offset_from_rva(at-0x400000)
    assert result[offset:offset+5]==b'\xe8'+struct.pack('<i',PREVIOUS-at-5)
    result[offset:offset+5]=b'\xe8'+struct.pack('<i',ENTRY-at-5)
    result.extend((code()+b'TIO-original-avatars-FC-v1').ljust(SIZE,b'\0'))
    for n in (8,16):struct.pack_into('<I',result,s.get_file_offset()+n,s.SizeOfRawData+SIZE)
    struct.pack_into('<I',result,p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+SIZE)
    return bytes(result)
