
"""Inspect original native loader/GPU output in the dedicated owned QA client.

This renders diagnostic samples in the main menu, without accepting terms,
authenticating a player or claiming a hosted battle was exercised.
Run in an interactive tool session and send `stop` to detach the probe.
"""
from pathlib import Path
import frida,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
root=ROOT/'work/rain-stripes-20261023'
info=json.loads((root/'process.json').read_text())
game=(root/'client-qa/game-a').resolve()
assert Path(info['root']).resolve()==game and (game/'.tio-owned-qa').is_file()
assert hashlib.sha256((game/'silver.dll').read_bytes()).hexdigest()=='7fd0a3b221e6bd967faed999de90b77b54f04ec16864fc4ea85d19b6d68fbe96'
s=frida.attach(info['pid']);events=[]
guard=s.create_script('rpc.exports={path(){return Process.mainModule.path;}};')
guard.load()
assert Path(guard.exports_sync.path()).resolve()==game/'ti.exe'
guard.unload()
x=s.create_script(Path(__file__).with_suffix('.js').read_text())
def event(m,d):
 events.append(m);(ROOT/'reports/rain-stripes-20261023/native-texture-proof.json').write_text(json.dumps(events,indent=2));print(json.dumps(m),flush=True)
x.on('message',event);x.load()
try:
 for line in sys.stdin:
  if line.strip()=='stop':break
finally:s.detach()
