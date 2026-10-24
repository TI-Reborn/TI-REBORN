"""Install the published canine release with the official launcher updater."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.dog_models_gui_20261021 import qa
from tools.publish_dog_models_20261021 import VERSION
p=argparse.ArgumentParser();p.add_argument('target',choices=('qa','saved'));mode=p.parse_args().target
game=qa.GAME if mode=='qa' else Path((Path.home()/'AppData/Local/TioLauncher/folder.txt').read_text(encoding='utf-8-sig').strip()).resolve()
assert game.is_dir() and (game/'ti.exe').is_file()
if mode=='qa':assert (game/'.tio-owned-qa').is_file()
else:assert game==(Path.home()/'AppData/Local/TIO-Online').resolve()
backup=qa.OUT/('local-before' if mode=='saved' else 'qa-update-before');records=[]
for name in qa.MAPPING:
 raw=(game/name).read_bytes();target=backup/name;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():assert target.read_bytes()==raw,'Preserve first backup'
 else:target.write_bytes(raw)
 records.append(dict(path=name,sha256=qa.sha(raw)))
(qa.OUT/(mode+'-install-backup.json')).write_text(json.dumps(dict(root=str(game),files=records),indent=2))
report=qa.OUT/(mode+'-launcher-update.json')
result=subprocess.run([str(qa.LAUNCHER),'--client-update-check',str(game),str(report)],creationflags=subprocess.CREATE_NO_WINDOW,timeout=180)
assert result.returncode==0
update=json.loads(report.read_text());assert update['passed'] and update['Version']==VERSION
for name,relative in qa.MAPPING.items():assert (game/name).read_bytes()==(qa.ASSET/relative).read_bytes(),name
done=dict(passed=True,root=str(game),version=VERSION,verified_resources=6,used_published_launcher=True,metrics=update['Metrics'])
(qa.OUT/(mode+'-installed.json')).write_text(json.dumps(done,indent=2));print(json.dumps(done))
