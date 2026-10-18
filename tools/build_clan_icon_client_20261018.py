"""Patch only native image preparation and the clan PNG/BMP dialog filter."""
import hashlib,json,struct,sys,urllib.request
from pathlib import Path
import pefile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy.client_equipment_batch import Code
OUT=ROOT/'reports/clan-icons-20261018';BASE=0x400000
BEFORE='a67564fa591a6b076e1be90defc892885cc5b399c7854fcb058403959dac36f5'
ENTRY,RELEASE,STRINGS=0xc81600,0xc81800,0xc81900
sha=lambda b:hashlib.sha256(b).hexdigest()

def patch(raw):
 assert sha(raw)==BEFORE
 pe=pefile.PE(data=raw);out=bytearray(raw);changes=[]
 free=next(i.address for e in pe.DIRECTORY_ENTRY_IMPORT for i in e.imports if i.name==b'FreeLibrary')
 def amend(va,old,new):
  off=pe.get_offset_from_rva(va-BASE);assert raw[off:off+len(old)]==old and len(old)==len(new)
  out[off:off+len(old)]=new;changes.append(dict(va=hex(va),offset=off,before=old.hex(),after=new.hex()))
 # The shared original upload frame reserves >10 KB; EBP-18 is outside
 # the canonical 822-byte read region and unused by its own locals.
 c=Code(ENTRY);c.emit('9c60');c.base()
 c.emit('8d83');c.word(STRINGS-BASE);c.emit('50 ff93');c.word(0xb7a100-BASE)
 c.emit('8945e8 85c0');c.branch('0f84','error')
 c.emit('8d93');c.word(STRINGS+0x40-BASE);c.emit('52 50 ff93');c.word(0xb7a170-BASE)
 c.emit('85c0');c.branch('0f84','free_error');c.emit('ff75fc ffd0 85c0');c.branch('0f84','free_cancel')
 c.emit('89442418 619d 6a00 b201');c.jump(0x837635)
 c.label('free_cancel');c.emit('ff75e8 ff93');c.word(free-BASE);c.emit('619d');c.jump(0x83774f)
 c.label('free_error');c.emit('ff75e8 ff93');c.word(free-BASE)
 c.label('error');c.emit('619d')
 # Error reporting uses original renderer with a managed Unicode string.
 # Keep every address in new code position-independent.
 c.emit('9c60');c.base();c.emit('8d93');c.word(0x8377f4-BASE);c.emit('b0ff');c.call(0xa0202c);c.emit('619d');c.jump(0x83774f)
 helper=c.finish(0x200)
 r=Code(RELEASE);r.call(0x4092dc);r.emit('9c60');r.base()
 r.emit('8d93');r.word(STRINGS+0x60-BASE);r.emit('52 ff75e8 ff93');r.word(0xb7a170-BASE)
 r.emit('85c0');r.branch('0f84','free');r.emit('ffd0');r.label('free');r.emit('ff75e8 ff93');r.word(free-BASE);r.emit('619dc3')
 strings=bytearray(0x180)
 name='tio_crest.dll'.encode('utf-16le')+b'\0\0';strings[:len(name)]=name
 strings[0x40:0x40+15]=b'NormalizeCrest\0';strings[0x60:0x60+13]=b'ReleaseCrest\0'
 text='PNG / BMP|*.png;*.bmp';encoded=text.encode('utf-16le')
 strings[0x74:0x80]=struct.pack('<HHii',1200,2,-1,len(text));strings[0x80:0x80+len(encoded)+2]=encoded+b'\0\0'
 amend(ENTRY,bytes(0x200),helper);amend(RELEASE,bytes(0x100),r.finish(0x100));amend(STRINGS,bytes(0x180),bytes(strings))
 amend(0x83762e,bytes.fromhex('6a008b4dfcb201'),b'\xe9'+struct.pack('<i',ENTRY-0x837633)+b'\x90\x90')
 amend(0x8376f1,b'\xe8'+struct.pack('<i',0x4092dc-0x8376f6),b'\xe8'+struct.pack('<i',RELEASE-0x8376f6))
 # This existing absolute immediate retains its original HIGHLOW relocation.
 amend(0x83e104,b'\xba'+struct.pack('<I',0x83e1d4),b'\xba'+struct.pack('<I',STRINGS+0x80))
 updated=pefile.PE(data=bytes(out));assert pe.get_data(pe.OPTIONAL_HEADER.DATA_DIRECTORY[5].VirtualAddress,pe.OPTIONAL_HEADER.DATA_DIRECTORY[5].Size)==updated.get_data(updated.OPTIONAL_HEADER.DATA_DIRECTORY[5].VirtualAddress,updated.OPTIONAL_HEADER.DATA_DIRECTORY[5].Size)
 return bytes(out),dict(before_sha256=sha(raw),after_sha256=sha(out),changes=changes,size_unchanged=len(out)==len(raw),relocations_unchanged=True,free_library_iat=hex(free),normalize_entry=hex(ENTRY),release_entry=hex(RELEASE))

def main():
 source=OUT/'silver-before.dll'
 if not source.exists():
  manifest=json.loads((OUT/'manifest-before.json').read_text(encoding='utf-8'));row=next(r for r in manifest['files'] if r['path']=='silver.dll');source.write_bytes(urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+row['sha256']).read())
 candidate,proof=patch(source.read_bytes());(OUT/'silver.dll').write_bytes(candidate);(OUT/'native-review.json').write_text(json.dumps(proof,indent=2));print(json.dumps({k:v for k,v in proof.items() if k!='changes'}))
if __name__=='__main__':main()
