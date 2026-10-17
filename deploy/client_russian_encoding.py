"""Pin the known Russian client's Delphi ANSI conversions to Windows-1251.

At VA AB6090 original initialization calls GetACP and stores EAX at AC7900.
Replace only that call with MOV EAX,1251 (same five bytes, no relocations).
No resources, skill values, game logic or Windows settings are changed.
"""
import hashlib

ORIGINAL_SHA='a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11'
PATCHED_SHA='6cb78fd9e71afa92d301a46ac7601e8280942dc97215d9826873fb83bb0fbe27'
OFFSET=0x6b4a90
ORIGINAL=bytes.fromhex('e8b7eb94ff')
PATCHED=bytes.fromhex('b8e3040000')


def patch(data):
    digest=hashlib.sha256(data).hexdigest()
    if digest==PATCHED_SHA:return data
    if digest!=ORIGINAL_SHA or data[OFFSET:OFFSET+5]!=ORIGINAL:
        raise ValueError('Unsupported silver.dll; refusing to patch')
    result=data[:OFFSET]+PATCHED+data[OFFSET+5:]
    if hashlib.sha256(result).hexdigest()!=PATCHED_SHA:
        raise ValueError('Patched client checksum mismatch')
    return result
