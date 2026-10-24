"""Publish only the approved 18 cells of the native skill atlas."""
import argparse,base64,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.publish_gameplay_equipment_client import PUBLISH
from tools.deploy_stage4_economy import remote
OUT=ROOT/'reports/ability-icons-20261020';ASSETS=ROOT/'assets/ability-icons-v1'
NAME='base/pda/skills.png';VERSION='2026.10.20.4'
STATE=r'''
import json,subprocess,sqlite3,hashlib
from pathlib import Path
r=dict(service=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','ActiveState','-p','NRestarts'],text=True),
 config_sha256=hashlib.sha256(Path('/etc/tio-server/server.toml').read_bytes()).hexdigest())
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 r.update(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],clans=db.execute('SELECT count(*) FROM clans').fetchone()[0])
 r['protected']={t:hashlib.sha256(repr(sorted(map(repr,db.execute('SELECT * FROM '+t).fetchall()))).encode()).hexdigest() for t in ('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')}
print(json.dumps(r))
'''

def sha(raw):return hashlib.sha256(raw).hexdigest()

def validate():
    from PIL import Image
    old=(OUT/'manifest-before.json').read_bytes();m=json.loads(old)
    row=next(r for r in m['files'] if r['path']==NAME)
    source=(OUT/'skills.png').read_bytes();candidate=(ASSETS/'skills-v1.png').read_bytes()
    assert sha(source)==row['sha256'] and sha(source)==sha((ASSETS/'source-skills.png').read_bytes())
    assert candidate[:8]==b'\x89PNG\r\n\x1a\n'
    before=Image.open(OUT/'skills.png').convert('RGBA');after=Image.open(ASSETS/'skills-v1.png').convert('RGBA')
    assert before.size==after.size==(256,256)
    items=json.loads((ASSETS/'catalog.json').read_text(encoding='utf-8'))['items'];ids={r['id'] for r in items}
    assert len(ids)==18
    for index in range(64):
        x,y=index%8*32,index//8*32;rect=(x,y,x+32,y+32)
        if index not in ids:assert before.crop(rect).tobytes()==after.crop(rect).tobytes(),index
        else:
            record=next(r for r in items if r['id']==index)
            exported=Image.open(ASSETS/'exports/32'/f"{index:02}-{record['slug']}.png").convert('RGBA')
            assert after.crop(rect).tobytes()==exported.tobytes(),index
    assert tuple(map(int,VERSION.split('.')))>tuple(map(int,m['version'].split('.')))
    m['version']=VERSION;row.update(size=len(candidate),sha256=sha(candidate),seed=False)
    new=(json.dumps(m,ensure_ascii=False,indent=2)+'\n').encode()
    (OUT/'manifest.json').write_bytes(new)
    report=dict(passed=True,source_sha256=sha(source),sha256=sha(candidate),dimensions=[256,256],replaced_ids=sorted(ids),other_cells_preserved=46,
                manifest_before_sha256=sha(old),manifest_after_sha256=sha(new),changed_paths=[NAME],version=VERSION)
    (OUT/'validation.json').write_text(json.dumps(report,indent=2));return old,new,candidate,report

def main(mode):
    OUT.mkdir(exist_ok=True,parents=True)
    if mode=='inspect':
        value=remote(STATE,{})
        (OUT/'hosted-before.json').write_text(json.dumps(value,indent=2));print(json.dumps({k:v for k,v in value.items() if k!='protected'}));return
    old,new,raw,proof=validate()
    if mode=='validate':print(json.dumps(proof));return
    if mode=='publish':
        assert not (OUT/'publication.json').exists()
        source=PUBLISH.replace('silver.dll',NAME).replace("(backup/'base/pda/skills.png').write_bytes(before)","(backup/'previous-skills.png').write_bytes(before)")
        source=source.replace('tio-before-equipment-client-','tio-before-ability-icons-')
        start=source.index("plan=p['plan']");end=source.index('service=subprocess.check_output',start)
        checks=r'''
plan=p['plan']
if sha(before)!=plan['source_sha256'] or sha(raw)!=plan['sha256'] or plan['replaced_ids']!=[1,2,4,6,10,12,14,15,16,17,18,19,20,21,22,23,24,26] or plan['other_cells_preserved']!=46:raise ValueError('Unreviewed skill atlas')
import struct
if raw[:8]!=bytes([137,80,78,71,13,10,26,10]) or struct.unpack('!II',raw[16:24])!=(256,256):raise ValueError('Unexpected atlas dimensions')
'''
        source=source[:start]+checks+source[end:]
        (OUT/'publisher-source.py').write_text(source,encoding='utf-8')
        result=remote(source,dict(before_manifest=base64.b64encode(old).decode(),after_manifest=base64.b64encode(new).decode(),candidate=base64.b64encode(raw).decode(),base_sha256=proof['source_sha256'],plan=proof))
        (OUT/'publication.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    elif mode=='verify':
        origin='https://185.184.42.88/updates/'
        assert urllib.request.urlopen(origin+'manifest.json',timeout=20).read()==new
        assert urllib.request.urlopen(origin+'blobs/'+sha(raw),timeout=20).read()==raw
        before=json.loads((OUT/'hosted-before.json').read_text());after=remote(STATE,{})
        assert after['integrity']=='ok' and after['service']==before['service'] and after['config_sha256']==before['config_sha256']
        assert after['protected']==before['protected'],'Player activity changed protected tables; inspect instead of overwriting'
        after.update(passed=True,trusted_https=True,version=VERSION,atlas_sha256=sha(raw))
        (OUT/'hosted-after.json').write_text(json.dumps(after,indent=2));print(json.dumps({k:v for k,v in after.items() if k!='protected'}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('inspect','validate','publish','verify'));main(p.parse_args().mode)
