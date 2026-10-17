"""Original main-room ready toggle, leave and start builders (not BA family)."""
from verify_arena_requests_native import run
from verify_auth_native import ROOT, EXPECTED_SHA
import json

if __name__=='__main__':
    cases=[]
    for entry,eax,ready,expected in ((0x81dae8,0,0,'2c01'),(0x81dae8,0,1,'2c00'),
                                    (0xa08a20,0,0,'2a01'),(0xa08a20,1,0,'2a00'),
                                    (0xa08ab0,255,0,'2e'),(0xa08ab0,0,0,'2e00'),
                                    (0xa08ab0,1,0,'2e01'),(0xa08ab0,2,0,'2e02')):
        packet=run(entry,eax,ready=ready)
        assert packet.hex()==expected,(hex(entry),packet.hex())
        cases.append({'entry':hex(entry),'eax':eax,'ready':ready,'packet_hex':packet.hex()})
    (ROOT/'evidence/room_actions_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Main-room ready, leave and start builders:8 cases PASS')
