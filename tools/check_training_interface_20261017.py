"""Local original-instruction proof of the training base/base4 UI mismatch."""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
from verify_world_catalog_native import xml_loader,run,put32,get32
from unicorn.x86_const import UC_X86_REG_ESI

OUT=ROOT/'reports/training-status-20261017'

def prepare(raw):
    import re
    changes=[]
    def amend(match):
        block=match[0];identity=int(match[1])
        if identity not in (19,20,21,22):return block
        assert block.count(b'<value key="type" val="base" />')==1
        changes.append(identity)
        return block.replace(b'<value key="type" val="base" />',b'<value key="type" val="base4" />')
    result=re.sub(rb'<town\b[^>]*\bid="([0-9]+)"[^>]*>.*?</town>',amend,raw,flags=re.S)
    assert changes==[19,20,21,22]
    return result

def probe(raw):
    u,table,cases,visited,loader=xml_loader(raw)
    selected=[]
    for identity in (19,20,21,22):
        record=get32(u,table+(identity-1)*4)
        assert u.mem_read(record+0x23e,1)==b'\1'
        # Execute original TownInfo branch gate. base4 proceeds to its reader;
        # base skips it. No synthetic UI is used to claim rendered buttons.
        u.reg_write(UC_X86_REG_ESI,identity-1)
        end=0x7cf45a if u.mem_read(record+0x255,1)==b'\1' else 0x7cf6e1
        run(u,0x7cf3ea,end)
        selected.append(dict(town=identity,training=True,assault4_zone_reader_selected=end==0x7cf45a))
    return dict(loader=[c for c in cases if c['id']>=19],selection=selected,
        native_instructions=len(visited))

def main():
    raw=(ROOT/'reports/gameplay-completion/stage8-world/client/candidate/zones.xml').read_bytes()
    new=prepare(raw);OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'zones-base4-candidate.xml').write_bytes(new)
    before,after=probe(raw),probe(new)
    assert all(not c['assault4_zone_reader_selected'] for c in before['selection'])
    assert all(c['assault4_zone_reader_selected'] for c in after['selection'])
    report=dict(passed=True,before=before,after=after,changed_towns=[19,20,21,22],
        graphical_client_verified=False,published=False,hosted_data_modified=False,
        limitation='Original loader and TownInfo branch execute; DOM/RTL/allocation/UI helpers isolated.')
    (OUT/'training-interface-proof.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('PASS: four training towns select Assault4 only with type=base4; candidate not published')

if __name__=='__main__':main()
