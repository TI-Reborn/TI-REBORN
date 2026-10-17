"""Owned Lv4 TLS accounts: actual shared mine, second raider and price history.

Reuses audited earlier synthetic access fixtures without assigning/resetting
any level or save. Positive extraction/defender/tax use isolated SQL tests;
this live smoke test leaves the unowned checkpoint claim unchanged.
"""
import argparse
from collections import deque
from datetime import datetime,timezone
import json
from pathlib import Path
import struct
import traceback
from tools import verify_hosted_gameplay_modes as modes
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.world_bootstrap import decode_mychar_info
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
from tio.protocol.battle_move import BattleMove,encode_move_request

ROOT=Path(__file__).resolve().parents[1]

def exit_path(battle,actor):
    """Walk out of a multi-tile lift using ordinary accepted path movement."""
    blocked={tuple(p) for p in battle['blocked']};lift={tuple(p) for p in battle['lift']}
    occupied={(a['x'],a['y']) for a in battle['actors'] if a['hp'] and a['id']!=actor['id']}
    start=(actor['x'],actor['y']);queue=deque([(start,())]);seen={start}
    while queue:
        point,path=queue.popleft()
        if path and point not in lift:return path
        if len(path)>=actor['ap']:continue
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            target=(point[0]+dx,point[1]+dy)
            if target in seen or target in blocked|occupied or not (0<=target[0]<battle['width'] and 0<=target[1]<battle['height']):continue
            seen.add(target);queue.append((target,path+(target,)))
    return None
SNAPSHOT=modes.SNAPSHOT.replace("assert proven==names","assert len(proven)==6 and set(names)<=set(proven)")
SNAPSHOT=SNAPSHOT.replace("for o in room.members],","for o in room.members if o in roster],")
SNAPSHOT=SNAPSHOT.replace("actors=[dict(id=a.actor_id", "mine_help=battle.get('mine_help'),mine_raiders=battle.get('mine_raiders'),lift=list(field.mining.layout.lift),blocked=list(field.blocked),actors=[dict(id=a.actor_id")

class Fixture:
    def __init__(self,paths):
        self.fixtures=[]
        for path in paths:
            p=path.resolve();assert p.parent==Path.home()/'AppData/Local/TIO-emulator/shared-mines-qa' and not p.is_symlink()
            d=json.loads(p.read_text());assert d.pop('version')==1
            self.fixtures.append(FreshSurroundingsQA(**d))
        a,b=self.fixtures;assert len(a.names)==len(b.names)==3
        self.names=[*a.names,b.names[1]];self.passwords=[*a.passwords,b.passwords[1]];self.host=a.host
    def status(self,source):
        return self.fixtures[0].remote(SNAPSHOT,dict(names=self.names,fixtures=[f.ownership_payload() for f in self.fixtures],source_hashes=source))

class Network(modes.FourNetwork):
    def attach(self,index):
        peer=self.handoff(self.begin(index));self.received[index]=[];original=peer.receive
        def receive():
            p=original();self.received[index].append(p);return p
        peer.receive=receive;self.peers[index]=peer;records=self.case.character_screen(peer)
        name=self.fixture.names[index].encode();modes.require([(r.record_id,r.name_bytes) for r in records]==[(1,name)],'Owned primary character missing')
        peer.send(b'\x17\x01\0\0\0');modes.require(peer.receive().startswith(b'\x18'),'Native selection failed')
        peer.send(b'\x19');character=decode_mychar_info(peer.until(b'\x1a'))
        modes.require(character.character_id==1 and character.name_bytes==name,'Owned character identity changed')
        decode_asset_count(peer.until(b'\xc8\x39'));pet=decode_pet_info(peer.until(b'\x66'),human_equipment=True)
        modes.require(pet.fields['0x8c4aef']==4,'Prior audited level-four fixture required');self.ping(peer)

