"""Upload the reviewed client overlay, verify the hosted candidate, then deploy."""
from reservation_texture_assets import *
import tarfile

def main():
    release=json.loads((OUT/'client-release/manifest.json').read_text(encoding='utf-8'))
    assert release['version']=='2026.10.06.3'
    assert json.loads((OUT/'asset-verification.json').read_text())['passed']
    tests=OUT/'tests.tar.gz'
    with tarfile.open(tests,'w:gz') as tar:
        for name in ('test_reservation_visuals.py','test_map_generation.py','test_cities.py','test_shared_team_arena.py'):
            tar.add(ROOT/'tests'/name,arcname='tests/'+name)
    scp=['scp','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10']
    for local,name in ((OUT/'patch.tar.gz','tio-reservation-textures-patch.tar.gz'),
                       (tests,'tio-reservation-textures-tests.tar.gz'),
                       (ROOT/'tools/verify_reservation_candidate_remote.py','verify_reservation_candidate_remote.py'),
                       (ROOT/'tools/deploy_reservation_remote.py','deploy_reservation_remote.py')):
        subprocess.run(scp+[str(local),'root@185.184.42.88:/root/'+name],check=True)
    for name,report in (('verify_reservation_candidate_remote.py','hosted-candidate'),
                        ('deploy_reservation_remote.py','deployment')):
        p=subprocess.run(SSH+['python3 /root/'+name],capture_output=True,text=True,encoding='utf-8')
        (OUT/(report+'.log')).write_text(p.stdout+p.stderr,encoding='utf-8')
        if p.returncode:raise RuntimeError(p.stdout+p.stderr)
        result=json.loads(p.stdout.strip().splitlines()[-1])
        (OUT/(report+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result),flush=True)

if __name__=='__main__':main()
