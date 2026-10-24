"""Publish the reviewed native PNG chooser/converter and two dialog strings."""
import argparse,base64,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
from tools.publish_training_base_client_20261018 import REMOTE as TRAINING
OUT=ROOT/'reports/clan-icons-20261018'

def remote_source():
    source=TRAINING
    changes={
      "d85d854996b3f031d3c75e1a4619e294c7f4be8418492c5db2599fdce8eb5509":"020b4c7ea775d1226b212799c4738342187136fbd2655567d12ee830580ecadc",
      "2026.10.17.2":"2026.10.18.2", "2026.10.18.1":"2026.10.18.3",
      "tio-training-client-":"tio-clan-icons-client-", "tio-before-training-client-":"tio-before-clan-icons-client-",
      "assert set(request['assets'])==allowed":"assert set(request['assets'])==allowed|{'tio_crest.dll'}",
      "   key=b'\\r\\ntb02t=';assert key not in previous\n   assert candidate.startswith(previous.rstrip(b'\\r\\n')+key)\n   assert candidate.endswith(b'\\r\\n') and candidate.count(key)==1":
      "   import re\n   pattern=rb'(?m)^m152=[^\\r\\n]*'\n   assert len(re.findall(pattern,previous))==len(re.findall(pattern,candidate))==1\n   assert re.sub(pattern,b'',previous)==re.sub(pattern,b'',candidate)\n   assert b'PNG' in re.search(pattern,candidate)[0] and b'BMP' in re.search(pattern,candidate)[0]",
      " assert set(changed)==allowed":
      " assert set(changed)==allowed\n assert not any(r['path']=='tio_crest.dll' for r in updated['files'])\n helper=base64.b64decode(request['assets']['tio_crest.dll']);assert sha(helper)==request['helper_sha256']\n atomic(helper,live/'blobs'/sha(helper))\n updated['files'].append(dict(path='tio_crest.dll',size=len(helper),sha256=sha(helper)))\n changed.append('tio_crest.dll')",
    }
    for before,after in changes.items():
        assert before in source,before
        source=source.replace(before,after)
    return source

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('prepare','publish'));args=p.parse_args()
    proof=json.loads((OUT/'native-review.json').read_text())
    request=dict(action=args.action)
    if args.action=='prepare':
        assert json.loads((OUT/'native-hook-execution.json').read_text())['passed']
        assert json.loads((OUT/'native-image-conversion.json').read_text())['passed']
        request.update(assets={n:base64.b64encode((OUT/n).read_bytes()).decode() for n in ('silver.dll','tio_crest.dll','base/russian.lng','base/english.lng')},proof=proof)
        import hashlib
        request['helper_sha256']=hashlib.sha256((OUT/'tio_crest.dll').read_bytes()).hexdigest()
    else:
        gui=json.loads((OUT/'gui-verification.json').read_text(encoding='utf-8'))
        assert gui['passed'] and gui['png_selected'] and gui['native_upload'] and gui['second_account_verified']
        assert json.loads((OUT/'deployment.json').read_text())['passed']
        assert json.loads((OUT/'launcher/public-verification.json').read_text())['status']=='passed'
        request.update(client_sha256=gui['client_sha256'],prepared=json.loads((OUT/'client-prepared.json').read_text()))
    code='request='+repr(request)+"\nbuilder={'__name__':'crest_archive_builder'}\nexec(compile("+repr((ROOT/'launcher/build_archive.py').read_text())+",'archive-builder','exec'),builder)\n"+remote_source()
    r=subprocess.run(SSH+['python3 -'],input=code,capture_output=True,encoding='utf-8',timeout=900)
    if r.returncode:raise RuntimeError(r.stderr[-2000:])
    value=json.loads(r.stdout);(OUT/('client-prepared.json' if args.action=='prepare' else 'client-publication.json')).write_text(json.dumps(value,indent=2));print(json.dumps(value))
if __name__=='__main__':main()
