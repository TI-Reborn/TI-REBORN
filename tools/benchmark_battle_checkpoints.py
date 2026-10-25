"""Measure eight real-account slots across four authoritative test matches.

Temporary database only; fixtures provision independent persistent inventories.
This is a server-side benchmark, not a graphical-client load test.
"""
from pathlib import Path
import argparse
import json
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def run(source=ROOT,fixtures=None):
    sys.path[:0]=[str(source),str(fixtures or source/'tests')]
    import test_shared_team_arena as fixture
    fixture.ROOT=source
    from server.battle_journal import BattleJournal
    from server.team_arena import TeamArena
    from tio.owned_pets import OwnedPetStore
    from tio.wallets import WalletStore
    from tio import battle_checkpoints
    from tio.protocol.battle_turn import encode_end_turn
    from tio.turn_repeats import END_TURN_REPEAT_SECONDS
    c=fixture.SharedTeamTests();c.setUp()
    try:
        for index in range(4):
            old=c.sessions[index];s=fixture.Session();s.__dict__.update(old.__dict__)
            s.account='extra'+str(index);s.probe_character_name=s.account.encode()
            WalletStore(c.path).ensure(s.account)
            _,pet,inventory=OwnedPetStore(c.path).list(old.account)[0]
            OwnedPetStore(c.path).ensure(s.account,pet,inventory,human=True);c.sessions.append(s)
        c.hub.journal=BattleJournal(c.hub,c.path,wall=lambda:1000)
        for pair in range(4):
            for index in (2*pair,2*pair+1):c.send(index,b'\xba\3\0\1')
            for index in (2*pair,2*pair+1):c.send(index,b'\x36')
        c.hub.tick();latencies=[]
        for cycle in range(40):
            for pair in range(4):
                owner=c.hub.identities[c.sessions[2*pair]];battle=c.hub.battles[owner]
                current=battle['arena']._turns[battle['room'].room_id][0]
                index=next(i for i,s in enumerate(c.sessions) if c.hub.identities[s]==current)
                # The fixture clock is frozen; step past the native
                # repeated-end-turn fence (tio.turn_repeats) so each end is real.
                c.now+=END_TURN_REPEAT_SECONDS+.01
                started=time.perf_counter();replies=c.send(index,encode_end_turn());c.hub.tick()
                assert not any(p[0]==0xf0 for p in replies)
                assert battle['arena']._turns[battle['room'].room_id][0]!=current
                latencies.append((time.perf_counter()-started)*1000)
                for queue in c.hub.queues.values():queue.clear()
        rows=battle_checkpoints.read(c.path)
        assert len(rows)==4 and sum(len(row[4]) for row in rows)==8
        hub=TeamArena(clock=lambda:0);hub.journal=BattleJournal(hub,c.path,wall=lambda:1000)
        started=time.perf_counter();restored=hub.journal.recover();seconds=time.perf_counter()-started
        assert len(restored)==4 and len(hub.account_owners)==8
        return dict(kind='four simultaneous authoritative matches; eight independent account inventories; temporary SQLite',
            matches=4,accounts=8,actions=len(latencies),p50_ms=round(statistics.median(latencies),3),
            p95_ms=round(sorted(latencies)[int(.95*(len(latencies)-1))],3),max_ms=round(max(latencies),3),
            snapshot_bytes=[len(row[1].encode()) for row in rows],recover_seconds=round(seconds,3))
    finally:c.doCleanups()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=ROOT);parser.add_argument('--fixtures',type=Path)
    args=parser.parse_args();print(json.dumps(run(args.source,args.fixtures)))
