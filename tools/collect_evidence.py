"""Persist exact x86 bytes/disassembly, jump tables, and resource structural diffs."""
import collections
import difflib
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET
import capstone
import pefile

ROOT = Path(__file__).resolve().parents[1]
E = ROOT/'evidence'
TI = Path(r'C:\Program Files (x86)\TIOnline')
AZT = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Affected Zone Tactics')
RANGES = {
    ('TI','silver.dll'): [(0x9f5548,0x286),(0x87daa4,0x20),(0x87dafc,0xda),(0x87ce60,0x11e),(0x605d68,0x5a),(0x87c5e4,0x1f),(0x87c604,0x150),(0x87d00c,0x124),(0x87d1cc,0x230),(0x87d400,0x208),(0x87d608,0x29c),(0x87d8a4,0x200),(0x87c76c,0x48),(0x87c7b4,0xb4),(0x87c8fc,0x88),(0x673464,0x60)],
    ('TI','ti.exe'): [(0x718fb8,0x220),(0x728657,0x3f)],
    ('TI','gold.dll'): [(0x10001010,0x53)],
    ('AZT','silver.dll'): [(0xce6d14,0x28),(0xce6d74,0xfd),(0xce5608,0x18f),(0x4f04f0,0x19),(0x4f05fc,0x1c)],
}


def main():
    provenance = []
    md = capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
    for (label,name),ranges in RANGES.items():
        path = (TI if label=='TI' else AZT)/name
        raw=path.read_bytes(); pe=pefile.PE(data=raw)
        digest=hashlib.sha256(raw).hexdigest()
        for va,size in ranges:
            code=pe.get_data(va-pe.OPTIONAL_HEADER.ImageBase,size)
            filename=f'{label}.{name}.{va:08x}.asm'
            lines=[f'; Source: {path}',f'; SHA-256: {digest}',f'; Preferred VA: 0x{va:x}, file offset: 0x{pe.get_offset_from_rva(va-pe.OPTIONAL_HEADER.ImageBase):x}', '; Linear disassembly stops at undecodable embedded data; jump tables recorded separately.']
            lines += [f'{i.address:08x} {i.bytes.hex():24} {i.mnemonic:8} {i.op_str}' for i in md.disasm(code,va)]
            (E/filename).write_text('\n'.join(lines)+'\n',encoding='utf-8')
            provenance.append({'file':filename,'binary_sha256':digest,'va':hex(va),'bytes_hex':code.hex()})
        if name=='silver.dll':
            table = 0x87dac4 if label=='TI' else 0xce6d3c
            pointers=struct.unpack('<14I',pe.get_data(table-pe.OPTIONAL_HEADER.ImageBase,56))
            (E/f'{label}.login_dispatch_table.json').write_text(json.dumps({'table_va':hex(table),'binary_sha256':digest,'entries':{f'0x{n:02X}':hex(v) for n,v in enumerate(pointers)}},indent=2),encoding='utf-8')
    (E/'disassembly_provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    names=json.loads((E/'TI.silver.dll.strings.json').read_text())
    (E/'packet_name_anchors.json').write_text(json.dumps([s for s in names if any(x in s['string'] for x in ('RECV_','SEND_','PacketHandler','HandlePacket'))],indent=2),encoding='utf-8')
    rawstructures=json.loads((E/'resource_structures.json').read_text())
    deltas={}
    for name, sides in rawstructures.items():
        if not sides['TI'] or not sides['AZT']:
            deltas[name]={'status':'missing in one client'}; continue
        tip=TI/sides['TI'][0]['path']; azp=AZT/sides['AZT'][0]['path']
        if tip.suffix=='.xml':
            ts=sides['TI'][0]['structure']; azs=sides['AZT'][0]['structure']
            deltas[name]={'shape_count_changes':{key:{'TI':ts.get(key,0),'AZT':azs.get(key,0)} for key in sorted(ts.keys()|azs.keys()) if ts.get(key)!=azs.get(key)}}
            # Canonical XML preserves values while normalizing attribute order.
            try:
                a=ET.canonicalize(tip.read_bytes()).replace('><','>\n<').splitlines()
                b=ET.canonicalize(azp.read_bytes()).replace('><','>\n<').splitlines()
            except (ET.ParseError,UnicodeError,ValueError) as exc:
                deltas[name]['canonical_diff_error']=str(exc); continue
        else:
            a=tip.read_bytes().decode('cp1251').splitlines()
            b=azp.read_bytes().decode('cp1251').splitlines()
            deltas[name]={'status':'text config diff; decoding chosen for inspection, not network encoding'}
        (E/f'{name}.diff').write_text('\n'.join(difflib.unified_diff(a,b,fromfile='TI/'+name,tofile='AZT/'+name))+'\n',encoding='utf-8')
    (E/'resource_structure_diff.json').write_text(json.dumps(deltas,indent=2),encoding='utf-8')
    print('Saved disassembly, provenance, dispatcher tables, packet-name anchors, XML/config diffs.')


if __name__=='__main__':
    main()
