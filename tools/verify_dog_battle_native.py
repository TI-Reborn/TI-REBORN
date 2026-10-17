"""Saved hire-dog66 -> battle3B original reader; scene/UI helpers isolated."""
import tempfile
from trace_battle_soldier_native import trace
from verify_auth_native import ROOT,EXPECTED_SHA,json
from battle_actor_fixture import actor_packet
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.wallets import WalletStore


if __name__=='__main__':
    template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
    results=[]
    with tempfile.TemporaryDirectory() as folder:
        from pathlib import Path
        db=Path(folder)/'probe.sqlite3';WalletStore(db).ensure('probe')
        hire=HireStore(db,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
        for resource in (3,4,5):
            pet,inventory,_=hire.hire('probe',resource)
            wire=actor_packet(pet,1,inventory,human=False)
            result=trace(human=False,body=wire[1:])
            assert result['consumed']==len(wire)-1
            assert result['model']['health']==100 and result['model']['max_health']==100
            results.append({'resource':resource,'packet_hex':wire.hex(),'model':result['model'],
                            'consumed':result['consumed'],'limitations':result['limitations']})
    (ROOT/'evidence/dog_battle_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'cases':results},indent=2)+'\n')
    print('Original dog battle reader:3 resource cases PASS')
