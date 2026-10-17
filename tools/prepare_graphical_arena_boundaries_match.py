"""Use the frozen owned hosted stager with strict published .3 boundaries."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import prepare_graphical_arena_match as stage
from tools.arena_boundaries_validation import VERSION,published_boundary_scene

stage.VERSION=VERSION
stage.OUTPUT=ROOT/'reports/arena-boundaries-implementation/client-qa/matches'
stage.published_scene=published_boundary_scene

if __name__=='__main__':
    try:stage.main()
    except Exception as error:
        print('{"event":"boundary_graphical_match_failed","error_type":"'+type(error).__name__+'"}',file=sys.stderr)
        raise SystemExit(1)
