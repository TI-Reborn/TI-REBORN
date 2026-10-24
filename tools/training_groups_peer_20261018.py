"""Second hosted TLS account creates real groups for native selection QA."""
import json,socket,ssl,sys,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import verify_training_base_20261018_hosted as q
OUT=ROOT/'reports/training-groups-20261018'
data=json.loads((ROOT/'.secrets/training-groups-20261018.json').read_text());name=data['names'][1]
case=q.MultiAccountTests();case.clients=[];tls=q.GameTLSTests();tls.case=case;ctx=ssl.create_default_context()
def connect(kind,*,preface=None,**kwargs):
 s=ctx.wrap_socket(socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15),server_hostname='ti-reborn.com');case.clients.append(s)
 if preface is not None:s.sendall(preface)
 return s
tls.connect=connect;peer=tls.handoff(tls.begin(name,42002,password=data['passwords'][1]));case.enter(peer,name)
evidence=[]
def command(packet=None,expected=None):
 if packet is not None:peer.send(packet)
 peer.send(b'\x70');rows=[];fence=False
 for _ in range(512):
  p=peer.receive();rows.append(p);fence|=p==b'\x9e'
  if p.startswith(b'\xf0\x8a\x01\0\0'):raise AssertionError('Own QA request rejected')
  if fence and (expected is None or any(x.startswith(expected) for x in rows)):return rows
 raise AssertionError('Missing response')
try:
 for line in sys.stdin:
  op=line.strip()
  if op=='stop':break
  if op=='create':rows=command(q.encode_request(q.CREATE_ROOM),b'\xc8\x24')
  elif op=='disband':rows=command(q.encode_request(0x23),b'\xc8\x25')
  elif op=='list':rows=command(q.encode_request(q.REQUEST_ROOMS),b'\xc8\x26')
  else:rows=command()
  value=dict(op=op,rooms=[q.room_state(p) for p in rows if q.room_state(p)],deleted=[int.from_bytes(p[2:6],'little') for p in rows if p[:2]==b'\xc8\x25'],lists=[p.hex() for p in rows if p[:2]==b'\xc8\x26'])
  evidence.append(value);print(json.dumps(value),flush=True)
finally:
 for s in case.clients:s.close()
 (OUT/'peer-verification.json').write_text(json.dumps(evidence,indent=2))
