"""Persist the four known Upgrade Kit UI fixes in the distributed silver.dll.

Only two panel HideUpgradeBoxes stores and two warehouse exclusions change.
Item identity, exchange policy, other filters and network code are preserved.
"""
import hashlib
import pefile
from .client_character_onboarding import patch as onboarding

BASE_SHA='569844809fe607ad33ce966210262db8fbc6332488bfadd2b1dda9a85f653f72'
SITES=((0x9a7f3a,bytes.fromhex('c680a202000001'),bytes.fromhex('c680a202000000')),
       (0x9ba21b,bytes.fromhex('c680a202000001'),bytes.fromhex('c680a202000000')),
       (0x9159f7,b'\x33\xdb',b'\x90\x90'),(0x9171b2,b'\x33\xdb',b'\x90\x90'))


def patch(data):
    # Recognize our own complete result by restoring all sites and checking
    # the entire underlying release, not merely finding a marker string.
    if len(data)>0x100:
        try:
            pe=pefile.PE(data=data)
            offsets=[pe.get_offset_from_rva(va-0x400000) for va,_,_ in SITES]
            if all(data[o:o+len(new)]==new for o,(_,_,new) in zip(offsets,SITES)):
                original=bytearray(data)
                for o,(_,old,_) in zip(offsets,SITES):original[o:o+len(old)]=old
                if hashlib.sha256(original).hexdigest()!=BASE_SHA:raise ValueError('Unsupported patched silver.dll')
                return data
        except pefile.PEFormatError as exc:raise ValueError('Unsupported silver.dll') from exc
    try:base=onboarding(data)
    except (pefile.PEFormatError,IndexError) as exc:raise ValueError('Unsupported silver.dll') from exc
    if hashlib.sha256(base).hexdigest()!=BASE_SHA:raise ValueError('Unsupported silver.dll release')
    pe=pefile.PE(data=base);result=bytearray(base)
    for va,old,new in SITES:
        offset=pe.get_offset_from_rva(va-0x400000)
        if result[offset:offset+len(old)]!=old:raise ValueError('Unexpected kit filter bytes')
        result[offset:offset+len(old)]=new
    return bytes(result)
