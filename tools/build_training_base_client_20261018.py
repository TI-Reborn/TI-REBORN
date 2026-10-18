"""Exact hosted-client correction for Training Base group tabs and idle caption."""
import hashlib,json,struct,sys
from pathlib import Path
import pefile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/training-base-20261018/client'
BEFORE='9a8fb8f12af25c6c81a96ac623b1217b4deaeaa1008d5c4e3ead8feba9ff75ed'
sha=lambda b:hashlib.sha256(b).hexdigest()

def patch(raw):
    assert sha(raw)==BEFORE
    p=pefile.PE(data=raw);last=p.sections[-1];base=p.OPTIONAL_HEADER.ImageBase
    rva=last.VirtualAddress+last.Misc_VirtualSize
    assert last.Misc_VirtualSize==last.SizeOfRawData and last.PointerToRawData+last.SizeOfRawData==len(raw)
    assert rva%4096==0 and last.Characteristics&0x20000000
    out=bytearray(raw);changes=[]
    def amend(va,old,new,purpose):
        off=p.get_offset_from_rva(va-base);assert raw[off:off+len(old)]==old and len(old)==len(new)
        # Hooks contain no absolute relocation operands.
        assert not any(va-base<=e.rva<va-base+len(old) for b in p.DIRECTORY_ENTRY_BASERELOC for e in b.entries if e.type==3)
        out[off:off+len(old)]=new;changes.append(dict(va=hex(va),offset=off,before=old.hex(),after=new.hex(),purpose=purpose))
    for va in (0x827a47,0x827a51):
        amend(va,b'\xe8'+struct.pack('<i',0xa51a78-va-5),b'\x90'*5,'Do not select a hidden legacy territory tab in the training-only branch')
    # Tail-call native translation. Preserve EDX destination, ECX and original
    # EAX key when this is an ordinary territory base. All new addressing is PIC.
    start=base+rva
    stub=bytearray(b'\x50\x51\x52')
    def call(target):stub.extend(b'\xe8'+struct.pack('<i',target-(start+len(stub)+5)))
    call(0x822234);stub.extend(b'\x84\xc0\x5a\x59\x58\x74\x0c')
    call(start+len(stub)+5);stub.extend(b'\x58\x05'+struct.pack('<I',0))
    # The popped address is the byte following call, not the end of LEA/add.
    popped_offset=20
    assert stub[15]==0xe8 and len(stub)==26
    struct.pack_into('<I',stub,22,0x100-popped_offset)
    stub.extend(b'\xe9'+struct.pack('<i',0x6675e0-(start+len(stub)+5)))
    # JZ skips CALL/POP/ADD (11 bytes); destination is the tail JMP.
    stub[14]=11
    amend(0x826e97,b'\xe8'+struct.pack('<i',0x6675e0-0x826e9c),b'\xe8'+struct.pack('<i',start-0x826e9c),'Use training-only permanent-registration caption when no scheduled date exists')
    extra=bytearray(4096);extra[:len(stub)]=stub
    key='tb02t'.encode('utf-16-le')
    # Delphi immutable UnicodeString header: CodePage, ElementSize, RefCount, Length.
    extra[0xf4:0x100]=struct.pack('<HHii',1200,2,-1,5)
    extra[0x100:0x100+len(key)+2]=key+b'\0\0'
    extra[0x200:0x220]=b'TIO-training-ready-groups-v1'.ljust(32,b'\0')
    # Only the two character.clan_id comparisons are adapted. Actual room
    # presence, readiness, leadership and all packet state remain authoritative.
    guard_va=start+0x300
    guard=(b'\x50\x51\x52\xe8'+struct.pack('<i',0x822234-(guard_va+8))+
           b'\x84\xc0\x5a\x59\x58\x75\x07\x83\xb8\x80\x02\x00\x00\x00\xc3')
    extra[0x300:0x300+len(guard)]=guard
    for va in (0x791b05,0x793d85):
        amend(va,b'\x83\xb8\x80\x02\x00\x00\x00',b'\xe8'+struct.pack('<i',guard_va-va-5)+b'\x90\x90','Training permits accounts without a clan; ordinary base clan gate is preserved')
    # Original checkbox callback sends the current ready flag. Training's
    # server API accepts the desired flag, so adapt this one UI toggle.
    ready_va=start+0x400
    ready=(b'\x9c\x50\x51\x52\xe8'+struct.pack('<i',0x822234-(ready_va+9))+
           b'\x84\xc0\x5a\x59\x58\x74\x03\x83\xf2\x01\x9d'+
           b'\xe9'+struct.pack('<i',0x639354-(ready_va+25)))
    assert len(ready)==25;extra[0x400:0x419]=ready
    amend(0x792a33,b'\xe8'+struct.pack('<i',0x639354-0x792a38),b'\xe8'+struct.pack('<i',ready_va-0x792a38),'Convert a native Training Base checkbox toggle to the desired authoritative ready state')
    for field in ('Misc_VirtualSize','SizeOfRawData'):
        struct.pack_into('<I',out,last.get_field_absolute_offset(field),getattr(last,field)+4096)
    struct.pack_into('<I',out,p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),rva+4096)
    out.extend(extra)
    return bytes(out),dict(before_sha256=sha(raw),after_sha256=sha(out),changes=changes,relocation_changes=[],helper_va=start,helper=stub.hex(),new_key_va=start+0x100,guard_va=guard_va,ready_va=ready_va,appended_bytes=4096)

def main():
    OUT.mkdir(exist_ok=True)
    source=ROOT/'work/training-base-20261018/gui/game-a/silver.dll'
    raw=(OUT/'silver-before.dll').read_bytes() if (OUT/'silver-before.dll').exists() else source.read_bytes()
    candidate,proof=patch(raw)
    (OUT/'silver-before.dll').write_bytes(raw);(OUT/'silver.dll').write_bytes(candidate)
    for language,caption in [('russian','Старт по готовности групп'),('english','Starts when groups are ready')]:
        path=source.parent/'base'/f'{language}.lng';data=path.read_bytes()
        if b'\r\ntb02t=' in data:data=data.split(b'\r\ntb02t=')[0]+b'\r\n'
        new=data.rstrip(b'\r\n')+b'\r\ntb02t='+caption.encode('cp1251')+b'\r\n'
        target=OUT/'base'/path.name;target.parent.mkdir(exist_ok=True);target.write_bytes(new)
    (OUT/'native-review.json').write_text(json.dumps(proof,indent=2))
    print(json.dumps(proof))
if __name__=='__main__':main()
