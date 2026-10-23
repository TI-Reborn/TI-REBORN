"""Bounded Groza XML release and hot-read server catalogue; no restart or DB writes."""
import base64,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.publish_gameplay_xml_client import publisher
from tools.deploy_stage4_economy import remote

OUT=ROOT/'reports/groza-20261019';WORK=ROOT/'work/groza-20261019'
sha=lambda raw:hashlib.sha256(raw).hexdigest()


def main():
    assert json.loads((OUT/'native-regression.json').read_text())['passed']
    assert json.loads((OUT/'hosted-two-account.json').read_text())['passed']
    source=json.loads((OUT/'client-baseline.json').read_text())
    old=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read()
    manifest=json.loads(old);assert manifest['version']==source['version']
    name='base/shared config/skills.xml';raw=(WORK/'skills-candidate.xml').read_bytes()
    prior=next(x for x in manifest['files'] if x['path']==name)
    assert prior==source['files'][name]['record']
    prior.update(sha256=sha(raw),size=len(raw),seed=False)
    manifest['version']='2026.10.19.1'
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    files={}
    for path in ('evidence/skills_diagnostic.xml',):
        before=(WORK/'baseline'/path).read_bytes()
        if path.endswith('.xml'):
            token=b'<value key="target" val="target_area" />';assert before.count(token)==1
            after=before.replace(token,b'<value key="target" val="target_grenade" />\n    <value key="itemConsumeId" val="340" />')
        else:
            text=before.decode();text=text.replace("'area':'target_area'","'area':'target_grenade'")
            token="        for key,val in mapped.items():"
            assert text.count(token)==1
            text=text.replace(token,"        # Native ground selection and Groza projectile metadata.\n        if ability_id==27:mapped['itemConsumeId']='340'\n"+token)
            after=text.encode();compile(text,path,'exec')
        files[path]=dict(before=sha(before),after=sha(after),raw=base64.b64encode(after).decode())
        target=WORK/'candidate'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(after)
    code=publisher()
    anchor="service=subprocess.check_output"
    validation="""server_files=p['server_files']
if set(server_files)!={'evidence/skills_diagnostic.xml'}:raise ValueError('Unexpected server scope')
for path,row in server_files.items():
 if sha((root/path).read_bytes())!=row['before']:raise RuntimeError('Server baseline changed')
 data=base64.b64decode(row['raw'],validate=True)
 if sha(data)!=row['after']:raise ValueError('Server candidate differs')
 if path.endswith('.py'):compile(data,path,'exec')
 else:
  x=ET.fromstring((root/path).read_bytes());y=ET.fromstring(data)
  oldrows={int(n.get('id')):semantic(n) for n in x};newrows={int(n.get('id')):semantic(n) for n in y}
  if oldrows.keys()!=newrows.keys() or [i for i in oldrows if oldrows[i]!=newrows[i]]!=[27]:raise ValueError('Unrelated server skills changed')
"""
    assert code.count(anchor)==1;code=code.replace(anchor,validation+anchor)
    anchor="target=live/'blobs'/record['sha256']"
    install="""for path,row in server_files.items():
 saved=backup/'server-files'/path;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/path,saved)
 if sha((root/path).read_bytes())!=row['before']:raise RuntimeError('Server changed during backup')
for path,row in server_files.items():atomic(base64.b64decode(row['raw']),root/path)
"""
    assert code.count(anchor)==1;code=code.replace(anchor,install+anchor)
    code=code.replace("report=dict(version=", "report=dict(server_files={n:{k:v for k,v in row.items() if k!='raw'} for n,row in server_files.items()},server_catalogue_hot_read=True,version=")
    payload=dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),
        candidate=base64.b64encode(raw).decode(),base_sha256=source['files'][name]['record']['sha256'],
        path=name,changed_ids=[27],added_ids=[],server_files=files)
    result=remote(code,payload)
    (OUT/'publication.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUT/'previous-manifest.json').write_bytes(old);(OUT/'manifest.json').write_bytes(new)
    assert urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read()==new
    assert urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+sha(raw),timeout=30).read()==raw
    (OUT/'https-verification.json').write_text(json.dumps(dict(passed=True,version=manifest['version'],trusted_https=True,sha256=sha(raw)),indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
