"""Extend the exact hosted FC avatar reader while preserving every other byte."""
import hashlib
import pefile
from .client_avatars import ENTRY, code

BASE_SHA = '64f377d0f8022314ac64361f59a8fd887da1122323bee0df0f725a5548c2cdce'
MAX_AVATAR = 10012


def patch(source):
    if hashlib.sha256(source).hexdigest() != BASE_SHA:
        raise ValueError('Exact hosted six-avatar release required')
    pe = pefile.PE(data=source)
    offset = pe.get_offset_from_rva(ENTRY - 0x400000)
    before, after = code(max_avatar=10006), code(max_avatar=MAX_AVATAR)
    if source[offset:offset+len(before)] != before:
        raise ValueError('Published FC reader changed')
    result = bytearray(source)
    result[offset:offset+len(after)] = after
    assert sum(a != b for a, b in zip(source, result)) == 1
    return bytes(result)
