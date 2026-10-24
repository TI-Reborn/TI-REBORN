"""Four idle owners, real membership SQL, deterministic empty other phases."""
import argparse
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tree',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();tree=args.tree.resolve();sys.path[:0]=[str(tree/'tests'),str(tree)]
    import test_shared_team_arena as fixture
    case=fixture.SharedTeamTests();case.setUp()
    try:
        hub=case.hub;hub.init_assault(case.path)
        for session in case.sessions:hub.identity(session)
        # Measure periodic listings, not the changing wall-clock assault scheduler.
        hub.tick_assault_events=lambda:None
        hub.tick();packets={o:list(q) for o,q in hub.queues.items()}
        times=[]
        for _ in range(60):
            started=time.perf_counter();hub.tick();times.append(1000*(time.perf_counter()-started))
        statements=[];opened=[];original=sqlite3.connect
        def connect(*a,**kw):
            db=original(*a,**kw);opened.append(db);db.set_trace_callback(statements.append);return db
        with patch.object(sqlite3,'connect',side_effect=connect):hub.tick()
        import hashlib
        result=dict(accounts=4,iterations=60,fixture_only=True,median_ms=statistics.median(times),max_ms=max(times),
                    connections=len(opened),selects=sum(s.lstrip().upper().startswith('SELECT') for s in statements),
                    packet_sha256=hashlib.sha256(repr(packets).encode()).hexdigest())
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
    finally:case.doCleanups()


if __name__=='__main__':main()
