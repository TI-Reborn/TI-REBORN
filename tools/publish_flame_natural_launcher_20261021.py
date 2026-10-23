"""Publish checked 0.1.27 over the fresh 0.1.26 backup, preserving hosted data."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/flame-natural-20261021';WORK=ROOT/'work/flame-natural-20261021'
def main(mode):
 proof=json.loads((OUT/'visual-validation.json').read_text());assert proof['passed'] and proof['real_native_client'] and proof['hosted_accounts']==2
 assert json.loads((OUT/'native-unit.json').read_text())['passed']
 assert json.loads((OUT/'launcher-self-test.json').read_text())['passed']
 candidate=WORK/'launcher/TIO Launcher.exe';sha=hashlib.sha256(candidate.read_bytes()).hexdigest();size=candidate.stat().st_size
 assert sha=='d568508f14115fb8a59dea1501325005338a92b3b26a81a85f1cbb6530148ecb'
 receipt=json.loads((OUT/'launcher-backup.json').read_text());old=receipt['publication_baseline']['launcher']
 assert old['sha256']=='ea849c3f5291e1387d99fe2951ef0c0e2d51e2dff34a041b2c7afcd783d85263'
 remote_exe='/root/TIO-Launcher-flame-natural-0.1.27.exe';remote_tool='/root/tio-publish-flame-natural-20261021.py'
 if mode=='inspect':
  for source,dest in ((candidate,remote_exe),(ROOT/'tools/publish_launcher_update_remote.py',remote_tool)):
   r=subprocess.run(['scp','-i',str(Path.home()/'.ssh/tio_server'),str(source),'root@185.184.42.88:'+dest],capture_output=True,timeout=180)
   assert r.returncode==0,'Scoped candidate upload failed'
 args=['python3',remote_tool,'--backup',receipt['backup'],'--candidate',remote_exe,'--version','0.1.27','--sha256',sha,'--bytes',str(size),
       '--baseline-version','0.1.26','--baseline-sha256',old['sha256'],'--baseline-bytes',str(old['bytes']),'--'+mode]
 r=subprocess.run(SSH+[' '.join(args)],capture_output=True,encoding='utf-8',timeout=120)
 if r.returncode:raise RuntimeError(r.stderr[-1800:])
 result=json.loads(r.stdout);(OUT/('launcher-'+mode+'.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('inspect','apply'));main(p.parse_args().mode)
