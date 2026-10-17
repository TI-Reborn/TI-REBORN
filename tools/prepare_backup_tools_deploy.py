"""Build a reviewable Stage3 backup-tools package locally; never contacts a host."""
from datetime import datetime, timezone
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.deploy_backup_tools_remote import FILES, MAX_BYTES


def remote_script(arguments, *, source=None):
    """A static /usr/bin/python3 - SSH command receives reviewed code via stdin."""
    source = source or (ROOT / 'tools/deploy_backup_tools_remote.py').read_text(encoding='utf-8')
    return ('import sys\nsys.argv=' + repr(['backup-tools-stage3', *arguments]) + '\n'
            + 'exec(compile(' + repr(source) + ", 'reviewed-backup-tools', 'exec'), "
            + "{'__name__':'__main__'})\n")


def prepare(directory, *, root=ROOT, validate_dump=None, now=None):
    directory, root = Path(directory), Path(root)
    if directory.exists() or directory.is_symlink():
        raise FileExistsError(directory)
    if validate_dump is not None and not str(validate_dump).startswith(('/root/', '/var/backups/tio-portal/')):
        raise ValueError('Select a known private remote PostgreSQL dump')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware package time required')
    stamp = now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    raw, records = {}, []
    for name, (target, mode) in FILES.items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing package source')
        contents = path.read_bytes().replace(b'\r\n', b'\n')
        if b'\r' in contents:
            raise ValueError('Unsupported source line endings')
        if name.endswith('.py'):
            ast.parse(contents.decode('utf-8'), filename=name)
        raw[name] = contents
        records.append({'source': name, 'target': target, 'mode': mode,
                        'size': len(contents), 'sha256': hashlib.sha256(contents).hexdigest()})
    manifest = {'schema': 1, 'kind': 'backup-tools-stage3', 'files': records}
    manifest_bytes = (json.dumps(manifest, indent=2) + '\n').encode()
    if sum(len(value) for value in raw.values()) + len(manifest_bytes) > MAX_BYTES:
        raise ValueError('Package size limit exceeded')
    directory.mkdir(parents=True)
    archive_path = directory / 'backup-tools-stage3.tar.gz'
    with tarfile.open(archive_path, mode='w:gz') as archive:
        for name, contents in list(raw.items()) + [('manifest.json', manifest_bytes)]:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(contents), 0o644, int(now.timestamp())
            archive.addfile(info, io.BytesIO(contents))
    archive_sha = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (directory / 'manifest.json').write_bytes(manifest_bytes)
    helper = (root / 'tools/deploy_backup_tools_remote.py').read_text(encoding='utf-8').replace('\r\n', '\n')
    (directory / 'deploy_backup_tools_remote.py').write_text(helper, encoding='utf-8', newline='\n')
    remote_archive = '/root/tio-backup-tools-' + stamp + '.tar.gz'
    inspection = '/root/tio-backup-tools-' + stamp + '-inspection.json'
    installed = '/root/tio-backup-tools-' + stamp + '-installed.json'
    common = ['--archive', remote_archive, '--sha256', archive_sha]
    invocations = {
        'inspect': common + ['--inspect', '--report', inspection],
        'apply': common + ['--apply', '--baseline', inspection, '--report', installed],
    }
    if validate_dump is not None:
        invocations['validate'] = common + ['--validate-dump', str(validate_dump),
                                           '--report', '/root/tio-backup-tools-' + stamp + '-restore.json']
    for name, arguments in invocations.items():
        (directory / (name + '-remote.stdin.py')).write_text(remote_script(arguments, source=helper),
                                                           encoding='utf-8', newline='\n')
    result = {'archive': str(archive_path.resolve()), 'archive_sha256': archive_sha,
              'files': records, 'remote_archive': remote_archive,
              'inspection_report': inspection, 'installation_report': installed,
              'ssh_command': '/usr/bin/python3 -',
              'stdin_scripts': {name: str((directory / (name + '-remote.stdin.py')).resolve())
                                for name in invocations},
              'remote_operations_executed': False}
    (directory / 'package.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate-dump', help='Existing remote private dump for a separately invoked restore drill')
    args = parser.parse_args(argv)
    directory = args.output or ROOT / 'reports/site-backups' / ('backup-tools-package-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    print(json.dumps(prepare(directory, validate_dump=args.validate_dump)))


if __name__ == '__main__':
    main()
