"""Read-only inventory of duplicate static payloads in old hosted rollback copies."""
import hashlib
import json
import os
from pathlib import Path
import stat
import time


def fingerprint(p):
    s = p.lstat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_uid, s.st_gid,
            s.st_mtime_ns, s.st_ctime_ns, s.st_nlink]


def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        while b := f.read(1024 * 1024):
            h.update(b)
    return h.hexdigest()


def main():
    os.nice(10)
    cutoff = time.time() - 86400
    candidates = {}
    for directory in sorted(Path('/root').glob('tio-before-*')):
        if directory.is_symlink() or not directory.is_dir():
            continue
        for p in directory.rglob('*'):
            s = p.lstat()
            if (not stat.S_ISREG(s.st_mode) or s.st_size < 5 * 1024**2
                    or s.st_nlink != 1 or s.st_mtime > cutoff
                    or p.suffix.lower() not in ('.exe', '.dll', '.zip', '.gz')
                    or p.resolve() != p or os.listxattr(p)):
                continue
            candidates.setdefault((s.st_size, s.st_mode, s.st_uid, s.st_gid), []).append(p)
    groups = []
    for paths in candidates.values():
        if len(paths) < 2:
            continue
        by_hash = {}
        for p in paths:
            before = fingerprint(p)
            sha = digest(p)
            assert fingerprint(p) == before, 'Backup changed while hashing'
            by_hash.setdefault(sha, []).append({'path': str(p), 'stat': before})
        for sha, files in by_hash.items():
            if len(files) > 1:
                groups.append({'sha256': sha, 'files': files})
    report = {'created': time.time(), 'groups': groups,
              'reclaimable_bytes': sum((len(g['files'])-1)*g['files'][0]['stat'][2] for g in groups),
              'note': 'Hardlinks retain bytes, paths, ownership and mode. Original per-path timestamps are recorded here.'}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
