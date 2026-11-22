"""Prepare two owned QA game copies solely from the current public manifest.

No accounts, SSH, UI, game processes or native authentication are used. Verified
immutable assets may be hardlinked; executable modules and mutable/config files
are independent copies. Personal installed files are neither read nor copied.
Run again after publishing a release to refresh these same owned QA copies.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hosted_graphical_qa_bridge import HASHES, accepted_native_hashes, static_guards


ORIGIN = 'https://185.184.42.88/updates/'
INSTALLED = Path('C:/Users/jundu/AppData/Local/TIO-Online')
QA_BASE = ROOT/'reports/arena-surroundings-implementation/client-qa'
MARKER = '.tio-owned-qa'
PROOF = 'qa-client-provenance.json'
CREATOR = 'tools/prepare_hosted_graphical_qa.py'
BINARIES = {'ti.exe', 'orange.dll', 'silver.dll', 'gold.dll', 'ode.dll', 'd3dx9_26.dll', 'tio_crest.dll'}
CONFIGS = {'base/config.cfg', 'base/autoexec.cfg'}
IMMUTABLE = {'.t', '.s', '.png', '.tga', '.jpg', '.jpeg', '.dds', '.bmp',
             '.wav', '.ogg', '.mp3', '.avi', '.fx', '.ttf'}
QA_GENERATED = {'base/shared config/customization.xml',
                'base/shared config/premiumaccount.xml', 'base/shared config/services.xml'}
SETTINGS = (
    'orange_addr 185.184.42.88\r\norange_port 28512\r\n'
    'g_language russian\r\nr_fullscreen 0\r\nr_width 1024\r\nr_height 768\r\n'
    'sound_enable 0\r\ng_reglink https://185.184.42.88/register/\r\n'
).encode('ascii')


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def personal_name(name):
    name = name.lower()
    return (name in {'login.ini', 'skillbar.dat', 'log.txt', 'log_old.txt'} or name.startswith('notes-')
            or Path(name).suffix in {'.log', '.bak', '.dmp'})


def validate_manifest(manifest):
    if manifest.get('schema') != 1 or not isinstance(manifest.get('version'), str):
        raise ValueError('Unsupported public client manifest')
    records = manifest.get('files')
    if not isinstance(records, list) or not 1 <= len(records) <= 20000:
        raise ValueError('Invalid public manifest file count')
    seen = set()
    for record in records:
        relative = record.get('path', '')
        path = PurePosixPath(relative)
        parts = path.parts
        if (not relative or path.is_absolute() or relative != path.as_posix()
                or relative.lower() in seen or not parts
                or not (relative.lower() in BINARIES or len(parts) > 1 and parts[0] == 'base')):
            raise ValueError('Invalid or duplicate public client path')
        for part in parts:
            if (not re.fullmatch(r'[A-Za-z0-9_ .()\-]+', part) or part in ('.', '..')
                    or part.endswith(('.', ' '))
                    or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)):
                raise ValueError('Unsafe public client path')
        if personal_name(parts[-1]):
            raise ValueError('Public manifest includes personal/writable player data')
        size, checksum = record.get('size'), record.get('sha256')
        if (type(size) is not int or not 0 <= size <= 512*1024*1024
                or not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum)):
            raise ValueError('Invalid public client size/SHA')
        seed = record.get('seed', False)
        if type(seed) is not bool or seed != (relative.lower() in CONFIGS):
            raise ValueError('Public seed configuration policy changed')
        seen.add(relative.lower())
    if not BINARIES <= seen or not CONFIGS <= seen:
        raise ValueError('Public manifest lacks required native/config resources')
    by_name = {r['path'].lower(): r for r in records}
    for name in HASHES:
        if by_name[name]['sha256'] not in accepted_native_hashes(name):
            raise ValueError('Published native module differs from the graphical harness pin: '+name)
    return records


def checked_target(root, relative):
    """Enforce an absolute owned root and reject any reparse/symlink component."""
    root = Path(root).absolute()
    target = root.joinpath(*PurePosixPath(relative).parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('QA destination escaped its owned directory')
    current = target
    while True:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('QA destination contains a filesystem link')
        if current == root:
            break
        if current.parent == current:
            raise ValueError('QA destination is outside its owned directory')
        current = current.parent
    return target


def own_copy(root):
    root = Path(root).absolute()
    if root.parent.resolve() != QA_BASE.resolve() or root.name not in ('game-a', 'game-b'):
        raise ValueError('Prepare only the two explicitly owned QA copy directories')
    if root.resolve().is_relative_to(INSTALLED.resolve()) or INSTALLED.resolve().is_relative_to(root.resolve()):
        raise ValueError('QA copy overlaps the installed personal game')
    checked_target(root, MARKER)
    root.mkdir(parents=True, exist_ok=True)
    marker = root/MARKER
    if marker.exists():
        saved = json.loads(marker.read_text(encoding='utf-8'))
        if saved.get('creator') != CREATOR or saved.get('root') != str(root):
            raise ValueError('QA directory marker is not owned by this preparation tool')
    else:
        if any(root.iterdir()):
            raise ValueError('Refuse to adopt a nonempty unmarked game directory')
        marker.write_text(json.dumps(dict(schema=1, creator=CREATOR, root=str(root)), indent=2)+'\n', encoding='utf-8')
    return root


def matches(path, record):
    return (path.is_file() and not path.is_symlink()
            and path.stat().st_size == record['size'] and digest(path) == record['sha256'])


def replace_private(target, *, data=None, source=None, hardlink=False):
    """Replace an owned pathname atomically; never truncate a linked source."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.qa-stage-', dir=target.parent)
    os.close(handle)
    temporary = Path(temporary)
    try:
        if hardlink:
            temporary.unlink()
            os.link(source, temporary)
        elif source is not None:
            shutil.copyfile(source, temporary)
        else:
            temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def download(record):
    with urllib.request.urlopen(ORIGIN+'blobs/'+record['sha256'], timeout=45) as response:
        data = response.read(record['size']+1)
    if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('Public blob size/SHA does not match the current manifest')
    return data


