"""Second real TLS participant; reports native rosters and selectable groups."""
import sys,json,time,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools import clan_icons_hosted_20261018 as q
from test_clan_crest_projections import roster
from test_training_group_list import listed
from tio.protocol.assault import encode_request,CREATE_ROOM,JOIN_ROOM,REQUEST_ROOMS,DISBAND_ROOM
OUT=ROOT/'reports/clan-crest-projections-20261018';q.PRIVATE=ROOT/'.secrets/clan-crest-projections-20261018.json'
data=json.loads(q.PRIVATE.read_text());clients=q.Clients(data);clients.connect(1);evidence=[]
print(json.dumps(dict(second_account_connected=True)),flush=True)
try:
 for line in sys.stdin:
  op=line.strip()
  if op=='stop':break
  packet=encode_request(CREATE_ROOM if op=='create' else DISBAND_ROOM if op=='disband' else REQUEST_ROOMS) if op in ('create','disband','list') else b'\xc7\x01'
  rows=clients.command(1,packet)
  result=dict(op=op,global_rosters=[{n.decode():v for n,v in roster(p).items()} for p in rows if p[:2]==b'\xc7\x02'],location_rosters=[{n.decode():v for n,v in roster(p).items()} for p in rows if p[:1]==b'\x4f'],groups=[listed(p) for p in rows if p[:2]==b'\xc8\x26'],room_packets=[p.hex() for p in rows if p[:2]==b'\xc8\x24'])
  evidence.append(result);print(json.dumps(result),flush=True)
finally:
 clients.close();(OUT/'peer-verification.json').write_text(json.dumps(evidence,indent=2))
