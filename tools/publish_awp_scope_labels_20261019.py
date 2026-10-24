"""Append only the missing native p09n label, preserving all other locale bytes."""
import base64,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.prepare_awp_scope_20261019 import WORK,OUT,sha
from tools.deploy_stage4_economy import remote
from tools.publish_gameplay_xml_client import publisher

LABELS={'base/russian.lng':'Снайперский прицел','base/english.lng':'Sniper scope','base/german.lng':'Zielfernrohr'}

def main():
    origin='https://185.184.42.88/updates/'
    old=urllib.request.urlopen(origin+'manifest.json',timeout=20).read();manifest=json.loads(old)
    assert manifest['version']=='2026.10.19.3'
    files={}
    for name,label in LABELS.items():
        row=next(r for r in manifest['files'] if r['path']==name)
        before=urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=20).read()
        assert sha(before)==row['sha256'] and not any(line.startswith(b'p09n=') for line in before.splitlines())
        addition=('\r\np09n='+label+'\r\n').encode('cp1251');raw=before+addition
        files[name]=dict(before=sha(before),after=sha(raw),raw=base64.b64encode(raw).decode(),addition=base64.b64encode(addition).decode())
        (WORK/(Path(name).name+'-before')).write_bytes(before)
        (WORK/(Path(name).name+'-candidate')).write_bytes(raw)
        row.update(sha256=sha(raw),size=len(raw),seed=False)
    manifest['version']='2026.10.19.4';new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    code=publisher();start=code.index('if changed!=');end=code.index('service=subprocess',start)
    validation='''files=p['files']
if set(files)!={'base/russian.lng','base/english.lng','base/german.lng'} or set(changed)!=set(files):raise ValueError('Unrelated label release')
for name,row in files.items():
 prior=next(x for x in a['files'] if x['path']==name);record=next(x for x in b['files'] if x['path']==name)
 before=(live/'blobs'/prior['sha256']).read_bytes();raw=base64.b64decode(row['raw'],validate=True);addition=base64.b64decode(row['addition'],validate=True)
 if sha(before)!=row['before'] or sha(raw)!=row['after'] or raw!=before+addition:raise RuntimeError('Locale baseline changed')
 if any(line.startswith(b'p09n=') for line in before.splitlines()) or not addition.startswith(b'\\r\\np09n=') or len(addition.splitlines())!=2:raise ValueError('Unexpected locale keys')
 if record['sha256']!=sha(raw) or record['size']!=len(raw) or record['seed']:raise ValueError('Manifest differs')
'''
    code=code[:start]+validation+code[end:]
    code=code.replace("(backup/'manifest.json').write_bytes(old);(backup/'previous.xml').write_bytes(before)","(backup/'manifest.json').write_bytes(old)\nfor name,row in files.items():\n target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((live/'blobs'/row['before']).read_bytes())")
    start=code.index("target=live/'blobs'/record['sha256']");end=code.index("if subprocess.check_output",start)
    code=code[:start]+'''for name,row in files.items():
 target=live/'blobs'/row['after'];raw=base64.b64decode(row['raw'])
 if target.exists():
  if target.read_bytes()!=raw:raise RuntimeError('Immutable blob differs')
 else:atomic(raw,target)
atomic(new,live/'manifest.json')
if (live/'manifest.json').read_bytes()!=new:raise RuntimeError('Published manifest differs')
'''+code[end:]
    code=code.replace("source_sha256=sha(before),sha256=sha(raw),size=len(raw)","files={n:{k:v for k,v in row.items() if k in ('before','after')} for n,row in files.items()}")
    result=remote(code,dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),files=files))
    (OUT/'labels-publication.json').write_text(json.dumps(result,indent=2));(OUT/'labels-manifest.json').write_bytes(new)
    assert urllib.request.urlopen(origin+'manifest.json',timeout=20).read()==new
    for name,row in files.items():assert sha(urllib.request.urlopen(origin+'blobs/'+row['after'],timeout=20).read())==row['after']
    (OUT/'labels-https-verification.json').write_text(json.dumps(dict(passed=True,trusted_https=True,version=manifest['version'],files=result['files']),indent=2))
    print(json.dumps(result))

if __name__=='__main__':main()