def clean_old_owned_files(root, current):
    proof = root/PROOF
    previous = set()
    if proof.exists():
        previous = set(json.loads(proof.read_text(encoding='utf-8')).get('managed_paths', ()))
    removed = []
    # Never enumerate or delete the installed personal game. All candidates
    # here are individually resolved inside a verified .tio-owned-qa root.
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        checked = checked_target(root, relative)
        if relative in current or relative in {MARKER, PROOF}:
            continue
        if relative in previous or relative in QA_GENERATED or personal_name(path.name):
            checked.unlink()
            removed.append(relative)
        else:
            raise ValueError('Unexpected file in the dedicated QA copy: '+relative)
    return removed


def prepare_copy(root, manifest, records, manifest_sha, verified_sources, *, hardlinks=True):
    root = own_copy(root)
    wanted = {record['path'] for record in records}
    removed = clean_old_owned_files(root, wanted)
    counts, rows = Counter(), []
    bytes_written = 0
    for index, record in enumerate(records, 1):
        relative = record['path']
        target = checked_target(root, relative)
        if relative.lower() in CONFIGS:
            replace_private(target, data=SETTINGS)
            method = 'fresh_hosted_config'
            actual_sha = hashlib.sha256(SETTINGS).hexdigest()
            actual_size = len(SETTINGS)
            bytes_written += len(SETTINGS)
        else:
            if matches(target, record):
                method = 'existing_owned_verified'
            else:
                source = verified_sources.get(relative)
                if source is None or not matches(source, record):
                    installed = INSTALLED.joinpath(*PurePosixPath(relative).parts)
                    source = installed if matches(installed, record) else None
                if source is not None:
                    immutable = hardlinks and target.suffix.lower() in IMMUTABLE
                    if immutable:
                        try:
                            replace_private(target, source=source, hardlink=True)
                            method = 'verified_asset_hardlink'
                        except OSError:
                            replace_private(target, source=source)
                            method = 'verified_source_copy'
                            bytes_written += record['size']
                    else:
                        replace_private(target, source=source)
                        method = 'verified_source_copy'
                        bytes_written += record['size']
                else:
                    replace_private(target, data=download(record))
                    method = 'public_https_blob'
                    bytes_written += record['size']
                if not matches(target, record):
                    raise ValueError('Prepared file differs from the public manifest: '+relative)
            verified_sources[relative] = target
            actual_sha, actual_size = record['sha256'], record['size']
        counts[method] += 1
        rows.append(dict(path=relative, method=method, published_sha256=record['sha256'],
                         published_size=record['size'], qa_sha256=actual_sha, qa_size=actual_size))
        if index % 500 == 0:
            print(json.dumps(dict(progress=root.name, verified=index, total=len(records))), flush=True)
    # Re-read every completed resource: two configs are the sole explicit local
    # overrides, with their own expected bytes; every other file must match the
    # actual published size and SHA.
    for record in records:
        target = checked_target(root, record['path'])
        if record['path'].lower() in CONFIGS:
            if target.read_bytes() != SETTINGS:
                raise ValueError('Fresh QA config changed')
        elif not matches(target, record):
            raise ValueError('Final QA resource verification failed: '+record['path'])
    guards = static_guards(root)
    proof = dict(schema=1, creator=CREATOR, manifest_url=ORIGIN+'manifest.json',
                 manifest_version=manifest['version'], manifest_sha256=manifest_sha,
                 prepared_utc=datetime.now(timezone.utc).isoformat(), game_root=str(root),
                 manifest_files=len(records), non_config_files_verified=len(records)-len(CONFIGS),
                 methods=dict(counts), estimated_bytes_written=bytes_written,
                 independent_seed_configs=sorted(CONFIGS), removed_owned_files=removed,
                 managed_paths=sorted(wanted), native_pins={name:digest(root/name) for name in HASHES},
                 static_guard_functions=len(guards), graphical_clients_started=0,
                 personal_files_copied=0, accounts_created=0, files=rows)
    (root/PROOF).write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return proof


