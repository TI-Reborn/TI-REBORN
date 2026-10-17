"""Build separate keep-visible candidate/verifier/reviewer; old freezes intact."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from deploy import client_arena_browsing_visible as patcher
FOLDER=ROOT/'reports/gameplay-completion/legacy-status-20261011/client-main-list-visibility'
OLD=FOLDER.parent/'client-empty-roster-navigation'
def main():
    FOLDER.mkdir(exist_ok=True);source=FOLDER.parent/'client-freshness/silver.dll';raw=patcher.patch(source.read_bytes());target=FOLDER/'silver.dll'
    if target.exists():assert target.read_bytes()==raw
    else:target.write_bytes(raw)
    text=(ROOT/'tools/verify_arena_empty_roster_navigation_native.py').read_text(encoding='utf8').replace('client_arena_empty_roster_navigation as patcher','client_arena_browsing_visible as patcher').replace('client-empty-roster-navigation','client-main-list-visibility')
    (ROOT/'tools/verify_arena_browsing_visible_native.py').write_text(text,encoding='utf8')
    builder=(ROOT/'tools/build_arena_empty_roster_navigation_native.py').read_text(encoding='utf8').replace('client_arena_empty_roster_navigation as patcher','client_arena_browsing_visible as patcher').replace('tools.verify_arena_empty_roster_navigation_native import','tools.verify_arena_browsing_visible_native import').replace('tools/verify_arena_empty_roster_navigation_native.py','tools/verify_arena_browsing_visible_native.py')
    # These two callbacks now call the scoped presentation wrapper. Their
    # original surrounding bodies are guarded below and original callee stays.
    builder=builder.replace("('Team_navigation_callback',0x9443d0,0x1e),('Wall_navigation_callback',0x944434,0x1e),","('Team_navigation_header',0x9443d0,0xd),('Team_navigation_tail',0x9443e2,0xc),('Wall_navigation_header',0x944434,0xd),('Wall_navigation_tail',0x944446,0xc),")
    (ROOT/'tools/build_arena_browsing_visible_native.py').write_text(builder,encoding='utf8')
    (FOLDER/'owned-c-rows-before-fix.json').write_bytes((OLD/'owned-c-rows-before-fix.json').read_bytes())
    print('NEW keep-visible candidate',patcher.sha(raw),len(raw))
if __name__=='__main__':main()
