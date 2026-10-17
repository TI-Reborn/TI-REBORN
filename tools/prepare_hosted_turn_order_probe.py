"""Reuse the fresh-account TCP onboarding setup for a bounded order check."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'tools/verify_hosted_team_heartbeat.py').read_text()
source=source.replace("prefix='qh'","prefix='qo'").replace('reports/wall-disconnect/hosted-','reports/turn-order/hosted-')
source=source.replace('ArenaCreateRequest(4,0,8,2,40,1,1,0,0)',
    'ArenaCreateRequest(mode,0,4 if mode==1 else 8,2,40,1,1,0,0)')
source=source.replace('def combat_run(host):','def combat_run(host,mode):')
start=source.index('        import threading\n')
end=source.index("        for peer in peers:peer.send(b'\\x2a\\x01')",start)
source=source[:start]+'''        from tio.protocol.binary import Reader
        sequences=[]
        for packets in received:
            ordered=[p for p in packets if p[0]==0x71]
            assert len(ordered)==1
            r=Reader(ordered[0]);assert r.u8()==0x71;count=r.u8()
            entries=tuple((r.u32(),r.u8()) for _ in range(count));r.finish()
            assert count==(4 if mode==1 else 8)
            assert tuple(n for owner,n in entries)==tuple(range(count))
            sequences.append(tuple(owner for owner,n in entries))
        assert sequences[0][0]==1 and sequences[1][1]==1
        assert sequences[0][2:]==sequences[1][2:]
        assert len(set(sequences[0]))==len(sequences[0])
        assert len(set(sequences[1]))==len(sequences[1])
        result['displayed_numbers']=[list(range(1,len(s)+1)) for s in sequences]
        result['wire_owner_sequences']=sequences
        result['mode']=mode
        result['checks'].append('Both peers receive native71 after members and before loading; same interleaved turn order with local ID alias')
        peers[0].until(b'\\x38',max_packets=2048)
        peers[0].send(encode_end_turn())
        updates=peers[0].until(b'\\xc8\\x17',max_packets=2048)
        assert int.from_bytes(updates[2:6],'little')==sequences[0][1]
        result['checks'].append('Actual next turn owner agrees with displayed number2')
''' +source[end:]
source=source.replace("if __name__=='__main__':combat_run(sys.argv[1])",
    "if __name__=='__main__':combat_run(sys.argv[1],int(sys.argv[2]))")
(ROOT/'tools/verify_hosted_turn_order.py').write_text(source)