def prepare(copies=('a', 'b'), *, hardlinks=True):
    with urllib.request.urlopen(ORIGIN+'manifest.json', timeout=25) as response:
        raw = response.read(8*1024*1024+1)
    if len(raw) > 8*1024*1024:
        raise ValueError('Public client manifest exceeds its size limit')
    manifest = json.loads(raw)
    records = validate_manifest(manifest)
    verified = {}
    proofs = [prepare_copy(QA_BASE/('game-'+copy), manifest, records,
                           hashlib.sha256(raw).hexdigest(), verified, hardlinks=hardlinks)
              for copy in copies]
    result = dict(manifest_url=ORIGIN+'manifest.json', client_version=manifest['version'],
                  manifest_sha256=hashlib.sha256(raw).hexdigest(),
                  copies=[{key: proof[key] for key in ('game_root', 'manifest_files', 'methods',
                          'estimated_bytes_written', 'static_guard_functions')} for proof in proofs],
                  graphical_clients_started=0, personal_files_copied=0, accounts_created=0)
    QA_BASE.mkdir(parents=True, exist_ok=True)
    (QA_BASE/'prepared-copies.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copies', choices=('a', 'b'), nargs='+', default=('a', 'b'))
    parser.add_argument('--no-hardlinks', action='store_true')
    args = parser.parse_args()
    if len(args.copies) != len(set(args.copies)):
        parser.error('Do not prepare the same QA copy twice')
    prepare(tuple(args.copies), hardlinks=not args.no_hardlinks)
