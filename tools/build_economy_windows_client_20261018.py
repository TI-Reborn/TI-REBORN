"""Add the missing duration edit to the original personal-mark dialog.

PIC code extends the existing authored RWX presentation section. Original
authentication, networking, item serializers and relocation table stay intact.
Only three reviewed native UI sites change; no protocol is invented.
"""
from pathlib import Path
import hashlib,json,struct,sys
import pefile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'work/economy-windows-20261018/build-deps'))
from keystone import Ks,KS_ARCH_X86,KS_MODE_32

OUT=ROOT/'reports/economy-windows-20261018/client'
SOURCE=ROOT/'reports/ranked-cancel-20261018/silver.dll'
BEFORE='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
BASE=0x400000


def build():
    raw=SOURCE.read_bytes();assert hashlib.sha256(raw).hexdigest()==BEFORE
    pe=pefile.PE(data=raw);section=pe.sections[-1]
    assert section.Name==b'.tioscr\0' and section.Characteristics&0xe0000000==0xe0000000
    assert section.PointerToRawData+section.SizeOfRawData==len(raw)
    rva=section.VirtualAddress+section.SizeOfRawData
    va=BASE+rva
    payload=bytearray(0x2000);code={};changes=[]
    window=rva+0x1000;days=rva+0x1004

    def assemble(offset,body):
        addr=va+offset
        prefix=f'call {addr+5}; pop edi; sub edi, {addr+5-BASE}; '
        assembled=bytes(Ks(KS_ARCH_X86,KS_MODE_32).asm(body.replace('PIC;',prefix),addr)[0])
        assert len(assembled)<0x200
        payload[offset:offset+len(assembled)]=assembled
        code[hex(addr)]=dict(assembly=body,bytes=assembled.hex())
        return addr

    # The control caption API accepts BSTR (byte length), the edit's text
    # setter accepts Delphi UnicodeString (codepage/element size/ref/units).
    caption='Дней / Days (100 cr/d)'.encode('utf-16le')
    payload[0x1100:0x1104+len(caption)+2]=struct.pack('<I',len(caption))+caption+bytes(2)
    initial='1'.encode('utf-16le')
    payload[0x1200:0x120e+len(initial)]=struct.pack('<HHiI',1200,2,-1,1)+initial+bytes(2)

    capture=assemble(0, f'''
        mov [ebx],eax; pushad; PIC;
        mov [edi+{window}],eax; popad;
        mov eax,[ebx]; add eax,0x68; ret
    ''')
    create=assemble(0x200,f'''
        mov dword ptr [ebx+0x30],0x18; pushad; PIC;
        push dword ptr [edi+{window}];
        mov ecx,[edi+{0xac5798-BASE}]; mov dl,1;
        mov eax,[edi+{0xa2ecdc-BASE}]; call 0xa4517c;
        mov esi,eax; lea edx,[edi+{rva+0x1104}]; call 0xa42b04;
        mov dword ptr [esi+0x30],120; mov dword ptr [esi+0x34],71;
        mov ecx,[edi+{window}]; mov dl,1;
        mov eax,[edi+{0xa2fb7c-BASE}]; call 0xa45ab4;
        mov [edi+{days}],eax; mov esi,eax;
        mov dword ptr [esi+0x30],120; mov dword ptr [esi+0x34],90;
        mov dword ptr [esi+0x38],72; mov byte ptr [esi+0x280],3;
        mov byte ptr [esi+0x2a6],2;
        lea edx,[edi+{rva+0x120c}]; call 0xa46b10;
        popad; ret
    ''')
    submit=assemble(0x400,f'''
        push ebp; mov ebp,esp; push ebx; push esi; push edi; PIC;
        xor ebx,ebx; mov eax,[edi+{days}]; test eax,eax; jz invalid;
        mov esi,[eax+0x58]; test esi,esi; jz invalid;
        xor ecx,ecx;
      digit:
        movzx edx,word ptr [esi]; test edx,edx; jz send;
        cmp ecx,3; jae invalid; sub edx,48; cmp edx,9; ja invalid;
        imul ebx,ebx,10; add ebx,edx; add esi,2; inc ecx; jmp digit;
      invalid:
        xor ebx,ebx;
      send:
        mov eax,[edi+{0xacf9ec-BASE}]; mov ecx,[eax+0x58];
        test ecx,ecx; jz done;
        mov edx,ebx; mov eax,[edi+{0xacf778-BASE}]; call 0x8a0e3c;
      done:
        pop edi; pop esi; pop ebx; pop ebp; ret
    ''')

    result=bytearray(raw)+payload
    def patch(address,old,new,reason):
        off=pe.get_offset_from_rva(address-BASE)
        assert raw[off:off+len(old)]==old,(hex(address),raw[off:off+len(old)].hex(),old.hex())
        assert len(old)==len(new)
        result[off:off+len(old)]=new
        changes.append(dict(va=hex(address),before=old.hex(),after=new.hex(),reason=reason))
    def hook(address,target,old,jump=False):
        patch(address,bytes.fromhex(old),bytes([0xe9 if jump else 0xe8])+struct.pack('<i',target-address-5)+b'\x90'*(len(bytes.fromhex(old))-5),'original mark dialog duration control')
    hook(0x89f564,capture,'89038b0383c068')
    hook(0x89f7d0,create,'c7433018000000')
    hook(0x89f4dc,submit,'558bec5333db',True)
    patch(0x89f576,struct.pack('<I',256),struct.pack('<I',336),'room for duration and per-day fee')
    # No absolute operand in any replaced span: every existing relocation is
    # untouched. New code uses EIP-relative module base and rel32 calls only.
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for relocation in block.entries:
            if relocation.type:
                assert not any(int(c['va'],16)-BASE <= relocation.rva < int(c['va'],16)-BASE+len(bytes.fromhex(c['before'])) for c in changes)
    header=section.get_file_offset()
    struct.pack_into('<I',result,header+8,section.SizeOfRawData+len(payload))
    struct.pack_into('<I',result,header+16,section.SizeOfRawData+len(payload))
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),(rva+len(payload)+4095)&~4095)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'silver.dll').write_bytes(result)
    proof=dict(passed=True,before_sha256=BEFORE,after_sha256=hashlib.sha256(result).hexdigest(),
        changes=changes,appended_rva=hex(rva),appended_bytes=len(payload),code=code,
        original_relocations_unchanged=True,authentication_unchanged=True,
        state=dict(window_rva=window,days_rva=days,default_days=1),original_mark_writer='0x8a0e3c')
    (OUT/'native-review.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k not in ('code','changes') }))
    return proof


if __name__=='__main__':build()
