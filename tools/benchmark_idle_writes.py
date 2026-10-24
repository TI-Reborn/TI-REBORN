"""Compare empty background passes without hosted player data or wall-clock races."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import tempfile
import time
from unittest.mock import patch


def state(path):
    with sqlite3.connect(path) as db:
        result={}
        for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted='"'+table.replace('"','""')+'"'
            result[table]=db.execute('SELECT * FROM '+quoted+' ORDER BY rowid').fetchall()
    return sha256(repr(result).encode()).hexdigest()


def measure(call,path):
    call();before=state(path);statements=[];original=sqlite3.connect
    def connect(*args,**kwargs):
        db=original(*args,**kwargs);db.set_trace_callback(statements.append);return db
    with patch.object(sqlite3,'connect',side_effect=connect):value=call()
    times=[]
    for _ in range(30):
        start=time.perf_counter();call();times.append(1000*(time.perf_counter()-start))
    unchanged=before==state(path);assert unchanged
    return dict(median_ms=statistics.median(times),max_ms=max(times),
        select_count=sum(s.lstrip().upper().startswith('SELECT') for s in statements),
        writer_begin_count=sum(s.upper()=='BEGIN IMMEDIATE' for s in statements),
        mutation_statements=sum(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for s in statements),
        database_rows_unchanged=unchanged,output_sha256=sha256(repr(value).encode()).hexdigest())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tree',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    tree=args.tree.resolve();sys.path[:0]=[str(tree/'tests'),str(tree)]
    import test_party_travel as fixture
    from tio.sc_auction import SCAuctionStore
    fixture.PartyTravelTests.setUpClass();case=fixture.PartyTravelTests();case.setUp()
    try:
        room=case.group(('alice','bravo','charlie','delta'))
        def sync():
            return [(case.parties.set_online(owner,True),case.parties.recover_leader(room['id']),case.contracts.target_for(owner)) for owner in ('alice','bravo','charlie','delta')]
        result={'four_party_status_sync':measure(sync,case.path),
            'missing_contract_target':measure(lambda:case.contracts.target_for('alice'),case.path)}
        auction=SCAuctionStore(case.path);auction.tick(now=100)
        result['idle_auction_tick']=measure(lambda:auction.tick(now=150),case.path)
        result.update(iterations_each=30,fixture_only=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
    finally:case.doCleanups();fixture.PartyTravelTests.tearDownClass()


if __name__=='__main__':main()
