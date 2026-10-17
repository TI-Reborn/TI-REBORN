"""Four ordinary hosted accounts buy/use smoke and flash through native TLS."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools import verify_hosted_gameplay_modes as modes
from tools.verify_hosted_equipment_batch import SNAPSHOT as BASE,hashes
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.item_list import decode_item_list
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.equipment_batch import EquipmentBatchRequest,encode_equipment_batch,STAGE,COMMIT
from tio.protocol.item_action import ItemAction
from tio.protocol.battle_item_visuals import decode_item_visuals

SNAPSHOT=BASE.replace("slot=i.client_slot,equipped=i.equipped)","slot=i.client_slot,equipped=i.equipped,count=i.count)")
SNAPSHOT=SNAPSHOT.replace("members=[dict(owner=o,account=roster[o][0]",
 "effects=__import__('copy').deepcopy(getattr(field.combat,'item_effects',{})),targets={a.actor_id:[[x,y] for y in range(max(0,a.y-5),min(field.height,a.y+6)) for x in range(max(0,a.x-5),min(field.width,a.x+6)) if (x,y) not in field.blocked and 2<=max(abs(a.x-x),abs(a.y-y))<=5] for a in field._actors.values()},members=[dict(owner=o,account=roster[o][0]")
SNAPSHOT=SNAPSHOT.replace("states.append(dict(account=n,", "credit_rewards=sum(json.loads(body).get('temporary_credits',0) for body,position in db.execute('SELECT a.body,p.position FROM achievement_awards a JOIN achievement_prizes p ON p.account=a.account AND p.id=a.id WHERE a.account=? AND p.delivered=1',(n,)) if position==len(json.loads(body)['prizes'])) if 'achievement_prizes' in tables else 0\n  states.append(dict(delivered_credit_rewards=credit_rewards,account=n,")

class Fixture(modes.FourFixture):
    def status(self,source):return self.fixtures[0].remote(SNAPSHOT,dict(names=self.names,
        fixtures=[f.ownership_payload() for f in self.fixtures],source_hashes=source))

def run(fixture,args,report,source):
    before=fixture.status(source)
    modes.require(before['game_connections']==0 and not any(before['idle'].values()),'Other sessions or retained battles')
    modes.require(all(len(s['pets'])==1 and s['pets'][0]['progression']['0x8c4aef']==1 for s in before['states']),'Ordinary saved starter roster required')
    net=modes.FourNetwork(fixture,args.host,args.server_name,29512,29513,modes.tls_context(),local_session_port=28513)
    offers=json.loads((ROOT/'config/city_catalogs.json').read_text())['item_categories']['0']
    try:
        for index in range(4):net.attach(index,net.begin(index),fresh=False,expected_wallet=before['states'][index]['wallet'])
        for index in range(4):
            for template in (318,320):
                offer=next(o for o in offers if o['item_id']==template)
                replies=net.command(index,encode_shop_purchase(ShopPurchase(1,0,offer['unknown_u32_01'],1)))
                modes.require(any(p[0]==0x30 and any(i.template_id==template for i in decode_item_list(p)[1]) for p in replies),'Native owned item purchase failed')
        offsets={i:len(net.received[i]) for i in range(4)}
        for index in range(4):net.command(index,b'\xba\3\0\1')
        _,battle=modes.load_battle(net,fixture,source,tuple(range(4)),offsets)
        def current():return modes.one_battle(fixture.status(source),tuple(range(4)),fixture.names)
        owner=battle['turn'];index=next(i for i,n in enumerate(fixture.names) if any(m['account']==n and m['owner']==owner for m in battle['members']))
        actor=next(a for a in battle['actors'] if a['owner']==owner);nonce=1
        def use(template):
            nonlocal nonce
            state=current();present=next(a for a in state['actors'] if a['id']==actor['id'])
            item=next(i for i in present['items'] if i['template']==template)
            net.command(index,encode_equipment_batch(EquipmentBatchRequest(STAGE,nonce,ItemAction(actor['id'],item['id'],4))))
            net.command(index,encode_equipment_batch(EquipmentBatchRequest(COMMIT,nonce)));nonce+=1
            target=state['targets'][str(actor['id'])][0]
            packets=net.command(index,encode_attack_request(AttackRequest(actor['id'],*target)))
            after=current();updated=next(a for a in after['actors'] if a['id']==actor['id'])
            remaining=sum(i['count'] for i in updated['items'] if i['id']==item['id'])
            modes.require(remaining==item['count']-1,'Authoritative item quantity did not decrease once')
            modes.require(updated['ap']==present['ap']-2-(7 if template==318 else 6),'Item use AP differs')
            modes.require(any(p[0]==0x4b for p in packets),'Native attack result missing')
            modes.require(any(p[0]==0xf7 for p in packets),'Recipient item visual snapshot missing')
            for p in packets:
                if p[0]==0xf7:decode_item_visuals(p)
            return after
        smoke=use(318);modes.require(smoke['effects']['areas'],'Authoritative smoke area absent')
        # Finish a full human turn circle, then use the other ordinary item.
        for _ in range(4):
            state=current();who=state['turn'];target=next(i for i,n in enumerate(fixture.names) if any(m['account']==n and m['owner']==who for m in state['members']))
            net.command(target,encode_end_turn())
        use(320)
        report['items']=dict(real_accounts=4,ordinary_purchases=True,smoke_consumed=True,flash_consumed=True,
            smoke_shared_state=True,native_attack_results=True,recipient_f7_validated=True,costs_including_equipment=[9,8])
        for target in range(4):net.command(target,b'\x2a\1')
        after=modes.wait_state(fixture,source,lambda s:not s['checkpoints'] and not s['leases'] and not any(s['idle'].values()))
        awards=[a['delivered_credit_rewards']-b['delivered_credit_rewards'] for a,b in zip(after['states'],before['states'])]
        expected=[[w[0]-330+award,w[1]] for w,award in zip(modes.balances(before),awards)]
        report['wallets_before']=modes.balances(before);report['wallets_after']=modes.balances(after)
        report['delivered_achievement_credit_rewards']=awards
        modes.require(modes.balances(after)==expected,'Lawful shop debits and durable achievement rewards differ')
        report['purchase_debits_per_account']=330
    finally:
        for target in tuple(net.peers):
            try:net.command(target,b'\x2a\1')
            except Exception:pass
        net.close();final=modes.wait_state(fixture,source,lambda s:s['game_connections']==0)
        report['foreign_preservation']=modes.preserve(before,final)
        report['cleanup']=dict(connections=final['game_connections'],retained=final['idle'],leases=len(final['leases']))
        report['tls_channels']=[c.metadata() for c in net.connections]
    report.update(passed=True,source_sha256=source)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--fixture',action='append',type=Path,required=True)
    parser.add_argument('--deployment',action='append',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--host',default='185.184.42.88');parser.add_argument('--server-name',default='ti-reborn.com');args=parser.parse_args()
    if args.output.exists():raise ValueError('Preserve previous evidence')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),graphical_clients_started=0,
        limitations=['Automated native TLS sessions; no graphical-client acceptance',
        'Hosted level-one accounts validate smoke/flash. Gold/level-gated optics and boosters validated in isolated multiaccount tests/native client harness.'])
    try:
        loaded=modes.load_fixtures(args.fixture);run(Fixture(loaded.fixtures),args,report,hashes(args.deployment))
    except BaseException as error:
        import traceback
        report.update(error_type=type(error).__name__,error_locations=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)])
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False)))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
