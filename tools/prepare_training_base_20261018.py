"""Package only inspected, tested Training Base server changes."""
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/training-base-20261018'
REPORT=ROOT/'reports/training-base-20261018'
FILES=('server/training_arena.py','server/contracts_service.py')


def main():
    manifest={name:{side:hashlib.sha256((WORK/folder/name).read_bytes()).hexdigest()
                   for side,folder in (('before','baseline'),('after','candidate'))} for name in FILES}
    (REPORT/'patch-manifest.json').write_text(json.dumps(manifest,indent=2))
    with tarfile.open(WORK/'patch.tar.gz','w:gz') as archive:
        for name in FILES:archive.add(WORK/'candidate'/name,arcname=name)
        raw=json.dumps(manifest).encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(raw)
        archive.addfile(entry,io.BytesIO(raw))
    with tarfile.open(WORK/'tests.tar.gz','w:gz') as archive:
        archive.add(WORK/'candidate/tests',arcname='tests',filter=lambda item:None if '__pycache__' in Path(item.name).parts else item)
    result=dict(archive=str(WORK/'patch.tar.gz'),sha256=hashlib.sha256((WORK/'patch.tar.gz').read_bytes()).hexdigest(),files=list(FILES),player_data_included=False)
    (REPORT/'package.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':main()
