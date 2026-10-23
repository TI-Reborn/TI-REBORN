"""Compare actual-city lookups and outbound bytes using isolated SQLite fixtures."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tree',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();tree=args.tree.resolve()
    sys.path[:0]=[str(tree/'tests'),str(tree)]
    import test_shared_team_arena as fixture
    case=fixture.SharedTeamTests();case.setUp()
    try:
        case.create(0);case.create(1,4)
        for session in case.sessions[2:]:case.hub.identity(session)
        def reset():
            for q in case.hub.queues.values():q.clear()
            case.hub.arena_listing_cache.clear();case.hub.wager_listing_cache.clear()
        reset()
        with patch.object(case.hub,'city',wraps=case.hub.city) as city:
            case.hub.tick()
        packets={str(o):[p.hex() for p in q] for o,q in case.hub.queues.items()}
        calls=city.call_count;times=[]
        for _ in range(40):
            reset();start=time.perf_counter();case.hub.tick()
            times.append(1000*(time.perf_counter()-start))
        result=dict(iterations=len(times),real_fixture_accounts=4,idle_viewers=2,rooms=2,
            city_calls_per_tick=calls,median_ms=statistics.median(times),max_ms=max(times),
            outbound_sha256=sha256(json.dumps(packets,sort_keys=True).encode()).hexdigest(),
            packets=packets,scope='TeamArena.tick with real temporary SQLite; no network')
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='packets'}))
    finally:case.doCleanups()


if __name__=='__main__':main()
