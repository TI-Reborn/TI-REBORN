"""Complete the material-only texture replacement, preserving the active release.

The additional 397 original textures include variant, seasonal and reserve
resources not reached by the static scene/catalog traversal. The already
verified 328 images are preserved byte-for-byte.
"""
import argparse,base64,collections,hashlib,json,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path
from PIL import Image,ImageChops,ImageStat
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import publish_wasteland_materials_20261022 as first
from tools.deploy_stage4_economy import remote
from tools.build_visual_asset_catalog import decode
TASK=ROOT/'reports/remaining-textures-20261021';OUT=TASK/'phase2-complete';OUT.mkdir(exist_ok=True)
ASSET=ROOT/'assets/wasteland-materials-v1';ORIGINAL=ROOT/'work/remaining-textures-20261021/original'
PACKAGE=OUT/'additional-original-materials.zip';REMOTE_PACKAGE='/root/tio-complete-materials-20261022.zip';VERSION='2026.10.22.2'
sha=lambda b:hashlib.sha256(b).hexdigest()

REMOTE=first.REMOTE
edits={
 "'/root/tio-wasteland-materials-20261022.zip'":repr(REMOTE_PACKAGE),
 "b['version']=='2026.10.22.1' and a['version']=='2026.10.21.8'":"b['version']=='2026.10.22.2' and a['version']=='2026.10.22.1'",
 "len(expected)==328":"len(expected)==397",
 "for g in ('items','models','setting')}=={'items':8,'models':6,'setting':314}":"for g in ('items','models','setting','gfx')}=={'items':209,'models':65,'setting':118,'gfx':5}",
 "len(z.namelist())==328":"len(z.namelist())==397",
 "files=328":"files=397",
 "tio-before-wasteland-materials-":"tio-before-complete-materials-",
}
for old,new in edits.items():
    assert old in REMOTE,old
    REMOTE=REMOTE.replace(old,new)
compile(REMOTE,'<complete guarded material publisher>','exec')

def prepare():
    old=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read()
    assert old==(TASK/'phase1-active/manifest.json').read_bytes()
    (OUT/'manifest-before.json').write_bytes(old);m=json.loads(old);rows={r['path']:r for r in m['files']}
    proof=json.loads((TASK/'texture-proof.json').read_text(encoding='utf-8'));assert len(proof)==725 and len({t['path'] for t in proof})==725
    earlier={t['path']:t for t in json.loads((TASK/'phase1-active/texture-proof.json').read_text(encoding='utf-8'))}
    evidence=[];changed=[]
    for t in proof:
        n=t['path'];raw=(ASSET/'native'/n).read_bytes();source=(ORIGINAL/n).read_bytes()
        assert sha(source)==t['source_sha256'] and sha(raw)==t['sha256'] and len(raw)==t['size'] and raw!=source
        a,_=decode(source);b,codec=decode(raw);assert list(b.size)==t['native_size']
        if t.get('entirely_new_blender_geometry'):
            assert n in earlier and b.size==a.size and b.getchannel('A').getextrema()==(0,255)
        elif t['native_resolution_increased']:
            assert n.startswith('base/models/') and 1<b.width/a.width<=4 and b.width/a.width==b.height/a.height and max(b.size)<=1024
            assert a.getchannel('A').getextrema()==b.getchannel('A').getextrema()==(255,255)
        else:assert b.size==a.size and b.getchannel('A').tobytes()==a.getchannel('A').tobytes()
        if n in earlier:
            assert sha(raw)==earlier[n]['sha256']==rows[n]['sha256'],'Preserve already accepted active texture: '+n
        else:
            assert sha(source)==rows[n]['sha256'] and not rows[n]['seed']
            changed.append(n)
        rows[n].update(sha256=sha(raw),size=len(raw),seed=False)
        delta=ImageStat.Stat(ImageChops.difference(a.convert('RGB').resize(b.size,Image.Resampling.NEAREST),b.convert('RGB'))).mean
        evidence.append(dict(path=n,codec=codec,source=list(a.size),output=list(b.size),mean_rgb_change=delta,already_accepted=n in earlier))
    assert len(changed)==397
    m.update(version=VERSION,news='Обновлены 725 материальных текстур клиента: окружение, грунт, модели и предметы. Новые устройства построены в Blender. Обновите игру через лаунчер.')
    new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
    (OUT/'texture-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'changed-paths.json').write_text(json.dumps(changed,indent=2))
    with zipfile.ZipFile(PACKAGE,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for n in changed:z.write(ASSET/'native'/n,n)
    report=dict(passed=True,version=VERSION,total_material_textures=725,additional_resources=397,preserved_accepted_resources=328,
        total_groups=dict(collections.Counter(t['path'].split('/')[1] for t in proof)),changed_groups=dict(collections.Counter(n.split('/')[1] for n in changed)),
        native_model_maps=sum(t['native_resolution_increased'] for t in proof),new_blender_icons=8,new_soil_textures=7,
        package_sha256=sha(PACKAGE.read_bytes()),package_size=PACKAGE.stat().st_size,manifest_sha256=sha(new),evidence=evidence)
    (OUT/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k!='evidence'}))
    visual=json.loads((TASK/'phase1-active/gui-visual-candidate.json').read_text());visual.update(active_resources_preserved_byte_identical=True,new_resources_statically_unreferenced_or_variants=True,additional_textures_checked_by_native_codec_contracts=True,complete_graphical_coverage_of_additional_resources=False)
    (OUT/'gui-visual-candidate.json').write_text(json.dumps(visual,indent=2))

def payload(mode):
    r=json.loads((OUT/'validation.json').read_text(encoding='utf-8'));assert sha(PACKAGE.read_bytes())==r['package_sha256']
    names=set(json.loads((OUT/'changed-paths.json').read_text()));proof=[t for t in json.loads((OUT/'texture-proof.json').read_text(encoding='utf-8')) if t['path'] in names]
    p=dict(mode=mode,before_manifest=base64.b64encode((OUT/'manifest-before.json').read_bytes()).decode(),after_manifest=base64.b64encode((OUT/'manifest.json').read_bytes()).decode(),package_sha256=r['package_sha256'],proof=proof)
    if mode=='publish':p['visual']=json.loads((OUT/'gui-visual-candidate.json').read_text())
    return p

def upload():
    p=subprocess.run(['scp','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=15',str(PACKAGE),'root@185.184.42.88:'+REMOTE_PACKAGE],capture_output=True,text=True,timeout=120)
    if p.returncode:raise RuntimeError('Private texture upload failed: '+p.stderr)
    remote("from pathlib import Path;import json;p=Path('/root/tio-complete-materials-20261022.zip');p.chmod(0o600);print(json.dumps(dict(private=True,size=p.stat().st_size)))",{})
    print(json.dumps(dict(uploaded_private_art_package=True,bytes=PACKAGE.stat().st_size)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','upload','validate','publish','verify'));mode=p.parse_args().mode
    if mode=='prepare':prepare()
    elif mode=='upload':upload()
    elif mode=='verify':
        first.OUT=OUT;first.VERSION=VERSION;first.verify()
    else:
        if mode=='publish':assert not (OUT/'publication.json').exists()
        r=remote(REMOTE,payload(mode));(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(r,indent=2));print(json.dumps({k:v for k,v in r.items() if not k.startswith('protected')}))
