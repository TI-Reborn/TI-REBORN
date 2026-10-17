"""One explicit fresh encrypted capture followed by independent local proof."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    reports=ROOT/'reports/site-backups'
    capture_report=reports/'offsite-capture-launcher014.json'
    verify_report=reports/'offsite-verified-launcher014.json'
    if any(path.exists() or path.is_symlink() for path in (capture_report,verify_report)):
        raise FileExistsError('Refusing to replace existing recovery evidence')
    build_sha=hashlib.sha256((ROOT/'web/.next/BUILD_ID').read_bytes()).hexdigest()
    # Child prints only sanitized summary. Its plaintext archive stays in RAM
    # until CurrentUser DPAPI encryption; this adapter never writes plaintext.
    result=subprocess.run([sys.executable,str(ROOT/'tools/offsite_backup_windows.py')],
                          check=True,capture_output=True,text=True)
    capture=json.loads(result.stdout)
    with capture_report.open('x',encoding='utf-8') as output:output.write(json.dumps(capture,indent=2)+'\n')
    print(json.dumps({'capture':capture,'report':str(capture_report)}),flush=True)
    result=subprocess.run([sys.executable,str(ROOT/'tools/verify_launcher_014_offsite.py'),
        '--verify',capture['path'],'--portal-build-sha256',build_sha,'--report',str(verify_report)],
        check=True,capture_output=True,text=True)
    verified=json.loads(result.stdout)
    if verified['bundle_sha256']!=capture['bundle_sha256']:raise ValueError('Independent recovery checksum differs')
    print(json.dumps({'verified':verified,'report':str(verify_report)}),flush=True)


if __name__=='__main__':main()
