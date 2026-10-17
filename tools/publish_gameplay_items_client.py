"""Publish the bounded item adapter and reviewed XML against exact live blobs."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import urllib.request
from tools.deploy_gameplay_completion import ROOT
from tools.deploy_stage4_economy import remote
from tools.publish_gameplay_equipment_client import READ,PUBLISH as EQUIPMENT_PUBLISH
from deploy.client_battle_items import patch,patch_plan,BASE_SHA

def sha(raw):return hashlib.sha256(raw).hexdigest()

def publisher():
    code=EQUIPMENT_PUBLISH.replace("if changed!=['silver.dll']:raise ValueError('Expected only equipment DLL change')",
        "if set(changed)!={'silver.dll','base/shared config/items.xml'}:raise ValueError('Expected only item DLL/XML change')")
    code=code.replace("len(plan['changes'])!=7","len(plan['changes'])!=8")
    code=code.replace("prefix='tio-before-equipment-client-'","prefix='tio-before-items-client-'")
    anchor="service=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True)"
    addition="""from xml.etree import ElementTree as ET
xml_prior=next(x for x in a['files'] if x['path']=='base/shared config/items.xml')
xml_record=next(x for x in b['files'] if x['path']=='base/shared config/items.xml')
xml_before=(live/'blobs'/xml_prior['sha256']).read_bytes();xml_raw=base64.b64decode(p['xml_candidate'],validate=True)
if sha(xml_before)!=p['xml_base_sha256'] or sha(xml_before)!=xml_prior['sha256'] or len(xml_before)!=xml_prior['size']:raise RuntimeError('Published XML base changed')
if sha(xml_raw)!=xml_record['sha256'] or len(xml_raw)!=xml_record['size'] or xml_record['seed']:raise ValueError('XML candidate differs')
def semantic(n):return n.tag,tuple(sorted(n.attrib.items())),(n.text or '').strip(),tuple(semantic(c) for c in n)
x={int(n.get('id')):semantic(n) for n in ET.fromstring(xml_before)};y={int(n.get('id')):semantic(n) for n in ET.fromstring(xml_raw)}
if sorted(i for i in x if x[i]!=y.get(i))!=[24,35] or sorted(y.keys()-x.keys())!=list(range(5001,5012)):raise ValueError('Unrelated XML semantics changed')
"""
    if code.count(anchor)!=1:raise RuntimeError('Publisher service guard changed')
    code=code.replace(anchor,addition+anchor)
    code=code.replace("(backup/'silver.dll').write_bytes(before)","(backup/'silver.dll').write_bytes(before);(backup/'items.xml').write_bytes(xml_before)")
    code=code.replace("atomic(new,live/'manifest.json')","""xml_target=live/'blobs'/xml_record['sha256']
if xml_target.exists():
 if xml_target.read_bytes()!=xml_raw:raise RuntimeError('Immutable XML blob differs')
else:atomic(xml_raw,xml_target)
atomic(new,live/'manifest.json')""")
    code=code.replace("manifest_sha256=sha(new))","manifest_sha256=sha(new),xml_sha256=sha(xml_raw),xml_semantics_preserved=True)")
    return code

def verify(folder,version):
    origin='https://185.184.42.88/updates/';manifest=(folder/'client/manifest.json').read_bytes()
    with urllib.request.urlopen(origin+'manifest.json',timeout=30) as response:actual=response.read()
    if actual!=manifest:raise ValueError('HTTPS manifest differs')
    verified={}
    for row in json.loads(manifest)['files']:
        if row['path'] not in ('silver.dll','base/shared config/items.xml'):continue
        with urllib.request.urlopen(origin+'blobs/'+row['sha256'],timeout=60) as response:blob=response.read()
        if sha(blob)!=row['sha256'] or len(blob)!=row['size']:raise ValueError('HTTPS item blob differs')
        verified[row['path']]=row['sha256']
    (folder/'client/https-verification.json').write_text(json.dumps(dict(passed=True,version=version,origin=origin,trusted_https=True,files=verified),indent=2)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--version',required=True);parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    folder=args.folder.resolve()
    if not folder.is_relative_to(ROOT/'reports/gameplay-completion'):raise ValueError('Expected gameplay folder')
    if args.verify_only:verify(folder,args.version);print('Trusted HTTPS item release verified');return
    if (folder/'client/publication.json').exists():raise ValueError('Preserve publication proof')
    for name in ('validation.json','hosted-items.json','catalog.json'):
        if not json.loads((folder/name).read_text())['passed']:raise ValueError('Item verification incomplete')
    old=base64.b64decode(remote(READ,{})['manifest'],validate=True);manifest=json.loads(old)
    if tuple(map(int,args.version.split('.')))<=tuple(map(int,manifest['version'].split('.'))):raise ValueError('Version must increase')
    source=(folder/'client/source/silver.dll').read_bytes();candidate=(folder/'client/candidate/silver.dll').read_bytes()
    if sha(source)!=BASE_SHA or patch(source)!=candidate or patch(candidate)!=candidate:raise ValueError('DLL candidate changed')
    proof=json.loads((ROOT/'evidence/battle_item_client_native.json').read_text())
    if proof['preservation']['updated_sha256']!=sha(candidate):raise ValueError('Native item proof changed')
    xml_source=(folder/'client/source/items.xml').read_bytes();xml=(folder/'client/candidate/items.xml').read_bytes()
    for name,raw,previous in (('silver.dll',candidate,sha(source)),('base/shared config/items.xml',xml,sha(xml_source))):
        row=next(r for r in manifest['files'] if r['path']==name)
        if row['sha256']!=previous:raise ValueError('Exact published base changed')
        row.update(sha256=sha(raw),size=len(raw),seed=False)
    manifest['version']=args.version;new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    (folder/'client/previous-manifest.json').write_bytes(old);(folder/'client/manifest.json').write_bytes(new)
    report=remote(publisher(),dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),
        candidate=base64.b64encode(candidate).decode(),base_sha256=BASE_SHA,plan=patch_plan(source,candidate),
        xml_candidate=base64.b64encode(xml).decode(),xml_base_sha256=sha(xml_source)))
    (folder/'client/publication.json').write_text(json.dumps(report,indent=2)+'\n');verify(folder,args.version);print(json.dumps(report))

if __name__=='__main__':main()
