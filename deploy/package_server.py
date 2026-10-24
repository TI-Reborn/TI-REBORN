"""Build a source deployment bundle; never include saves or captured binaries."""
import argparse
from pathlib import Path
import tarfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.runtime import RUNTIME_ASSETS, RUNTIME_TOOLS


def package(output):
    files = list((ROOT / 'tio').rglob('*.py')) + list((ROOT / 'server').rglob('*.py'))
    files += list((ROOT / 'config').glob('*.json')) + [ROOT / 'config/server.toml']
    files += [ROOT / 'tools' / (name + '.py') for name in RUNTIME_TOOLS]
    files += [ROOT / 'evidence' / name for name in RUNTIME_ASSETS]
    files += list((ROOT / 'deploy').glob('*.py'))
    files += list((ROOT / 'deploy').glob('*.service'))
    files += list((ROOT / 'deploy').glob('*.timer'))
    files += [ROOT / 'deploy/BACKUPS.md', ROOT / 'MULTIPLAYER.md', ROOT / 'TEAM_LOBBIES.md', ROOT / 'CITY_SOCIAL.md', ROOT / 'SURVIVAL_MULTIPLAYER.md']
    files += [ROOT / name for name in ('requirements.txt', 'SERVER_AUDIT.md',
        'DEPLOY.md', 'CLIENT_CONNECTION.md', 'deploy/FIREWALL.md', 'deploy/tio-server.service')]
    # Validate before creating the archive. Refuse accidental overwrite.
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    with Path(output).open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for path in sorted(set(files)):
            info = archive.gettarinfo(str(path), arcname=path.relative_to(ROOT).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mode = 0o644
            with path.open('rb') as source:
                archive.addfile(info, source)
    print(f'Created {output}: {len(set(files))} runtime/documentation files; no player data')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    package(parser.parse_args().output)
