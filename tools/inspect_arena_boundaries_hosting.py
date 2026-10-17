"""Capture only read-only hosted .2 inputs for a future boundary .3 release."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/arena-boundaries-implementation'
KEY=Path.home()/'.ssh/tio_server'
SSH=['ssh','-i',str(KEY),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
SOURCES=('tio/arena_map.py','tio/map_generation.py','tio/arena_surroundings.py',
    'config/battle_map_profiles.json','config/arena_surroundings.json','config/arena_fragments.json',
    'config/reservation_visuals.json','tio/protocol/battle_ground.py')

INSPECTION=r'''
import base64,hashlib,json,re,sqlite3,struct,subprocess
from pathlib import Path
from contextlib import closing
from collections import Counter
def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def command(*args):return subprocess.check_output(args,text=True,timeout=20).strip()
root=Path('/opt/tio-emulator');web=Path('/var/www/tio-client');live=web/'updates'
manifest_raw=(live/'manifest.json').read_bytes();manifest=json.loads(manifest_raw)
records={r['path']:r for r in manifest['files']}
if manifest['version']!='2026.10.07.2' or not len(records)==len(manifest['files'])==6218:
 raise RuntimeError('Expected the current .2 release; rebase explicitly')
fragment=command('systemctl','show','tio-server','--property=FragmentPath','--value')
connections=command('ss','-Htn','state','established','( sport = :28512 or sport = :28513 )').splitlines()
listeners=command('ss','-Hltn','( sport = :28512 or sport = :28513 )').splitlines()
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 db.execute('BEGIN');names=sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))
 counts={};fingerprints={}
 for name in names:
  rows=sorted(repr(row) for row in db.execute('SELECT * FROM "'+name.replace('"','""')+'"'))
  counts[name]=len(rows);fingerprints[name]=hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest()
 schema=list(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'))
 database=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],accounts=counts['accounts'],
  checkpoints=counts['battle_checkpoints'],pending=counts['battle_settlement_jobs'],table_counts=counts,
  table_sha256=fingerprints,schema_sha256=hashlib.sha256(json.dumps(schema).encode()).hexdigest(),
  read_consistent_transaction=True)
selected={p:r for p,r in records.items() if re.fullmatch(
 r'base/(maps/as_(rv|de|ny|mz)_[1-3]_(38|57)\.s|setting/arena_surroundings/as_(rv|de|ny|mz)_[1-3]_(38|57)_p[0-9]{4}\.(t|png))',p)}
if len(selected)!=1128:raise RuntimeError('The current .2 surroundings set differs')
tiles=[];scenes=[];blobs=True;colors=Counter();scene_data={}
for path,r in sorted(selected.items()):
 blob=live/'blobs'/r['sha256'];blobs=blobs and blob.is_file() and blob.stat().st_size==r['size']
 if path.endswith(('.t','.s')):
  raw=blob.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=r['sha256']:raise RuntimeError('Published TILE/SET hash differs')
  if path.endswith('.t'):
   if len(raw)!=544 or raw[:8]!=b'TI TILE\0':raise RuntimeError('Unexpected TILE envelope')
   color,alpha=struct.unpack_from('<II',raw,52);colors[f'{color:08x}/{alpha}']+=1
   tiles.append(dict(**r,native_size=len(raw),color_hex=f'{color:08x}',alpha=alpha))
  else:
   scenes.append(r);scene_data[path]=base64.b64encode(raw).decode()
downloads=[]
for path in sorted(web.rglob('*')):
 if not path.is_file() or 'blobs' in path.relative_to(web).parts:continue
 relative=path.relative_to(web)
 if len(relative.parts)<=3 and (relative.parts[0]=='downloads' or path.suffix in ('.json','.txt')):
  downloads.append(dict(path=str(path),relative=relative.as_posix(),size=path.stat().st_size,sha256=digest(path)))
result=dict(host='185.184.42.88',read_only=True,service=command('systemctl','is-active','tio-server'),
 pid=command('systemctl','show','tio-server','--property=MainPID','--value'),established_connections=len(connections),
 gameplay_listeners=len(listeners),database=database,configuration_sha256=digest('/etc/tio-server/server.toml'),
 fragment_path=fragment,fragment_sha256=digest(fragment),
 sources={name:dict(path=str(root/name),size=(root/name).stat().st_size,sha256=digest(root/name)) for name in SOURCE_FILES},
 client_version=manifest['version'],manifest_sha256=hashlib.sha256(manifest_raw).hexdigest(),manifest_record_count=len(records),
 surroundings_record_count=len(selected),surroundings_extensions=dict(Counter(Path(p).suffix for p in selected)),
 tile_records=tiles,scene_records=scenes,surroundings_tiles_color_alpha_counter=dict(colors),
 all_surroundings_blob_files_present_and_size_matched=blobs,all_surroundings_tile_and_scene_blobs_sha_matched=True,
 launcher_baseline=dict(files=downloads),manifest_base64=base64.b64encode(manifest_raw).decode(),scene_data=scene_data)
print(json.dumps(result))
'''


def sha(raw):return hashlib.sha256(raw).hexdigest()


def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def inspect():
    script='SOURCE_FILES='+repr(SOURCES)+'\n'+INSPECTION
    process=subprocess.run(SSH+['python3 -'],input=script,text=True,encoding='utf-8',capture_output=True,timeout=120)
    if process.returncode:raise RuntimeError('Read-only SSH baseline failed: '+process.stderr.strip())
    data=json.loads(process.stdout);manifest_raw=base64.b64decode(data.pop('manifest_base64'))
    if sha(manifest_raw)!=data['manifest_sha256']:raise RuntimeError('Returned manifest SHA differs')
    current=json.loads(manifest_raw);completed=(ROOT/'reports/arena-surroundings-fog/client-release/manifest.json').read_bytes()
    old=json.loads((ROOT/'reports/arena-surroundings-fog/previous-client-manifest.json').read_bytes())
    oldrecords={r['path']:r for r in old['files']};currentrecords={r['path']:r for r in current['files']}
    data['completed_release_2_manifest_exact']=completed==manifest_raw
    data['legacy_5090_records_preserved']=all(currentrecords[p]==r for p,r in oldrecords.items()
        if not p.startswith(('base/maps/as_','base/setting/arena_surroundings/as_')))
    data['inspected_at_utc']=datetime.now(timezone.utc).isoformat();data['schema']='arena-boundaries-hosting/v1'
    data['next_release_candidate']='2026.10.07.3';data['database_backup_created_now']=False
    data['scope']='Read-only code/config/unit hashes, consistent database row hashes and published manifest/TILE/SET inspection; no account, match, upload or server writes.'
    launcher=data.pop('launcher_baseline');scenes=data.pop('scene_data')
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'previous-client-manifest.json').write_bytes(manifest_raw)
    save(OUT/'launcher-baseline.json',launcher)
    for path,encoded in scenes.items():
        raw=base64.b64decode(encoded)
        if sha(raw)!=currentrecords[path]['sha256']:raise RuntimeError('Returned scene SHA differs')
        target=OUT/'remote-scenes'/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    data['passed']=all((data['service']=='active',data['established_connections']==0,data['gameplay_listeners']==2,
        data['database']['integrity']=='ok',data['database']['accounts']==177,
        data['database']['checkpoints']==data['database']['pending']==0,data['completed_release_2_manifest_exact'],
        data['legacy_5090_records_preserved'],data['surroundings_tiles_color_alpha_counter']=={'00b1b1b1/255':552},
        data['all_surroundings_blob_files_present_and_size_matched']))
    save(OUT/'remote-before.json',data)
    print(json.dumps(dict(passed=data['passed'],read_only=True,client_version=data['client_version'],
        accounts=data['database']['accounts'],established_connections=data['established_connections'],
        checkpoints=data['database']['checkpoints'],tinted_tiles=len(data['tile_records']),scene_count=len(data['scene_records']),
        manifest_sha256=data['manifest_sha256'])))
    if not data['passed']:raise RuntimeError('Recorded baseline is not clean; resolve drift before preparing .3')
    return data


if __name__=='__main__':inspect()
