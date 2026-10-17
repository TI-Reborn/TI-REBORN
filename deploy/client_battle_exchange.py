"""Checked release extension: own-merc exchange opening6E, loose gear and 1AP gate.

Native98F478 remains the confirmation writer. No changes to ground/city trade.
"""
import hashlib,struct
import pefile
from .client_battle_loot import patch as previous,ENTRY as GROUND_ENTRY,HOOK,RVA

BASE_SHA='99b239f5371b4aeb88f48cb8dec3e98e57f677099baba766b1285f250118d3c2'
OPEN=0x400000+RVA+0x800
PREDICATE=0x400000+RVA+0xa00
SIGNATURE=b'TIO-own-merc-exchange-v1'


def opening():
    out=bytearray()
    def emit(s):out.extend(bytes.fromhex(s))
    def word(v):out.extend(struct.pack('<I',v&0xffffffff))
    def call(target):emit('e8');word(target-(OPEN+len(out)+4))
    call(0x9b1440)  # Existing two-panel inventory window.
    emit('9c60 e800000000 5f 81ef');word(OPEN+12-0x400000)
    emit('8b97');word(0xac4b04-0x400000)  # Target index; EBX=active, ESI=array.
    emit('8b1496 8b5228 8b049e 8b4028 31c9 6a00')
    call(0x98f478)  # Empty native6E: activeID,targetID,0,0. Server opening lease.
    emit('619d c3')
    return bytes(out).ljust(0x200,b'\0')


def predicate():
    out=bytearray();fixups=[]
    def emit(s):out.extend(bytes.fromhex(s))
    def word(v):out.extend(struct.pack('<I',v&0xffffffff))
    def fallback():emit('0f85');fixups.append(len(out));word(0)
    emit('9c60 e800000000 5b 81eb');word(PREDICATE+7-0x400000)
    emit('8b93');word(0xac64a0-0x400000)
    emit('803a00 0f84');fixups.append(len(out));word(0)
    emit('8b93');word(0xac5f18-0x400000)
    emit('803a01');fallback()
    # Own-merc transfers preserve property/rental metadata. Equipped items
    # remain subject to the existing separate UI gate and server validation.
    emit('c744241c01000000 619d c3')
    tail=len(out);emit('619d e9');word(GROUND_ENTRY-(PREDICATE+len(out)+4))
    for at in fixups:struct.pack_into('<i',out,at,tail-at-4)
    out.extend(SIGNATURE)
    return bytes(out).ljust(0x200,b'\0')


def sites():
    return ((0x95cdaa,b'\xe8'+struct.pack('<i',0x9b1440-0x95cdaa-5),b'\xe8'+struct.pack('<i',OPEN-0x95cdaa-5)),
            (HOOK,b'\xe9'+struct.pack('<i',GROUND_ENTRY-HOOK-5),b'\xe9'+struct.pack('<i',PREDICATE-HOOK-5)),
            (0x95cd23,bytes.fromhex('3a4205'),bytes.fromhex('3a4206')),
            (0x95ce65,bytes.fromhex('3a4205'),bytes.fromhex('3a4206')))


def patch(data):
    pe=pefile.PE(data=data)
    if SIGNATURE in data:
        section=pe.sections[-1];original=bytearray(data)
        assert section.VirtualAddress==RVA and section.SizeOfRawData==0xc00
        assert data[section.PointerToRawData+0x800:]==opening()+predicate()
        for va,old,new in sites():
            off=pe.get_offset_from_rva(va-0x400000)
            if data[off:off+len(new)]!=new:raise ValueError('Exchange hook changed')
            original[off:off+len(old)]=old
        del original[section.PointerToRawData+0x800:]
        for field in (8,16):struct.pack_into('<I',original,section.get_file_offset()+field,0x800)
        if hashlib.sha256(original).hexdigest()!=BASE_SHA:raise ValueError('Unknown exchange base')
        return data
    base=previous(data)
    if hashlib.sha256(base).hexdigest()!=BASE_SHA:raise ValueError('Unknown client release')
    pe=pefile.PE(data=base);section=pe.sections[-1];result=bytearray(base)
    if section.VirtualAddress!=RVA or section.SizeOfRawData!=0x800 or section.PointerToRawData+0x800!=len(base):
        raise ValueError('Unexpected release extension')
    for va,old,new in sites():
        off=pe.get_offset_from_rva(va-0x400000)
        if base[off:off+len(old)]!=old:raise ValueError('Unexpected exchange bytes')
        result[off:off+len(new)]=new
    result.extend(opening()+predicate())
    for field in (8,16):struct.pack_into('<I',result,section.get_file_offset()+field,0xc00)
    return bytes(result)
