"""Check tracked/exported files for forbidden state and common secret formats.

This is a deterministic guard, not an exhaustive secret/security audit.
Reports filenames and line numbers only, never matched secret values.
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_EVIDENCE = {'items_diagnostic.xml', 'skills_diagnostic.xml',
                    'zones_diagnostic.xml', 'customization_diagnostic.xml', 'owned_pet_trial.json'}
FORBIDDEN_DIRS = {'data', '.secrets', 'reports', 'work', 'output', 'backups',
                  'node_modules', '__pycache__', '.venv', 'venv'}
FORBIDDEN_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.pem', '.key', '.pfx', '.p12',
                      '.dump', '.exe', '.dll', '.bin', '.zip', '.gz', '.pyc', '.log'}
PATTERNS = {
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'github-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'aws-access-key': re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    'credential-url': re.compile(r'\b(?:postgres(?:ql)?|mysql|https?)://[^\s/:]+:[^\s/@]+@'),
}


def check():
    if (ROOT / '.git').exists():
        result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, check=True, capture_output=True)
        paths = [ROOT / p.decode('utf-8') for p in result.stdout.split(b'\0') if p]
    else:
        paths = [p for p in ROOT.rglob('*') if p.is_file()
                 and not set(p.relative_to(ROOT).parts) & {'__pycache__', '.venv', '.git'}]
    if not paths:
        raise RuntimeError('No files selected; stage the prepared snapshot first')
    problems = []
    for path in paths:
        rel = path.relative_to(ROOT)
        if (set(rel.parts) & FORBIDDEN_DIRS or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or path.name.startswith('.env') or path.name.endswith('.local.toml')
            or '.sqlite3-' in path.name or '.db-' in path.name
            or (rel.parts[0] == 'evidence' and path.name not in ALLOWED_EVIDENCE)):
            problems.append(f'{rel.as_posix()}: forbidden state/file type')
            continue
        if path.is_symlink():
            problems.append(f'{rel.as_posix()}: symbolic link')
            continue
        raw = path.read_bytes()
        if raw.startswith(b'SQLite format 3\x00'):
            problems.append(f'{rel.as_posix()}: SQLite content')
        try:
            value = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            problems.append(f'{rel.as_posix()}: non-UTF8 content needs review')
            continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(value):
                # Reviewed f-string template: generated ephemeral credentials, no literal secret.
                if (label == 'credential-url'
                    and rel.as_posix() == 'tools/test_portal_isolated_postgres.py'
                    and match.group() == 'postgresql://' + '{name}:{password}@'):
                    continue
                line = value.count('\n', 0, match.start()) + 1
                problems.append(f'{rel.as_posix()}:{line}: {label}')
    for problem in problems:
        print(problem)
    print(f'Checked {len(paths)} files; findings: {len(problems)}')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(check())
