"""Resume the already extracted, pinned legal-page release without uploading it.

The original deployment workflow remains unchanged on disk. Its archive
extraction is replaced by a complete byte comparison with the accepted local
artifact. Its process output uses a pipe drained into the same private root log,
and cleanup terminates the owned preflight process group even after early exit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from tools import deploy_portal_stage3_remote as original


ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'reports/user-agreement-20261012'
ORIGINAL_SHA = '7ddbaf889d989db5a3895b434b93785208860bf17f64c2735c646960929d6327'
ARCHIVE_SHA = 'a9eac1ffed59eb3eb1c4fc61d5bc93138ebd8f4eff0e116555c766d24aa5b186'
CANONICAL_SHA = '0deaddc280cbcafc25bab83e4a28dc5af045e8c7b878579dd23c22bfcce04484'
INVENTORY_SHA = '6f3121253517f80f36f8e89222f192cd8fa797fb7a4f053cc029c1d08316e5a4'

VERIFY_EXISTING = r'''
target=Path('/opt/tio-portal/releases/tireborn-20261012-user-agreement')
if current.resolve(strict=True)==target:raise RuntimeError('Release is already active')
if target.is_symlink() or target.resolve(strict=True)!=target:raise RuntimeError('Unexpected candidate path')
minimum_free=200*1024*1024
def storage_ready():
    stat=os.statvfs('/')
    if stat.f_bavail*stat.f_frsize<minimum_free:raise RuntimeError('Insufficient nonroot free space for portal activation')
    return stat.f_bavail*stat.f_frsize
free_before=storage_ready()
expected=configuration['inventory']['regular_files']
for relative,row in expected.items():
    parts=Path(relative).parts
    if relative.startswith('/') or '..' in parts:raise RuntimeError('Unsafe qualified inventory path')
    path=target/relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(target):raise RuntimeError('Qualified release member missing or replaced')
    if path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Qualified release file changed')
allowed_logs={
    'preflight-private.log','preflight-recheck-private.log',
    'preflight-health-diagnostic-private.log','preflight-pipe-private.log',
    'node-stdio-root-private.log','node-stdio-tio-web-private.log',
    'node-root-file-combined-private.log','node-runuser-file-combined-private.log',
    'node-runuser-files-separate-private.log','node-runuser-files-separate-stderr-private.log',
    'echo-runuser-file-combined-private.log',
}
for folder,dirs,files in os.walk(target,followlinks=False):
    for name in dirs+files:
        path=Path(folder)/name;relative=path.relative_to(target).as_posix()
        if path.is_symlink():
            if relative!='.next-agreement-polish/cache' or path.resolve()!=target/'.next/cache':raise RuntimeError('Unexpected candidate link')
        elif path.is_file() and relative not in expected:
            if relative not in allowed_logs and not relative.startswith('.next/cache/'):raise RuntimeError('Unexpected candidate file')
if not (target/'.next-agreement-polish/cache').is_symlink():raise RuntimeError('Missing inspected cache link')
if len(expected)!=19919:raise RuntimeError('Qualified inventory count mismatch')
'''

PIPE_START = '''    process=subprocess.Popen(['runuser','-u','tio-web','--','/opt/tio-node/bin/node','server.js'],cwd=target,
        env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    reader_errors=[]
    def drain_output():
        try:
            for chunk in iter(lambda:process.stdout.read(65536),b''):
                output.write(chunk);output.flush()
        except BaseException as error:
            reader_errors.append(type(error).__name__)
    reader=threading.Thread(target=drain_output,daemon=True);reader.start()
'''

PIPE_FINISH = '''    finally:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait(5)
        reader.join(5)
        if reader.is_alive() or reader_errors:raise RuntimeError('Private preflight output cleanup failed')
'''


def remote_source():
    path = ROOT / 'tools/deploy_portal_stage3_remote.py'
    if hashlib.sha256(path.read_bytes()).hexdigest() != ORIGINAL_SHA:
        raise RuntimeError('Original deployment workflow changed')
    source = original.REMOTE
    begin = source.index("archive=Path(configuration['archive'])")
    end = source.index('# Verify the complete Linux release')
    source = source[:begin] + VERIFY_EXISTING + '\n' + source[end:]
    source = source.replace('import hashlib,json,os,posixpath,pwd,grp,subprocess,tarfile,time,urllib.request,shlex,signal',
                            'import hashlib,json,os,posixpath,pwd,grp,subprocess,tarfile,time,urllib.request,shlex,signal,threading', 1)
    source = source.replace("log=target/'preflight-private.log'", "log=target/'preflight-resume-private.log'", 1)
    old_start = """    process=subprocess.Popen(['runuser','-u','tio-web','--','/opt/tio-node/bin/node','server.js'],cwd=target,
        env=environment,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
"""
    old_finish = """    finally:
        if process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(5)
            except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(5)
"""
    if source.count(old_start) != 1 or source.count(old_finish) != 1:
        raise RuntimeError('Original preflight shape changed')
    source = source.replace(old_start, PIPE_START, 1).replace(old_finish, PIPE_FINISH, 1)
    source = source.replace('point(target)\ntry:', 'free_before_activation=storage_ready()\npoint(target)\ntry:', 1)
    source = source.replace('print(json.dumps(result))', '''result.update(resumed_existing_qualified_release=True,archive_uploaded=False,archive_extracted=False,
    qualified_regular_files_verified=len(expected),preflight_stdio='pipe-drained-to-root-private-log',
    preflight_process_group_cleanup_verified=True,nonroot_free_before_bytes=free_before,
    nonroot_free_before_activation_bytes=free_before_activation,
    original_deployment_workflow_sha256=configuration['original_workflow_sha256'],
    resume_workflow_sha256=configuration['resume_workflow_sha256'],
    qualified_inventory_sha256=configuration['inventory_sha256'])
print(json.dumps(result))''', 1)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Preserve the existing deployment report')
    inventory_path = FOLDER / 'portal-qualified-file-inventory.json'
    if hashlib.sha256(inventory_path.read_bytes()).hexdigest() != INVENTORY_SHA:
        raise RuntimeError('Qualified inventory changed')
    inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    archive = Path(inventory['archive_absolute_path'])
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise RuntimeError('Accepted local archive changed')
    if hashlib.sha256((ROOT / 'web/src/lib/user-agreement.json').read_bytes()).hexdigest() != CANONICAL_SHA:
        raise RuntimeError('Accepted agreement changed')
    prior = json.loads((FOLDER / 'portal-predeployment-backup.json').read_text(encoding='utf-8'))
    if prior['backup'] != '/root/tio-before-site-backups-sii8l1mz':
        raise RuntimeError('Unexpected rollback backup')
    configuration = {'backup': prior['backup'], 'previous_release': prior['previous_portal_release'],
                     'sha256': ARCHIVE_SHA, 'release_id': 'tireborn-20261012-user-agreement',
                     'dist_dir': '.next-agreement-polish', 'inventory': inventory,
                     'inventory_sha256': INVENTORY_SHA, 'original_workflow_sha256': ORIGINAL_SHA,
                     'resume_workflow_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    script = remote_source().replace('CONFIGURATION', repr(configuration), 1)
    compile(script, '<qualified-portal-resume>', 'exec')
    result = subprocess.run(['ssh', '-i', str(Path.home() / '.ssh/tio_server'), '-o', 'BatchMode=yes',
                             '-o', 'ConnectTimeout=15', 'root@185.184.42.88', 'python3 -'],
                            input=script, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Qualified portal resume failed; current code-only rollback and private diagnostics are retained')
    data = json.loads(result.stdout)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(data))


if __name__ == '__main__':
    main()
