"""Execute original history parser INCLUDING its native in-place reversal."""
import json,struct,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[1])]
from verify_auth_native import *
from verify_mining_native import run
from tio.protocol.mining import price_history

OUT=ROOT/'reports/crystal-quotes-20261018'

def display(values):
 packet=price_history(values)
 def setup(u):
  put32(u,0xac64a0,DATA+0x1000)
  put32(u,0xac5e50,DATA+0x2000);put32(u,DATA+0x2000,DATA+0x3000)
  put32(u,DATA+0x3000,DATA+0x8000)
  put32(u,DATA+0x3004,DATA+0x6000);put32(u,DATA+0x3008,0)
  put32(u,DATA+0x5ffc,144)
  put32(u,DATA+0x8008,STACK+0x200);u.mem_write(STACK+0x200,b'\xc3')
 # 6f9200 must execute. The old probe stubbed precisely this reversal.
 u=emulator();u.mem_write(DATA,packet[2:]);setup(u)
 def hook(uc,va,size,_):
  if va in (0x6f908c,0x6ef16c):return_from_stub(uc)
 u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
 u.emu_start(0x834d0c,0x834d96,count=100000)
 assert u.reg_read(UC_X86_REG_EIP)==0x834d96
 assert get32(u,u.reg_read(UC_X86_REG_EBP)-4)-DATA==len(packet)-2
 assert get32(u,DATA+0x3008)==len(values)
 actual=[struct.unpack('<4f',u.mem_read(DATA+0x6000+16*i,16)) for i in range(len(values))]
 expected=[struct.unpack('<4f',struct.pack('<4f',*v)) for v in reversed(values)]
 assert actual==expected
 return actual

def main():
 chronological=tuple((n,)*4 for n in (27.79975,26.80,42.65))
 legacy=display(chronological);correct=display(tuple(reversed(chronological)))
 assert abs(legacy[-1][0]-27.79975)<.00001
 assert abs(correct[-1][0]-42.65)<.00001
 for n in (1,2,3,50,144):
  data=tuple((float(i),)*4 for i in range(n));assert len(display(tuple(reversed(data))))==n
 result=dict(passed=True,silver_sha256=EXPECTED_SHA,reader='0x834d0c',reverse_call='0x834d8c',real_reverse='0x6f9200',legacy_display=legacy,correct_display=correct,length_cases=[1,2,3,50,144],stubbed=['clear graph','refresh caption/UI','collection listener'],real_array_copy=True,real_reverse_executed=True,graphical_rendering=False)
 (OUT/'native-execution.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
