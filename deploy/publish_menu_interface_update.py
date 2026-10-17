"""Publish a prepared UI release and verify its public HTTPS content."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.deploy_menu_interface_remote import read_release, sha, unpack_release, validate_blob

HOST = 'root@185.184.42.88'
URL = 'https://185.184.42.88/updates/'
OPTIONS = ['-i', str(Path.home() / '.ssh/tio_server'), '-o', 'BatchMode=yes',
           '-o', 'ConnectTimeout=10']


def fetch(relative):
    with urllib.request.urlopen(URL + relative, timeout=45) as response:
        return response.read()


def publish(output):
    output = Path(output).resolve(strict=True)
    old, new, before, after, allowed = read_release(output / 'client-release')
    proof = json.loads((output / 'release-verification.json').read_bytes())
    archive = output / 'patch.tar.gz'
    archive_sha = sha(archive.read_bytes())
    if (proof['archive_sha256'] != archive_sha or proof['manifest_sha256'] != sha(new)
            or proof['previous_manifest_sha256'] != sha(old)
            or set(proof['changed_paths']) != allowed):
        raise ValueError('Prepared release differs from its verification record')
    with tempfile.TemporaryDirectory(prefix='tio-ui-package-check-') as temporary:
        packaged_old, packaged_new, _, _, packaged_allowed = unpack_release(
            archive, archive_sha, Path(temporary))
        if packaged_old != old or packaged_new != new or packaged_allowed != allowed:
            raise ValueError('Archive contents differ from the reviewed client release')
    if fetch('manifest.json') != old:
        raise ValueError('Public hosted baseline changed; rebuild against the current manifest')
    script = ROOT / 'tools/deploy_menu_interface_remote.py'
    remote_archive = '/root/tio-menu-interface-' + archive_sha[:16] + '.tar.gz'
    remote_script = '/root/deploy-menu-interface-' + sha(script.read_bytes())[:16] + '.py'
    for local, remote in ((archive, remote_archive), (script, remote_script)):
        subprocess.run(['scp'] + OPTIONS + [str(local), HOST + ':' + remote], check=True)
    command = 'python3 ' + shlex.quote(remote_script) + ' --archive ' + shlex.quote(remote_archive)
    command += ' --expected-archive-sha256 ' + shlex.quote(archive_sha)
    result = subprocess.run(['ssh'] + OPTIONS + [HOST, command], capture_output=True,
                            text=True, encoding='utf-8')
    (output / 'deployment.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    deployment = json.loads(result.stdout.strip().splitlines()[-1])
    (output / 'deployment.json').write_text(json.dumps(deployment, indent=2) + '\n')
    public_manifest = fetch('manifest.json')
    if public_manifest != new:
        raise RuntimeError('Published HTTPS manifest differs from the prepared release')

    def check(name):
        record = after[name]
        raw = fetch('blobs/' + record['sha256'])
        validate_blob(raw, record)
        return dict(path=name, sha256=sha(raw), size=len(raw))

    with ThreadPoolExecutor(max_workers=8) as pool:
        files = list(pool.map(check, sorted(allowed)))
    https = dict(passed=True, version=json.loads(new)['version'], verified_files=len(files),
                 manifest_sha256=sha(public_manifest), files=files)
    (output / 'https-release.json').write_text(json.dumps(https, indent=2) + '\n')
    result = subprocess.run([sys.executable, str(ROOT / 'deploy/check_connection.py'),
                             '--host', '185.184.42.88', '--port', '28512'],
                            capture_output=True, text=True, encoding='utf-8')
    (output / 'transport-verification.log').write_text(result.stdout + result.stderr,
                                                      encoding='utf-8')
    if result.returncode:
        raise RuntimeError('UI release is published, but gameplay transport check failed: '
                           + result.stdout + result.stderr)
    return dict(deployment=deployment, https_verified_files=len(files),
                transport_challenge='PASS', full_game_login_tested=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(publish(args.output)))


if __name__ == '__main__':
    main()
