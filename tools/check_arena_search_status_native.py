"""Bounded original full-renderer status2 regression check; no frozen edits."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_arena_lobby_navigation_native as original
from deploy.client_server_list_status import sha
FOLDER=original.FOLDER.parent/'client-search-availability'
def main():
 FOLDER.mkdir(exist_ok=True)
 text=Path(original.__file__).read_text(encoding='utf8')
 start=text.index('def lobby(');end=text.index('\n\ndef main():',start)
 code=text[start:end].replace('stake=0):','stake=0,status=0):').replace('capacity,members,0,1,2,1,0,stake','capacity,members,status,1,2,1,0,stake').replace('ArenaRoom(73,0,mode,0,0,members','ArenaRoom(73,0,mode,status,0,members')
 namespace=original.__dict__.copy();exec(code,namespace)
 raw=(original.FOLDER/'silver.dll').read_bytes();cases=[]
 for base in (0x400000,0x10400000):
  for typed in (False,True):
   for mode,capacity in ((1,2),(4,4)):
    for roster in ([],[(4,1)],[(1,1)]):
     row=namespace['lobby'](raw,base,mode,1,capacity,roster,typed=typed,status=2)
     row['status']=2;row['expected_search_colour']='ff606060' if row['eligible'] else 'ff6060ff'
     row['search_colour_correct']=row['colour_hex']==row['expected_search_colour'];cases.append(row)
 report=dict(passed=all(r['search_colour_correct'] for r in cases),frozen_afaa_native_sha256=sha(raw),cases=cases,scope='Complete original BA02/C82C parser/colour and877158 draw, status2 underfull, owned-none/4/1, both bases',frozen_files_modified=False)
 (FOLDER/'afaa-search-regression.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(passed=report['passed'],cases=len(cases),eligible_search_green=sum(r['eligible'] and r['colour_hex']=='ff50e070' for r in cases))))
if __name__=='__main__':main()
