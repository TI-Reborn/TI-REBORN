"""Read listener and certificate metadata only; never read private keys."""
from pathlib import Path
import json
import shlex
import subprocess


def main():
    code=r'''import re,json,subprocess,pathlib
config=chr(10).join(p.read_text() for p in pathlib.Path('/etc/nginx/sites-enabled').glob('*') if p.is_file())
certs=list(dict.fromkeys(re.findall(r'ssl_certificate\s+([^;]+);',config)))
metadata={}
for path in certs:
 p=subprocess.run(['openssl','x509','-in',path,'-noout','-dates','-ext','subjectAltName'],capture_output=True,text=True,check=True)
 metadata[path]=p.stdout.strip()
print(json.dumps(dict(listeners=subprocess.run(['ss','-ltn'],capture_output=True,text=True,check=True).stdout,
 certificates=metadata,cpus=subprocess.run(['nproc'],capture_output=True,text=True,check=True).stdout.strip())))'''
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
        'root@185.184.42.88','python3 -c '+shlex.quote(code)],capture_output=True,text=True,check=True,timeout=30)
    folder=Path(__file__).resolve().parents[1]/'reports/stage2-admission-capacity'
    data=json.loads(result.stdout);(folder/'tls-readiness.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data,indent=2))


if __name__=='__main__':main()
