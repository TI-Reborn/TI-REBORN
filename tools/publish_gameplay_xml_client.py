"""Publish a bounded XML-only catalogue release, preserving other client blobs."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET
from tools.deploy_gameplay_completion import ROOT
from tools.deploy_stage4_economy import remote
from tools.publish_gameplay_equipment_client import READ,PUBLISH

def sha(raw):return hashlib.sha256(raw).hexdigest()

def publisher():
    code=PUBLISH.replace("if changed!=['silver.dll']:raise ValueError('Expected only equipment DLL change')",
        "if changed!=[p['path']]:raise ValueError('Expected one reviewed XML change')")
    start=code.index("prior=next(x for x in a['files']")
    end=code.index("service=subprocess.check_output",start)
    replacement="""name=p['path']
if name not in ('base/shared config/skills.xml','base/shared config/zones.xml','base/shared config/services.xml'):raise ValueError('Unexpected XML path')
prior=next(x for x in a['files'] if x['path']==name);record=next(x for x in b['files'] if x['path']==name)
before=(live/'blobs'/prior['sha256']).read_bytes();raw=base64.b64decode(p['candidate'],validate=True)
if sha(before)!=p['base_sha256'] or sha(before)!=prior['sha256'] or len(before)!=prior['size']:raise RuntimeError('Published XML changed')
if sha(raw)!=record['sha256'] or len(raw)!=record['size'] or record['seed']:raise ValueError('Candidate differs')
from xml.etree import ElementTree as ET
def semantic(n):return n.tag,tuple(sorted(n.attrib.items())),(n.text or '').strip(),tuple(semantic(c) for c in n)
x=ET.fromstring(before);y=ET.fromstring(raw)
if x.tag!=y.tag or x.attrib!=y.attrib:raise ValueError('Root XML changed')
oldrows={int(n.get('id')):semantic(n) for n in x};newrows={int(n.get('id')):semantic(n) for n in y}
if len(oldrows)!=len(x) or len(newrows)!=len(y):raise ValueError('Duplicate IDs')
if oldrows.keys()-newrows.keys():raise ValueError('Existing records removed')
if sorted(i for i in oldrows if oldrows[i]!=newrows[i])!=p['changed_ids'] or sorted(newrows.keys()-oldrows.keys())!=p['added_ids']:raise ValueError('Unrelated XML semantics changed')
"""
    code=code[:start]+replacement+code[end:]
    code=code.replace("prefix='tio-before-equipment-client-'","prefix='tio-before-gameplay-xml-client-'")
    code=code.replace("(backup/'silver.dll').write_bytes(before)","(backup/'previous.xml').write_bytes(before)")
    return code

def verify(folder):
    origin='https://185.184.42.88/updates/';manifest=(folder/'client/manifest.json').read_bytes()
    with urllib.request.urlopen(origin+'manifest.json',timeout=30) as r:assert r.read()==manifest
    publication=json.loads((folder/'client/publication.json').read_text())
    entry=next(r for r in json.loads(manifest)['files'] if r['path']==publication['changed'][0])
    with urllib.request.urlopen(origin+'blobs/'+entry['sha256'],timeout=30) as r:raw=r.read()
    assert sha(raw)==entry['sha256'] and len(raw)==entry['size']
    (folder/'client/https-verification.json').write_text(json.dumps(dict(passed=True,trusted_https=True,version=publication['version'],path=entry['path'],sha256=sha(raw)),indent=2)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',type=Path,required=True);p.add_argument('--version',required=True)
    p.add_argument('--name',choices=('skills','zones','services'),required=True);p.add_argument('--added',type=int,nargs='*',default=[]);p.add_argument('--changed',type=int,nargs='*',default=[]);p.add_argument('--verify-only',action='store_true');args=p.parse_args()
    folder=args.folder.resolve();assert folder.is_relative_to(ROOT/'reports/gameplay-completion')
    if args.verify_only:verify(folder);print('Trusted HTTPS catalogue verified');return
    assert not (folder/'client/publication.json').exists()
    for name in ('validation.json','hosted-mines.json','catalog.json'):assert json.loads((folder/name).read_text())['passed']
    old=base64.b64decode(remote(READ,{})['manifest'],validate=True);manifest=json.loads(old)
    assert tuple(map(int,args.version.split('.')))>tuple(map(int,manifest['version'].split('.')))
    path='base/shared config/'+args.name+'.xml';source=(folder/'client/source'/f'{args.name}.xml').read_bytes();raw=(folder/'client/candidate'/f'{args.name}.xml').read_bytes();ET.fromstring(raw)
    row=next(r for r in manifest['files'] if r['path']==path);assert row['sha256']==sha(source) and row['size']==len(source)
    row.update(sha256=sha(raw),size=len(raw),seed=False);manifest['version']=args.version
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();(folder/'client/previous-manifest.json').write_bytes(old);(folder/'client/manifest.json').write_bytes(new)
    report=remote(publisher(),dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),candidate=base64.b64encode(raw).decode(),base_sha256=sha(source),path=path,changed_ids=sorted(args.changed),added_ids=sorted(args.added)))
    (folder/'client/publication.json').write_text(json.dumps(report,indent=2)+'\n');verify(folder);print(json.dumps(report))

if __name__=='__main__':main()
