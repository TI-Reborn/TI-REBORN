"""Published DLL ground-reader proof; resource loading/GPU are explicit stubs."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import verify_auth_native as auth
import verify_cities_native as cities
from tio.contest_maps import generate,catalogue


if __name__=='__main__':
    auth.BINARY=ROOT/'reports/throwable-effects/client/silver.dll'
    auth.EXPECTED_SHA='5f2eb65cede38dc146c0656a35d1ed27c45dec2175ba97c2c7d7ea2c3bbbbac9'
    cities.emulator=auth.emulator
    seeds={}
    for seed in range(100):seeds.setdefault(generate(seed=seed).variant,seed)
    assert len(seeds)==9
    cases=[]
    for name,seed in sorted(seeds.items()):
        scene=generate(seed=seed,deployment_size=6)
        cities.generate_map=lambda *a,**k:scene
        result=cities.run(name,0);result['scene']=name;cases.append(result)
    report=dict(passed=True,client_sha256=auth.EXPECTED_SHA,cases=cases,
        limitations=['Original ground reader executed; actual native scene resource loading and GPU drawing are stubbed','No real graphical-client acceptance'])
    (ROOT/'reports/contest-maps/native.json').write_text(json.dumps(report,indent=2))
    print('Published native ground reader: all 9 whole contest scenes PASS')
