"""Temporarily remove the authored geyser in mine03; preserve original bytes.

All real deposits are server-created after discovery. A hard-coded scenery
geyser bypasses that protocol. Caller must ensure no client is running yet.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[1]


def without_deposits(raw):
    if raw[:8]!=b'TI SET\0\2':raise ValueError('Unsupported mine scene')
    w,h,count=struct.unpack_from('<3H',raw,12)
    if (w,h)!=(60,60):raise ValueError('Unexpected mine dimensions')
    offset=32+w*h*2;end=offset+count*72
    if end>len(raw):raise ValueError('Truncated mine scene')
    records=[raw[offset+i*72:offset+(i+1)*72] for i in range(count)]
    kept=[r for r in records if r[1:1+r[0]] not in (b'mine_heyser.t',b'mine_gasdrill.t')]
    result=bytearray(raw[:offset]);struct.pack_into('<H',result,16,len(kept))
    return bytes(result)+b''.join(kept)+raw[end:]


@contextmanager
def hidden_static_deposits(base,backup_root):
    source=next(m for m in json.loads((ROOT/'config/mine_maps.json').read_text()) if m['file']=='mine_03')
    target=Path(base)/'maps/mines_01/mine_03.s'
    backup=Path(backup_root)/('mine_03-original-'+source['sha256']+'.s')
    observed=target.read_bytes()
    if hashlib.sha256(observed).hexdigest()==source['sha256']:
        original=observed
        backup.parent.mkdir(parents=True,exist_ok=True)
        if backup.exists():
            if backup.read_bytes()!=original:raise ValueError('Mine scene backup differs; preserved')
        else:
            with backup.open('xb') as stream:stream.write(original)
    else:
        original=backup.read_bytes()
        if hashlib.sha256(original).hexdigest()!=source['sha256'] or observed!=without_deposits(original):
            raise ValueError('Unknown modified mine scene; preserved')
    patched=without_deposits(original)
    if target.read_bytes()!=observed:raise ValueError('Mine scene changed during preflight')
    try:
        target.write_bytes(patched)
        yield
    finally:
        if target.read_bytes()==patched:target.write_bytes(original)
        else:print('Mine scene changed during session; preserved:',target)
