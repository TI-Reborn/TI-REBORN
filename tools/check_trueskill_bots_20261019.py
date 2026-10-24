"""Run task checks on the exact hosted runtime snapshot plus bounded candidate."""
import json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.prepare_trueskill_bots_20261019 import WORK,OUT,FILES,main

def check(modules):
    main();stage=WORK/'test-runtime';stage.mkdir(exist_ok=True)
    for name in ('server','tio','tools','config','evidence'):
        if not (stage/name).exists():shutil.copytree(WORK/'baseline'/name,stage/name)
    shutil.copytree(ROOT/'tests',stage/'tests',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    for name in FILES:shutil.copyfile(WORK/'candidate'/name,stage/name)
    for name in ('config/battle_item_catalog_extension.xml','evidence/battle_item_native.json'):
        shutil.copyfile(ROOT/name,stage/name)
    r=subprocess.run([sys.executable,'-m','unittest',*modules,'-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage.resolve())+os.pathsep+str((stage/'tests').resolve()),'PYTHONUTF8':'1'},text=True,encoding='utf-8',capture_output=True,timeout=240)
    report=dict(passed=r.returncode==0,modules=modules,isolated_database=True,hosted_runtime_baseline=True,log=r.stdout+r.stderr)
    (OUT/'local-checks.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return r.returncode

if __name__=='__main__':raise SystemExit(check(sys.argv[1:] or ['test_ranked_bots']))
