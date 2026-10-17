"""Repair SC payment after Windows rebases Silver away from 0x400000.

The 15.1 patch left HIGHLOW relocations over relative calls and new clear code.
The imported AC6078 variable actually aliases ACFF9C in the real PE; restore
the original direct loads instead of retaining unnecessary getters.
"""
import hashlib,struct,json
from pathlib import Path
import pefile

SOURCE_SHA='b56c5e5e83ea1a7720b0fbe94cad7547f072aaae31265fb949fecfe4dd674fd3'
BASE=0x400000

def patch(source):
    assert hashlib.sha256(source).hexdigest()==SOURCE_SHA,'Unexpected published Silver'
    pe=pefile.PE(data=source);raw=bytearray(source);changes=[]
    def edit(va,before,after,reason):
        assert len(before)==len(after)
        at=pe.get_offset_from_rva(va-BASE);assert raw[at:at+len(before)]==before,hex(va)
        raw[at:at+len(after)]=after
        changes.append({'va':hex(va),'offset':at,'before':before.hex(),'after':after.hex(),'reason':reason})
    assert pe.get_dword_at_rva(0xac6078-BASE)==0xacff9c,'SC imported global alias changed'
    for va,original in [(0x8dada6,bytes.fromhex('be9cffac00')),
                        (0x8da139,bytes.fromhex('a19cffac00')),
                        (0x8da2c3,bytes.fromhex('a19cffac00')),
                        (0x8da306,bytes.fromhex('a19cffac00'))]:
        at=pe.get_offset_from_rva(va-BASE);before=bytes(raw[at:at+5]);assert before[0]==0xe8
        edit(va,before,original,'Restore original relocated load of shared SC basket global')
    # Retired Gold confirmation is unreachable after its mass-clear entry.
    # Remove its two now-unused getters without changing live absolute operands.
    for va,length in ((0x8da470,16),(0x8da480,15)):
        at=pe.get_offset_from_rva(va-BASE)
        edit(va,bytes(raw[at:at+length]),b'\x90'*length,'Retire unnecessary basket getter')
    start,end=0x8ee584,0x8ee665;code=bytearray()
    def emit(hexbytes):code.extend(bytes.fromhex(hexbytes))
    def call(va):code.extend(b'\xe8'+struct.pack('<i',va-(start+len(code)+5)))
    # ESI is already saved by the native refresh prologue. All new operands
    # use module-relative offsets; no new PE relocation entries are required.
    call(start+5);emit('5e81ee');code.extend(struct.pack('<I',start+5-BASE))
    emit('8b86');code.extend(struct.pack('<I',0xac6078-BASE))
    emit('8b008b80c4020000837808000f95c08b96');code.extend(struct.pack('<I',0xad0020-BASE));emit('88424a')
    emit('8d55cc8d86');code.extend(struct.pack('<I',0x8dbe9c-BASE));call(0x6675e0)
    emit('8b55cc8d45d0');call(0x40c05c)
    emit('8b55d08b86');code.extend(struct.pack('<I',0xad0020-BASE));call(0xa42b04)
    emit('b2018b86');code.extend(struct.pack('<I',0xad0020-BASE));call(0xa42e28)
    code.extend(b'\xe9'+struct.pack('<i',end-(start+len(code)+5)))
    assert len(code)<=end-start
    at=pe.get_offset_from_rva(start-BASE)
    edit(start,bytes(raw[at:at+end-start]),bytes(code)+b'\x90'*(end-start-len(code)),
         'Position-independent clear refresh: live basket rows, localized caption, visible control')
    # A HIGHLOW over legacy SETNE/JMP corrupts executable bytes on rebase.
    # Newer clear refresh and the retired getter bytes likewise contain no
    # absolute operands. Neutralize those old entries, preserving block sizes.
    regions=((0x8da470,0x8da48f),(0x8daef3,0x8daf36),(start,end))
    disabled=[]
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            va=BASE+entry.rva
            if entry.type and any(lo<=va<hi for lo,hi in regions):
                assert entry.type==3
                offset=entry.struct.get_file_offset();before=struct.unpack_from('<H',raw,offset)[0]
                struct.pack_into('<H',raw,offset,before&0xfff)
                disabled.append(hex(va))
    assert disabled==['0x8da480','0x8daeff','0x8ee585','0x8ee597','0x8ee5ab','0x8ee5be','0x8ee5ce','0x8ee5ee','0x8ee60e','0x8ee61d','0x8ee635','0x8ee644','0x8ee65c'],disabled
    checked=pefile.PE(data=raw)
    for block in checked.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            assert not entry.type or not any(lo<=BASE+entry.rva<hi for lo,hi in regions)
    struct.pack_into('<I',raw,checked.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),checked.generate_checksum())
    return bytes(raw),{'source_sha256':SOURCE_SHA,'sha256':hashlib.sha256(raw).hexdigest(),'code_changes':changes,
                       'neutralized_highlow_addresses':disabled,'shared_basket_variable':'[AC6078] == ACFF9C',
                       'new_absolute_relocations':0}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    candidate,report=patch(args.source.read_bytes());(args.out/'silver.dll').write_bytes(candidate)
    (args.out.parent/'native-patches.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.out.parent/'client-changes.json').write_text(json.dumps([{'path':'silver.dll','source':'silver.dll','before':SOURCE_SHA,'sha256':report['sha256'],'size':len(candidate)}],indent=2)+'\n')
    print(json.dumps({'sha256':report['sha256'],'neutralized_relocations':len(report['neutralized_highlow_addresses'])}))
