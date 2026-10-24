"""Reuse the qualified dependency archive while replacing the complete rebuilt Next output."""
import hashlib
import json
from pathlib import Path
import tarfile

folder = Path('reports/seo-20261018')
base = folder/'portal-seo.tar.gz'
target = folder/'portal-seo-final.tar.gz'
web = Path('web'); build = '.next-seo-release'
standalone = web/build/'standalone'
if target.exists(): raise RuntimeError('Preserve existing archives')
if not (standalone/'server.js').is_file(): raise RuntimeError('Missing rebuilt standalone')
replacements = [p for p in standalone.iterdir() if p.name != 'node_modules' and not p.name.startswith('.env')]
replaced = {p.name for p in replacements}
def safe(member):
    if any(part.startswith('.env') for part in Path(member.name).parts): return None
    member.uid = member.gid = 0; member.uname = member.gname = 'root'
    return member
with tarfile.open(base, 'r:gz') as old, tarfile.open(target, 'w:gz', dereference=True, compresslevel=3) as new:
    for member in old:
        if Path(member.name).parts[0] in replaced: continue
        new.addfile(member, old.extractfile(member) if member.isfile() else None)
    for path in replacements: new.add(path, arcname=path.name, filter=safe)
    new.add(web/build/'static', arcname=build+'/static', filter=safe)
with tarfile.open(target) as archive:
    names=archive.getnames()
    if any(any(part.startswith('.env') for part in Path(name).parts) for name in names): raise RuntimeError('Environment file in archive')
    if len(names) != len(set(names)): raise RuntimeError('Duplicate archive member')
data = dict(archive=str(target), sha256=hashlib.sha256(target.read_bytes()).hexdigest(), bytes=target.stat().st_size,
    reused_dependency_archive_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
    replacement_roots=sorted(replaced), environment_files_excluded=True)
(folder/'package-final.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
print(json.dumps(data))
