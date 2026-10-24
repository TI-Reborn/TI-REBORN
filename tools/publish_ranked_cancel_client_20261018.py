"""Manifest-last publication of the native TrueSkill cancel fix."""
import argparse,base64,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
from tools.publish_training_base_client_20261018 import REMOTE as SOURCE
OUT=ROOT/'reports/ranked-cancel-20261018'

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','publish'));args=p.parse_args();source=SOURCE
 for old,new in {
  'd85d854996b3f031d3c75e1a4619e294c7f4be8418492c5db2599fdce8eb5509':'9a4ddefa204002bd5428dab996c6894d89138a605fd1969e39e42dc1a59730f9',
  '2026.10.17.2':'2026.10.18.4','2026.10.18.1':'2026.10.18.5',
  "allowed={'silver.dll','base/russian.lng','base/english.lng'}":"allowed={'silver.dll'}",
  'tio-training-client-':'tio-ranked-cancel-client-','tio-before-training-client-':'tio-before-ranked-cancel-client-',
 }.items():
  assert old in source;source=source.replace(old,new)
 request=dict(action=args.action)
 if args.action=='prepare':
  assert json.loads((OUT/'native-execution.json').read_text())['passed']
  request.update(assets={'silver.dll':base64.b64encode((OUT/'silver.dll').read_bytes()).decode()},proof=json.loads((OUT/'native-review.json').read_text()))
 else:
  gui=json.loads((OUT/'gui-verification.json').read_text());assert gui['passed'] and gui['native_close_sends_cancel'] and gui['city_unblocked_after_close']
  assert json.loads((OUT/'hosted-two-account.json').read_text())['passed']
  assert json.loads((OUT/'deployment.json').read_text())['passed']
  request.update(client_sha256=gui['client_sha256'],prepared=json.loads((OUT/'client-prepared.json').read_text()))
 code='request='+repr(request)+"\nbuilder={'__name__':'premium_archive_builder'}\nexec(compile("+repr((ROOT/'launcher/build_archive.py').read_text())+",'archive-builder','exec'),builder)\n"+source
 r=subprocess.run(SSH+['python3 -'],input=code,capture_output=True,encoding='utf8',timeout=900)
 if r.returncode:raise RuntimeError(r.stderr[-1500:])
 v=json.loads(r.stdout);(OUT/('client-prepared.json' if args.action=='prepare' else 'client-publication.json')).write_text(json.dumps(v,indent=2));print(json.dumps(v))
if __name__=='__main__':main()
