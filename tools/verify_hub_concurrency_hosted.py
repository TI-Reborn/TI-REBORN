"""Bounded four-account TLS city workload; no bids or real-player actions.

Request-to-heartbeat-fence timings include networking, queueing and unrelated
server work. They are not combat action latency or a controlled A/B benchmark.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import socket
import ssl
import statistics
import struct
import threading
import time
import traceback

from verify_performance_hosted import ROOT,constants,remote,GameTLSTests,MultiAccountTests

TRADE_CLEANUP=r'''
import json,sqlite3,hashlib
from tio.rating_visibility import QA_LOGIN
names=set(request);assert len(names)==4 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE')
 rows=db.execute('SELECT id,parties FROM player_trade_receipts').fetchall()
 ids=[i for i,p in rows if {a for a,pet in json.loads(p)}<=names]
 assert len(ids)<=3
 def unrelated():return sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM player_trade_receipts') if r[0] not in ids)
 before=unrelated()
 triggers=db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='player_trade_receipts' AND upper(sql) LIKE '%BEFORE DELETE%'").fetchall()
 for name,source in triggers:db.execute('DROP TRIGGER "'+name.replace('"','""')+'"')
 for identity in ids:db.execute('DELETE FROM player_trade_receipts WHERE id=?',(identity,))
 for name,source in triggers:db.execute(source)
 assert unrelated()==before
 assert db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name='player_trade_receipts' AND upper(sql) LIKE '%BEFORE DELETE%'").fetchall()==triggers
 print(json.dumps(dict(qa_receipts_removed=len(ids),unrelated_receipts_preserved=True)))
'''

WOUND_QA=r'''
import json
from tio.rating_visibility import QA_LOGIN
from tio.db_transaction import transaction
from tio.battle_recovery import save_wounds,CREDITS_PER_HP
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info
names=request;assert len(names)==4 and all(QA_LOGIN.fullmatch(n) for n in names)
path='/var/lib/tio-server/reservation.sqlite3';store=OwnedPetStore(path)
with transaction(path) as db:
 for owner in names:
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(owner,)).fetchone()
  pet=decode_pet_info(store.list(owner)[0][1],human_equipment=True)
  save_wounds(db,owner,{1:max(1,pet.fields['0x8c4a07']-20)})
print(json.dumps(dict(fixture='Only four disposable QA fighters wounded by <=20 HP',credits_per_hp=CREDITS_PER_HP)))
'''

HEALTH_STATE=r'''
import json,sqlite3
from tio.protocol.pet_info import decode_pet_info
from tio.rating_visibility import QA_LOGIN
names=request;assert all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 values={}
 for owner in names:
  raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(owner,)).fetchone()[0]
  f=decode_pet_info(raw,human_equipment=True).fields
  values[owner]=dict(hp=f['0x8c4ab1'],maximum=f['0x8c4a07'])
print(json.dumps(values))
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label',choices=('before','after'))
    parser.add_argument('--report-dir',type=Path,required=True)
    parser.add_argument('--trade',action='store_true',help='Also settle three equal-value trades between own QA peers while two other peers read')
    parser.add_argument('--heal',action='store_true',help='Artificially wound own disposable QA fighters, then pay for native treatment concurrently')
    parser.add_argument('--rounds',type=int,choices=range(1,7),default=6)
    args=parser.parse_args();args.report_dir.mkdir(parents=True,exist_ok=True)
    names=['qp'+secrets.token_hex(4)+s for s in 'abcd']
    passwords=[secrets.token_hex(16) for _ in names]
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();sql=constants();provision=None
    entered=[]
    report=dict(passed=False,authenticated_accounts=4,graphical_clients=False,
                timing='request to heartbeat fence; includes client network and worker queue')
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=20)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def ask(peer,packet,expected=None):
        started=time.perf_counter();peer.send(packet)
        if packet!=b'\x70':peer.send(b'\x70')
        fenced=False;matched=expected is None
        for _ in range(1024):
            if time.perf_counter()-started>30:raise TimeoutError('response/fence deadline: '+packet[:3].hex())
            reply=peer.receive()
            if reply[:5]==b'\xf0\x8a\1\0\0':raise AssertionError('native request rejected')
            if reply==b'\x9e':fenced=True
            if expected and (expected(reply) if callable(expected) else reply.startswith(expected)):matched=True
            if matched and fenced:return (time.perf_counter()-started)*1000
        raise AssertionError('response/fence missing')
    try:
        provision=remote(sql['CREATE'],list(zip(names,passwords)))
        # Recovery receipt contains no passwords, tokens or configuration.
        (args.report_dir/('concurrent-'+args.label+'-fixtures.json')).write_text(json.dumps(dict(names=names,provision=provision),indent=2)+'\n',encoding='utf-8')
        print('Provisioned four disposable excluded accounts',flush=True)
        report['ranking_excluded']=provision['ranking_excluded'];peers=[]
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,35001+i,password=password));case.enter(peer,name)
            entered.append(name)
            ask(peer,struct.pack('<Bii',0x1b,-154,-318));peers.append(peer)
            print('Authenticated peer '+str(i+1),flush=True)
        before=remote(__import__('verify_performance_hosted').PARTY_STATE,names)
        barrier=threading.Barrier(4)
        def worker(index):
            peer=peers[index];samples={'room_list':[],'sc_catalogue':[],'inventory':[]}
            requests=(('room_list',b'\xba\1',b'\xc8\x2c'),
                      ('sc_catalogue',b'\xbd\1\0\0\0',b'\xf8\1\1'),
                      ('inventory',b'\x2f\1\0\1\0\0\0',b'\x30'))
            for round in range(args.rounds):
                barrier.wait(timeout=30)
                for key,packet,expected in requests:
                    samples[key].append(ask(peer,packet,expected))
                if index==0:print('Completed concurrent round '+str(round+1),flush=True)
                time.sleep(.1)
            return samples
        with ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(worker,range(4)))
        if args.trade:
            from tio.protocol import player_trade as wire
            start=threading.Barrier(3)
            def reader(index):
                start.wait(timeout=20)
                for _ in range(9):ask(peers[index],b'\xba\1',b'\xc8\x2c')
            def trade():
                start.wait(timeout=20);samples=[]
                a,b=peers[:2]
                for _ in range(3):
                    a.send(wire.invite_request(names[1].encode(),1));assert b.until(b'\x85')==wire.invitation(names[0].encode())
                    ask(b,wire.answer_request(True,1),b'\x87');ask(a,b'\x70',b'\x87')
                    ask(a,wire.offer_request(wire.CREDITS_ID,10),b'\x89');ask(b,b'\x70',b'\x8a')
                    ask(b,wire.offer_request(wire.CREDITS_ID,10),b'\x89');ask(a,b'\x70',b'\x8a')
                    began=time.perf_counter();ask(a,wire.confirm_request())
                    ask(b,wire.confirm_request(),b'\x8c');a.until(b'\x8c')
                    samples.append((time.perf_counter()-began)*1000)
                return samples
            with ThreadPoolExecutor(max_workers=3) as executor:
                reads=[executor.submit(reader,i) for i in (2,3)];trades=executor.submit(trade)
                report['trade_confirm_both_accounts_ms']=trades.result()
                for read in reads:read.result()
            report['equal_value_trades_settled']=3
        charges={owner:0 for owner in names}
        if args.heal:
            from tio.protocol.asset_count import decode_asset_count
            report['healing_fixture']=remote(WOUND_QA,names)
            def heal(index):
                credits=next(c for a,c,g in before['wallets'] if a==names[index])
                # Require a changed balance: old queued 9E/C839 packets are not
                # an acknowledgement of this treatment. Allow passive 1-HP ticks.
                def paid(packet):return packet.startswith(b'\xc8\x39') and credits-40<=decode_asset_count(packet).credits<credits
                return ask(peers[index],b'\x7c\1\1\0\0\0',paid)
            with ThreadPoolExecutor(max_workers=4) as executor:report['four_concurrent_treatments_ms']=list(executor.map(heal,range(4)))
            health=remote(HEALTH_STATE,names)
            assert all(v['hp']==v['maximum'] for v in health.values())
            healed=remote(__import__('verify_performance_hosted').PARTY_STATE,names)
            charges={owner:credits-next(c for a,c,g in healed['wallets'] if a==owner) for owner,credits,gold in before['wallets']}
            assert all(0<cost<=20*report['healing_fixture']['credits_per_hp'] for cost in charges.values())
            report['treatment_charges']=list(charges.values())
        after=remote(__import__('verify_performance_hosted').PARTY_STATE,names)
        assert [[a,c-charges[a],g] for a,c,g in before['wallets']]==after['wallets'] and before['inventory']==after['inventory']
        report['latency_ms']={}
        for key in results[0]:
            values=sorted(x for result in results for x in result[key]);n=len(values)
            report['latency_ms'][key]=dict(count=n,median=statistics.median(values),
                p95=values[__import__('math').ceil(.95*n)-1],max=max(values))
        report.update(passed=True,read_requests=4*3*args.rounds+(18 if args.trade else 0),qa_wallets_accounted_for_and_inventories_unchanged=True,
            limitations='City protocol load. No combat movement/shooting latency measured. Treatment uses artificial QA-only wounds. Trade and healing timings have only 3/4 samples.')
    except BaseException:
        report['error']=traceback.format_exc();raise
    finally:
        for channel in case.clients:
            try:channel.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            try:channel.close()
            except OSError:pass
        if provision is not None:
            # Closing a socket is not proof that the authoritative hub detached
            # it. Wait for server-side leave, then let disconnect finish. Never
            # delete accounts still referenced by a city session.
            cleanup_ready=not entered
            for attempt in range(10):
                if cleanup_ready:break
                time.sleep(2)
                state=remote('''
import json,subprocess
names=request
log=subprocess.check_output(['journalctl','-u','tio-server','--since','15 minutes ago','--no-pager'],text=True)
print(json.dumps(dict(detached=all('presence_leave account='+n+' ' in log for n in names))))
''',entered)
                cleanup_ready=state['detached']
            if not cleanup_ready:raise RuntimeError('QA account cleanup deferred: sessions not yet detached')
            time.sleep(2)
            if args.trade:report['trade_cleanup']=remote(TRADE_CLEANUP,names)
            report['cleanup']=[remote(sql['CLEANUP'],dict(names=names[start:start+2],protected_before=provision['protected_before'],require_unchanged_players=False)) for start in (0,2)]
        (args.report_dir/('concurrent-'+args.label+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
