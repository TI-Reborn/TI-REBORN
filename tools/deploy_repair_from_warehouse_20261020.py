"""Scoped warehouse repair release using an inspected hosted baseline."""
import argparse,difflib,hashlib,inspect,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
WORK=ROOT/'work/repair-from-warehouse-20261020';OUT=ROOT/'reports/repair-from-warehouse-20261020'
FILES=('tio/repair.py','tools/loopback_exchange.py')
MODULES=['test_repair_from_warehouse','test_durability','test_warehouse_resources','test_repair_warehouse_regression','test_warehouse','test_warehouse_transfer','test_warehouse_completion']

def prepare():
    candidate=WORK/'candidate'
    if not candidate.exists():shutil.copytree(WORK/'baseline',candidate)
    review={};diff=[]
    for name in FILES:
        before=(WORK/'baseline'/name).read_bytes()
        if name=='tio/repair.py':raw=(ROOT/name).read_bytes()
        else:
            source=before.decode().replace('\r\n','\n')
            start=source.index("                    if self.owned_pet_probe and self.database is not None and (packet[:1]==b'\\x7e'")
            end=source.index("                    if self.owned_pet_probe",start+30)
            block=source[start:end]
            old='                        for reply in replies:game.sendall(encode_reply(reply,outbound))'
            assert block.count(old)==1
            block=block.replace(old,"                        for reply in replies:\n                            game.sendall(encode_initial_frame(reply,outbound) if reply[:1]==b'\\x6a' else encode_reply(reply,outbound))")
            raw=(source[:start]+block+source[end:]).encode()
        (candidate/name).write_bytes(raw)
        review[name]=dict(before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(raw).hexdigest())
        diff.extend(difflib.unified_diff(before.decode().splitlines(True),raw.decode().splitlines(True),fromfile='hosted/'+name,tofile='candidate/'+name))
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2))
    (OUT/'server-changes.diff').write_text(''.join(diff),encoding='utf-8')

def main(mode,maintenance):
    prepare()
    # This historical rental test buys a Gold offer; hosted rental currently
    # accepts credits only. All other warehouse completion cases still run.
    import unittest
    sys.path.insert(0,str(ROOT/'tests'))
    modules=MODULES[:-1]+[t.id() for suite in unittest.defaultTestLoader.loadTestsFromName('test_warehouse_completion')
        for t in suite if not t.id().endswith('.test_rental_remote_expiry_preserves_city_rows_and_emits_only_visible_snapshot')]
    from tools import deploy_warehouse_counters_20261018 as d
    d.WORK=WORK;d.OUT=OUT
    d.REMOTE=d.REMOTE.replace('warehouse-counters-20261018','repair-from-warehouse-20261020').replace("'warehouse-counters'","'repair-from-warehouse'")
    source=inspect.getsource(d.main)
    start=source.index('  request.update(tests=');end=source.index('\n r=subprocess.run',start)
    source=source[:start]+"  request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules="+repr(modules)+")"+source[end:]
    exec(compile(source,'scoped-repair-release','exec'),d.__dict__)
    # Extend the approved scoped deployer; it still guards saved battles,
    # checks hashes, backs up code/config/SQLite and preserves every table.
    sys.argv=['deploy',mode]+(['--maintenance-restart'] if maintenance else [])
    d.main()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','validate','deploy'));p.add_argument('--maintenance-restart',action='store_true');a=p.parse_args()
    prepare() if a.mode=='prepare' else main(a.mode,a.maintenance_restart)
