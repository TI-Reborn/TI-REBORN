"""Read actual hosted sources/update manifest; preserve them before editing."""
from pathlib import Path
import hashlib, json, shlex, subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/dog-encounters'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']
FILES=('tools/loopback_exchange.py','tio/arena_service.py','tio/locations.py','tio/battle_rewards.py','tio/ranks.py',
       'server/runtime.py','server/battle_reconnect.py','evidence/items_diagnostic.xml')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    code="""import pathlib,json,sys,hashlib,sqlite3,subprocess
r=pathlib.Path('/opt/tio-emulator'); names=json.load(sys.stdin)
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
integrity=d.execute('PRAGMA integrity_check').fetchone()[0],accounts=d.execute('SELECT count(*) FROM accounts').fetchone()[0],
checkpoints=d.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],
pending=d.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],
files={n:dict(sha=hashlib.sha256((r/n).read_bytes()).hexdigest(),source=(r/n).read_text()) for n in names},
client_manifest=pathlib.Path('/var/www/tio-client/updates/manifest.json').read_text())))"""
    process=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(FILES),capture_output=True,text=True,encoding='utf-8')
    if process.returncode:raise RuntimeError(process.stderr)
    data=json.loads(process.stdout)
    records=data.pop('files');manifest=data.pop('client_manifest')
    (OUT/'previous-client-manifest.json').write_text(manifest,encoding='utf-8')
    hashes={}
    for name,record in records.items():
        target=OUT/'remote-before'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(record['source'],encoding='utf-8',newline='')
        hashes[name]=record['sha']
    (OUT/'before-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    (OUT/'inspection.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    print(json.dumps(dict(**data,different_local_files=[n for n,h in hashes.items() if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h])))

if __name__=='__main__':main()