def run(fixture,source,report):
    before=fixture.status(source);modes.require(before['game_connections']==0 and not any(before['idle'].values()),'Server must be idle before owned verification')
    net=Network(fixture,'185.184.42.88','ti-reborn.com',29512,29513,modes.tls_context(),local_session_port=28513)
    report['step']='login'
    try:
        for i in range(4):net.attach(i)
        report['step']='native_menus'
        graph=net.command(0,b'\xb0\x21');modes.require(any(p[:2]==b'\xb0\x1f' and len(p)>=18 for p in graph),'Native real price history absent')
        menu=net.command(0,b'\xb0\x2c');modes.require(all(any(p[:2]==bytes((0xb0,c)) for p in menu) for c in (0x26,0x27,0x2b)),'Native shared round state absent')
        report['step']='queued_raiders'
        net.command(1,b'\xb0\x14\2');net.command(3,b'\xb0\x14\2')
        net.command(0,b'\xb0\x14\1')
        def battle():
            s=fixture.status(source);modes.require(len(s['checkpoints'])==1,'One shared mine required');b=s['checkpoints'][0]
            modes.require(b['kind']=='mine' and {m['account'] for m in b['members']}<=set(fixture.names),'Foreign mine participant; stop verification');return b
        b=battle();report['last_battle']=b;modes.require(len(b['members'])==2,'First queued raider not admitted alone')
        report['step']='radio_call'
        owner=next(m['owner'] for m in b['members'] if m['account']==fixture.names[1]);actor=next(a for a in b['actors'] if a['owner']==owner)
        net.command(1,encode_ability_cast(AbilityCast(28,actor['id'],0,actor['x'],actor['y'])))
        s=modes.wait_state(fixture,source,lambda s:len(s['checkpoints'])==1 and len(s['checkpoints'][0]['members'])==3);b=s['checkpoints'][0]
        modes.require({m['account'] for m in b['members']}=={fixture.names[i] for i in (0,1,3)},'Second called raider not admitted')
        modes.require(any(len(pair)==2 for pair in b['mine_raiders'].values()),'Frozen raider pair absent')
        report['step']='scene_loading'
        for i in (0,1,3):net.command(i,b'\x36')
        s=modes.wait_state(fixture,source,lambda s:s['checkpoints'] and s['checkpoints'][0]['turn'] is not None);b=s['checkpoints'][0]
        report['last_battle']=b;report['step']='lawful_exit'
        owner=next(m['owner'] for m in b['members'] if m['account']==fixture.names[0]);actor=next(a for a in b['actors'] if a['owner']==owner)
        modes.require(b['turn']==owner,'Miner initial turn required for lawful cleanup')
        path=exit_path(b,actor)
        modes.require(path is not None,'Lawful exit path unavailable within action points')
        net.command(0,encode_move_request(BattleMove(actor['id'],path)))
        for i in (0,1,3):net.command(i,b'\x2a\1');net.command(i,b'\x36')
        report['mine']=dict(connected_accounts=4,shared_human_seats=3,first_raider_fifo=True,radio_second_raider=True,one_authoritative_field=True,native_price_history=True,native_round_state=True,checkpoint_owner_changed=False,positive_extraction_hosted=False,defender_hosted=False)
    except Exception as e:
        # Public assertion text is safe; TLS peer exceptions may contain wire
        # bytes and are deliberately kept out of the evidence file.
        report['primary_error']=dict(type=type(e).__name__,message=str(e) if isinstance(e,AssertionError) else None)
        raise
    finally:
        for i in tuple(net.peers):
            try:net.command(i,b'\xb0\x19');net.command(i,b'\x2a\1');net.command(i,b'\x36')
            except Exception:pass
        net.close();final=modes.wait_state(fixture,source,lambda s:s['game_connections']==0 and not any(s['idle'].values()),seconds=210)
        report['preservation']=modes.preserve(before,final);report['cleanup']=dict(connections=final['game_connections'],retained=final['idle']);report['tls_channels']=[c.metadata() for c in net.connections]
    report.update(passed=True,source_sha256=source)
    report.pop('last_battle',None)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path,action='append',required=True);p.add_argument('--deployment',type=Path,action='append',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    assert len(a.fixture)==2 and not a.output.exists();report=dict(passed=False,timestamp_utc=datetime.now(timezone.utc).isoformat(),graphical_clients_started=0,access_level='Previously audited synthetic Lv4; not earned progression',local_player_data_uploaded=False)
    try:
        source={}
        for deployment in a.deployment:
            proof=json.loads(deployment.read_text());assert proof['source_parity']
            source.update(proof['source_sha256'])
        assert 'server/mine_requests.py' in source and 'tio/mine_rounds.py' in source
        run(Fixture(a.fixture),source,report)
    except Exception as e:report.update(error_type=type(e).__name__,error_locations=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(e.__traceback__)])
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(passed=report['passed'],report=str(a.output))));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
