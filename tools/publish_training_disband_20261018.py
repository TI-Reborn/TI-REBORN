"""Reuse manifest-last publisher for one reviewed Training Base DLL correction."""
import argparse,base64,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
from tools.publish_training_base_client_20261018 import REMOTE
OUT=ROOT/'reports/training-disband-20261018'
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','publish'));args=p.parse_args()
 baseline=json.loads((OUT/'baseline.json').read_text());proof=json.loads((OUT/'native-review.json').read_text())
 assert json.loads((OUT/'native-execution.json').read_text())['passed']
 request=dict(action=args.action)
 if args.action=='prepare':request.update(assets={'silver.dll':base64.b64encode((OUT/'silver.dll').read_bytes()).decode()},proof=proof)
 else:
  gui=json.loads((OUT/'gui-verification.json').read_text());assert gui['disband_confirmed'] and gui['recreate_confirmed']
  request.update(prepared=json.loads((OUT/'client-prepared.json').read_text()),client_sha256=proof['after_sha256'])
 remote=REMOTE
 replacements={"sha(raw)=='d85d854996b3f031d3c75e1a4619e294c7f4be8418492c5db2599fdce8eb5509'":"sha(raw)=="+repr(baseline['manifest_sha256']),"old['version']=='2026.10.17.2'":"old['version']=='2026.10.18.1'","updated['version']='2026.10.18.1'":"updated['version']='2026.10.18.2'","allowed={'silver.dll','base/russian.lng','base/english.lng'}":"allowed={'silver.dll'}",'tio-training-client-':'tio-training-disband-','tio-before-training-client-':'tio-before-training-disband-'}
 for old,new in replacements.items():assert old in remote;remote=remote.replace(old,new)
 source='request='+repr(request)+"\nbuilder={'__name__':'disband_archive_builder'}\nexec(compile("+repr((ROOT/'launcher/build_archive.py').read_text())+",'archive-builder','exec'),builder)\n"+remote
 result=subprocess.run(SSH+['python3 -'],input=source,capture_output=True,encoding='utf-8',timeout=900)
 if result.returncode:raise RuntimeError(result.stderr[-2000:])
 value=json.loads(result.stdout);(OUT/('client-prepared.json' if args.action=='prepare' else 'client-publication.json')).write_text(json.dumps(value,indent=2));print(json.dumps(value))
if __name__=='__main__':main()
