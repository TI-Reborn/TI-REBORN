"""Use the published launcher updater for the user's saved installation."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.female_fighter_gui_20261021 import qa
local=Path.home()/'AppData/Local/TioLauncher/folder.txt'
game=Path(local.read_text(encoding='utf-8-sig').strip()).resolve()
assert game==(Path.home()/'AppData/Local/TIO-Online').resolve() and (game/'ti.exe').is_file()
backup=qa.OUT/'local-install-before';records=[]
for name in qa.MAPPING:
 source=game/name;raw=source.read_bytes();target=backup/name;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():assert target.read_bytes()==raw,'Preserve first backup'
 else:target.write_bytes(raw)
 records.append(dict(path=name,sha256=qa.sha(raw)))
(qa.OUT/'local-install-backup.json').write_text(json.dumps(dict(root=str(game),files=records),indent=2))
report=qa.OUT/'local-launcher-update.json'
result=subprocess.run([str(qa.LAUNCHER),'--client-update-check',str(game),str(report)],creationflags=subprocess.CREATE_NO_WINDOW,timeout=180)
assert result.returncode==0
update=json.loads(report.read_text());assert update['passed'] and update['Version']=='2026.10.21.1'
for name,relative in qa.MAPPING.items():assert (game/name).read_bytes()==(qa.ASSET/relative).read_bytes(),name
(qa.OUT/'local-installed.json').write_text(json.dumps(dict(passed=True,root=str(game),version=update['Version'],verified_resources=6,used_published_launcher=True),indent=2))
print(json.dumps(dict(passed=True,root=str(game),version=update['Version'],files=6,metrics=update['Metrics'])))
