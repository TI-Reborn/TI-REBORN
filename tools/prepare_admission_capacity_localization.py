"""Inspect actual remote sources and prepare a code-only guarded update."""
from pathlib import Path
import hashlib,json,shlex,subprocess,tarfile

ROOT=Path(__file__).resolve().parents[1]
FILES=('tio/battle_exchange.py',)
HOST='root@185.184.42.88'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',HOST]

def main():
    folder=ROOT/'reports/stage2-admission-capacity/localization';folder.mkdir(parents=True,exist_ok=True)
    code='''import pathlib,json,sys,hashlib,sqlite3
root=pathlib.Path('/opt/tio-emulator');files=json.load(sys.stdin)
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
accounts=db.execute('SELECT count(*) FROM accounts').fetchone()[0],
files={n:dict(sha=hashlib.sha256((root/n).read_bytes()).hexdigest(),source=(root/n).read_text())
if (root/n).exists() else dict(sha=None,source=None) for n in files})))'''
    data=json.loads(subprocess.run(SSH+['python3 -c '+shlex.quote(code)],input=json.dumps(FILES),
                                 capture_output=True,text=True,check=True,encoding='utf-8').stdout)
    assert data['integrity']=='ok'
    manifest={}
    for name,remote in data['files'].items():
        if remote['source'] is not None:
            target=folder/'remote-before'/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(remote['source'],encoding='utf-8',newline='')
        manifest[name]=dict(before=remote['sha'],after=hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (folder/'inspection.json').write_text(json.dumps(dict(integrity=data['integrity'],accounts=data['accounts']),indent=2)+'\n')
    with tarfile.open(folder/'patch.tar.gz','w:gz') as archive:
        for name in FILES:archive.add(ROOT/name,arcname=name)
        archive.add(folder/'manifest.json',arcname='manifest.json')
    print(json.dumps(dict(files=len(FILES),integrity=data['integrity'],accounts=data['accounts'])))

if __name__=='__main__':main()
