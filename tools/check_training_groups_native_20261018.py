"""Execute original row reader and mandatory crest getters; no GUI claim."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
from check_training_strings_native_20261018 import NativeStrings
from verify_auth_native import DATA,STOP,UC_X86_REG_EAX,UC_X86_REG_EIP,get32
from tio.protocol.assault import RoomListItem,encode_room_list
OUT=ROOT/'reports/training-groups-20261018'
cases=[]
for present in (False,True):
 for name in (b'Creator','Игрок Ёж'.encode('cp1251')):
  for players,ready in ((1,0),(3,0),(4,0),(4,1)):
   value=0 if present else None
   packet=encode_room_list((RoomListItem(0x30000042,name,value,value,4,players,ready),))
   probe=NativeStrings(packet[6:]);probe.run(0x63aa10)
   assert get32(probe.u,0xacd0e8)-DATA==len(packet)-6
   probe.stop_at=0x42ad7c
   for entry in (0x63add8,0x63ae3c):
    probe.run(entry)
    if present:
     assert probe.u.reg_read(UC_X86_REG_EIP)==STOP
     assert probe.u.reg_read(UC_X86_REG_EAX)==0
    else:assert probe.u.reg_read(UC_X86_REG_EIP)==0x42ad7c
   cases.append(dict(present=present,players=players,ready=ready,mandatory_getters_returned=present,reader_bytes=len(packet)-6))
result=dict(passed=True,cases=cases,limitation='Original reader/getters execute; managed strings isolated. Hosted native GUI verified separately.')
(OUT/'native-crest-getters.json').write_text(json.dumps(result,indent=2));print(json.dumps(dict(passed=True,cases=len(cases))))
