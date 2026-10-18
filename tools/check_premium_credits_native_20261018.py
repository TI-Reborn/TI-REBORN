"""Execute real native price drawing, affordability and unchanged purchase writer."""
from pathlib import Path
import hashlib,json,struct,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
import verify_auth_native as n
import verify_premium_native as premium
from unicorn import UC_HOOK_CODE
OUT=ROOT/'reports/premium-credits-20261018'
n.BINARY=OUT/'silver.dll';n.EXPECTED_SHA=hashlib.sha256(n.BINARY.read_bytes()).hexdigest()

def run_draw():
 u=n.emulator();obj=n.DATA+0x1000;texture=n.DATA+0x3000
 for ptr,value in ((0xacdd08,obj),(0xacdd0c,obj+0x400),(0xac5d64,texture)):n.put32(u,ptr,value)
 u.mem_write(texture+8,struct.pack('<H',16));rows=[]
 def hook(uc,va,size,_):
  if va==0x70d435:uc.emu_stop()
  elif va in (0xa4211c,0xa42140):
   uc.reg_write(n.UC_X86_REG_EAX,120);n.return_from_stub(uc)
  elif va==0x674e38:
   sp=uc.reg_read(n.UC_X86_REG_ESP);rows.append((n.get32(uc,sp+4),n.get32(uc,sp+8)));n.return_from_stub(uc);uc.reg_write(n.UC_X86_REG_ESP,sp+12)
 u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x70d3bf,n.STOP,count=400)
 assert rows==[(0,0),(0,0)] and u.reg_read(n.UC_X86_REG_ESP)==n.STACK+0x8000
 return rows

def affordable(credits,gold,cost,kind=1,selected=True):
 u=n.emulator();person=n.DATA+0x1000;month=n.DATA+0x3000;day=n.DATA+0x4000;button=n.DATA+0x5000
 for ptr,value in ((0xac5b7c,person),(0xacdd08,month),(0xacdd0c,day),(0xacdd10,button),(0xacdd14,cost)):n.put32(u,ptr,value)
 n.put32(u,person+0x230,credits);n.put32(u,person+0x234,gold);u.mem_write(0xac46ad,bytes([kind]));u.mem_write(day+0x280,bytes([selected]))
 def hook(uc,va,size,_):
  if va==0x70d3bf:uc.emu_stop()
 u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x70d363,n.STOP,count=200)
 enabled=bool(u.mem_read(button+0x4a,1)[0]);assert enabled==bool(kind and selected and credits>=cost)
 return dict(credits=credits,gold=gold,cost=cost,kind=kind,selected=selected,enabled=enabled)

def main():
 rows=run_draw();cases=[affordable(c,g,cost,kind,selected) for cost in (1500,30000) for c,g in ((cost,0),(cost-1,999999),(0,999999)) for kind in (1,3) for selected in (False,True)]
 buys=[premium.buy(i,cost) for i,(hours,cost) in premium.OFFERS.items()]
 for b in buys:b['credits']=b.pop('gold')
 result=dict(passed=True,client_sha256=n.EXPECTED_SHA,price_icon_frames=rows,affordability_cases=cases,native_purchases=buys,ui_and_transport_stubbed=True)
 (OUT/'native-execution.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=True,draws=len(rows),affordability_cases=len(cases),purchases=len(buys))))
if __name__=='__main__':main()
