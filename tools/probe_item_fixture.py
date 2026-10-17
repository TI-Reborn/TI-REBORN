"""Install diagnostic XML, recovering verified leftovers from interrupted runs."""
import sys
import zlib
import csv
import subprocess
import tempfile
import hashlib
from contextlib import nullcontext
from pathlib import Path
import capture_loaded_orange

target=Path(r'C:\Program Files (x86)\TIOnline\base\shared config\items.xml')
fixture=Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml'


def recover_leftovers(files, backup_root):
    """Back up and remove only byte-identical emulator catalogs, as one preflight.

    Validate every file first so a foreign catalog aborts without partial cleanup.
    The caller must establish that the client is not running.
    """
    existing=[]
    for path,source in files:
        if not path.exists():continue
        raw=source.read_bytes();observed=path.read_bytes()
        # Recognize the exact earlier three-town fixture after this upgrade,
        # including a session that was already running when the source changed.
        decoded=observed
        try:decoded=zlib.decompress(observed)
        except zlib.error:pass
        legacy_zones=path.name=='zones.xml' and hashlib.sha256(decoded).hexdigest() in (
            '3e77904eba7644c11a2844751bb8eb8370c15871d1bd668f09b0bcf760956f3a',
            '053a9a58371a325718ad9fc4ae9745884d9fb558c1b0a42b652ab9fbd61aa8b1',
            '5a6e40864581b843104b719f1f9dc1bcc1acd580a89a4ba699cc5ad4c15a155e',
            '89b90dd7d6ac981a8e5e56d4e15114372827d5f42b65edb21d1b2160eaf89844',
            '5ac02571739c78ce2da0bb37918f3470c01bce396b41966eff846561c48f2309')
        legacy_skills=path.name=='skills.xml' and hashlib.sha256(decoded).hexdigest()=='9cef86148a906dd605fb4dc0500f67de9b4a471c5f8df4322130364c3d38aadd'
        # Exact pre-stacking catalog, left by an older running/interrupted session.
        legacy_items=path.name=='items.xml' and hashlib.sha256(decoded).hexdigest() in ('66c182cd27e7a481e4627635a40efd0ba559d4d96686ec43e0723d178b736a1c','03ac67e9849ed3ecae3cd1b0a75404a3018575b71a1ecfa57c013b6a6f50adaa','23d17fe3b01ddd76ca2e2b12ba366c09b82e77b1edf9d67777159393067c6bc9')
        if observed not in (raw,zlib.compress(raw)) and not (legacy_zones or legacy_skills or legacy_items):
            raise FileExistsError('Existing non-emulator catalog preserved: '+str(path))
        existing.append((path,observed))
    if not existing:return
    backup_root.mkdir(parents=True,exist_ok=True)
    backup=Path(tempfile.mkdtemp(prefix='shared-config-',dir=backup_root))
    for path,observed in existing:
        (backup/path.name).write_bytes(observed)
    for path,observed in existing:
        if path.read_bytes()!=observed:
            raise FileExistsError('Catalog changed during startup; preserved: '+str(path))
        path.unlink()
    print('Recovered interrupted session catalogs; backup:',backup,flush=True)


if __name__=='__main__':
    raw=fixture.read_bytes()
    target.parent.mkdir(parents=True,exist_ok=True)
    network='--shared-config' in sys.argv
    if network:
        tasks=subprocess.check_output(['tasklist','/FI','IMAGENAME eq ti.exe','/FO','CSV','/NH'],text=True,errors='replace')
        if any(row and row[0].lower()=='ti.exe' for row in csv.reader(tasks.splitlines())):
            raise RuntimeError('TI client is already running; close it before starting another session')
        files=[(target,fixture),(target.with_name('skills.xml'),fixture.parent/'skills_diagnostic.xml')]
        if '--mychar-probe' in sys.argv:
            files.append((target.with_name('zones.xml'),fixture.parent/'zones_diagnostic.xml'))
        recover_leftovers(files,fixture.parent.parent/'data/session-backups')
    else:
        with target.open('xb') as stream:stream.write(raw)
    zones=target.with_name('zones.xml')
    skills=target.with_name('skills.xml')
    skills_raw=(fixture.parent/'skills_diagnostic.xml').read_bytes() if network else None
    if network and skills.exists():raise FileExistsError('Existing skills preserved')
    if network and '--mychar-probe' in sys.argv and zones.exists():raise FileExistsError('Existing zones preserved')
    try:
        sys.argv=['capture_loaded_orange.py','--fix-user32']+([] if network else ['--load-item-fixture'])+sys.argv[1:]
        from mine_scene_fixture import hidden_static_deposits
        with hidden_static_deposits(target.parent.parent,fixture.parent.parent/'data/session-backups') if network else nullcontext():
            capture_loaded_orange.main()
    finally:
        if network and skills.exists():
            if skills.read_bytes() in (skills_raw,zlib.compress(skills_raw)):skills.unlink()
            else:print('Unexpected skills content preserved')
        # Never remove a file that changed during the probe.
        if target.exists():
            observed=target.read_bytes()
            (fixture.parent/'items_last_probe_saved.bin').write_bytes(observed)
            if observed in (raw,zlib.compress(raw)):target.unlink()
            else:print('Catalog differs from fixture; preserved at',target)

        if network and zones.exists() and '--mychar-probe' in sys.argv:
            zone_raw=(fixture.parent/'zones_diagnostic.xml').read_bytes()
            if zones.read_bytes() in (zone_raw,zlib.compress(zone_raw)):zones.unlink()
            else:print('Unexpected zones content preserved')
