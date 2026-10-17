"""Package only the bot finishing, checked against the inspected hosted baseline."""
from hashlib import sha256
import io
import json
from pathlib import Path
import tarfile

from check_bot_finishing import ROOT,WORK,FILES


def digest(path):return sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    report=ROOT/'reports/bot-finishing-20261016'
    checks=json.loads((report/'automated-checks.json').read_text())
    if not checks['passed']:raise RuntimeError('Automated checks must pass before packaging')
    manifest={}
    for name in FILES:
        if (ROOT/name).read_bytes()!=(WORK/'candidate'/name).read_bytes():
            raise RuntimeError('Untested source change: '+name)
        manifest[name]=dict(before=digest(WORK/'baseline'/name),after=digest(ROOT/name))
    (report/'patch-manifest.json').write_text(json.dumps(manifest,indent=2))
    output=WORK/'patch.tar.gz'
    with tarfile.open(output,'w:gz') as archive:
        for name in FILES:archive.add(ROOT/name,arcname=name)
        raw=json.dumps(manifest).encode();entry=tarfile.TarInfo('manifest.json');entry.size=len(raw)
        archive.addfile(entry,io.BytesIO(raw))
    value=dict(archive=str(output),sha256=digest(output),files=len(FILES),data_files_included=False)
    (report/'package.json').write_text(json.dumps(value,indent=2));print(json.dumps(value))


if __name__=='__main__':main()
