"""Execute original B01F reader and append actual four-float quote records.

Only graph UI refresh and its listener are isolated; native array copying,
float readers and wire consumption execute. No graphical rendering claimed.
"""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1])]
from verify_auth_native import *
from verify_mining_native import run
from tio.protocol.mining import price_history


def verify():
    values=((1.0,)*4,(0.9999,)*4,(1.0099,)*4)
    packet=price_history(values)
    def setup(u):
        put32(u,0xac64a0,DATA+0x1000)
        put32(u,0xac5e50,DATA+0x2000);put32(u,DATA+0x2000,DATA+0x3000)
        put32(u,DATA+0x3000,DATA+0x8000)
        put32(u,DATA+0x3004,DATA+0x6000);put32(u,DATA+0x3008,0)
        put32(u,DATA+0x5ffc,16)
        put32(u,DATA+0x8008,STACK+0x200);u.mem_write(STACK+0x200,b'\xc3')
    u=run(packet,0x834d0c,0x834d96,setup,(0x6f908c,0x6f9200,0x6ef16c))
    assert get32(u,DATA+0x3008)==len(values)
    actual=[struct.unpack('<4f',u.mem_read(DATA+0x6000+16*i,16)) for i in range(len(values))]
    expected=[struct.unpack('<4f',struct.pack('<4f',*v)) for v in values]
    assert actual==expected
    return dict(passed=True,sha256=EXPECTED_SHA,reader='834d0c',array_append='6f87c8',records=actual,
        consumed_payload_bytes=len(packet)-2,graphical_rendering=False,
        isolated_calls=['graph clear UI','graph refresh UI','quote caption UI','graph listener'])


if __name__=='__main__':
    result=verify()
    (ROOT/'evidence/crystal_history_native.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Original crystal price-history reader and native record copying: PASS')
