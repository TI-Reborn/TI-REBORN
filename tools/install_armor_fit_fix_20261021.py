"""Use the unmodified official updater for the QA copy and saved player install."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.armor_fit_gui_20261021 import qa,OUT
from tools.publish_armor_fit_fix_20261021 import VERSION,NAME
parser=argparse.ArgumentParser();parser.add_argument('target',choices=('qa','saved'));mode=parser.parse_args().target
game=qa.GAME if mode=='qa' else Path((Path.home()/'AppData/Local/TioLauncher/folder.txt').read_text(encoding='utf-8-sig').strip()).resolve()
assert game.is_dir() and (game/'ti.exe').is_file()
if mode=='qa':assert (game/'.tio-owned-qa').is_file()
else:assert game==(Path.home()/'AppData/Local/TIO-Online').resolve()
old=(game/NAME).read_bytes();backup=OUT/(mode+'-xml-before.xml');assert not backup.exists();backup.write_bytes(old)
report=OUT/(mode+'-launcher-update.json')
r=subprocess.run([str(qa.LAUNCHER),'--client-update-check',str(game),str(report)],creationflags=subprocess.CREATE_NO_WINDOW,timeout=180);assert r.returncode==0
update=json.loads(report.read_text());assert update['passed'] and update['Version']==VERSION
assert (game/NAME).read_bytes()==(qa.ASSET/'items.xml').read_bytes()
result=dict(passed=True,root=str(game),version=VERSION,verified_resources=1,used_published_launcher=True,metrics=update['Metrics'])
(OUT/(mode+'-installed.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
