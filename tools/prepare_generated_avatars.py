"""Inspect the authoritative avatar release without touching hosted saves."""
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.provision_user_test_accounts import remote

FOLDER = ROOT / 'reports/generated-avatars-20261013'
SOURCES = ('config/avatars.json', 'tio/avatars.py')


def inspect():
    FOLDER.mkdir(parents=True, exist_ok=True)
    result = remote(r'''
import base64,hashlib,json,pathlib,sqlite3,subprocess
from contextlib import closing
root=pathlib.Path('/opt/tio-emulator');live=pathlib.Path('/var/www/tio-client/updates')
manifest=(live/'manifest.json').read_bytes();parsed=json.loads(manifest)
dll=next(r for r in parsed['files'] if r['path']=='silver.dll')
raw=(live/'blobs'/dll['sha256']).read_bytes()
assert hashlib.sha256(raw).hexdigest()==dll['sha256']
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 counts={n:db.execute('SELECT count(*) FROM '+n).fetchone()[0] for n in ('accounts','battle_checkpoints','battle_settlement_jobs')}
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
 manifest_b64=base64.b64encode(manifest).decode(),silver_b64=base64.b64encode(raw).decode(),counts=counts,
 sources={n:dict(text=(root/n).read_text(),sha256=hashlib.sha256((root/n).read_bytes()).hexdigest()) for n in ('config/avatars.json','tio/avatars.py')})))
''', {})
    (FOLDER / 'previous-manifest.json').write_bytes(base64.b64decode(result.pop('manifest_b64')))
    (FOLDER / 'silver-source.dll').write_bytes(base64.b64decode(result.pop('silver_b64')))
    (FOLDER / 'inspection.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(dict(service=result['service'],counts=result['counts'],dll_sha256=hashlib.sha256((FOLDER/'silver-source.dll').read_bytes()).hexdigest())))


if __name__ == '__main__':
    inspect()
