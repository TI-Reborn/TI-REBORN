"""Execute full old/new disband callback, including both stock branch gates."""
import hashlib,itertools,json,sys
from pathlib import Path
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/training-disband-20261018'
def run(raw,base,training,member,queued,leader):
 p=pefile.PE(data=raw);p.relocate_image(base);u=Uc(UC_ARCH_X86,UC_MODE_32)
 u.mem_map(base,(p.OPTIONAL_HEADER.SizeOfImage+4095)&~4095);u.mem_write(base,p.get_memory_mapped_image())
 u.mem_map(0x50000000,0x10000);stop=0x50000000;sp=0x50008000
 u.mem_write(sp,stop.to_bytes(4,'little'));u.reg_write(UC_X86_REG_ESP,sp);u.reg_write(UC_X86_REG_EBP,0x12345678)
 u.reg_write(UC_X86_REG_EBX,0x87654321);u.reg_write(UC_X86_REG_ESI,0xabcdef01);u.reg_write(UC_X86_REG_EDI,0x10fedcba)
 delta=base-0x400000
 for index,(addr,value) in enumerate(((0xac585c,member),(0xac5520,queued),(0xac63b4,leader))):
  ptr=0x50000100+index*8;u.mem_write(addr+delta,ptr.to_bytes(4,'little'));u.mem_write(ptr,bytes((int(value),)))
 packets=[];draft=bytearray()
 def ret():
  s=u.reg_read(UC_X86_REG_ESP);u.reg_write(UC_X86_REG_EIP,int.from_bytes(u.mem_read(s,4),'little'));u.reg_write(UC_X86_REG_ESP,s+4)
 def hook(u,pc,size,_):
  va=pc-delta
  if va==0x822234:u.reg_write(UC_X86_REG_EAX,int(training));ret()
  elif va==0x629764:draft.clear();ret()
  elif va in (0x639384,0x639220):draft.extend(b'\xc8'+bytes((0x23 if va==0x639384 else 0x1f,)));ret()
  elif va==0x629938:packets.append(bytes(draft));ret()
  elif va in (0xa6a114,0x639380,0x63921c,0xa03040,0xa03344):ret()
 u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x792c74+delta,stop,count=300)
 assert u.reg_read(UC_X86_REG_EIP)==stop and u.reg_read(UC_X86_REG_ESP)==sp+4
 for reg,value in ((UC_X86_REG_EBP,0x12345678),(UC_X86_REG_EBX,0x87654321),(UC_X86_REG_ESI,0xabcdef01),(UC_X86_REG_EDI,0x10fedcba)):assert u.reg_read(reg)==value
 return [p.hex() for p in packets]
def main():
 old=(OUT/'silver-before.dll').read_bytes();new=(OUT/'silver.dll').read_bytes();review=json.loads((OUT/'native-review.json').read_text());assert hashlib.sha256(new).hexdigest()==review['after_sha256']
 allowed={i for r in review['changed_ranges'] for i in range(r['offset'],r['offset']+r['size'])}
 assert all(i in allowed for i,(a,b) in enumerate(zip(old,new)) if a!=b) and len(old)==len(new)
 cases=[]
 for base,training,member,queued,leader in itertools.product((0x400000,0x18000000,0x31000000),(False,True),(False,True),(False,True),(False,True)):
  before=run(old,base,training,member,queued,leader);after=run(new,base,training,member,queued,leader)
  expected=(['c823','c81f'] if member else ['c81f']) if training else before
  assert after==expected,(base,training,member,queued,leader,before,after)
  cases.append(dict(base=hex(base),training=training,member=member,queued=queued,leader=leader,before=before,after=after))
 report=dict(passed=True,cases=cases,case_count=len(cases),ordinary_bases_preserved=True,all_file_changes_reviewed=True,limitation='UI side effects and transport isolated; GUI acceptance separate')
 (OUT/'native-execution.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='cases'}))
if __name__=='__main__':main()
