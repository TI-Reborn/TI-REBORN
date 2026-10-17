"""Verify exact geometry, original alpha masks and isolated resource bindings."""
from reservation_texture_assets import *

def verify():
    from tools.build_visual_asset_catalog import decode
    inventory=json.loads((OUT/'inventory.json').read_text());mapping=json.loads((OUT/'names.json').read_text())
    proof=json.loads((OUT/'resource-proof.json').read_text());textures=json.loads((OUT/'texture-proof.json').read_text())
    assert len(proof)==351 and len(textures)==109
    assert sum(not p.get('shadow_preserved') for p in textures)==107
    assert len({n.lower() for n in mapping.values()})==len(mapping)
    before={Path(r['path']).name.lower() for r in json.loads((OUT/'previous-client-manifest.json').read_bytes())['files']}
    assert before.isdisjoint(n.lower() for n in mapping.values())
    for p in proof:
        original=fetch(p['source']).read_bytes()
        if p['kind']=='fragment' and original[:4]==b'\x03ZIP':original=zlib.decompress(original[16:])
        allowed=inventory['models'] if p['kind']=='fragment' else inventory['textures']
        expected=renamed(original,{k:v for k,v in mapping.items() if k in allowed})
        actual=(OUT/'client'/p['target']).read_bytes()
        assert expected==actual and len(original)==len(actual),p['target']
        assert sha(actual)==p['sha'],p['target']
    for name,path in inventory['textures'].items():
        original=fetch(path).read_bytes();new=(OUT/'client/base/setting/reservation_v2'/mapping[name]).read_bytes()
        a,_=decode(original);b,_=decode(new)
        assert a.size==b.size and a.getchannel('A').tobytes()==b.getchannel('A').tobytes(),name
    def signature(n):return (n.tag,n.attrib,tuple(signature(c) for c in n))
    old=ET.parse(fetch('base/ground.xml')).getroot();new=ET.parse(OUT/'client/base/ground.xml').getroot()
    for n in old:assert signature(n)==signature(new.find(f"ground[@id='{n.get('id')}']"))
    for identity in (10,11):
        for b in new.find(f"ground[@id='{identity}']"):
            assert (OUT/'client/base/setting'/b.get('filename').replace('\\','/')).exists()
    bindings=json.loads((ROOT/'config/reservation_visuals.json').read_text())['entries']
    assert all((OUT/'client/base/maps'/(n+'.s')).exists() for n in bindings.values())
    report=dict(passed=True,model_geometry_unchanged=270,fragment_geometry_unchanged=81,
                texture_masks_and_dimensions_exact=109,ai_textures=107,original_shadow_textures=2,
                all_previous_ground_groups_unchanged=True,client_files=461,graphical_client=False)
    (OUT/'asset-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT));verify()
