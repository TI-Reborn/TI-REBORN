"""Execute the explicitly reviewed one-time 0.1.4 publication package.

The package fixes the candidate hash, backup and SSH-stdin source. Does not build
or alter the portal; public HTTPS verification is a separate read-only tool.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',type=Path,required=True)
    args=parser.parse_args();package=json.loads((args.package/'package.json').read_text())
    reports=ROOT/'reports/login-incident'
    destinations=[reports/'launcher-014-publication-inspection.json',reports/'launcher-014-publication-receipt.json']
    if any(p.exists() or p.is_symlink() for p in destinations):raise FileExistsError('Refusing to replace publication evidence')
    key=str(Path.home()/'.ssh/tio_server')
    result=subprocess.run(['scp','-i',key,'-o','BatchMode=yes','-o','ConnectTimeout=15',
        package['candidate'],'root@185.184.42.88:'+package['remote_candidate']],capture_output=True)
    if result.returncode:raise RuntimeError('Candidate transfer failed; output suppressed')
    for action,destination in zip(('inspect','apply'),destinations):
        source=Path(package['stdin_scripts'][action]).read_text(encoding='utf-8')
        result=subprocess.run(['ssh','-i',key,'-o','BatchMode=yes','-o','ConnectTimeout=15',
            'root@185.184.42.88','/usr/bin/python3 -'],input=source,text=True,capture_output=True)
        if result.returncode:raise RuntimeError('Publication '+action+' failed; private output suppressed')
        data=json.loads(result.stdout)
        with destination.open('x',encoding='utf-8') as output:output.write(json.dumps(data,indent=2)+'\n')
        print(json.dumps({'action':action,'report':str(destination),'result':data}),flush=True)


if __name__=='__main__':main()
