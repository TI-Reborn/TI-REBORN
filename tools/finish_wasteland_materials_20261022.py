"""Include the illustrated face-mask atlas and wooden training target material."""
import argparse,base64,hashlib,json,subprocess,sys,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import publish_wasteland_materials_20261022 as first
from tools.deploy_stage4_economy import remote
from tools.build_visual_asset_catalog import decode
TASK=ROOT/'reports/remaining-textures-20261021';OUT=TASK/'phase3-final';OUT.mkdir(exist_ok=True)
ASSET=ROOT/'assets/wasteland-materials-v1';VERSION='2026.10.22.3'
NAMES={'base/models/armor_masks.jpg','base/models/target_diffuse.jpg'}
PACKAGE=OUT/'target-and-face-masks.zip';REMOTE_PACKAGE='/root/tio-target-face-materials-20261022.zip'
sha=lambda b:hashlib.sha256(b).hexdigest()
REMOTE=first.REMOTE
for old,new in {
 "'/root/tio-wasteland-materials-20261022.zip'":repr(REMOTE_PACKAGE),
 "b['version']=='2026.10.22.1' and a['version']=='2026.10.21.8'":"b['version']=='2026.10.22.3' and a['version']=='2026.10.22.2'",
 "len(expected)==328":"len(expected)==2",
 "for g in ('items','models','setting')}=={'items':8,'models':6,'setting':314}":"for g in ('items','models','setting')}=={'items':0,'models':2,'setting':0}",
 "len(z.namelist())==328":"len(z.namelist())==2",
 "files=328":"files=2",
 "tio-before-wasteland-materials-":"tio-before-target-face-materials-",
}.items():
    assert old in REMOTE;REMOTE=REMOTE.replace(old,new)
compile(REMOTE,'<guarded final two materials>','exec')

def prepare():
    old=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read();assert old==(TASK/'phase2-complete/manifest.json').read_bytes()
    (OUT/'manifest-before.json').write_bytes(old);m=json.loads(old);rows={r['path']:r for r in m['files']}
    proof=json.loads((TASK/'texture-proof.json').read_text(encoding='utf-8'));assert len(proof)==727 and len({r['path'] for r in proof})==727
    previous=json.loads((TASK/'phase2-complete/texture-proof.json').read_text(encoding='utf-8'));assert len(previous)==725
    preserved={t['path']:t for t in previous};changed=[]
    for t in proof:
        name=t['path'];raw=(ASSET/'native'/name).read_bytes();assert sha(raw)==t['sha256']
        if name not in NAMES:
            assert sha(raw)==rows[name]['sha256']==preserved[name]['sha256'];continue
        before=(ROOT/'work/remaining-textures-20261021/original'/name).read_bytes();assert sha(before)==rows[name]['sha256']==t['source_sha256']
        a,_=decode(before);b,_=decode(raw);assert raw[:2]==b'\xff\xd8' and raw[-2:]==b'\xff\xd9'
        assert 1<b.width/a.width<=4 and b.width/a.width==b.height/a.height and max(b.size)<=1024
        assert a.getchannel('A').getextrema()==b.getchannel('A').getextrema()==(255,255)
        rows[name].update(sha256=sha(raw),size=len(raw),seed=False);changed.append(t)
    assert {t['path'] for t in changed}==NAMES
    m.update(version=VERSION,news='Обновлены 727 материальных текстур клиента: окружение, грунт, модели и предметы. Материалы и новые устройства подготовлены в Blender. Обновите игру через лаунчер.')
    new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'manifest.json').write_bytes(new)
    (OUT/'texture-proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    with zipfile.ZipFile(PACKAGE,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for t in changed:z.write(ASSET/'native'/t['path'],t['path'])
    r=dict(passed=True,version=VERSION,total_material_textures=727,additional_resources=2,preserved_accepted_resources=725,corrected_classification='armor_masks.jpg is illustrated face-cover diffuse artwork, not a camouflage control mask',target_geometry_and_scoring_unchanged=True,printed_target_registration_preserved=True,package_sha256=sha(PACKAGE.read_bytes()),manifest_sha256=sha(new))
    (OUT/'validation.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))

def payload(mode):
    r=json.loads((OUT/'validation.json').read_text());assert sha(PACKAGE.read_bytes())==r['package_sha256']
    p=dict(mode=mode,before_manifest=base64.b64encode((OUT/'manifest-before.json').read_bytes()).decode(),after_manifest=base64.b64encode((OUT/'manifest.json').read_bytes()).decode(),package_sha256=r['package_sha256'],proof=[t for t in json.loads((OUT/'texture-proof.json').read_text(encoding='utf-8')) if t['path'] in NAMES])
    if mode=='publish':p['visual']=json.loads((TASK/'phase1-active/gui-visual-candidate.json').read_text())
    return p

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','upload','validate','publish','verify'));mode=p.parse_args().mode
    if mode=='prepare':prepare()
    elif mode=='upload':
        r=subprocess.run(['scp','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',str(PACKAGE),'root@185.184.42.88:'+REMOTE_PACKAGE],capture_output=True,text=True,timeout=90)
        if r.returncode:raise RuntimeError('Final material upload failed: '+r.stderr)
        remote("from pathlib import Path;import json;p=Path('/root/tio-target-face-materials-20261022.zip');p.chmod(0o600);print(json.dumps(dict(private=True,size=p.stat().st_size)))",{});print(json.dumps(dict(uploaded=True,bytes=PACKAGE.stat().st_size)))
    elif mode=='verify':first.OUT=OUT;first.VERSION=VERSION;first.verify()
    else:
        if mode=='publish':assert not (OUT/'publication.json').exists()
        r=remote(REMOTE,payload(mode));(OUT/('publication.json' if mode=='publish' else 'remote-validation.json')).write_text(json.dumps(r,indent=2));print(json.dumps({k:v for k,v in r.items() if not k.startswith('protected')}))
