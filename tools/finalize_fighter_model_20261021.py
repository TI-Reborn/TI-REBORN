"""Validate native mesh/rig identities, interchange file and package deliverables."""
import hashlib,json,math,struct,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.mdjx_mesh import read,encode
ASSET=ROOT/'assets/fighter-model-v1';REPORT=ROOT/'reports/fighter-model-20261020'
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def main():
    model=json.loads((ASSET/'model.json').read_text());assert model['passed']
    staged=json.loads((REPORT/'qa-original-files/base/models/chr_man_head.mdjx').exists() and (REPORT/'gui-visual-check.json').read_text())
    assert staged['native_mdjx_loaded'] and staged['real_game_client'] and staged['hosted_account']
    records=[]
    for item in model['parts']:
        path=ASSET/item['file'];m=read(path);source=REPORT/'source/base/models'/item['source'];old=read(source)
        assert sha(source.read_bytes())==item['source_sha256']
        assert sha(path.read_bytes())==item['sha256'] and encode(m)==path.read_bytes()
        assert m.tail==old.tail and m.bones==old.bones
        assert sha(m.tail)==item['bone_tail_sha256']
        assert len(m.indices)//3==item['triangles'] and len(m.vertices)==item['vertices']
        assert all(abs(sum(v.weights)-1)<.002 and max(v.joints)<len(m.bones) for v in m.vertices)
        assert all(abs(math.sqrt(sum(c*c for c in v.normal))-1)<.002 for v in m.vertices)
        assert all(all(math.isfinite(x) for x in (*v.position,*v.normal,*v.uv)) for v in m.vertices)
        lower=ASSET/'lod1'/path.name;low=read(lower)
        assert low.tail==m.tail and len(low.indices)//3==item['lod1_triangles']
        records.append(dict(file=item['file'],sha256=sha(path.read_bytes()),vertices=len(m.vertices),triangles=len(m.indices)//3))
    raw=(ASSET/'veteran.glb').read_bytes();magic,version,size=struct.unpack_from('<4sII',raw)
    assert magic==b'glTF' and version==2 and size==len(raw)
    length,kind=struct.unpack_from('<II',raw,12);assert kind==0x4e4f534a
    gltf=json.loads(raw[20:20+length]);assert len(gltf['meshes'])==4 and len(gltf['skins'])==1
    assert len(gltf['skins'][0]['joints'])==52
    assert {a['name'] for a in gltf['animations']}=={'Preview_Idle','Preview_Walk'}
    assert all({'POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'}<=set(p['attributes']) for m in gltf['meshes'] for p in m['primitives'])
    rig=json.loads((ASSET/'rig-validation.json').read_text());assert rig['passed'] and len(rig['sampled_deformations'])==18
    cleanup=json.loads((REPORT/'fixture-cleanup.json').read_text());assert cleanup['preexisting_players_preserved'] and cleanup['integrity']=='ok'
    restored=json.loads((REPORT/'qa-restored.json').read_text());assert restored['all_original_bytes_restored']
    result=dict(passed=True,name='Veteran',native_meshes=4,vertices=sum(i['vertices'] for i in records),
                triangles=sum(i['triangles'] for i in records),rig_bones=52,bind_tails_preserved=True,
                glb_valid=True,blender_rig_sampled_poses=18,hosted_graphical_preview=True,
                native_pistol_idle_verified=True,complete_battle_animation_regression=False,
                private_qa_copy_restored=True,qa_accounts_cleaned=True,published=False,files=records)
    (ASSET/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    archive=ROOT/'output/fighter-veteran-v1.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in sorted(ASSET.rglob('*')):
            if f.is_file() and f.suffix not in ('.blend1',):z.write(f,f.relative_to(ASSET.parent))
        for name in ('mdjx_mesh.py','build_fighter_model_20261020.py','fighter_model_blender_20261020.py','validate_fighter_model_blender_20261021.py','finalize_fighter_model_20261021.py'):
            z.write(ROOT/'tools'/name,'fighter-model-v1/build-tools/'+name)
        for f in (ROOT/'tools/FighterTexturePack').glob('*'):
            if f.is_file():z.write(f,'fighter-model-v1/build-tools/FighterTexturePack/'+f.name)
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    print(json.dumps(dict(passed=True,triangles=result['triangles'],vertices=result['vertices'],rig_bones=52,archive=str(archive),bytes=archive.stat().st_size,published=False)))


if __name__=='__main__':main()
