"""A second real TLS account observes native disband and can lead a new group."""
import json,socket,ssl,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import verify_training_base_20261018_hosted as q
def main():
 data=json.loads((ROOT/'.secrets/training-disband-20261018.json').read_text());name=data['names'][1]
 case=q.MultiAccountTests();case.clients=[];tls=q.GameTLSTests();tls.case=case;ctx=ssl.create_default_context()
 def connect(kind,*,preface=None,**kwargs):
  s=ctx.wrap_socket(socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15),server_hostname='ti-reborn.com');case.clients.append(s)
  if preface is not None:s.sendall(preface)
  return s
 tls.connect=connect;peer=tls.handoff(tls.begin(name,41002,password=data['passwords'][1]));case.enter(peer,name)
 seen=[]
 def command(packet=None,expected=None):
  if packet is not None:peer.send(packet)
  peer.send(b'\x70');rows=[];fence=False
  for _ in range(512):
   p=peer.receive();rows.append(p);fence|=p==b'\x9e'
   if p[:2]==b'\xc8\x25':seen.append(dict(deleted=int.from_bytes(p[2:6],'little')))
   if p.startswith(b'\xf0\x8a\x01\0\0'):raise AssertionError('Own QA command rejected')
   if fence and (expected is None or any(x.startswith(expected) for x in rows)):return rows
  raise AssertionError('Missing response')
 try:
  command(q.encode_request(q.JOIN_ROOM,int(sys.argv[1],0)),b'\xc8\x24');print(json.dumps(dict(joined=True)),flush=True)
  for line in sys.stdin:
   op=line.strip()
   if op=='deleted':command(expected=b'\xc8\x25');print(json.dumps(dict(seen=seen)),flush=True)
   elif op=='create':
    rows=command(q.encode_request(q.CREATE_ROOM),b'\xc8\x24');group=next(q.room_state(p)['id'] for p in rows if q.room_state(p));print(json.dumps(dict(created=group)),flush=True)
   elif op=='disband':command(q.encode_request(0x23),b'\xc8\x25');print(json.dumps(dict(disbanded=True)),flush=True)
   elif op=='stop':break
   else:command();print(json.dumps(dict(alive=True,seen=seen)),flush=True)
 finally:
  for channel in case.clients:channel.close()
  (ROOT/'reports/training-disband-20261018/peer-verification.json').write_text(json.dumps(dict(deletions=seen,tls_account=name),indent=2))
if __name__=='__main__':main()
