"""Stage only launcher admission changes on the freshly inspected VPS code."""
import argparse,difflib,hashlib,inspect,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
WORK=ROOT/'work/launcher-required-20261020';OUT=ROOT/'reports/launcher-required-20261020'
FILES=('server/config.py','server/tls.py','server/multi.py')
MODULES=['test_launch_admission','test_game_tls','test_login','test_server_login']

def once(s,old,new):assert s.count(old)==1,old;return s.replace(old,new)
def prepare():
    candidate=WORK/'candidate'
    if not candidate.exists():shutil.copytree(WORK/'baseline',candidate)
    review={};diff=[]
    for name in FILES:
        before=(WORK/'baseline'/name).read_bytes()
        if name!='server/multi.py':raw=(ROOT/name).read_bytes()
        else:
            s=before.decode().replace('\r\n','\n')
            s=once(s,"            bridge_port=read_bridge_preface(connection,deadline) if kind=='login' else None",
                "            policy=self.config.tls.launch_manifests\n            bridge_port=read_bridge_preface(connection,deadline,policy) if kind=='login' or policy is not None else None")
            s=once(s,'            login_listener = stack.enter_context(self.bind(self.config.bind_address,self.config.game_port))\n            game_listener = stack.enter_context(self.bind(self.config.bind_address,self.config.session_port))',
                "            direct_bind='127.0.0.1' if self.config.tls.launch_manifests is not None else self.config.bind_address\n            login_listener = stack.enter_context(self.bind(direct_bind,self.config.game_port))\n            game_listener = stack.enter_context(self.bind(direct_bind,self.config.session_port))")
            raw=s.encode()
        (candidate/name).write_bytes(raw)
        review[name]=dict(before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(raw).hexdigest())
        diff.extend(difflib.unified_diff(before.decode().splitlines(True),raw.decode().splitlines(True),fromfile='hosted/'+name,tofile='candidate/'+name))
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2));(OUT/'server-changes.diff').write_text(''.join(diff),encoding='utf-8')

def main(mode):
    prepare()
    from tools import deploy_warehouse_counters_20261018 as d
    d.WORK=WORK;d.OUT=OUT
    d.REMOTE=d.REMOTE.replace('warehouse-counters-20261018','launcher-required-20261020').replace("'warehouse-counters'","'launcher-required'")
    source=inspect.getsource(d.main)
    start=source.index('  request.update(tests=');end=source.index('\n r=subprocess.run',start)
    source=source[:start]+"  request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules="+repr(MODULES)+")"+source[end:]
    # The existing guarded deployer also installs this explicitly scoped config
    # value during stopped cutover, and restores it with code on any failure.
    def transform_deployer():
        s=(ROOT/'tools/deploy_game_operations_remote.py').read_text()
        s=once(s,'KEEP_TABLES=',"SCOPES['launcher-required']=frozenset("+repr(FILES)+")\nKEEP_TABLES=")
        s=once(s,'    stopped=False;applied=[]',"    config_before=CONFIG.read_bytes()\n    assert b'launch_manifests' not in config_before\n    (args.backup/'server-before.toml').write_bytes(config_before)\n    stopped=False;applied=[]")
        anchor="        run('runuser','-u','tio','--',str(ROOT/'.venv/bin/python'),'-m','server','--config',str(CONFIG),'--check')"
        install='''        text=config_before.decode()
        assert text.count('[tls]')==1
        CONFIG.write_text(text.replace('[tls]', '[tls]\\nlaunch_manifests="/var/www/tio-client"'))
        config_hash=digest(CONFIG)
'''
        s=once(s,anchor,install+anchor)
        s=once(s,"        for path in applied:","        CONFIG.write_bytes(config_before)\n        for path in applied:")
        compile(s,'guarded-admission-deployer','exec')
        (OUT/'deployer-source.py').write_text(s)
        return s
    d.transform_deployer=transform_deployer
    source=once(source,"(ROOT/'tools/deploy_game_operations_remote.py').read_text()",'transform_deployer()')
    exec(compile(source,'scoped-launcher-admission','exec'),d.__dict__)
    sys.argv=['deploy',mode];d.main()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('prepare','validate','deploy'));a=p.parse_args()
    prepare() if a.mode=='prepare' else main(a.mode)
