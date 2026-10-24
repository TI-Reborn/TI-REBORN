"""Allow genuine repair kits17/18/19 through the two warehouse list rebuilds.

Exact currently published client only. Remove two unconditional XOR EBX,EBX
instructions after IsRepairKit; retain prior and subsequent filter decisions.
This transformer never writes a file or contacts the hosting service.
"""
import hashlib
import pefile

# Filled from the immutable publication inspected for this change, not from a
# potentially modified installed client. A different release requires review.
BASE_SHA='8b163bea1a13ec994d379094ab6c59034955e99fc7c2d6f98c605fc583e30e4b'
SITES=((0x9159bc,0x9159c7,bytes.fromhex('8bc7e8fd5e160084c0740233db')),
       (0x917168,0x917177,bytes.fromhex('8d8560fdffffe84d47160084c0740233db')))


def digest(raw):return hashlib.sha256(raw).hexdigest()


def patch(source):
    if digest(source)!=BASE_SHA:raise ValueError('Repair-kit warehouse patch needs the exact inspected published silver.dll')
    pe=pefile.PE(data=source)
    try:
        if pe.FILE_HEADER.Machine!=0x14c or pe.OPTIONAL_HEADER.ImageBase!=0x400000:raise ValueError('Unexpected native image')
        result=bytearray(source)
        for start,site,expected in SITES:
            at=pe.get_offset_from_rva(start-0x400000)
            if source[at:at+len(expected)]!=expected:raise ValueError('Warehouse filter instruction boundary changed')
            at=pe.get_offset_from_rva(site-0x400000)
            if source[at:at+2]!=b'\x33\xdb':raise ValueError('Unexpected repair-kit exclusion')
            result[at:at+2]=b'\x90\x90'
        return bytes(result)
    finally:pe.close()


def review(source,candidate):
    if patch(source)!=candidate:raise ValueError('Candidate differs from reviewed exact transformer')
    pe=pefile.PE(data=source)
    try:
        offsets=[pe.get_offset_from_rva(site-0x400000) for _,site,_ in SITES]
        changed=[i for i,(a,b) in enumerate(zip(source,candidate)) if a!=b]
        if len(source)!=len(candidate) or changed!=sorted(i for at in offsets for i in (at,at+1)):
            raise ValueError('Unexpected client changes')
        return dict(source_sha256=digest(source),candidate_sha256=digest(candidate),size=len(candidate),
                    changed_bytes=4,sites=[dict(address=hex(site),offset=at,before='33db',after='9090') for (_,site,_),at in zip(SITES,offsets)],
                    scope='warehouse filtering of repair kits17/18/19',network_protocol_unchanged=True,
                    other_filters_preserved=True)
    finally:pe.close()
