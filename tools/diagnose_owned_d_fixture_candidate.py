"""Replay the failed reviewed fixture on an isolated remote backup copy only."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.prepare_owned_d_dual_negative_fixture import FOLDER,MUTATE
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA

REPLAY=r'''
import io,json,pathlib,sqlite3,tempfile,sys,traceback
from contextlib import redirect_stdout
payload=json.load(sys.stdin)
snapshot=pathlib.Path(payload.pop('snapshot')).resolve()
assert snapshot==pathlib.Path('/root/tio-before-dual-negative-qa-l58v409y/reservation.sqlite3')
code=payload.pop('candidate_source')
isolated=pathlib.Path(tempfile.mkdtemp(prefix='tio-dual-negative-debug-',dir='/root'));isolated.chmod(0o700)
copy=isolated/'reservation.sqlite3'
with sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(copy) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
copy.chmod(0o600)
point="action=data['action'];assert action in ('prepare','restore')"
assert code.count(point)==1
injection="path=pathlib.Path("+repr(str(copy))+")\nbackup=lambda:pathlib.Path("+repr(str(isolated))+")\n"
patched=code.replace(point,injection+point)
original_lines=code.splitlines();patched_lines=patched.splitlines()
capture=io.StringIO();sys.stdin=io.StringIO(json.dumps(payload))
result=dict(authoritative_mutation=False,snapshot=str(snapshot),isolated_copy=str(copy),candidate_source_exact_except_path_and_backup=True)
try:
 with redirect_stdout(capture):exec(compile(patched,'<owned-D-isolated-candidate-replay>','exec'),{})
except BaseException as error:
 frames=[]
 for frame in traceback.extract_tb(error.__traceback__):
  source=patched_lines[frame.lineno-1].strip() if frame.filename=='<owned-D-isolated-candidate-replay>' else None
  frames.append(dict(file=frame.filename,line=frame.lineno,function=frame.name,source=source))
 result.update(replay_passed=False,error_type=type(error).__name__,message=str(error),frames=frames)
else:
 result.update(replay_passed=True,receipt=json.loads(capture.getvalue()))
with sqlite3.connect(copy.as_uri()+'?mode=ro',uri=True) as db:
 result['isolated_receipt_count']=db.execute('SELECT COUNT(*) FROM service_completion_receipts WHERE account=?',(payload['account'],)).fetchone()[0]
 result['isolated_dismissal_count']=db.execute('SELECT COUNT(*) FROM service_dismissals WHERE account=?',(payload['account'],)).fetchone()[0]
print(json.dumps(result))
'''

def main():
    fixture=FreshSurroundingsQA.load_private(ROOT/'reports/arena-surroundings/private/qs3110ad96.json')
    pin=json.loads((FOLDER/'d-dual-negative-fixture-review.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((ROOT/'tools/prepare_owned_d_dual_negative_fixture.py').read_bytes()).hexdigest()==pin['tool_sha256']
    result=fixture.remote(REPLAY,{**fixture.ownership_payload(),**pin,'action':'prepare','snapshot':'/root/tio-before-dual-negative-qa-l58v409y/reservation.sqlite3','candidate_source':MUTATE})
    output=FOLDER/'d-dual-negative-fixture-isolated-debug.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(evidence=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),**result),ensure_ascii=False))

if __name__=='__main__':main()
