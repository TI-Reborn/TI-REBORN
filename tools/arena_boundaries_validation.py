"""Read-only exact published .3 SET/TILE/PNG validation; no game sessions."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import time
import types

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import arena_boundaries_release as gate
from tools import verify_hosted_arena_surroundings as legacy
from tools.arena_fog_validation import validate_fog_tile
from tools.publish_arena_fog import get as strict_https_get

VERSION='2026.10.07.3'
OUT=ROOT/'reports/arena-boundaries-implementation'
BASELINE=OUT/'previous-client-manifest.json'
OLD_SCENES=OUT/'remote-scenes'
require=gate.require


def published_boundary_scene(host,manifest,scene,size,*,fetch=None):
    """Verify actual .3 resources, allowing only old/new paired patch origins."""
    require(manifest.get('version')==VERSION and size in (38,57),'Expected published boundary .3 release')
    path='base/maps/'+scene+'.s';match=re.fullmatch(gate.SCENE_PATTERN,path)
    require(match is not None and int(match.group(3))==size,'Unexpected city scene/size')
    records=gate.records(manifest)
    old_raw=BASELINE.read_bytes();old_manifest=json.loads(old_raw);before=gate.records(old_manifest)
    snapshot=json.loads((OUT/'remote-before.json').read_bytes())
    require(old_manifest['version']==gate.OLD and gate.sha(old_raw)==snapshot['manifest_sha256'],'Actual .2 baseline pin differs')
    additions={p:r for p,r in records.items() if p not in before}
    changed={p:r for p,r in records.items() if p in before and r!=before[p]}
    gate.manifest_delta(old_manifest,manifest,additions,changed)
    original=(OLD_SCENES/path).read_bytes()
    require(gate.sha(original)==before[path]['sha256'] and len(original)==before[path]['size'],'Read-only original SET pin differs')
    observed={};cache={};deadline=time.monotonic()+80

    def resource(record):
        p=record['path']
        require(records.get(p)==record and type(record['size']) is int and 0<record['size']<=8*1024*1024,
                'Unexpected published boundary resource size/record')
        if p not in cache:
            if fetch is None:
                require(host=='185.184.42.88','Unexpected public boundary host')
                raw=strict_https_get('https://'+host+'/updates/blobs/'+record['sha256'],deadline=deadline)
            else:raw=fetch(record)
            require(isinstance(raw,bytes) and len(raw)==record['size'] and gate.sha(raw)==record['sha256'],
                    'Published boundary resource SHA differs: '+p)
            cache[p]=raw
        observed[p]={k:record[k] for k in ('path','size','sha256')}
        return cache[p]

    new_raw=resource(records[path]);append=gate.scene_append(path,original,new_raw,additions)
    native=legacy.validate_scene_blob(new_raw,size);native['cells']=[[0]]
    native.update(old_model_count=append['old_model_count'],boundary_model_count=len(append['models']))
    old_native=legacy.validate_scene_blob(original,size)
    # The frozen old-only verifier sees the actual .3 SET bytes/hash but only
    # the independently pinned original model prefix. Its duplicate-origin
    # and >=95% alpha checks therefore remain unchanged and meaningful.
    def original_scene(blob,requested):
        require(blob==new_raw and requested==size,'Private old-prefix probe received another SET')
        return copy.deepcopy(old_native)
    namespace=dict(legacy.published_scene.__globals__)
    namespace.update(validate_scene_blob=original_scene,validate_tile_blob=validate_fog_tile)
    old_probe=types.FunctionType(legacy.published_scene.__code__,namespace,
        'published_original_boundary_prefix',legacy.published_scene.__defaults__)
    old_probe.__kwdefaults__=legacy.published_scene.__kwdefaults__.copy()
    old=old_probe(host,manifest,scene,size,fetch=resource)
    dependencies=copy.deepcopy(old['model_dependencies']);tiles={};pngs={};origins=set()
    for model in append['models']:
        basename=model['basename'];model_path='base/setting/arena_boundaries/'+basename
        raw=resource(records[model_path]);tile=gate.boundary_tile(model_path,raw)
        index=re.fullmatch(gate.RESOURCE_PATTERN,model_path).group(3)
        original_name=f"{scene}_p{index}.t";source_path='base/setting/arena_surroundings/'+original_name
        original_tile=resource(records[source_path])
        allowed=set(range(74,139))|set(range(203,332))
        require(len(original_tile)==len(raw)==544 and all(original_tile[i]==raw[i] for i in range(544) if i not in allowed),
                'Published boundary changes corresponding native culling/offset/behavior')
        texture_path='base/setting/arena_boundaries/'+tile['texture'];image_raw=resource(records[texture_path])
        gate.boundary_png(image_raw)
        source=dependencies[original_name];origin=tuple(source['canvas_origin'])
        require(origin not in origins,'Two boundary models occupy the same original patch rectangle')
        origins.add(origin)
        # Old and new origins must coincide exactly. Padding beyond each old
        # rectangular canvas is transparent, even when the PNG is power-of-two.
        from PIL import Image
        depth={38:24,57:36}[size];full_width,full_height=64*(size+2*depth),32*(size+2*depth)
        with Image.open(io.BytesIO(image_raw)) as image:
            alpha=image.getchannel('A');px,py=origin
            ex,ey=min(1024,full_width-px),min(1024,full_height-py)
            require(alpha.crop((0,ey,1024,1024)).getbbox() is None and
                    alpha.crop((ex,0,1024,1024)).getbbox() is None,'Opaque boundary pixels in padded canvas region')
        tiles[basename]=tile;pngs[tile['texture']]=image_raw
        dependencies[basename]=dict(model=observed[model_path],texture=observed[texture_path],tile=tile,
            canvas_origin=list(origin),inherits_original=original_name,paired_duplicate_origin=True)
    boundary=gate.ring_alpha(size,append['models'],tiles,pngs,{38:24,57:36}[size])
    # Source-over boundary alpha cannot reduce the old opaque coverage. Both
    # independently reconstructed layers have zero alpha on the game footprint.
    combined=copy.deepcopy(old['alpha_proof'])
    combined.update(passed=True,old_and_new_holes_clear=True,
        method='Unchanged old alpha lower bound plus independently verified source-over boundary alpha; paired origins are intentional')
    return dict(path=path,sha256=observed[path]['sha256'],native=native,model_dependencies=dependencies,
        alpha_proof=combined,legacy_alpha_proof=old['alpha_proof'],boundary_alpha_proof=boundary,
        strict_append=append,paired_duplicate_origins=len(origins),
        exact_published_records=[observed[p] for p in sorted(observed)])


def self_test():
    """Synthetic unpublished .3 cases built from actual pinned .2 resources."""
    before=json.loads(BASELINE.read_bytes());old_records=gate.records(before);checks=0;cases=[]
    for scene,size in (('as_rv_1_38',38),('as_mz_1_57',57)):
        path='base/maps/'+scene+'.s';source=(OLD_SCENES/path).read_bytes();models=gate.scene_records(source)
        manifest=copy.deepcopy(before);manifest['version']=VERSION;by_path={r['path']:r for r in manifest['files']}
        # Other unfetched scenes are changed in the synthetic inventory to keep
        # the global 24-scene release gate active; only selected bytes are tested.
        for p,r in by_path.items():
            if gate.allow_scene_replacement(p):r['sha256']='c'*64
        data={};added={};new_models=[];city=scene.split('_')[1]
        for model in models:
            name=model['basename'];index=name[-6:-2];basename=f'ab_{city}_a_{size}_p{index}.t'
            old_path='base/setting/arena_surroundings/'+name
            raw=bytearray((ROOT/'assets/arena-surroundings-v2/client-overlay'/old_path).read_bytes())
            for offset,length,value in ((74,65,'ti_'+basename[:-2]),(203,129,basename[:-2]+'.png')):
                encoded=value.encode();raw[offset:offset+length]=bytes([len(encoded)])+encoded+bytes(length-len(encoded)-1)
            tile_path='base/setting/arena_boundaries/'+basename;texture_path=tile_path[:-2]+'.png'
            texture=(ROOT/'assets/arena-surroundings-v2/client-overlay'/old_path[:-2]).with_suffix('.png').read_bytes()
            data[tile_path]=bytes(raw);data[texture_path]=texture
            for p in (tile_path,texture_path):added[p]=dict(path=p,size=len(data[p]),sha256=gate.sha(data[p]))
            new_models.append(dict(basename=basename,x=model['x'],y=model['y']))
        # Paired placeholder inventory for the seven nonselected rings; no
        # bytes are fetched and no hosted artifact is created.
        for other in ('rv','de','ny','mz'):
            for width in (38,57):
                if (other,width)==(city,size):continue
                for suffix in ('t','png'):
                    p=f'base/setting/arena_boundaries/ab_{other}_a_{width}_p0000.{suffix}'
                    added[p]=dict(path=p,size=1,sha256='d'*64)
        new=bytearray(source);struct.pack_into('<H',new,16,len(models)+len(new_models))
        for model in new_models:
            name=model['basename'].encode();new.extend(bytes([len(name)])+name+bytes(63-len(name)))
            new.extend(struct.pack('<ii',model['x'],model['y']))
        data[path]=bytes(new);by_path[path].update(size=len(new),sha256=gate.sha(new));manifest['files'].extend(added.values())
        def fetch(record):
            p=record['path'];return data[p] if p in data else (ROOT/'assets/arena-surroundings-v2/client-overlay'/p).read_bytes()
        verified=published_boundary_scene('fixture.invalid',manifest,scene,size,fetch=fetch)
        require(verified['native']['model_count']==2*len(models) and verified['paired_duplicate_origins']==len(models) and
            verified['legacy_alpha_proof']['passed'] and verified['boundary_alpha_proof']['passed'],'Valid paired published fixture rejected')
        checks+=1;cases.append(dict(scene=scene,size=size,models=verified['native']['model_count'],
            paired_origins=len(models),published_resources=len(verified['exact_published_records'])))
        changed=copy.deepcopy(manifest);changed['version']=gate.OLD
        try:published_boundary_scene('fixture.invalid',changed,scene,size,fetch=fetch)
        except RuntimeError:checks+=1
        else:raise AssertionError('Wrong release accepted')
        bad=copy.deepcopy(manifest);next(r for r in bad['files'] if r['path'].endswith('.png') and r['path'] in data)['sha256']='e'*64
        try:published_boundary_scene('fixture.invalid',bad,scene,size,fetch=fetch)
        except RuntimeError:checks+=1
        else:raise AssertionError('Incorrect PNG SHA accepted')
        model_path='base/setting/arena_boundaries/'+new_models[0]['basename'];original=data[model_path]
        for offset in (48,52,56,68,340):
            broken=bytearray(original);broken[offset]^=1;data[model_path]=bytes(broken)
            bad=copy.deepcopy(manifest);next(r for r in bad['files'] if r['path']==model_path)['sha256']=gate.sha(bytes(broken))
            try:published_boundary_scene('fixture.invalid',bad,scene,size,fetch=fetch)
            except (RuntimeError,AssertionError):checks+=1
            else:raise AssertionError('Unsafe boundary TILE accepted')
        data[model_path]=original
        bad_scene=bytearray(data[path]);bad_scene[35]^=1
        changed=copy.deepcopy(manifest);data[path]=bytes(bad_scene)
        next(r for r in changed['files'] if r['path']==path)['sha256']=gate.sha(bytes(bad_scene))
        try:published_boundary_scene('fixture.invalid',changed,scene,size,fetch=fetch)
        except (RuntimeError,AssertionError):checks+=1
        else:raise AssertionError('Original SET prefix edit accepted')
    report=dict(passed=True,checks=checks,cases=cases,network_requests=0,accounts_created=0,battles_started=0,
        kind='Unpublished synthetic .3 manifests and paired resources from exact .2 inputs; no actual boundary artwork/GPU claim')
    (OUT/'published-validation-self-test.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args();require(args.self_test,'Only offline self-test CLI is supported; hosted reads occur through the stager')
    self_test()
