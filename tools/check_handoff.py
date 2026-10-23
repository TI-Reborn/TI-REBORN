"""Check tracked/exported files for forbidden state and common secret formats.

This is a deterministic guard, not an exhaustive secret/security audit.
Reports filenames and line numbers only, never matched secret values.
"""
from pathlib import Path
import re
import hashlib
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


# Reviewed raster assets from the published launcher 0.1.33 source.
REVIEWED_BINARY_ASSETS = {'launcher/Assets/client-menu/background-source.png': '397567f4506d23af30af99639f2ad8d75bac77e9db68823d035dd0ed633716be', 'launcher/Assets/client-menu/gamelogo.png': '8994736275cbf4e990fb8457b7b6ff2495e7d3c5bc3339934414304c443101ae', 'launcher/Assets/client-menu/logo-source.png': '59e15c24a3cb9b9b0849b4a5f7613ebd7a138c1d7cfa6dc402b62c1a5b555d10', 'launcher/Assets/client-menu/mainbg.jpg': 'e66272a329d77ac5a7a784a9eaf36d1d64e41e6e4f33a195530e94ba990f90a0', 'launcher/Assets/tio-launcher.ico': 'bddd284056d9aebd46fb30eaf026ff1fb9d8a5ad0fc049935fd8548fa5ef35c8', 'launcher/Assets/tio-launcher.png': 'de9b1186f24d8bdb1bea853bfe44e75832b614b5ba865a0137a561c565c5bfd5', 'launcher/Assets/wasteland.png': 'f786023d6e6ef2081ec4555f2905e738f100feef37531ba0f2349bb92c991114'}

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
        if (rel.as_posix() in REVIEWED_BINARY_ASSETS
            and hashlib.sha256(raw).hexdigest() == REVIEWED_BINARY_ASSETS[rel.as_posix()]):
            continue
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
