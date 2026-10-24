"""Audit unchanged hosted equipment rules in an isolated runtime and temporary DBs."""
import base64,io,json,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_diagonal_doors_20261019 import remote
OUT=ROOT/'reports/turn-selection-equipment-20261019'

def main():
    buf=io.BytesIO()
    with tarfile.open(fileobj=buf,mode='w:gz') as tar:
        tar.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)
    result=remote('''import base64,io,json,os,shutil,subprocess,tarfile,tempfile,hashlib
from pathlib import Path
root=Path('/opt/tio-emulator');stage=Path(tempfile.mkdtemp(prefix='tio-equipment-audit-',dir='/opt'))
for n in ('server','tio','tools','config','evidence'):shutil.copytree(root/n,stage/n,ignore=shutil.ignore_patterns('__pycache__'))
with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request))) as tar:tar.extractall(stage,filter='data')
modules=['test_equipment_replacement_audit','test_equipment_batch','test_shared_equipment_batch','test_equipment','test_armor_equipment','test_battle_events']
p=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*modules,'-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},text=True,capture_output=True,timeout=180)
print(json.dumps(dict(passed=p.returncode==0,stage=str(stage),log=p.stdout+p.stderr,modules=modules,live_database_used=False,
 source_sha256={n:hashlib.sha256((stage/n).read_bytes()).hexdigest() for n in ('tio/equipment.py','tio/equipment_batch.py','tio/combat.py','server/team_arena.py')})))
''',base64.b64encode(buf.getvalue()).decode())
    (OUT/'remote-equipment-checks.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result));assert result['passed']

if __name__=='__main__':main()
