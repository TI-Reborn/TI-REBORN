"""Export an explicit source-only snapshot; never copy production state or secrets."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def source_paths(root: Path) -> list[Path]:
    files = set()
    for folder in ('server', 'tio', 'tools', 'tests', 'registration'):
        files.update((root / folder).rglob('*.py'))
    for pattern in ('*.json', '*.xml', '*.toml'):
        files.update((root / 'config').glob(pattern))
    for pattern in ('*.py', '*.service', '*.timer', '*.md', '*.sh', '*.nginx', '*.inc'):
        files.update((root / 'deploy').glob(pattern))
    for folder in ('registration/templates', 'registration/static'):
        files.update(p for p in (root / folder).rglob('*') if p.is_file()
                     and p.suffix in ('.html', '.css', '.js', '.svg'))
    files.update(root.glob('*.md'))
    files.update((root / 'docs').glob('*.md'))
    files.update((root / '.github/workflows').glob('server-checks.yml'))
    files.update(root / name for name in ('pyproject.toml', 'requirements.txt', 'registration/requirements.txt',
                                          'assets/item-icons-hd-v1/manifest.json', 'tools/full_tests_known.json',
                                          'tests/fixtures/game_tls/generate.ps1'))
    tree = ast.parse((root / 'server/runtime.py').read_text(encoding='utf-8-sig'))
    assets = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'RUNTIME_ASSETS' for t in node.targets))
    files.update(root / 'evidence' / name for name in assets)
    return sorted(files)


def build(destination: Path):
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite: {destination}')
    manifest = []
    for source in source_paths(ROOT):
        relative = source.relative_to(ROOT)
        if source.is_symlink() or source.resolve() != source.absolute():
            raise ValueError(f'Unexpected source link: {relative}')
        if not source.is_file():
            raise FileNotFoundError(source)
        content = source.read_bytes()
        manifest.append({'path': relative.as_posix(), 'bytes': len(content),
                         'sha256': hashlib.sha256(content).hexdigest()})
    destination.mkdir(parents=True)
    for item in manifest:
        target = destination / item['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / item['path'], target)
    (destination / 'SOURCE_MANIFEST.json').write_text(json.dumps({
        'description': 'Original source hashes before handoff documentation/metadata changes; not a production attestation.',
        'files': manifest}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'destination': str(destination), 'files': len(manifest),
                      'bytes': sum(i['bytes'] for i in manifest)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    build(parser.parse_args().destination)
