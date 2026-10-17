"""Verify the deployed batch through four ordinary owned TLS game sessions.

Uses existing starter weapons; never buys equipment, assigns fixtures or resets
saves. Reversible selections finish with the original inventory and cost 2 AP.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools import verify_hosted_gameplay_modes as modes
from tio.protocol.equipment_batch import EquipmentBatchRequest,encode_equipment_batch,STAGE,COMMIT,CANCEL
from tio.protocol.item_action import ItemAction
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_list import decode_item_list

SNAPSHOT=modes.SNAPSHOT.replace("blocked=(a.x,a.y) in field.blocked)",
 "blocked=(a.x,a.y) in field.blocked,inventory_sha256=hashlib.sha256(field.combat.inventories[a.actor_id]).hexdigest(),items=[dict(id=i.instance_id,template=i.template_id,slot=i.client_slot,equipped=i.equipped) for i in __import__('tio.protocol.item_list',fromlist=['decode_item_list']).decode_item_list(field.combat.inventories[a.actor_id])[1]])")


class Fixture(modes.FourFixture):
    def status(self,hashes):
        return self.fixtures[0].remote(SNAPSHOT,dict(names=self.names,
           fixtures=[f.ownership_payload() for f in self.fixtures],source_hashes=hashes))


def hashes(paths):
    values={}
    for path in paths:
        proof=json.loads(path.read_text(encoding='utf-8'))
        modes.require(proof.get('source_parity') is True,'Successful deployed source proof required')
        values.update(proof['source_sha256'])
    required={'tio/arena_equipment.py','tio/equipment_batch.py','tio/protocol/equipment_batch.py','tio/arena_service.py','server/team_arena.py'}
    modes.require(required<=values.keys(),'Equipment source proof incomplete')
    for name,digest in values.items():
        modes.require('..' not in Path(name).parts and not Path(name).is_absolute() and len(digest)==64,'Unsafe reviewed source proof')
    return {str(Path('/opt/tio-emulator')/name).replace('\\','/'):value for name,value in values.items()}


def run(fixture,args,report,source):
    before=fixture.status(source)
    modes.require(before['game_connections']==0 and not any(before['idle'].values()),'Other sessions or retained battles present')
    modes.validate_resumed_state(before,fixture.names)
    net=modes.FourNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,
       modes.tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        for index in range(4):net.attach(index,net.begin(index),fresh=False,expected_wallet=before['states'][index]['wallet'])
        offsets={i:len(net.received[i]) for i in range(4)}
        for index in range(4):net.command(index,b'\xba\x03\0\x01')
        active,battle=modes.load_battle(net,fixture,source,tuple(range(4)),offsets)
        owner=battle['turn'];index=next(i for i,n in enumerate(fixture.names) if any(m['account']==n and m['owner']==owner for m in battle['members']))
        actor=next(a for a in battle['actors'] if a['owner']==owner)
        gun=next(i for i in actor['items'] if i['template']==301)
        modes.require(not gun['equipped'] and gun['slot']==0,'Unmodified ordinary starter gun required')
        def request(operation,*,batch=1,identity=None,instance=None,option=255,target=index):
            action=ItemAction(actor['id'] if identity is None else identity,gun['id'] if instance is None else instance,option) if operation==STAGE else None
            return net.command(target,encode_equipment_batch(EquipmentBatchRequest(operation,batch,action)))
        def current():return modes.one_battle(fixture.status(source),tuple(range(4)),fixture.names)
        def self_actor():return next(a for a in current()['actors'] if a['id']==actor['id'])
        # Stage primary, secondary, then remove: no saved/in-memory change until OK.
        starts={i:len(net.received[i]) for i in range(4)}
        for option in (4,7,255):
            packets=request(STAGE,option=option)
            modes.require(any(p[0]==0x30 for p in packets),'Private inventory preview missing')
            modes.require(self_actor()['inventory_sha256']==actor['inventory_sha256'] and self_actor()['ap']==actor['ap'],'Stage changed authoritative gear or AP')
        net.sync()
        for target in range(4):
            if target!=index:
                modes.require(not any(p[0]==0x30 and decode_item_list(p)[0]==actor['id'] for p in net.received[target][starts[target]:]),'Another account received private inventory')
        request(COMMIT)
        changed=self_actor();modes.require(changed['ap']==actor['ap']-2 and changed['inventory_sha256']==actor['inventory_sha256'],'Atomic confirmation cost or restored final inventory differs')
        request(COMMIT);modes.require(self_actor()==changed,'Duplicate confirmation changed authoritative state')
        request(STAGE,batch=2,option=4);request(CANCEL,batch=2)
        request(COMMIT,batch=2);modes.require(self_actor()==changed,'Cancelled preview changed authoritative state')
        other=next(a for a in battle['actors'] if a['owner']!=owner)
        request(STAGE,batch=3,identity=other['id']);modes.require(self_actor()==changed,'Foreign actor selection changed own state')
        request(STAGE,batch=4,option=4);request(STAGE,batch=4,instance=0xffffffff)
        request(COMMIT,batch=4);modes.require(self_actor()==changed,'Invalid middle selection left a committable batch')
        request(STAGE,batch=5,option=4);net.command(index,encode_end_turn())
        request(COMMIT,batch=5)
        modes.require(next(a for a in current()['actors'] if a['id']==actor['id'])['inventory_sha256']==actor['inventory_sha256'],'Turn end applied an unconfirmed preview')
        report['equipment']=dict(real_accounts=4,stage_private=True,stage_no_ap_or_saved_change=True,
          three_changes_one_confirmation_ap=2,duplicate_no_second_charge=True,cancel=True,
          foreign_actor_rejected=True,invalid_middle_cancels=True,turn_end_cancels=True)
        for target in range(4):net.command(target,b'\x2a\x01')
        after=modes.wait_state(fixture,source,lambda s:not s['checkpoints'] and not s['leases'] and not any(s['idle'].values()))
        modes.require(modes.balances(before)==modes.balances(after),'Equipment check changed owned wallets')
    finally:
        for target in tuple(net.peers):
            try:net.command(target,b'\x2a\x01')
            except Exception:pass
        net.close();report['tls_channels']=[c.metadata() for c in net.connections]
        final=modes.wait_state(fixture,source,lambda s:s['game_connections']==0)
        report['foreign_preservation']=modes.preserve(before,final)
        report['cleanup']=dict(connections=final['game_connections'],retained=final['idle'],leases=len(final['leases']))
    report.update(passed=True,source_sha256=source)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',action='append',type=Path,required=True)
    parser.add_argument('--deployment',action='append',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--host',default='185.184.42.88');parser.add_argument('--server-name',default='ti-reborn.com')
    parser.add_argument('--login-port',type=int,default=29512);parser.add_argument('--session-port',type=int,default=29513)
    parser.add_argument('--loopback-session-port',type=int,default=28513);parser.add_argument('--ca-file',type=Path)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Preserve existing evidence')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),graphical_clients_started=0,
       limitations=['automated original packet/TLS validation; graphical client acceptance separate',
                    'hosted test uses the ordinary starter weapon; complete armor set and storage-fault rollback verified in isolated automated tests'])
    try:
        loaded=modes.load_fixtures(args.fixture);run(Fixture(loaded.fixtures),args,report,hashes(args.deployment))
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__
        report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
    with args.output.open('x',encoding='utf-8') as output:json.dump(report,output,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
