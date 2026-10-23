"""Use the existing guarded launcher publisher against the inspected 0.1.24."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
WORK=ROOT/'work/flamethrower-implementation-20261021'
OUT=ROOT/'reports/flamethrower-implementation-20261021'
def main(mode):
 candidate=WORK/'launcher/TIO Launcher.exe';sha=hashlib.sha256(candidate.read_bytes()).hexdigest();size=candidate.stat().st_size
 old=json.loads((WORK/'launcher_manifest-before.json').read_text())
 backup=json.loads((OUT/'launcher-backup.json').read_text())['backup']
 if mode=='inspect':
  for source,dest in ((candidate,'/root/TIO-Launcher-flame-0.1.25.exe'),
                      (ROOT/'tools/publish_launcher_update_remote.py','/root/tio-publish-flame-20261021.py')):
   r=subprocess.run(['scp','-i',str(Path.home()/'.ssh/tio_server'),str(source),'root@185.184.42.88:'+dest],capture_output=True,timeout=180)
   if r.returncode:raise RuntimeError('Scoped candidate upload failed')
 args=['python3','/root/tio-publish-flame-20261021.py','--backup',backup,'--candidate','/root/TIO-Launcher-flame-0.1.25.exe',
       '--version','0.1.25','--sha256',sha,'--bytes',str(size),'--baseline-version',old['version'],
       '--baseline-sha256',old['sha256'],'--baseline-bytes',str(old['size']),'--'+mode]
 r=subprocess.run(SSH+[' '.join(args)],capture_output=True,encoding='utf-8',timeout=90)
 if r.returncode:raise RuntimeError(r.stderr[-2200:])
 value=json.loads(r.stdout);(OUT/('launcher-'+mode+'.json')).write_text(json.dumps(value,indent=2));print(json.dumps(value))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('inspect','apply'));main(p.parse_args().mode)
