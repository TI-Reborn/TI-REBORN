"""Diagnose the reported 1000-credit exchange and auction visibility; no code deployment."""
from pathlib import Path
import json,secrets,socket,ssl,struct,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_trade_operations_hosted import remote,CREATE,CLEANUP,STATE,INSTALLED
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from tio.protocol import player_trade as wire
from tio.protocol.binary import Writer
REPORT=ROOT/'reports/trade-auction-diagnosis-20261015'

def run():
    REPORT.mkdir(exist_ok=True)
    installed=remote(INSTALLED,json.loads((ROOT/'reports/bank-trade-release-20261015/patch-manifest.json').read_text()))
    prefix='qm'+secrets.token_hex(4);names=[prefix+s for s in 'abc']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();provision=None
    report=dict(passed=False,fixtures=names,installed=installed,checks=[],production_code_modified=False)
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def until(peer,prefixes):
        deadline=time.monotonic()+35;seen=[]
        while time.monotonic()<deadline:
            packet=peer.receive();seen.append(packet[:2].hex())
            if packet.startswith(prefixes):return packet
        raise AssertionError('Missing response; packet kinds '+str(seen[-15:]))
    def state():return remote(STATE,names)
    def record(text):report['checks'].append(text);print(text,flush=True)
    try:
        provision=remote(CREATE,list(zip(names,passwords)));report['ranking_excluded']=provision['ranking_excluded']
        peers=[]
        for i in range(3):
            peer=tls.handoff(tls.begin(names[i],36001+i,password=passwords[i]));case.enter(peer,names[i])
            peer.send(struct.pack('<Bii',0x1b,-154,-318));peer.send(b'\xb1\x02');until(peer,b'\xb1\x03');peers.append(peer)
        a,b=peers[:2]
        for ident,types in ((811,()),(812,tuple(range(1,15)))):
            w=Writer().u8(0xc8).u8(8).u32(0).u32(ident).u8(1).u32(0).u32(len(types))
            for typ in types:w.u32(typ)
            w.u8(1).u8(0).u8(27).u8(1).u8(0).u8(100).u8(1).u32(3).u32(3).u32(1)
            a.send(w.build());reply=until(a,(b'\xc8\x09',b'\xf0'))
            assert reply.startswith(b'\xc8\x09'),reply[:12].hex()
            count=int.from_bytes(reply[14:18],'little');report.setdefault('auction_queries',[]).append(dict(types=types,lots=count,response=reply.hex()))
            assert count>=2,'Active medkit lots absent from buy response'
        record('Auction Buy returns active lots to a different account with default upgrade/durability ranges and all category filters')
        initial=state();assert initial[names[0]]['wallet']==[3000,0] and initial[names[1]]['wallet']==[3000,0]
        a.send(wire.invite_request(names[1].encode(),1));until(b,b'\x85')
        b.send(wire.answer_request(True,1));until(a,b'\x87');until(b,b'\x87')
        a.send(wire.offer_request(wire.CREDITS_ID,1000));own=until(a,(b'\x89',b'\x8c'));other=until(b,(b'\x8a',b'\x8c'))
        assert own.startswith(b'\x89') and other.startswith(b'\x8a'),'Window closed when offering 1000'
        assert state()==initial
        record('Adding exactly 1000 credits keeps both trade windows open and does not debit wallets')
        a.send(wire.confirm_request());notice=until(a,(b'\x22',b'\x8c'))
        assert notice.startswith(b'\x22')
        assert state()==initial
        record('First confirmation does not transfer money')
        b.send(wire.confirm_request());until(a,b'\x8c');until(b,b'\x8c')
        after=state();assert after[names[0]]['wallet']==[2000,0] and after[names[1]]['wallet']==[4000,0]
        assert after[names[0]]['inventory']==initial[names[0]]['inventory'] and after[names[1]]['inventory']==initial[names[1]]['inventory']
        record('Both confirmations close the windows and transfer exactly 1000 credits, preserving inventories and total funds')
        report['passed']=True
    finally:
        for connection in case.clients:
            try:connection.close()
            except OSError:pass
        time.sleep(1)
        try:
            if provision:report['cleanup']=remote(CLEANUP,names)
        finally:(REPORT/'hosted-diagnosis.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=report['passed'],checks=report['checks'],cleanup=report['cleanup'])),flush=True)

if __name__=='__main__':run()
