"""Pin a pending confirmation to its original sender across disconnects."""
import hashlib,inspect,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_awp_scope_20261019 as d
from tools.inspect_training_base_20261018 import remote

def main():
    work=ROOT/'work/friends-pending-fix-20261019';out=ROOT/'reports/friends-pending-fix-20261019';out.mkdir(parents=True,exist_ok=True)
    name='server/friends_service.py';raw=(ROOT/name).read_bytes()
    before=remote("import hashlib,json;from pathlib import Path;print(json.dumps(hashlib.sha256(Path('server/friends_service.py').read_bytes()).hexdigest()))")
    assert before=='ed804e868bf308c2f2b68a00cad82f8defaeae8caed4d1af293005b5cc08e7af'
    path=work/'candidate'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    (out/'server-review.json').write_text(json.dumps({name:dict(before=before,after=hashlib.sha256(raw).hexdigest())}))
    d.WORK=work;d.OUT=out;d.FILES=(name,)
    d.REMOTE=d.REMOTE.replace('awp-scope','friends-pending-fix').replace(" exec(compile(request['deployer']", " sys.argv.append('--maintenance-restart')\n exec(compile(request['deployer']")
    source=inspect.getsource(d.run).replace('awp-scope','friends-pending-fix');start=source.index('modules=[\n');end=source.index('])',start)+2
    source=source[:start]+"modules=['test_friends','test_presence'])"+source[end:]
    exec(compile(source,'friends-pending-fix-run','exec'),d.__dict__);d.run('validate');d.run('deploy')

if __name__=='__main__':main()
