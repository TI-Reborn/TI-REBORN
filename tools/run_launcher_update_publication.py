"""Stage and publish a tested launcher using a fresh hosted backup, via SSH."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def validated_identity(version,digest,size):
    if not isinstance(version,str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)',version):
        raise ValueError('Expected a three-part numeric launcher version')
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or type(size) is not int or not 1024*1024<=size<=200*1024*1024:
        raise ValueError('Expected a pinned launcher hash and bounded size')
    return {'version':version,'sha256':digest,'size':size}


def backup_identity(report):
    before=report['publication_baseline'];launcher=before['launcher'];row=before['metadata']['row']
    baseline=validated_identity(row['launcherVersion'],launcher['sha256'],launcher['bytes'])
    if (row['launcherUrl']!='/downloads/TIO-Launcher-'+baseline['version']+'.exe'
            or row['fileSizeBytes']!=baseline['size'] or launcher.get('mode')!=0o644
            or launcher.get('uid')!=0 or launcher.get('gid')!=0):
        raise ValueError('Fresh backup launcher and public metadata disagree')
    if report.get('sqlite_integrity')!='ok' or report.get('website_full_isolated_restore') is not True:
        raise ValueError('A verified fresh database backup is required')
    return baseline


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--backup-report', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--version', default='0.1.5')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if args.candidate.is_symlink():raise ValueError('Expected a regular candidate executable')
    candidate = args.candidate.resolve(strict=True)
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError('Expected a regular candidate executable')
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    size = candidate.stat().st_size
    backup_raw=args.backup_report.read_bytes()
    backup_report=json.loads(backup_raw);backup=backup_report['backup'];baseline=backup_identity(backup_report)
    validated_identity(args.version,digest,size)
    if tuple(map(int,args.version.split('.'))) <= tuple(map(int,baseline['version'].split('.'))):
        raise ValueError('New version must be newer than the fresh backup baseline')
    source_path = ROOT / 'tools/publish_launcher_update_remote.py'
    source = source_path.read_text(encoding='utf-8').replace('\r\n', '\n')
    ast.parse(source)
    version = args.version
    remote = '/root/TIO-Launcher-' + version + '-' + digest[:12] + '.exe'
    action = 'apply' if args.apply else 'inspect'
    report_path = args.reports / ('publication-' + action + '.json')
    if report_path.exists() or report_path.is_symlink():
        raise FileExistsError(report_path)
    args.reports.mkdir(parents=True, exist_ok=True)
    ssh_options = ['-i', str(Path.home() / '.ssh/tio_server'), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15']
    source_snapshot=args.reports/'publication-source.py'
    package_path=args.reports/'publication-package.json'
    if not args.apply:
        if source_snapshot.exists() or source_snapshot.is_symlink() or package_path.exists() or package_path.is_symlink():
            raise FileExistsError('Refusing to replace a publication package or its source snapshot')
        with source_snapshot.open('x',encoding='utf-8',newline='\n') as output:output.write(source)
        package = {'version': version, 'candidate': str(candidate), 'sha256': digest, 'size': size,
                   'remote_candidate': remote, 'backup': backup, 'baseline':baseline,
                   'backup_report_sha256':hashlib.sha256(backup_raw).hexdigest(),
                   'publisher_source':str(source_snapshot.resolve()),'publisher_sha256': hashlib.sha256(source.encode()).hexdigest()}
        with package_path.open('x', encoding='utf-8') as output:
            json.dump(package, output, indent=2)
        result = subprocess.run(['scp', *ssh_options, str(candidate), 'root@185.184.42.88:' + remote], capture_output=True)
        if result.returncode:
            raise RuntimeError('Candidate transfer failed; private output suppressed')
    else:
        if package_path.is_symlink() or source_snapshot.is_symlink():raise ValueError('Publication package symlinks are forbidden')
        package = json.loads(package_path.read_text())
        snapshot_source=source_snapshot.read_text(encoding='utf-8').replace('\r\n','\n')
        if (package['sha256'] != digest or package['size'] != size or package['backup'] != backup
                or package.get('version')!=version or package.get('baseline')!=baseline
                or package.get('candidate')!=str(candidate) or package.get('remote_candidate')!=remote
                or package.get('backup_report_sha256')!=hashlib.sha256(backup_raw).hexdigest()
                or package.get('publisher_source')!=str(source_snapshot.resolve())
                or package['publisher_sha256'] != hashlib.sha256(source.encode()).hexdigest()
                or package['publisher_sha256'] != hashlib.sha256(snapshot_source.encode()).hexdigest()):
            raise ValueError('Candidate, version, baseline, backup or publisher snapshot changed after inspection')
        source=snapshot_source
    arguments = ['launcher-update', '--' + action, '--backup', backup, '--candidate', remote,
                 '--version', version, '--sha256', digest, '--bytes', str(size),
                 '--baseline-version',baseline['version'],'--baseline-sha256',baseline['sha256'],'--baseline-bytes',str(baseline['size'])]
    stdin = 'import sys\nsys.argv=' + repr(arguments) + '\nexec(compile(' + repr(source) + ", 'launcher-update-publication', 'exec'), {'__name__':'__main__'})\n"
    result = subprocess.run(['ssh', *ssh_options, 'root@185.184.42.88', '/usr/bin/python3 -'],
                            input=stdin, text=True, capture_output=True)
    if result.returncode:
        # The publisher's final exception is intentionally sanitized.
        error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'No remote diagnostic'
        raise RuntimeError('Launcher ' + action + ' failed: ' + error)
    data = json.loads(result.stdout)
    with report_path.open('x', encoding='utf-8') as output:
        json.dump(data, output, indent=2)
    print(json.dumps({'action': action, 'version': version, 'sha256': digest, 'size': size,
                      'baseline':baseline,
                      'report': str(report_path.resolve()), 'backup': backup,
                      'journal': data.get('journal'), 'service_restarts': data.get('service_restarts')}))


if __name__ == '__main__':
    main()
