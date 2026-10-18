"""Route Training Base's existing disband callback through its native sender."""
import hashlib,json,struct,sys
from pathlib import Path
import pefile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy.client_equipment_batch import Code
OUT=ROOT/'reports/training-disband-20261018'
BEFORE='54dfaf7c7ede79684aad764540f9847c08710d26433fb11ccd02f73db441f8f0'
HOOK=0x792c7c;SLOT=0xc81500;SIZE=0x100
sha=lambda b:hashlib.sha256(b).hexdigest()
def patch(raw):
 assert sha(raw)==BEFORE
 p=pefile.PE(data=raw);off=p.get_offset_from_rva(HOOK-0x400000);slot=p.get_offset_from_rva(SLOT-0x400000)
 original=b'\xe8'+struct.pack('<i',0xa6a114-HOOK-5)
 assert raw[off:off+5]==original and raw[slot:slot+SIZE]==bytes(SIZE)
 assert not any(HOOK-0x400000<=e.rva<HOOK-0x400000+5 or SLOT-0x400000<=e.rva<SLOT-0x400000+SIZE for b in p.DIRECTORY_ENTRY_BASERELOC for e in b.entries if e.type==3)
 c=Code(SLOT);c.call(0xa6a114);c.emit('9c60');c.call(0x822234);c.emit('84c0');c.branch('0f84','restore')
 c.base();c.emit('8b83');c.word(0xac585c-0x400000);c.emit('803800');c.branch('0f84','list')
 c.emit('8d83');c.word(0x792c95-0x400000);c.branch('e9','return')
 c.label('list');c.emit('8d83');c.word(0x792cbb-0x400000)
 c.label('return');c.emit('89442424') # saved CALL return, after PUSHFD/PUSHAD
 c.label('restore');c.emit('619dc3');helper=c.finish(SIZE)
 result=bytearray(raw);result[slot:slot+SIZE]=helper;result[off:off+5]=b'\xe8'+struct.pack('<i',SLOT-HOOK-5)
 assert len(result)==len(raw)
 report=dict(before_sha256=sha(raw),after_sha256=sha(result),hook_va=HOOK,helper_va=SLOT,helper_bytes=SIZE,changed_ranges=[dict(offset=off,size=5),dict(offset=slot,size=SIZE)],relocations_unchanged=True,size_unchanged=True,scope='Training-only disband/leave; original native sender, response consumer and ordinary Assault4 conditions')
 return bytes(result),report
def main():
 raw=(OUT/'silver-before.dll').read_bytes();result,proof=patch(raw);(OUT/'silver.dll').write_bytes(result);(OUT/'native-review.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
if __name__=='__main__':main()
