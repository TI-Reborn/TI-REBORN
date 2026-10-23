"""Verify full trusted HTTPS downloads, live service/data and own upload cleanup."""
import hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import remote
OUT=ROOT/'reports/flame-blender-20261021';base='https://185.184.42.88/'
m=json.load(urllib.request.urlopen(base+'downloads/launcher-manifest.json',timeout=30));h=hashlib.sha256();size=0
with urllib.request.urlopen(base+'downloads/TIO-Launcher-0.1.28.exe',timeout=60) as stream:
 while block:=stream.read(1024*1024):h.update(block);size+=len(block)
assert m['version']=='0.1.28' and size==m['size']==119691426 and h.hexdigest()==m['sha256']=='eb3d2a8fd3879365190eec478734a384ba67ecc89b301011f8db01a2244248c1'
raw=urllib.request.urlopen(base+'updates/manifest.json',timeout=30).read();assert raw==(OUT/'manifest.json').read_bytes()
asset=(ROOT/'assets/flame-jet-v1/tio-flame-jet.png').read_bytes();digest=hashlib.sha256(asset).hexdigest()
assert urllib.request.urlopen(base+'updates/blobs/'+digest,timeout=30).read()==asset
r=dict(passed=True,trusted_https=True,launcher=m,client_version=json.loads(raw)['version'],atlas_sha256=digest)
(OUT/'https-verification.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
code='''import hashlib,json,os,shutil,sqlite3,subprocess
candidate='/root/TIO-Launcher-flame-blender-0.1.28.exe'
assert os.path.isfile(candidate) and not os.path.islink(candidate)
assert hashlib.sha256(open(candidate,'rb').read()).hexdigest()=='eb3d2a8fd3879365190eec478734a384ba67ecc89b301011f8db01a2244248c1'
os.unlink(candidate)
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
services={n:subprocess.check_output(['systemctl','show',n,'-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True) for n in ('tio-server','tio-portal','tio-game-api')}
r=dict(integrity=db.execute('pragma integrity_check').fetchone()[0],accounts=db.execute('select count(*) from accounts').fetchone()[0],services=services,free_bytes=shutil.disk_usage('/').free,server_code_sha256=hashlib.sha256(open('/opt/tio-emulator/tio/flamethrower.py','rb').read()).hexdigest(),website_http_status=int(subprocess.check_output(['curl','-s','-o','/dev/null','-w','%{http_code}','https://ti-reborn.com/ru'],text=True)),only_own_upload_removed=True)
assert r['integrity']=='ok' and r['accounts']==26 and r['free_bytes']>768*1024*1024 and r['website_http_status']==200
assert r['server_code_sha256']=='9119e6d0dc114c362d3ef4d15486e40e359e3a05243f0d157d366c1e5f177e11'
assert 'MainPID=338357' in services['tio-server'] and all('ActiveState=active' in s and 'NRestarts=0' in s for s in services.values())
r['passed']=True
print(json.dumps(r))'''
r=remote(code);(OUT/'hosted-final.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
probe=json.loads((OUT/'tls-native-probe.json').read_text());assert probe['passed']
print('Production loader/TLS probe passed separately from the recorded hosted graphical battle.')
