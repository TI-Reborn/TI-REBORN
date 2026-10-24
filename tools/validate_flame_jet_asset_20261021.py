"""Validate the exported Blender frames and embedded native production code."""
import hashlib,json,sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy.client_flame_stream import build
OUT=ROOT/'reports/flame-blender-20261021';ASSET=ROOT/'assets/flame-jet-v1/tio-flame-jet.png'
im=Image.open(ASSET);assert im.size==(512,512) and im.mode=='RGBA'
frames=[]
for bank in range(8):
 hashes=set()
 for f in range(8):
  tile=im.crop((f*64,bank*64,(f+1)*64,(bank+1)*64));hashes.add(hashlib.sha256(tile.tobytes()).hexdigest());a=tile.getchannel('A');assert a.getextrema()[1]>200
  if bank in (3,7):assert all(a.getpixel((x,32))>180 for x in range(10,54)),(bank,f)
 assert len(hashes)==8;frames.append(dict(bank=bank,unique_frames=len(hashes)))
p=json.loads((OUT/'launcher-native-proof.json').read_text());assert bytes.fromhex(p['code'])==build(p['allocation'],p['silver'])
r=dict(passed=True,rgba=True,dimensions=[512,512],tiles=64,dense_longitudinal_core=True,frames=frames,production_adapter_matches=True,sha256=hashlib.sha256(ASSET.read_bytes()).hexdigest())
(OUT/'texture-validation.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
