"""Scoped friendship release using inspected hosting baseline and idle guard."""
import argparse,difflib,hashlib,inspect,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_awp_scope_20261019 as d
WORK=ROOT/'work/friends-fix-20261019';OUT=ROOT/'reports/friends-fix-20261019'
FILES=('server/presence.py','server/friends_service.py','tio/friends.py','tio/protocol/friends.py')
MODULES=['test_friends','test_presence']

def main(mode):
    review={};diff=[]
    for name in FILES:
        before=WORK/'baseline'/name;old=before.read_bytes() if before.exists() else None
        raw=(ROOT/name).read_bytes();dest=WORK/'candidate'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        review[name]=dict(before=hashlib.sha256(old).hexdigest() if old is not None else None,after=hashlib.sha256(raw).hexdigest())
        diff.extend(difflib.unified_diff((old or b'').decode().splitlines(True),raw.decode().splitlines(True),fromfile='hosted-before/'+name,tofile='candidate/'+name))
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2));(OUT/'server-changes.diff').write_text(''.join(diff),encoding='utf-8')
    d.WORK=WORK;d.OUT=OUT;d.FILES=FILES
    d.REMOTE=d.REMOTE.replace('awp-scope','friends-fix').replace(" exec(compile(request['deployer']", " sys.argv.append('--maintenance-restart')\n exec(compile(request['deployer']")
    source=inspect.getsource(d.run).replace('awp-scope','friends-fix')
    start=source.index('modules=[\n');end=source.index('])',start)+2
    source=source[:start]+'modules='+repr(MODULES)+')'+source[end:]
    exec(compile(source,'scoped-friends-fix','exec'),d.__dict__);d.run(mode)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
