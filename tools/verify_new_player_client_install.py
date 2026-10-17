"""Read-only size/SHA256 verification of a launcher-installed client.

Only existing regular base/config.cfg and base/autoexec.cfg may differ when
explicitly marked seed=true in the manifest. Missing seeds still fail. This
matches the launcher rule: preserve existing personal configuration, create
the published seed if absent. No client files or server state are changed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports/new-player'
SEEDS = {'base/config.cfg', 'base/autoexec.cfg'}
BINARIES = {'ti.exe', 'silver.dll', 'orange.dll', 'gold.dll', 'ode.dll', 'd3dx9_26.dll'}


def manifest_records(value):
    """Accept release files/records, optional known wrappers, or a record map."""
    current = value
    version = None
    wrappers = []
    for _ in range(6):
        if isinstance(current, list):
            return current, version, wrappers
        if not isinstance(current, dict):
            raise ValueError('Manifest must contain a file record list or map')
        if 'schema' in current and current['schema'] != 1:
            raise ValueError('Unsupported release schema')
        version = current.get('version', version)
        keys = [key for key in ('files', 'records', 'manifest', 'release', 'client_manifest')
                if isinstance(current.get(key), (dict, list))]
        if keys:
            if len(keys) != 1:
                raise ValueError('Ambiguous manifest record wrappers')
            wrappers.append(keys[0]); current = current[keys[0]]
            continue
        if current and all(isinstance(row, dict) and 'size' in row and 'sha256' in row for row in current.values()):
            records = []
            for name, row in current.items():
                if row.get('path', name) != name:
                    raise ValueError('Manifest record-map path differs from its key')
                records.append(dict(row, path=name))
            return records, version, wrappers + ['path-map']
        raise ValueError('Manifest file records not found')
    raise ValueError('Manifest nesting exceeds the limit')


def validate_records(records):
    if not 1 <= len(records) <= 20000:
        raise ValueError('Unexpected manifest record count')
    seen = set()
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str):
            raise ValueError('Missing manifest file path')
        name = row['path']; normalized = name.lower(); parts = name.split('/')
        if (any(not re.fullmatch(r'[A-Za-z0-9_ .()\-]+', part) or part in ('.', '..') or
                part.endswith(('.', ' ')) or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)', part, re.I)
                for part in parts) or not (normalized in BINARIES or len(parts) > 1 and parts[0] == 'base') or
                normalized in seen or type(row.get('size')) is not int or not 0 <= row['size'] <= 512*1024*1024 or
                not isinstance(row.get('sha256'), str) or re.fullmatch(r'[a-f0-9]{64}', row['sha256']) is None or
                type(row.get('seed', False)) is not bool):
            raise ValueError('Invalid or duplicate manifest file record')
        leaf = parts[-1].lower()
        if (leaf == 'login.ini' or leaf.startswith('notes-') or leaf == 'skillbar.dat' or
                leaf.endswith(('.log', '.bak')) or (normalized in SEEDS) != row.get('seed', False)):
            raise ValueError('Only the two launcher seed configurations may be preserved')
        seen.add(normalized)
    if not BINARIES <= seen:
        raise ValueError('Manifest lacks required client binaries')


def ordinary(path):
    attributes = path.lstat()
    if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
        raise ValueError('Client path contains a link/reparse point')
    return attributes


def inspect_file(game_root, row):
    target = game_root.joinpath(*row['path'].split('/'))
    result = {'path':row['path'], 'seed':row.get('seed', False),
              'expected_size':row['size'], 'expected_sha256':row['sha256']}
    try:
        current = target
        while current != game_root:
            ordinary(current); current = current.parent
        before = ordinary(target)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Manifest target is not a regular file')
        if not target.resolve(strict=True).is_relative_to(game_root):
            raise ValueError('Manifest target escaped the client directory')
        digest = hashlib.sha256()
        with target.open('rb') as source:
            for chunk in iter(lambda:source.read(1024*1024), b''):
                digest.update(chunk)
        after = ordinary(target)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('File changed during verification')
        result.update(actual_size=after.st_size, actual_sha256=digest.hexdigest())
        matches = after.st_size == row['size'] and digest.hexdigest() == row['sha256']
        result['status'] = 'exact' if matches else 'allowed_seed_difference' if row.get('seed', False) else 'mismatch'
    except FileNotFoundError:
        result['status'] = 'missing'
    except (OSError, ValueError) as error:
        result.update(status='error', error_type=type(error).__name__)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=REPORTS/'public-manifest.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    game_root = args.game_root.absolute()
    if args.output.is_symlink() or not output.is_relative_to(REPORTS.resolve()) or output.suffix != '.json' or output.exists():
        raise ValueError('Use a fresh JSON report path within reports/new-player')
    if output.is_relative_to(game_root.resolve()):
        raise ValueError('The report must be outside the read-only client directory')
    ordinary(game_root); game_root = game_root.resolve(strict=True)
    if not game_root.is_dir():
        raise ValueError('Client directory does not exist')
    manifest = args.manifest.read_bytes()
    rows, version, wrappers = manifest_records(json.loads(manifest.decode('utf-8-sig')))
    validate_records(rows)
    files = [inspect_file(game_root, row) for row in rows]
    counts = {status:sum(row['status'] == status for row in files)
              for status in ('exact', 'allowed_seed_difference', 'mismatch', 'missing', 'error')}
    passed = not any(counts[key] for key in ('mismatch', 'missing', 'error'))
    report = {'passed':passed, 'observed_utc':datetime.now(timezone.utc).isoformat(),
        'read_only':True, 'client_writes':0, 'server_connections':0,
        'game_root':str(game_root), 'manifest':str(args.manifest.resolve()),
        'manifest_sha256':hashlib.sha256(manifest).hexdigest(), 'version':version,
        'manifest_wrappers':wrappers, 'file_count':len(rows), 'counts':counts,
        'scope':'Every manifest-listed file was checked for both size and SHA256; files outside the manifest are outside this verification.',
        'seed_policy':{'allowed_paths':sorted(SEEDS),
            'rule':'Only present regular files explicitly marked seed=true at these two paths may differ in size/SHA256. Missing, changed-during-read, linked or other mismatching files fail.',
            'reason':'Launcher preserves existing personal configurations and installs published seeds only when absent.',
            'allowed_differences':[row for row in files if row['status'] == 'allowed_seed_difference']},
        'files':files}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as target:
        target.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'output':str(output), 'passed':passed, 'version':version, 'file_count':len(rows), 'counts':counts}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
