"""Record reproducible hashes for local evidence; does not alter source artifacts."""
import datetime
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'evidence'
records=[]
for path in sorted(root.rglob('*')):
    if path.is_file() and path.name!='manifest.json':
        with path.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        records.append({'path':path.relative_to(root).as_posix(),'size':path.stat().st_size,'sha256':digest})
(root/'manifest.json').write_text(json.dumps({'recorded_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':records},indent=2)+'\n',encoding='utf-8')
print(f'Sealed {len(records)} evidence file hashes.')
