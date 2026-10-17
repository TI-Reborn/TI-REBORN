"""Create NEW search-status verifier/builder; prior freeze files are untouched."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_arena_lobby_search_status as patcher
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-search-availability'
OLD=FOLDER.parent/'client-availability-navigation'
def main():
    FOLDER.mkdir(exist_ok=True)
    source=FOLDER.parent/'client-freshness/silver.dll';raw=patcher.patch(source.read_bytes())
    target=FOLDER/'silver.dll'
    if target.exists():assert target.read_bytes()==raw
    else:target.write_bytes(raw)
    verifier=(ROOT/'tools/verify_arena_lobby_navigation_native.py').read_text(encoding='utf8')
    verifier=verifier.replace('client_arena_lobby_navigation as patcher','client_arena_lobby_search_status as patcher').replace('client-availability-navigation','client-search-availability')
    verifier=verifier.replace('stake=0):','stake=0,status=0):').replace('capacity,members,0,1,2,1,0,stake','capacity,members,status,1,2,1,0,stake').replace('ArenaRoom(73,0,mode,0,0,members','ArenaRoom(73,0,mode,status,0,members')
    verifier=verifier.replace('members>=capacity else patcher.GREEN','members>=capacity or status else patcher.GREEN')
    verifier=verifier.replace("'colour_hex'","'colour_hex'")
    verifier=verifier.replace("roster=roster,eligible=eligible,colour_hex=", "roster=roster,eligible=eligible,status=status,colour_hex=")
    verifier=verifier.replace("counts=[selected_count", "cases.extend(lobby(raw,base,mode,1,capacity,roster,typed=typed,status=2)\n        for base in (0x400000,0x10400000) for typed in (False,True) for mode,capacity in ((1,2),(4,4))\n        for roster in rosters)\n counts=[selected_count")
    (ROOT/'tools/verify_arena_lobby_search_status_native.py').write_text(verifier,encoding='utf8')
    builder=(ROOT/'tools/build_arena_lobby_navigation_native.py').read_text(encoding='utf8')
    builder=builder.replace('client_arena_lobby_navigation as patcher','client_arena_lobby_search_status as patcher').replace('tools.verify_arena_lobby_navigation_native import','tools.verify_arena_lobby_search_status_native import').replace('tools/verify_arena_lobby_navigation_native.py','tools/verify_arena_lobby_search_status_native.py')
    builder=builder.replace("full_eligible_abgr='ff606060'", "full_or_searching_eligible_abgr='ff606060'")
    (ROOT/'tools/build_arena_lobby_search_status_native.py').write_text(builder,encoding='utf8')
    evidence=OLD/'owned-c-rows-before-fix.json';copy=FOLDER/evidence.name
    if copy.exists():assert copy.read_bytes()==evidence.read_bytes()
    else:copy.write_bytes(evidence.read_bytes())
    print('NEW search-status candidate',patcher.sha(raw),'bytes',len(raw))
if __name__=='__main__':main()
