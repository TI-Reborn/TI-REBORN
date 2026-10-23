"""Package the tested movement fix; no client resources or player data."""
from hashlib import sha256
import io
import json
import tarfile
from check_encounter_movement import ROOT,WORK,REPORT,FILES


def main():
    assert json.loads((REPORT/'automated-checks.json').read_text())['passed']
    baseline=json.loads((REPORT/'baseline-sha256.json').read_text())
    manifest={}
    for name in FILES:
        raw=(ROOT/name).read_bytes()
        assert raw==(WORK/'candidate'/name).read_bytes(),'Untested code'
        assert sha256((WORK/'baseline'/name).read_bytes()).hexdigest()==baseline[name]
        manifest[name]=dict(before=baseline[name],after=sha256(raw).hexdigest())
    (REPORT/'patch-manifest.json').write_text(json.dumps(manifest,indent=2))
    archive_path=WORK/'patch.tar.gz'
    with tarfile.open(archive_path,'w:gz') as archive:
        for name in FILES:archive.add(ROOT/name,arcname=name)
        raw=json.dumps(manifest).encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(raw)
        archive.addfile(entry,io.BytesIO(raw))
    report=dict(archive=str(archive_path),sha256=sha256(archive_path.read_bytes()).hexdigest(),files=list(FILES),player_data_included=False)
    (REPORT/'package.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
