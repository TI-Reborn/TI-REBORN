"""Create a reviewable local client candidate bundle; never publish or install."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/repair-warehouse-20261017'


def main():
    for name in ('native-filter-verification.json','native-wire-verification.json','server-contract-tests.json'):
        assert json.loads((REPORT/name).read_text())['passed'],name
    verification=json.loads((REPORT/'not-applied-verification.json').read_text())
    assert not verification['hosted_update_applied'] and verification['client_manifest_unchanged'] and not verification['runtime_changed_files']
    prepared=json.loads((REPORT/'client/prepared.json').read_text())
    dll=REPORT/'client/candidate/silver.dll'
    assert hashlib.sha256(dll.read_bytes()).hexdigest()==prepared['candidate_sha256']
    out=ROOT/'output/repair-warehouse-20261017';out.mkdir(parents=True,exist_ok=True)
    entries={
        'client/silver.dll':dll,
        'README.ru.md':ROOT/'docs/REPAIR_KITS_WAREHOUSE_20261017.md',
        'deploy/client_repair_warehouse.py':ROOT/'deploy/client_repair_warehouse.py',
        'tests/test_repair_warehouse_regression.py':ROOT/'tests/test_repair_warehouse_regression.py',
        'checks/prepared.json':REPORT/'client/prepared.json',
    }
    for name in ('verify_repair_warehouse_native.py','verify_repair_warehouse_wire.py','check_repair_warehouse.py','prepare_repair_warehouse_client.py'):
        entries['tools/'+name]=ROOT/'tools'/name
    for name in ('native-filter-verification.json','native-wire-verification.json','server-contract-tests.json','not-applied-verification.json'):
        entries['checks/'+name]=REPORT/name
    manifest={name:dict(size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for name,path in entries.items()}
    archive=out/'repair-warehouse-candidate.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,path in entries.items():z.write(path,name)
        z.writestr('bundle-manifest.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name,record in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==record['sha256']
    result=dict(archive=str(archive),size=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                client_files=1,changed_bytes=4,published=False,installed=False,server_changes=False,player_database_included=False)
    (REPORT/'package.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':main()
