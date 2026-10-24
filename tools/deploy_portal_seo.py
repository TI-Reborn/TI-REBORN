"""Use the established portal release workflow with a complete read-only SEO preflight."""
import hashlib
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.deploy_portal_stage3_remote import REMOTE


PREFLIGHT = '''log=backup/'seo-preflight-private.log'
with log.open('xb') as output:
    log.chmod(0o600)
    process=subprocess.Popen(['runuser','-u','tio-web','--','/opt/tio-node/bin/node','server.js'],cwd=target,
        env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    def drain():
        for chunk in iter(lambda: process.stdout.read(4096), b''):
            output.write(chunk); output.flush()
    reader=threading.Thread(target=drain,daemon=True); reader.start()
    try:
        for attempt in range(25):
            if process.poll() is not None:raise RuntimeError('Release preflight exited; inspect private log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:3002/api/health',timeout=2) as response:data=json.load(response)
                if data.get('status')=='ok':break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('Release preflight health failed')
        import importlib.util
        spec=importlib.util.spec_from_file_location('seo_audit',configuration['audit_script'])
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        report=module.audit('http://127.0.0.1:3002')
        failures=module.check(report)
        (backup/'seo-preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\\n')
        if failures:raise RuntimeError('SEO preflight failed: '+repr(failures))
        preflight_pages=len(report['pages'])
    finally:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL);process.wait(5)
        reader.join(5)
        if reader.is_alive():raise RuntimeError('Preflight output drain did not finish')
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--release-id', default='tireborn-20261018-seo')
    parser.add_argument('--archive', default='portal-seo.tar.gz')
    parser.add_argument('--backup-report', default='backup.json')
    parser.add_argument('--report', default='deployment.json')
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'tireborn-[a-z0-9-]+', args.release_id): parser.error('Invalid release ID')
    if any(Path(value).name != value for value in (args.archive, args.backup_report, args.report)): parser.error('Reports must stay in the task folder')
    folder = Path('reports/seo-20261018')
    prior = json.loads((folder/args.backup_report).read_text(encoding='utf-8'))
    archive = folder/args.archive
    report_path = folder/args.report
    if report_path.exists(): raise RuntimeError('Deployment report already exists')
    release = args.release_id
    token = secrets.token_hex(6)
    remote_archive = '/root/tio-seo-'+token+'.tar.gz'
    remote_audit = '/root/tio-seo-audit-'+token+'.py'
    key = str(Path.home()/'.ssh/tio_server')
    for source, dest in [(archive, remote_archive), (Path('tools/audit_portal_seo.py'), remote_audit)]:
        subprocess.run(['scp','-i',key,'-o','BatchMode=yes',str(source),'root@185.184.42.88:'+dest],check=True,capture_output=True)
    configuration = dict(archive=remote_archive, sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        backup=prior['backup'], previous_release=prior['previous_portal_release'], release_id=release,
        dist_dir='.next-seo-release', audit_script=remote_audit)
    script = REMOTE.replace('configuration=CONFIGURATION', 'configuration='+repr(configuration), 1)
    script = script.replace('import hashlib,json,os,posixpath,pwd,grp,subprocess,tarfile,time,urllib.request,shlex,signal',
        'import hashlib,json,os,posixpath,pwd,grp,subprocess,tarfile,time,urllib.request,shlex,signal,threading', 1)
    start = script.index("log=target/'preflight-private.log'")
    end = script.index('\ndef point(path):', start)
    script = script[:start] + PREFLIGHT + script[end:]
    script = script.replace("'linux_release_preflight':'ok',", "'linux_release_preflight':'ok','seo_preflight_pages':preflight_pages,'seo_failures':[],", 1)
    script = script.replace("current=Path('/opt/tio-portal/current')", "game_before=subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts'],text=True)\ncurrent=Path('/opt/tio-portal/current')", 1)
    script = script.replace('point(target)\ntry:', '''# Preserve old static chunks for clients with the previous page already open.
import shutil
old_config=json.loads((previous/'server.js').read_text().split('const nextConfig = ',1)[1].split('\\n',1)[0])
old_static=previous/old_config['distDir']/'static'
new_static=target/configuration['dist_dir']/'static'
for source in old_static.rglob('*'):
    if source.is_file():
        dest=new_static/source.relative_to(old_static)
        if not dest.exists():dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
point(target)
try:''', 1)
    script = script.replace("print(json.dumps(result))", "result['game_process_unchanged']=game_before==subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts'],text=True)\nprint(json.dumps(result))", 1)
    result = subprocess.run(['ssh','-i',key,'-o','BatchMode=yes','root@185.184.42.88','python3 -'],input=script,text=True,capture_output=True)
    if result.returncode:
        (folder/'deployment-error.log').write_text(result.stderr,encoding='utf-8')
        raise RuntimeError('Deployment failed; see the local deployment-error.log')
    data = json.loads(result.stdout)
    report_path.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data))


if __name__ == '__main__': main()
