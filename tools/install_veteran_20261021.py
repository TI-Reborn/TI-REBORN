"""Install through the existing, unmodified official launcher updater."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.publish_veteran_20261021 import OUT,ASSET,VERSION,XML,MAPPING,sha
from tools.fighter_model_gui_20261021 import GAME,LAUNCHER
parser=argparse.ArgumentParser();parser.add_argument('target',choices=('qa','saved'));mode=parser.parse_args().target
game=GAME if mode=='qa' else Path((Path.home()/'AppData/Local/TioLauncher/folder.txt').read_text(encoding='utf-8-sig').strip()).resolve()
assert (game/'ti.exe').is_file()
if mode=='qa':assert (game/'.tio-owned-qa').is_file()
else:assert game==(Path.home()/'AppData/Local/TIO-Online').resolve()
report=OUT/(mode+'-launcher-update.json');assert not report.exists()
backup=OUT/(mode+'-xml-before.xml');backup.write_bytes((game/XML).read_bytes())
r=subprocess.run([str(LAUNCHER),'--client-update-check',str(game),str(report)],creationflags=subprocess.CREATE_NO_WINDOW,timeout=180)
assert r.returncode==0
update=json.loads(report.read_text());assert update['passed'] and update['Version']==VERSION
for name,source in MAPPING.items():assert (game/name).read_bytes()==(ASSET/source).read_bytes(),name
assert (game/XML).read_bytes()==(OUT/'public-items-after.xml').read_bytes()
result={'passed':True,'root':str(game),'version':VERSION,'verified_resources':7,'official_launcher_updater':True,'metrics':update['Metrics']}
(OUT/(mode+'-installed.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
