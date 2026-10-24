"""Own reserved QA account in a genuine graphical client with candidate launcher."""
import hashlib,json,sys,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import tio
from tools import verify_friends_hosted_20261019 as scope
from tools import groza_gui_20261019 as gui

def launch():
    launcher=ROOT/'work/friends-fix-20261019/launcher/TIO Launcher.exe'
    sha=hashlib.sha256(launcher.read_bytes()).hexdigest()
    source=(ROOT/'tools/hosted_graphical_qa_bridge.py').read_text(encoding='utf-8')
    old='d135224ae3803dfcaaaa3602cc2a1cfabe042a03a3c30238b81ddf4a1996dda8';assert source.count(old)==1
    auth=types.ModuleType('friends_guarded_bridge');auth.__file__=str(ROOT/'tools/hosted_graphical_qa_bridge.py');sys.modules[auth.__name__]=auth
    exec(compile(source.replace(old,sha),auth.__file__,'exec'),auth.__dict__);auth.static_guards=gui.guards
    data=scope.qa.load();root=gui.WORK/'game-a'
    bridge=auth.HostedGraphicalQaBridge(root,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),auto_select=True,launcher=launcher)
    scope.qa.OUT.joinpath('gui-client.json').write_text(json.dumps(dict(pid=bridge.pid,launcher_sha256=sha,root=str(root)),indent=2))
    print(json.dumps(dict(pid=bridge.pid,started=True,own_qa=True)),flush=True)
    try:
        for line in sys.stdin:
            cmd=line.strip()
            if cmd=='stop':break
            if cmd=='connect':print(json.dumps(bridge.start_connect()),flush=True)
            elif cmd=='status':print(json.dumps(bridge.status()),flush=True)
    finally:
        scope.qa.OUT.joinpath('gui-guards.json').write_text(json.dumps(bridge.events,indent=2));bridge.release(cleanup=True)

if __name__=='__main__':launch()
