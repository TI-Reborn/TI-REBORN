"""Bounded in-memory resource ABI fix for the exact published Silver image."""
import hashlib,json,sys
from pathlib import Path
import pefile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_throwable_effects as fx
SHA='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'

def plan():
    raw=(ROOT/'work/groza-20261019/gui/game-a/silver.dll').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==SHA
    pe=pefile.PE(data=raw);data=fx.extension();patches=[]
    for rva,size in [(fx.LOAD-0x400000,0x200),(fx.NAMES,0x300)]+[(fx.ROWS+i*64+32,4) for i in range(4)]:
        before=pe.get_data(rva,size);after=data[rva-fx.RVA:rva-fx.RVA+size]
        assert len(before)==len(after)==size
        patches.append(dict(rva=rva,before=before.hex(),after=after.hex()))
    return dict(sha256=SHA,patches=patches)

if __name__=='__main__':
    value=plan();out=ROOT/'launcher/Assets/native-throwable-effects.json'
    out.write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(dict(patches=len(value['patches']),texture_names='UnicodeString',fire_tile=[64,128])))
