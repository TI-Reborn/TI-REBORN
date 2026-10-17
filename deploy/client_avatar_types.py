"""Expand the exact published FC whitelist; preserve all other client bytes."""
import hashlib,pefile
from .client_avatars import ENTRY,code
BASE_SHA='ffa8c164856edf7d553bce591b6598982655c5200336a49d629b9fb254500b79'


def patch(source):
    if hashlib.sha256(source).hexdigest()!=BASE_SHA:raise ValueError('Exact hosted avatar release required')
    pe=pefile.PE(data=source);offset=pe.get_offset_from_rva(ENTRY-0x400000)
    before=code();after=code(max_avatar=10006)
    if source[offset:offset+len(before)]!=before:raise ValueError('Published FC reader changed')
    result=bytearray(source);result[offset:offset+len(after)]=after
    assert sum(a!=b for a,b in zip(source,result))==1
    return bytes(result)
