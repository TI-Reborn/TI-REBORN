"""Use the established owned public matchmaking harness for the fog release."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import prepare_graphical_arena_match as stage
from tools.arena_fog_validation import VERSION, published_fog_scene

stage.VERSION = VERSION
stage.OUTPUT = ROOT/'reports/arena-surroundings-fog/client-qa/matches'
stage.published_scene = published_fog_scene

if __name__ == '__main__':
    try:
        stage.main()
    except Exception as error:
        print('{"event":"fog_graphical_match_failed","error_type":"'+type(error).__name__+'"}', file=sys.stderr)
        raise SystemExit(1)
