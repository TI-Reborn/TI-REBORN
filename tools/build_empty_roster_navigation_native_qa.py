"""NEW actual-mode0 verifier/builder; all prior freezes remain immutable."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_arena_empty_roster_navigation as patcher
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-empty-roster-navigation'
OLD=FOLDER.parent/'client-search-availability'
def main():
    FOLDER.mkdir(exist_ok=True)
    source=FOLDER.parent/'client-freshness/silver.dll';raw=patcher.patch(source.read_bytes());target=FOLDER/'silver.dll'
    if target.exists():assert target.read_bytes()==raw
    else:target.write_bytes(raw)
    text=(ROOT/'tools/verify_arena_lobby_search_status_native.py').read_text(encoding='utf8')
    text=text.replace('client_arena_lobby_search_status as patcher','client_arena_empty_roster_navigation as patcher').replace('client-search-availability','client-empty-roster-navigation')
    text=text.replace('int(mode==4)','int(mode in (0,4))')
    text=text.replace('after_setup=False):','after_setup=False,completed_mode=4):')
    text=text.replace("u.mem_write(DATA+0x100d,b'\\x04')","u.mem_write(DATA+0x100d,bytes((completed_mode,)))")
    text=text.replace("==b'\\x04'","==bytes((completed_mode,))")
    text=text.replace('selectors.extend(selector(raw,base,0,True) for base in (0x400000,0x10400000))','selectors.extend(selector(raw,base,stale,True,0) for base in (0x400000,0x10400000) for stale in (0,4,8))\n selectors.extend(selector(raw,base,0,True,4) for base in (0x400000,0x10400000))')
    (ROOT/'tools/verify_arena_empty_roster_navigation_native.py').write_text(text,encoding='utf8')
    builder=(ROOT/'tools/build_arena_lobby_search_status_native.py').read_text(encoding='utf8')
    builder=builder.replace('client_arena_lobby_search_status as patcher','client_arena_empty_roster_navigation as patcher').replace('tools.verify_arena_lobby_search_status_native import','tools.verify_arena_empty_roster_navigation_native import').replace('tools/verify_arena_lobby_search_status_native.py','tools/verify_arena_empty_roster_navigation_native.py')
    (ROOT/'tools/build_arena_empty_roster_navigation_native.py').write_text(builder,encoding='utf8')
    evidence=OLD/'owned-c-rows-before-fix.json';copy=FOLDER/evidence.name
    if copy.exists():assert copy.read_bytes()==evidence.read_bytes()
    else:copy.write_bytes(evidence.read_bytes())
    print('NEW actual Arena mode0 candidate',patcher.sha(raw),'bytes',len(raw))
if __name__=='__main__':main()
