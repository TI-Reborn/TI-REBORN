"""Allow unmarked equipment in the active battle's ground-container UI.

The original generic exchange predicate rejects markable weapons/armor even
in opcode47's ground inventory. City trade, merc exchange and marked gear
continue through the original predicate. The server still authorizes transfers.
"""
import hashlib
import struct
import pefile
from .client_upgrade_kit import patch as upgrade_kit
from .client_character_onboarding_v1 import RVA

BASE_SHA='298b99e08234fcaba9346c475bb92194bf6fca16cb6627b1e44bde76e2363123'
HOOK=0xa7bd1c
ENTRY=0x400000+RVA+0x600
SIGNATURE=b'TIO-battle-ground-transfer-v1'


def code():
    out=bytearray();fixups=[]
    def emit(s):out.extend(bytes.fromhex(s))
    def word(n):out.extend(struct.pack('<I',n&0xffffffff))
    def fallback():emit('0f85');fixups.append(len(out));word(0)
    emit('9c60 e800000000 5b 81eb');word(ENTRY+7-0x400000)
    # AC64A0 is battle mode, AC5F18: ground=0, merc exchange=1, other=2.
    emit('8b93');word(0xac64a0-0x400000)
    emit('803a00 0f84');fixups.append(len(out));word(0)
    emit('8b93');word(0xac5f18-0x400000)
    emit('803a00');fallback()
    emit('80785800');fallback()
    emit('c744241c01000000 619d c3')
    tail=len(out)
    emit('619d 558bec5356 e9');word(HOOK+5-(ENTRY+len(out)+4))
    for at in fixups:struct.pack_into('<i',out,at,tail-at-4)
    out.extend(SIGNATURE)
    return bytes(out).ljust(0x200,b'\0')


def patch(data):
    try:pe=pefile.PE(data=data)
    except pefile.PEFormatError as exc:raise ValueError('Unsupported silver.dll') from exc
    if SIGNATURE in data:
        section=pe.sections[-1];original=bytearray(data)
        if section.VirtualAddress!=RVA or data[section.PointerToRawData+0x600:]!=code():
            raise ValueError('Unsupported battle loot patch')
        offset=pe.get_offset_from_rva(HOOK-0x400000)
        expected=b'\xe9'+struct.pack('<i',ENTRY-HOOK-5)
        if data[offset:offset+5]!=expected:raise ValueError('Unexpected loot hook')
        original[offset:offset+5]=bytes.fromhex('558bec5356')
        del original[section.PointerToRawData+0x600:]
        for field in (8,16):struct.pack_into('<I',original,section.get_file_offset()+field,0x600)
        if hashlib.sha256(original).hexdigest()!=BASE_SHA:raise ValueError('Unsupported underlying client')
        return data
    base=upgrade_kit(data)
    if hashlib.sha256(base).hexdigest()!=BASE_SHA:raise ValueError('Expected Upgrade Kit client')
    pe=pefile.PE(data=base);section=pe.sections[-1];result=bytearray(base)
    if section.VirtualAddress!=RVA or section.SizeOfRawData!=0x600 or section.PointerToRawData+0x600!=len(base):
        raise ValueError('Unexpected client section')
    offset=pe.get_offset_from_rva(HOOK-0x400000)
    if base[offset:offset+5]!=bytes.fromhex('558bec5356'):raise ValueError('Unexpected transfer predicate')
    result.extend(code())
    for field in (8,16):struct.pack_into('<I',result,section.get_file_offset()+field,0x800)
    result[offset:offset+5]=b'\xe9'+struct.pack('<i',ENTRY-HOOK-5)
    return bytes(result)
