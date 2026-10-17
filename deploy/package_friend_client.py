"""Package the installed client with a simple launcher and no saved credentials."""
import argparse
import hashlib
from ipaddress import IPv4Address
from pathlib import Path
import zipfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from deploy.client_russian_encoding import patch as patch_russian_encoding


def package(source, output, host):
    host = str(IPv4Address(host))
    source = Path(source).resolve()
    output = Path(output).resolve()
    required = ('ti.exe', 'orange.dll', 'silver.dll', 'gold.dll', 'base/config.cfg')
    for name in required:
        if not (source / name).is_file():
            raise FileNotFoundError(source / name)
    if output.is_relative_to(source):
        raise ValueError('Output must be outside the installed client')
    output.parent.mkdir(parents=True, exist_ok=True)
    root_files = {'ti.exe', 'orange.dll', 'silver.dll', 'gold.dll', 'ode.dll', 'd3dx9_26.dll'}
    files = [p for p in source.rglob('*') if p.is_file() and
             (p.relative_to(source).parts[0] == 'base' or p.name in root_files)]
    files = [p for p in files if p.name.lower() != 'login.ini' and
             not p.name.lower().startswith('notes-') and
             p.suffix.lower() not in {'.log', '.bak', '.dmp'}]
    overrides = {
        'orange_addr': host, 'orange_port': '28512',
        'cl_lastlogin': '', 'cl_lastpass': '', 'orange_login': '',
        'orange_plogin': '', 'orange_pchar': '', 'name': '',
    }
    # Latin-1 round-trips untouched bytes even for the original legacy encoding.
    lines = (source / 'base/config.cfg').read_bytes().decode('latin-1').splitlines()
    clean = [line for line in lines if not line.split() or line.split()[0] not in overrides]
    clean.extend(f'{key} {value}' for key, value in overrides.items())
    config = ('\r\n'.join(clean) + '\r\n').encode('latin-1')
    launcher = ('@echo off\r\nsetlocal\r\n'
                'cd /d "%~dp0"\r\n'
                'if not exist "%~dp0ti.exe" (\r\n'
                '  echo Extract the entire ZIP before launching the game.\r\n'
                '  pause\r\n  exit /b 1\r\n)\r\n'
                'start "" /D "%~dp0" "%~dp0ti.exe"\r\n')
    readme = f'''TIO — подключение к частному серверу

1. Распакуй ВЕСЬ архив в отдельную папку, например C:\\Games\\TIO-Friend.
2. Открой Launcher.cmd. Игра запускается из своей папки.
3. В окне игры введи логин player_two и пароль, полученный от владельца сервера.

Адрес {host} и порт 28512 уже настроены. Python устанавливать не нужно.
Паролей в архиве нет. Не запускай игру прямо из ZIP.
Если уже открыта другая копия игры, сначала закрой её.

Владелец сервера должен открыть TCP 28512 и 28513 для внешних подключений.
После этого сообщать свой IP не требуется. Самостоятельной регистрации пока нет:
каждому игроку владелец создаёт отдельный аккаунт и выдаёт пароль.
probe_user — аккаунт владельца. Одновременно два входа под одним логином запрещены.
На этом этапе игроки имеют отдельные сессии; общих PvP-боёв пока нет.
'''
    hashes = {}
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            relative = path.relative_to(source).as_posix()
            if relative == 'base/config.cfg':
                data = config
            elif relative == 'base/autoexec.cfg':
                data = f'orange_addr {host}\r\norange_port 28512\r\n'.encode('ascii')
            elif relative == 'silver.dll':
                data = patch_russian_encoding(path.read_bytes())
            else:
                data = path.read_bytes()
            archive.writestr('TIO-Friend/' + relative, data)
            if path.suffix.lower() in {'.exe', '.dll'}:
                hashes[relative] = hashlib.sha256(data).digest()
        archive.writestr('TIO-Friend/Launcher.cmd', launcher.encode('ascii'))
        archive.writestr('TIO-Friend/README.txt', readme.encode('utf-8-sig'))
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert not any(n.lower().endswith('/login.ini') for n in archive.namelist())
        for relative, digest in hashes.items():
            expected=(source / relative).read_bytes()
            if relative=='silver.dll':expected=patch_russian_encoding(expected)
            assert hashlib.sha256(expected).digest() == digest
        assert archive.read('TIO-Friend/base/config.cfg') == config
    print(f'Created and CRC-verified: {output} ({output.stat().st_size:,} bytes)')
    print(f'Game binaries verified: {len(hashes)}; silver.dll Russian encoding fix applied; saved credentials excluded.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(r'C:\Program Files (x86)\TIOnline'))
    parser.add_argument('--host', default='185.184.42.88')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    package(args.source, args.output, args.host)
