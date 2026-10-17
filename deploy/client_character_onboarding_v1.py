"""Known-build PE extension: server 12/05 -> next character list opens native editor.

Position-independent wrappers preserve registers/flags, use native 6d0318, and
leave normal logins unchanged. The original DLL on disk is not edited by patch().
"""
import hashlib
import struct
import pefile
from .client_russian_encoding import patch as russian_patch, ORIGINAL_SHA, PATCHED_SHA

RVA=0x817000
FLAG=RVA+0x1f0
SIGNATURE=b'TIO-appearance-step-v1'


def code():
    out=bytearray();labels={};fixups=[]
    def emit(raw):out.extend(bytes.fromhex(raw))
    def word(n):out.extend(struct.pack('<I',n))
    def relative(op,target):
        emit(op);word((target-(0x400000+RVA+len(out)+4))&0xffffffff)
    def branch(op,label):
        emit(op);fixups.append((len(out),label));word(0)
    def base():
        emit('e8 00000000 5b 81eb');word(RVA+len(out)-3)
    # At 88a8ad the original parser has subtracted four from the status byte.
    labels['arm']=len(out);emit('9c60');base()
    emit('c683');word(FLAG);emit('00 807c241c01');branch('0f85','armed')
    emit('c683');word(FLAG);emit('01')
    labels['armed']=len(out);emit('619d b001');relative('e8',0x8a2868);relative('e9',0x88a8b4)
    while len(out)<0x60:emit('90')
    labels['list']=len(out);emit('9c60');base()
    emit('80bb');word(FLAG);emit('01');branch('0f85','done')
    emit('8bb3');word(0xac618c-0x400000);emit('31ff')
    labels['scan']=len(out);emit('833cbe00');branch('0f85','found')
    emit('47 83ff1f');branch('0f82','scan');branch('e9','done')
    labels['found']=len(out)
    emit('8b93');word(0xac64b4-0x400000);emit('893a')
    emit('c683');word(FLAG);emit('00 89f8');relative('e8',0x6d0318)
    labels['done']=len(out);emit('619d 5f5e5b89ec5dc3')
    for at,label in fixups:struct.pack_into('<i',out,at,labels[label]-(at+4))
    if len(out)>=0x1d0:raise ValueError('Code overflow')
    out.extend(bytes(0x1d0-len(out)));out.extend(SIGNATURE)
    out.extend(bytes(0x200-len(out)))
    return bytes(out)


def patch(data):
    if SIGNATURE in data:
        pe=pefile.PE(data=data)
        section=pe.sections[-1]
        if section.Name.rstrip(b'\0')!=b'.tiochar' or section.VirtualAddress!=RVA or data[section.PointerToRawData:section.PointerToRawData+0x200]!=code():
            raise ValueError('Unexpected onboarding patch')
        return data
    if hashlib.sha256(data).hexdigest() not in (ORIGINAL_SHA,PATCHED_SHA):
        raise ValueError('Unsupported silver.dll')
    data=russian_patch(data);pe=pefile.PE(data=data)
    result=bytearray(data)
    def detour(va,target,expected):
        offset=pe.get_offset_from_rva(va-0x400000)
        if result[offset:offset+len(expected)]!=expected:raise ValueError('Unexpected hook bytes')
        result[offset:offset+len(expected)]=b'\xe9'+struct.pack('<i',target-va-5)+b'\x90'*(len(expected)-5)
    detour(0x88a8ad,0x400000+RVA,bytes.fromhex('b001e8b47f0100'))
    detour(0x88a435,0x400000+RVA+0x60,bytes.fromhex('5f5e5b8be55dc3'))
    offset=(len(result)+0x1ff)&~0x1ff
    result.extend(bytes(offset-len(result)));result.extend(code())
    header=pe.sections[-1].get_file_offset()+40
    if header+40>pe.OPTIONAL_HEADER.SizeOfHeaders:raise ValueError('No PE section header room')
    result[header:header+40]=struct.pack('<8sIIIIIIHHI',b'.tiochar',0x200,RVA,0x200,offset,0,0,0,0,0xe0000020)
    struct.pack_into('<H',result,pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'),len(pe.sections)+1)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x1000)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),0)
    return bytes(result)
