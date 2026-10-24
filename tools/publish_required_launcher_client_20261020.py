"""One-file native entry/icon publication with fresh hosted code/config/save backup."""
import base64,json,hashlib,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.publish_gameplay_equipment_client import PUBLISH
from tools.deploy_stage4_economy import remote
WORK=ROOT/'work/launcher-required-20261020';OUT=ROOT/'reports/launcher-required-20261020'

def main():
    old=(WORK/'manifest-before.json').read_bytes();manifest=json.loads(old)
    raw=(WORK/'ti.exe').read_bytes();plan=json.loads((OUT/'native-gate-plan.json').read_text())
    assert json.loads((OUT/'native-gate-verification.json').read_text())['passed']
    assert json.loads((OUT/'native-loader.json').read_text())['passed']
    assert hashlib.sha256(raw).hexdigest()==plan['after_sha256']
    row=next(r for r in manifest['files'] if r['path']=='ti.exe');assert row['sha256']==plan['before_sha256']
    row.update(sha256=plan['after_sha256'],size=len(raw));manifest['version']='2026.10.20.3'
    new=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    source=PUBLISH.replace('silver.dll','ti.exe').replace('tio-before-equipment-client-','tio-before-required-launcher-client-')
    start=source.index("plan=p['plan']");end=source.index('service=subprocess.check_output',start)
    verify=r'''
import struct
plan=p['plan']
assert sha(before)==plan['before_sha256'] and sha(raw)==plan['after_sha256']
assert sha(before)=='e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
def sections(b):
 pe=struct.unpack_from('<I',b,60)[0];n=struct.unpack_from('<H',b,pe+6)[0];opt=pe+24
 start=opt+struct.unpack_from('<H',b,pe+20)[0];result=[]
 for i in range(n):
  at=start+40*i;size,offset=struct.unpack_from('<II',b,at+16)
  result.append((b[at:at+8],b[offset:offset+size]))
 return opt,result
aopt,aa=sections(before);bopt,bb=sections(raw)
assert len(aa)==len(bb) and aa[:-1]==bb[:-1] and aa[-1][0].rstrip(bytes([0]))==bb[-1][0].rstrip(bytes([0]))==b'.rsrc'
assert struct.unpack_from('<I',raw,bopt+16)[0]==plan['guard_rva']
assert raw[-1024:]==bytes.fromhex(plan['payload'])
'''
    source=source[:start]+verify+source[end:]
    result=remote(source,dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),candidate=base64.b64encode(raw).decode(),base_sha256=plan['before_sha256'],plan=plan))
    (WORK/'manifest.json').write_bytes(new);(OUT/'client-publication.json').write_text(json.dumps(result,indent=2))
    origin='https://185.184.42.88/updates/'
    assert urllib.request.urlopen(origin+'manifest.json').read()==new
    assert urllib.request.urlopen(origin+'blobs/'+plan['after_sha256']).read()==raw
    print(json.dumps(result))

if __name__=='__main__':main()
