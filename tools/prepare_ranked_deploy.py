"""Inspect live sources and prepare a guarded code-only ranked update."""
from pathlib import Path
import hashlib,json,shlex,subprocess,tarfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('tio/ranked.py','tio/control_points.py','tio/protocol/ranked.py','tio/team_scene.py',
       'tio/battle_rewards.py','tio/battle_snapshot.py','tio/locations.py',
       'server/ranked_arena.py','server/team_arena.py','server/public_profile.py',
       'server/presence.py','server/battle_reconnect.py','tools/survival_scene.py')
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@185.184.42.88']

def main():
    folder=ROOT/'reports/ranked';folder.mkdir(parents=True,exist_ok=True)
    code='''import pathlib,json,sys,hashlib,sqlite3,subprocess
root=pathlib.Path('/opt/tio-emulator');files=json.load(sys.stdin)
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],
pending=db.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],
checkpoints=db.execute('SELECT status,count(*) FROM battle_checkpoints GROUP BY status').fetchall(),
service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
files={n:dict(sha=hashlib.sha256((root/n).read_bytes()).hexdigest(),source=(root/n).read_text())
if (root/n).exists() else dict(sha=None,source=None) for n in files})))'''
    data=json.loads(subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(FILES),
                        capture_output=True,text=True,check=True,encoding='utf-8').stdout)
    assert data['integrity']=='ok' and data['service']=='active' and not data['pending'] and not data['checkpoints'],data
    manifest={}
    for name,remote in data.pop('files').items():
        if remote['source'] is not None:
            target=folder/'remote-before'/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(remote['source'],encoding='utf-8',newline='')
        manifest[name]=dict(before=remote['sha'],after=hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (folder/'inspection.json').write_text(json.dumps(data,indent=2)+'\n')
    with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
        for name in FILES:tar.add(ROOT/name,arcname=name)
        tar.add(folder/'manifest.json',arcname='manifest.json')
    # Candidate tests run against the actual remote tree plus this overlay.
    with tarfile.open(folder/'tests.tar.gz','w:gz') as tar:
        for path in (ROOT/'tests').glob('*.py'):tar.add(path,arcname='tests/'+path.name)
    print(json.dumps(dict(files=len(FILES),**data)))

if __name__=='__main__':main()
