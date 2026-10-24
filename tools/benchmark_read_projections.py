"""Isolated four-owner fixtures: packet equivalence, SQL counts and timings."""
import argparse
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import statistics
import sys
import time
from unittest.mock import patch


def measure(call):
    call();statements=[];original=sqlite3.connect
    def connect(*args,**kwargs):
        db=original(*args,**kwargs);db.set_trace_callback(statements.append);return db
    with patch.object(sqlite3,'connect',side_effect=connect):value=call()
    times=[]
    for _ in range(30):
        start=time.perf_counter();call();times.append(1000*(time.perf_counter()-start))
    return dict(median_ms=statistics.median(times),max_ms=max(times),
        select_count=sum(s.lstrip().upper().startswith('SELECT') for s in statements),
        writer_begin_count=sum(s.upper()=='BEGIN IMMEDIATE' for s in statements),
        output_sha256=sha256(repr(value).encode()).hexdigest())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tree',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    tree=args.tree.resolve();sys.path[:0]=[str(tree/'tests'),str(tree)]
    import test_shared_team_arena as roster_fixture
    import test_party_travel as party_fixture
    from tio.owned_pets import OwnedPetStore
    from tio.protocol.abilities import AbilityEntry,encode_abilities
    roster=roster_fixture.SharedTeamTests();roster.setUp()
    party_fixture.PartyTravelTests.setUpClass();party=party_fixture.PartyTravelTests();party.setUp()
    try:
        roster.add_selected(0,4)
        with closing(sqlite3.connect(roster.path)) as db,db:
            db.execute('CREATE TABLE ability_states(account TEXT,pet_id INTEGER,revision INTEGER,packet BLOB,PRIMARY KEY(account,pet_id))')
            for i in range(1,5):db.execute('INSERT INTO ability_states VALUES (?,?,1,?)',('alice',i,encode_abilities(i,(AbilityEntry(1,1,0,1),))))
        store=OwnedPetStore(roster.path);result={'roster_four_pets':measure(lambda:store.list('alice'))}
        party.group(('alice','bravo','charlie','delta'))
        def refresh():
            party.locations._sent.clear()
            return tuple(party.locations.refresh(owner,index) for index,owner in enumerate(('alice','bravo','charlie','delta'),101))
        result['party_refresh_city_four']=measure(refresh)
        result['party_current_four']=measure(lambda:tuple(party.locations.current(o) for o in ('alice','bravo','charlie','delta')))
        party.travel.travel('alice',party.packet(-220,-280));party.now+=1
        result['party_refresh_moving_four']=measure(refresh)
        result['fixture_only']=True;result['iterations_each']=30
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result))
    finally:
        party.doCleanups();party_fixture.PartyTravelTests.tearDownClass();roster.doCleanups()


if __name__=='__main__':main()
