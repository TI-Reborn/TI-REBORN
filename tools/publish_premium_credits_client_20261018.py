"""Manifest-last publication of the two-byte premium currency icon fix."""
import argparse,base64,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
from tools.publish_training_base_client_20261018 import REMOTE as SOURCE
OUT=ROOT/'reports/premium-credits-20261018'

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','publish'));args=p.parse_args();source=SOURCE
 for old,new in {
  'd85d854996b3f031d3c75e1a4619e294c7f4be8418492c5db2599fdce8eb5509':'112849c8f009cd2f96a375229a47e0cb9e4fd8c190dd378c1466ce7d2e942606',
  '2026.10.17.2':'2026.10.18.3','2026.10.18.1':'2026.10.18.4',
  "allowed={'silver.dll','base/russian.lng','base/english.lng'}":"allowed={'silver.dll'}",
  'tio-training-client-':'tio-premium-credits-client-','tio-before-training-client-':'tio-before-premium-credits-client-',
 }.items():
  assert old in source;source=source.replace(old,new)
 request=dict(action=args.action)
 if args.action=='prepare':
  assert json.loads((OUT/'native-execution.json').read_text())['passed']
  request.update(assets={'silver.dll':base64.b64encode((OUT/'silver.dll').read_bytes()).decode()},proof=json.loads((OUT/'native-review.json').read_text()))
 else:
  gui=json.loads((OUT/'gui-verification.json').read_text());assert gui['passed'] and gui['credit_icons_visible'] and gui['daily_purchase_verified']
  assert json.loads((OUT/'launcher/public-verification.json').read_text())['status']=='passed'
  request.update(client_sha256=gui['client_sha256'],prepared=json.loads((OUT/'client-prepared.json').read_text()))
 code='request='+repr(request)+"\nbuilder={'__name__':'premium_archive_builder'}\nexec(compile("+repr((ROOT/'launcher/build_archive.py').read_text())+",'archive-builder','exec'),builder)\n"+source
 r=subprocess.run(SSH+['python3 -'],input=code,capture_output=True,encoding='utf8',timeout=900)
 if r.returncode:raise RuntimeError(r.stderr[-1500:])
 v=json.loads(r.stdout);(OUT/('client-prepared.json' if args.action=='prepare' else 'client-publication.json')).write_text(json.dumps(v,indent=2));print(json.dumps(v))
if __name__=='__main__':main()
