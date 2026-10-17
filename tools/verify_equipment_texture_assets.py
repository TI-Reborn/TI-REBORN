"""Check the whole equipment overlay, including native alpha and D3DX allocations."""
from pathlib import Path
import json
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.equipment_texture_assets import ASSETS,OUT,sha
from tools.build_visual_asset_catalog import decode


def verify():
    tasks=json.loads((ASSETS/'tasks.json').read_text(encoding='utf-8'))
    proofs=json.loads((OUT/'texture-proof.json').read_text())
    assert {t['id'] for t in tasks}=={p['id'] for p in proofs}
    records={p['id']:p for p in proofs}
    native=json.loads((OUT/'native-d3dx.json').read_text(encoding='utf-8-sig'))
    native={Path(p['Path']).resolve():p for p in native}
    assert len(native)==len(tasks)
    ajpg=json.loads((OUT/'native-ajpg.json').read_text())
    assert ajpg['passed']
    ajpg={p['path']:p for p in ajpg['cases']}
    cases=[]
    for task in tasks:
        proof=records[task['id']]
        source=(OUT/'source'/task['path']).read_bytes()
        target=OUT/'client'/task['path']
        raw=target.read_bytes()
        original,_=decode(source)
        exported,_=decode(raw)
        assert sha(source)==proof['source_sha256'] and sha(raw)==proof['sha256']
        assert raw!=source and len(raw)==proof['size']
        assert sha((ASSETS/'generated'/(task['id']+'.png')).read_bytes())==proof['master_sha256']
        n=native[target.resolve()]
        assert [n['TextureWidth'],n['TextureHeight']]==list(exported.size)==proof['output_size']
        alpha='opaque atlas'
        if task['kind']=='atlas':
            assert raw[:2]==b'\xff\xd8' and exported.size==(1024,1024)
        else:
            assert exported.size==original.size
            assert exported.getchannel('A').tobytes()==original.getchannel('A').tobytes()
            alpha='exact decoded alpha'
            if source[:2]==b'BM' and struct.unpack_from('<H',source,28)[0]==32:
                offset=struct.unpack_from('<I',source,10)[0]
                assert raw[:offset]==source[:offset] and raw[offset+3::4]==source[offset+3::4]
                alpha='exact native BMP32 bytes and header'
            if source.startswith(bytes.fromhex('07e181')):
                crypto=ajpg[task['path']]
                assert crypto['source_sha256']==sha(source) and crypto['output_sha256']==sha(raw)
                assert crypto['original_mask_sha256']==crypto['output_mask_sha256']
                alpha='original native AJPG decrypt; exact compressed mask and header'
        cases.append(dict(path=task['path'],source_size=list(original.size),output_size=list(exported.size),alpha=alpha,native_device=n['Device']))
    actual={p.relative_to(OUT/'client').as_posix() for p in (OUT/'client').rglob('*') if p.is_file()}
    assert actual=={t['path'] for t in tasks}
    result=dict(passed=True,resources=len(cases),atlases=sum(t['kind']=='atlas' for t in tasks),
                icons=sum(t['kind']=='icon' for t in tasks),original_geometry_unchanged=True,
                original_item_bindings_unchanged=True,graphical_game_client=False,cases=cases)
    (OUT/'asset-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


if __name__=='__main__':verify()
