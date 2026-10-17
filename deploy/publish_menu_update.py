"""Publish verified menu-only blobs first, then atomically replace the manifest."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

stage = Path('/root/tio-menu-20260924')
live = Path('/var/www/tio-client/updates')
old = json.loads((live / 'manifest.json').read_text())
new = json.loads((stage / 'manifest.json').read_text())
assert old['version'] == '2026.09.23.2', 'Unexpected current release'
assert new['version'] == '2026.09.24.1'
assert len(old['files']) == len(new['files'])
changed = {a['path'] for a, b in zip(old['files'], new['files']) if a != b}
assert changed == {'base/pda/mainbg.jpg', 'base/pda/gamelogo.png'}
for a, b in zip(old['files'], new['files']):
    assert a['path'] == b['path']
    if a['path'] in changed:
        assert not b['seed']
        blob = stage / 'blobs' / b['sha256']
        data = blob.read_bytes()
        assert len(data) == b['size']
        assert hashlib.sha256(data).hexdigest() == b['sha256']
        target = live / 'blobs' / b['sha256']
        if target.exists():
            assert target.read_bytes() == data
        else:
            with target.open('xb') as output:
                output.write(data)
            target.chmod(0o644)
backup = Path(tempfile.mkdtemp(prefix='tio-before-menu-', dir='/root'))
shutil.copy2(live / 'manifest.json', backup / 'manifest.json')
with tempfile.NamedTemporaryFile(dir=live, prefix='.menu-', delete=False) as output:
    output.write((stage / 'manifest.json').read_bytes())
    pending = Path(output.name)
pending.chmod(0o644)
pending.replace(live / 'manifest.json')
print('Published', new['version'], 'previous manifest:', backup)
