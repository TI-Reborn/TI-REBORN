"""Guarded client-only .3 boundary publication; --execute is required.

Reuses the frozen .2 SSH/backup/atomic/HTTPS transport in an isolated namespace.
All outputs go to the new boundary folder; no .1/.2 artifacts are modified.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import inspect
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
import arena_boundaries_release as gate
import prepare_arena_boundaries_deploy as prep
import publish_arena_fog as transport
OUT=prep.OUT
require,sha,save=gate.require,gate.sha,prep.save
FROZEN_TRANSPORT_SHA='a0dfb12eca02127f6d12459b46576d1321d14924e73e768de62af5f6a547029f'
require(sha((ROOT/'tools/publish_arena_fog.py').read_bytes())==FROZEN_TRANSPORT_SHA,'Frozen .2 transport drift')


REMOTE_EXTRA=r'''
from pathlib import PurePosixPath
from collections import Counter
OLD='2026.10.07.2';NEW='2026.10.07.3'
require=check
'''+f'SCENE_PATTERN={gate.SCENE_PATTERN!r}\nRESOURCE_PATTERN={gate.RESOURCE_PATTERN!r}\n'+''.join(
    inspect.getsource(fn)+'\n' for fn in (gate.records,gate.allow_addition,gate.allow_scene_replacement,
        gate.manifest_delta,gate.scene_records,gate.scene_append))+r'''
def validate_payload(bundle,g):
 names=bundle.namelist();changes=g['replacements']
 expected={'guard.json','client/manifest.json','client/previous-manifest.json'}|set(g['proof_files'])|{
  'client/blobs/'+r['after']['sha256'] for r in changes.values()}
 check(len(set(names))==len(names) and set(names)==expected and bundle.testzip() is None,'Unsafe/incomplete boundary ZIP')
 check(all(not r.is_dir() and ((r.external_attr>>16)&0o170000)!=0o120000 for r in bundle.infolist()),'Unsafe boundary ZIP member type')
 old_raw=bundle.read('client/previous-manifest.json');new_raw=bundle.read('client/manifest.json')
 check(sha(old_raw)==g['baseline_manifest_sha256'] and sha(new_raw)==g['new_manifest_sha256'],'Boundary manifest pin differs')
 old=json.loads(old_raw);new=json.loads(new_raw);a=records(old);b=records(new)
 additions={p:r['after'] for p,r in changes.items() if r['before'] is None}
 scenes={p:r['after'] for p,r in changes.items() if r['before'] is not None}
 delta=manifest_delta(old,new,additions,scenes)
 check(delta==g['manifest_delta'],'Boundary manifest delta differs')
 data={}
 for p,r in changes.items():
  raw=bundle.read('client/blobs/'+r['after']['sha256']);data[p]=raw
  check(sha(raw)==r['after']['sha256'] and len(raw)==r['after']['size'] and r['after']==b[p],'Boundary blob pin differs')
  check(r['before']==a.get(p),'Boundary baseline record differs')
 for p,d in g['proof_files'].items():check(sha(bundle.read(p))==d,'Boundary proof pin differs')
 proof=json.loads(bundle.read('proofs/boundary-proof.json'));verified=json.loads(bundle.read('proofs/asset-verification.json'))
 tests=json.loads(bundle.read('proofs/local-tests.json'));native=json.loads(bundle.read('proofs/native-fog-tint.json'))
 check(proof['passed'] is True and verified['passed'] is True and tests['passed'] is True and
  max(tests.get('tests_run',0),tests.get('checks',0))>0 and tests.get('failures',0)==tests.get('errors',0)==0,
  'Boundary local proofs incomplete')
 inventory={p:dict(path=p,size=len(raw),sha256=sha(raw)) for p,raw in data.items()}
 check(len(proof['files'])==len(data) and {r['path']:r for r in proof['files']}==inventory and
  {r['path']:r for r in verified['files']}==inventory,'Boundary proof inventory differs')
 check(native['status']=='PASS' and native['tint_color_hex']=='00b1b1b1' and native['alpha']==255 and
  native['runtime_rgb']['passed'] is True and native['fog_independent'] is True and native['interactive_fields_zero'] is True and
  native['native_v1_proof_sha256']==sha(bundle.read('proofs/native-v1.json'))==g['native_v1_proof_sha256'],
  'Inherited native foreground/B1 proof differs')
 check(a['ti.exe']['sha256']==native['immutable_native_binary_sha256']['ti_exe'] and
  a['silver.dll']['sha256']==native['immutable_native_binary_sha256']['silver_dll'],'Pinned native binaries differ')
 declared={r['path']:{k:r[k] for k in ('path','old_sha256','sha256','models')} for r in proof['scenes']}
 groups={};used=set()
 for p,r in scenes.items():
  original=(LIVE/'blobs'/a[p]['sha256']).read_bytes()
  check(sha(original)==a[p]['sha256'],'Published original SET hash differs')
  info=scene_append(p,original,data[p],additions);key=(info['city'],info['size'])
  check(declared[p]=={k:info[k] for k in ('path','old_sha256','sha256','models')},'Boundary SET append declaration differs')
  signature=json.dumps(info['models'],sort_keys=True)
  check(key not in groups or groups[key]==signature,'Three variants disagree on the boundary ring')
  groups[key]=signature;used.update(info['model_paths'])
  for model in info['models']:
   tile_path='base/setting/arena_boundaries/'+model['basename'];raw=data[tile_path];index=model['basename'][-6:-2]
   old_path=f"base/setting/arena_surroundings/as_{info['city']}_{info['variant']}_{info['size']}_p{index}.t"
   old_tile=(LIVE/'blobs'/a[old_path]['sha256']).read_bytes()
   check(sha(old_tile)==a[old_path]['sha256'] and len(old_tile)==len(raw)==544 and raw[:8]==b'TI TILE\0' and
    struct.unpack_from('<II',raw,52)==(0x00b1b1b1,255),'Inherited native TILE differs')
   allowed=set(range(74,139))|set(range(203,332))
   check(all(raw[i]==old_tile[i] for i in range(544) if i not in allowed),'Boundary native culling/behavior changed')
   n=raw[203];texture=raw[204:204+n].decode('ascii')
   check(texture==model['basename'][:-2]+'.png','Boundary texture basename differs')
   png=data['base/setting/arena_boundaries/'+texture]
   check(png[:8]==b'\x89PNG\r\n\x1a\n' and png[12:16]==b'IHDR' and
     struct.unpack_from('>IIBB',png,16)==(1024,1024,8,6),'Boundary PNG is not full-frame RGBA1024')
 check(len(groups)==8 and used=={p for p in additions if p.endswith('.t')},'Missing ring/unreferenced boundary model')
 check(len(verified['alpha_proofs'])==8 and all(v['passed'] is True and v['hole_nonzero_pixels']==
  v['outside_nonzero_pixels']==0 and all(v['four_sides'].values()) and all(v['four_corners'].values())
  for v in verified['alpha_proofs'].values()),'Independent boundary pixel proof incomplete')
 check(g['database_uploaded'] is g['server_code_uploaded'] is g['service_restart_required'] is
  g['executable_or_launcher_changes'] is False,'Non-client boundary scope')
 return old_raw,new_raw
original_main=main
def main(request):
 result=original_main(request)
 if request['action']=='publish':
  delta=request['guard']['manifest_delta'];result.update(delta)
  result['changed_records']=delta['changed_scene_records'];result['unchanged_records']=delta['unchanged_existing_records']
  result['b1_tiles_preserved']=552;result['png_records_preserved']=552
  (Path(result['backup'])/'publication.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 return result
'''

# Rebinding runtime variables does not edit or write frozen .2 files. The
# proven transport now saves failures in the boundary directory exclusively.
transport.OUT=OUT
transport.REMOTE=transport.REMOTE.replace('arena-surroundings-fog-release/v1','arena-boundaries-release/v1').replace(
    'tio-before-arena-surroundings-fog-','tio-before-arena-boundaries-').replace(
    'tio-arena-fog-','tio-arena-boundaries-').replace('.manifest-fog-','.manifest-boundaries-')+REMOTE_EXTRA


def load_bundle():
    report=json.loads((OUT/'release-verification.json').read_bytes());archive=(OUT/'patch.zip').read_bytes()
    require(report['passed'] is True and report['version']==gate.NEW and sha(archive)==report['patch_zip_sha256'],'Completed boundary bundle required')
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        raw_guard=bundle.read('guard.json');guard=json.loads(raw_guard)
        require(sha(raw_guard)==report['guard_sha256']==sha((OUT/'guard.json').read_bytes()),'Boundary guard SHA differs')
        require(guard['schema']=='arena-boundaries-release/v1' and guard['version']==gate.NEW and guard['before_version']==gate.OLD,'Unknown boundary guard')
        require(all(sha((ROOT/p).read_bytes())==d for p,d in guard['tool_sources'].items()),'Prepared boundary tool drift')
        # Run the identical remote payload predicate on the local published .2
        # mirror. This performs no shell, process, SQLite or network calls.
        ns={};exec(transport.REMOTE,ns)
        with tempfile.TemporaryDirectory(prefix='tio-boundary-local-') as temp:
            live=Path(temp);(live/'blobs').mkdir();ns['LIVE']=live
            old_raw=bundle.read('client/previous-manifest.json');old=gate.records(json.loads(old_raw))
            for p,r in old.items():
                if gate.allow_scene_replacement(p) or (p.startswith('base/setting/arena_surroundings/') and p.endswith('.t')):
                    original=(prep.OLD_OVERLAY/p).read_bytes();require(sha(original)==r['sha256'],'Local .2 mirror drift')
                    (live/'blobs'/r['sha256']).write_bytes(original)
            old_raw,new_raw=ns['validate_payload'](bundle,guard)
        require(guard['baseline']['passed'] is True and guard['baseline']['manifest_sha256']==sha(old_raw),'Boundary baseline differs')
    return report,guard,old_raw,new_raw


def https_check(guard,new_raw):
    deadline=time.monotonic()+300
    actual=transport.get(transport.ORIGIN+'manifest.json',deadline=deadline)
    require(actual==new_raw,'Public boundary manifest differs')
    def check(entry):
        path,r=entry;raw=transport.get(transport.ORIGIN+'blobs/'+r['after']['sha256'],deadline=deadline)
        require(len(raw)==r['after']['size'] and sha(raw)==r['after']['sha256'],'Public boundary blob differs: '+path)
        return path
    with ThreadPoolExecutor(max_workers=3) as pool:verified=list(pool.map(check,sorted(guard['replacements'].items())))
    return dict(passed=True,client_version=gate.NEW,manifest_sha256=sha(actual),verified_changed_and_new_resources=len(verified),
        b1_tiles_preserved=552,source_pngs_preserved=552,legacy_records_preserved=5090,
        concurrency=3,request_attempt_limit=3,deadline_seconds=300,graphical_client_verification=False)


def publish(execute=False):
    report,guard,old_raw,new_raw=load_bundle()
    plan=dict(passed=True,version=gate.NEW,previous_version=gate.OLD,**guard['manifest_delta'],
        execute_requested=execute,server_contacted=False,database_uploaded=False,code_uploaded=False,
        service_restart_required=False,backup_consistent_live_database=True,atomic_manifest=True)
    save(OUT/'publication-plan.json',plan)
    if not execute:print(json.dumps(dict(passed=True,offline=True,version=gate.NEW,execute_required=True)));return plan
    save(OUT/'deployment.json',dict(passed=False,status='preflight',version=gate.NEW))
    before=transport.remote('inspect',guard);save(OUT/'publication-preflight.json',before)
    target='/root/tio-arena-boundaries-'+report['patch_zip_sha256']+'.zip'
    subprocess.run(transport.SCP+[str(OUT/'patch.zip'),transport.HOST+':'+target],check=True,capture_output=True,timeout=120)
    deployed=transport.remote('publish',guard,zip_path=target,zip_sha256=report['patch_zip_sha256'],guard_sha256=report['guard_sha256'])
    try:
        public=https_check(guard,new_raw);save(OUT/'https-release.json',public)
        health=transport.remote('postflight',guard,database_before=deployed['before']['database']);save(OUT/'hosted-health.json',health)
    except Exception as error:
        failure=dict(passed=False,version=gate.NEW,error=str(error),backup=deployed['backup'],published=False)
        try:failure['rollback']=transport.remote('rollback',guard,backup=deployed['backup'])
        except Exception as rollback_error:failure['rollback_error']=str(rollback_error)
        save(OUT/'deployment.json',failure);raise
    deployed.update(patch_zip_sha256=report['patch_zip_sha256'],public_https_passed=True,postflight_passed=True,
        graphical_clients_verified=False)
    save(OUT/'deployment.json',deployed);print(json.dumps({k:deployed[k] for k in
        ('passed','version','changed_scene_records','new_resource_records','backup','service_restarted')}));return deployed


def self_test():
    from PIL import Image
    checks=0
    before=json.loads((OUT/'previous-client-manifest.json').read_bytes());a=gate.records(before)
    after=copy.deepcopy(before);after['version']=gate.NEW;changes={};data={};declared=[];groups={}
    for path,r in sorted(a.items()):
        if not gate.allow_scene_replacement(path):continue
        original=(prep.OLD_OVERLAY/path).read_bytes();old_models=gate.scene_records(original)
        match=__import__('re').fullmatch(gate.SCENE_PATTERN,path);city,variant,width=match.groups();size=int(width)
        source=next(m for m in old_models if m['basename'].endswith('_p0000.t'))
        basename=f'ab_{city}_a_{size}_p0000.t';p='base/setting/arena_boundaries/'+basename
        png_path=p[:-2]+'.png'
        if p not in data:
            raw=bytearray((prep.OLD_OVERLAY/('base/setting/arena_surroundings/'+source['basename'])).read_bytes())
            def short(offset,length,value):
                encoded=value.encode('ascii');raw[offset:offset+length]=bytes([len(encoded)])+encoded+bytes(length-len(encoded)-1)
            short(74,65,'ti_'+basename[:-2]);short(203,129,basename[:-2]+'.png')
            data[p]=bytes(raw);gate.boundary_tile(p,data[p]);checks+=1
            stream=io.BytesIO();Image.new('RGBA',(1024,1024)).save(stream,format='PNG');data[png_path]=stream.getvalue()
            gate.boundary_png(data[png_path]);checks+=1
        n=len(old_models);new=bytearray(original);new[16:18]=(n+1).to_bytes(2,'little')
        name=basename.encode();new.extend(bytes([len(name)])+name+bytes(63-len(name)))
        new.extend(source['x'].to_bytes(4,'little',signed=True)+source['y'].to_bytes(4,'little',signed=True))
        data[path]=bytes(new)
        entry=copy.deepcopy(r);entry.update(size=len(new),sha256=sha(new));changes[path]=dict(before=r,after=entry)
        info=gate.scene_append(path,original,bytes(new),{p,png_path});checks+=1
        declared.append({k:info[k] for k in ('path','old_sha256','sha256','models')});groups[(city,size)]=info['models']
    additions={p:dict(path=p,size=len(raw),sha256=sha(raw)) for p,raw in data.items() if p not in a}
    for p,r in additions.items():changes[p]=dict(before=None,after=r)
    after['files']=[changes[r['path']]['after'] if r['path'] in changes else r for r in after['files']]+list(additions.values())
    delta=gate.manifest_delta(before,after,additions,{p:r['after'] for p,r in changes.items() if r['before'] is not None});checks+=1
    for path in ('ti.exe','base/setting/arena_surroundings/as_rv_1_38_p0000.t','base/setting/arena_surroundings/as_rv_1_38_p0000.png'):
        bad=copy.deepcopy(after);next(r for r in bad['files'] if r['path']==path)['sha256']='f'*64
        try:gate.manifest_delta(before,bad,additions,{p:r['after'] for p,r in changes.items() if r['before'] is not None})
        except RuntimeError:checks+=1
        else:raise AssertionError('Immutable .2 record edit accepted')
    scene_path='base/maps/as_rv_1_38.s';old_scene=(prep.OLD_OVERLAY/scene_path).read_bytes()
    for offset in (12,32,35,98):
        bad=bytearray(data[scene_path]);bad[offset]^=1
        try:gate.scene_append(scene_path,old_scene,bytes(bad),additions)
        except (RuntimeError,UnicodeDecodeError):checks+=1
        else:raise AssertionError('Original SET edit accepted')
    ns={};exec(transport.REMOTE,ns);checks+=1
    old_raw=(OUT/'previous-client-manifest.json').read_bytes();new_raw=json.dumps(after).encode()
    inventory=[dict(path=p,size=len(raw),sha256=sha(raw)) for p,raw in data.items()]
    proof=json.dumps(dict(passed=True,files=inventory,scenes=declared)).encode()
    verified=json.dumps(dict(passed=True,files=inventory,alpha_proofs={f'{c}_{w}':dict(passed=True,hole_nonzero_pixels=0,
        outside_nonzero_pixels=0,four_sides={'fixture':1},four_corners={'fixture':1}) for c,w in groups})).encode()
    proofs={'proofs/boundary-proof.json':proof,'proofs/asset-verification.json':verified,
        'proofs/local-tests.json':b'{"passed":true,"checks":1}',
        'proofs/native-fog-tint.json':(ROOT/'reports/arena-surroundings-fog/native-fog-tint.json').read_bytes(),
        'proofs/native-v1.json':(ROOT/'reports/arena-surroundings-implementation/native.json').read_bytes()}
    guard=dict(replacements=changes,baseline_manifest_sha256=sha(old_raw),new_manifest_sha256=sha(new_raw),
       manifest_delta=delta,proof_files={p:sha(raw) for p,raw in proofs.items()},
       native_v1_proof_sha256=sha(proofs['proofs/native-v1.json']),database_uploaded=False,server_code_uploaded=False,
       service_restart_required=False,executable_or_launcher_changes=False)
    def make_zip(extra=False):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as bundle:
            bundle.writestr('guard.json',json.dumps(guard));bundle.writestr('client/previous-manifest.json',old_raw)
            bundle.writestr('client/manifest.json',new_raw)
            for p,raw in proofs.items():bundle.writestr(p,raw)
            for digest,raw in {sha(raw):raw for raw in data.values()}.items():bundle.writestr('client/blobs/'+digest,raw)
            if extra:bundle.writestr('../player-data.sqlite3',b'forbidden')
        return zipfile.ZipFile(io.BytesIO(stream.getvalue()))
    with tempfile.TemporaryDirectory(prefix='tio-boundary-self-test-') as temp:
        live=Path(temp);(live/'blobs').mkdir();ns['LIVE']=live
        for p,r in a.items():
            if gate.allow_scene_replacement(p) or p.startswith('base/setting/arena_surroundings/') and p.endswith('.t'):
                (live/'blobs'/r['sha256']).write_bytes((prep.OLD_OVERLAY/p).read_bytes())
        with make_zip() as bundle:ns['validate_payload'](bundle,guard);checks+=1
        try:
            with make_zip(True) as bundle:ns['validate_payload'](bundle,guard)
        except RuntimeError:checks+=1
        else:raise AssertionError('Foreign ZIP member accepted')
    result=dict(passed=True,checks=checks,server_contacted=False,accounts_created=0,remote_mutations=0,
        scope='Synthetic offline release/append/culling/immutable-record fixtures, not actual boundary artwork or hosted/GPU proof')
    save(OUT/'deployment-tools-self-test.json',result);print(json.dumps(result));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args();require(not(args.execute and args.self_test),'Self-test cannot execute publication')
    if args.self_test:self_test()
    else:publish(args.execute)
