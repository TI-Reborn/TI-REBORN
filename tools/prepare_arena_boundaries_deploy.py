"""Offline .2 -> .3 boundary packaging; no hosted writes or player data."""
import argparse
import copy
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
import arena_boundaries_release as gate
import prepare_arena_fog_deploy as fog
OUT=ROOT/'reports/arena-boundaries-implementation'
OVERLAY=ROOT/'assets/arena-boundaries-v1/client-overlay'
OLD_OVERLAY=ROOT/'assets/arena-surroundings-v2/client-overlay'
sha,require=gate.sha,gate.require


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def prepare(proof_path,tests_path):
    save(OUT/'release-verification.json',dict(passed=False,status='preparing',published=False))
    baseline=json.loads((OUT/'remote-before.json').read_bytes());old_raw=(OUT/'previous-client-manifest.json').read_bytes()
    old=json.loads(old_raw);before=gate.records(old);launcher=json.loads((OUT/'launcher-baseline.json').read_bytes())
    require(baseline['passed'] is True and baseline['read_only'] is True and baseline['client_version']==gate.OLD and
        baseline['manifest_sha256']==sha(old_raw) and len(before)==6218,'Matching clean .2 baseline required')
    proof_raw=proof_path.read_bytes();proof=json.loads(proof_raw);tests_raw=tests_path.read_bytes();tests=json.loads(tests_raw)
    require(proof.get('passed') is True and isinstance(proof.get('files'),list) and isinstance(proof.get('scenes'),list) and
            isinstance(proof.get('rings'),list) and len(proof['scenes'])==24 and len(proof['rings'])==8,'Completed boundary proof required')
    require(tests.get('passed') is True and max(tests.get('tests_run',0),tests.get('checks',0))>0 and
            tests.get('failures',0)==tests.get('errors',0)==0,'Completed positive-count checks required')
    paths={p.relative_to(OVERLAY).as_posix():p for p in OVERLAY.rglob('*') if p.is_file()}
    expected_scenes={p for p in before if gate.allow_scene_replacement(p)}
    additions={p for p in paths if p not in before}
    require(set(paths)==expected_scenes|additions and additions and all(gate.allow_addition(p) for p in additions) and
            not any(p.is_symlink() for p in paths.values()),'Only 24 SETs and new approved boundary TILE/PNG files allowed')
    inventory=[];data={};changes={};new_records={};new=copy.deepcopy(old);new['version']=gate.NEW
    new['news']='На всех четырёх городских аренах добавлены декоративные границы. Закройте игру и откройте лаунчер для обновления.\n\n'+old.get('news','')
    for path,file in sorted(paths.items()):
        raw=file.read_bytes();data[path]=raw;entry=dict(path=path,size=len(raw),sha256=sha(raw));inventory.append(entry)
        if path in before:
            source=(OLD_OVERLAY/path).read_bytes()
            require(sha(source)==before[path]['sha256'] and len(source)==before[path]['size'],'Old SET source differs from actual .2')
            record=copy.deepcopy(before[path]);record.update(size=len(raw),sha256=sha(raw));changes[path]=dict(before=before[path],after=record)
        else:new_records[path]=entry;changes[path]=dict(before=None,after=entry)
    require(len(proof['files'])==len(inventory) and {r['path']:r for r in proof['files']}=={r['path']:r for r in inventory},'Boundary inventory hash differs')
    for i,r in enumerate(new['files']):
        if r['path'] in changes:new['files'][i]=changes[r['path']]['after']
    new['files'].extend(new_records[p] for p in sorted(new_records))
    delta=gate.manifest_delta(old,new,new_records,{p:changes[p]['after'] for p in expected_scenes})
    tiles={};pngs={};raster_info={}
    for path in additions:
        if path.endswith('.t'):tiles[Path(path).name]=gate.boundary_tile(path,data[path])
        else:pngs[Path(path).name]=data[path];raster_info[path]=gate.boundary_png(data[path])
    scene_info={p:gate.scene_append(p,(OLD_OVERLAY/p).read_bytes(),data[p],additions) for p in sorted(expected_scenes)}
    for path,scene in scene_info.items():
        for model in scene['models']:
            new_path='base/setting/arena_boundaries/'+model['basename']
            index=model['basename'][-6:-2]
            old_path=f"base/setting/arena_surroundings/as_{scene['city']}_{scene['variant']}_{scene['size']}_p{index}.t"
            original=(OLD_OVERLAY/old_path).read_bytes();replacement=data[new_path]
            require(sha(original)==before[old_path]['sha256'],'Original culling TILE differs from actual .2')
            permitted=set(range(74,139))|set(range(203,332))
            require(len(original)==len(replacement)==544 and all(original[i]==replacement[i] for i in range(544) if i not in permitted),
                    'Boundary culling/anchor/offset/dimensions differ from corresponding original TILE')
    declared={s['path']:{k:s[k] for k in ('path','old_sha256','sha256','models')} for s in proof['scenes']}
    require(len(declared)==24 and declared=={p:{k:s[k] for k in ('path','old_sha256','sha256','models')} for p,s in scene_info.items()},'Declared scene append differs')
    groups={};used=set();alpha={}
    for s in scene_info.values():
        key=(s['city'],s['size']);signature=json.dumps(s['models'],sort_keys=True)
        require(key not in groups or groups[key]==signature,'Three city variants use different boundary rings')
        groups[key]=signature;used.update(s['model_paths'])
        if key not in alpha:alpha[key]=gate.ring_alpha(s['size'],s['models'],tiles,pngs,{38:24,57:36}[s['size']])
    require(used=={p for p in additions if p.endswith('.t')} and len(groups)==8,'Unused boundary model or missing ring')
    town_codes={'reservation':'rv','denver':'de','new_york':'ny','military_zone':'mz'}
    declared_rings={}
    for ring in proof['rings']:
        city=town_codes.get(ring['town'],ring['town']);key=(city,ring['width'])
        require(key in groups and key not in declared_rings and ring['depth']==alpha[key]['depth'] and
            [ring['canvas_width'],ring['canvas_height']]==alpha[key]['canvas_dimensions'] and
            ring['alpha_proof']['hole_nonzero_pixels']==0 and ring['render_proof']['full_uv'] is True,'Boundary ring geometry/proof differs')
        require(json.dumps([{k:m[k] for k in ('basename','x','y')} for m in ring['models']],sort_keys=True)==groups[key], 'Ring model anchors differ')
        for model in ring['models']:
            info=tiles[model['basename']]
            require(model['texture_basename']==info['texture'] and model['screen_offset']==info['screen_offset'],'Ring TEX/shift differs')
        declared_rings[key]=ring
    require(len(declared_rings)==8,'Eight complete ring proofs required')
    native_path=ROOT/'reports/arena-surroundings-fog/native-fog-tint.json';native_raw=native_path.read_bytes()
    v1_path=ROOT/'reports/arena-surroundings-implementation/native.json';v1_raw=v1_path.read_bytes()
    fog.validate_native_proof(json.loads(native_raw),sha(v1_raw))
    require(before['ti.exe']['sha256']==fog.NATIVE_HASHES['ti_exe'] and before['silver.dll']['sha256']==fog.NATIVE_HASHES['silver_dll'], 'Pinned production native binaries differ')
    package_proofs={'proofs/boundary-proof.json':proof_raw,'proofs/local-tests.json':tests_raw,
        'proofs/native-fog-tint.json':native_raw,'proofs/native-v1.json':v1_raw,
        'proofs/approved-proposals.json':(ROOT/'assets/arena-boundary-proposals-v1/review.json').read_bytes()}
    palette_raw=(ROOT/'assets/arena-boundaries-v1/native-palette/palette.json').read_bytes()
    palette_proof_raw=(OUT/'palette-verification.json').read_bytes();palette_proof=json.loads(palette_proof_raw)
    require(json.loads(palette_raw)['passed'] is True and palette_proof['passed'] is True and
        palette_proof['palette_sha256']==sha(palette_raw) and palette_proof['source_manifest_sha256']==sha(old_raw) and
        palette_proof['hosted_baseline']['sha256']==sha((OUT/'remote-before.json').read_bytes()), 'Native palette source proof differs')
    package_proofs.update({'proofs/native-palette.json':palette_raw,'proofs/palette-verification.json':palette_proof_raw})
    verified_assets=dict(passed=True,files=inventory,scenes=list(scene_info.values()),
        alpha_proofs={f'{city}_{size}':v for (city,size),v in alpha.items()},rasters=raster_info,**delta)
    package_proofs['proofs/asset-verification.json']=(json.dumps(verified_assets,ensure_ascii=False,indent=2)+'\n').encode()
    new_raw=(json.dumps(new,ensure_ascii=False,indent=2)+'\n').encode()
    guard=dict(schema='arena-boundaries-release/v1',before_version=gate.OLD,version=gate.NEW,baseline=baseline,
        launcher_baseline=launcher,baseline_manifest_sha256=sha(old_raw),new_manifest_sha256=sha(new_raw),
        replacements=changes,manifest_delta=delta,native_v1_proof_sha256=sha(v1_raw),
        proof_files={p:sha(v) for p,v in package_proofs.items()},
        tool_sources={p:sha((ROOT/p).read_bytes()) for p in ('tools/arena_boundaries_release.py',
          'tools/prepare_arena_boundaries_deploy.py','tools/publish_arena_boundaries.py','tools/publish_arena_fog.py')},
        database_uploaded=False,server_code_uploaded=False,service_restart_required=False,executable_or_launcher_changes=False,
        old_b1_tiles_preserved=True,old_source_pngs_preserved=True,new_tile_color_hex='00b1b1b1',new_tile_alpha=255,
        approved_boundary_choice={city:'A' for city in ('reservation','denver','new_york','military_zone')},
        native_proof_scope='Reuse pinned executed foreground geometry/UV and B1 visibility-independent native vertex proof; fresh GUI verification is separate')
    release=OUT/'client-release';release.mkdir(parents=True,exist_ok=True)
    (release/'manifest.json').write_bytes(new_raw);(release/'previous-manifest.json').write_bytes(old_raw);save(OUT/'guard.json',guard)
    archive=OUT/'patch.zip';blobs={sha(v):v for v in data.values()}
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as bundle:
        bundle.writestr('guard.json',(OUT/'guard.json').read_bytes());bundle.writestr('client/manifest.json',new_raw)
        bundle.writestr('client/previous-manifest.json',old_raw)
        for p,v in package_proofs.items():bundle.writestr(p,v)
        for d,v in blobs.items():bundle.writestr('client/blobs/'+d,v)
    save(OUT/'asset-verification.json',verified_assets)
    report=dict(passed=True,version=gate.NEW,previous_version=gate.OLD,**delta,patch_zip_sha256=sha(archive.read_bytes()),
        patch_zip_size=archive.stat().st_size,guard_sha256=sha((OUT/'guard.json').read_bytes()),manifest_sha256=sha(new_raw),
        unique_immutable_blobs=len(blobs),server_contacted=False,published=False,database_uploaded=False)
    save(OUT/'release-verification.json',report);print(json.dumps({k:report[k] for k in
       ('passed','version','changed_scene_records','new_resource_records','patch_zip_sha256','published')}));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof',type=Path,default=ROOT/'assets/arena-boundaries-v1/boundary-proof.json')
    parser.add_argument('--tests-report',type=Path,required=True)
    args=parser.parse_args();prepare(args.proof,args.tests_report)
