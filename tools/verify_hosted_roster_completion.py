"""Ordinary owned-account roster/tutorial QA over verified hosted TLS.

Provision delegates ONLY accounts creation to Stage7Fixture after its fresh
integrity-checked hosted backup. All later remote SQL is read-only. Never writes
levels, money, inventory, character ownership or runtime code administratively.
No graphical client is launched, and no credentials or raw auth packets print.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time
import zlib
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_hosted_stage7 import Stage7Fixture,PRESERVATION
from tools.verify_hosted_arena_surroundings import OWNERSHIP,require
from tools.verify_game_tls_hosted import TlsNetworkQA,tls_context
from tio.appearance import encode_request as appearance_request
from tio.protocol.character_create import CharacterCreateRequest,encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.world_bootstrap import decode_mychar_info
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.city_catalogs import decode_pet_shop,decode_service_shop
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.shared_config import decode_shared_config_data
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.hire import encode_hire_request
from tio.protocol.proficiency_decrease import ProficiencyDecrease,encode_proficiency_decrease
from tio.protocol.abilities import decode_abilities
from tio.weapon_proficiency import SAVED,number

PHASES=('stage1-modes','stage2-equipment','stage3-items','stage4-mines','stage5-roster')


def deployment_hashes(directory):
    """Pin deployed revisions; local sources can legitimately be the next phase."""
    result={};previous=''
    for phase in PHASES:
        proof=json.loads((Path(directory)/phase/'deployment.json').read_text(encoding='utf-8'))
        require(proof.get('source_parity') is True,'Reviewed successful source parity required')
        stamp=proof.get('timestamp_utc','');require(isinstance(stamp,str) and stamp>=previous,'Deployment proofs must be ordered');previous=stamp
        values=proof.get('source_sha256');require(isinstance(values,dict) and 1<=len(values)<=512,'Bounded source proof required')
        for path,digest in values.items():
            require(isinstance(path,str) and re.fullmatch(r'(?:tio|server|tools|config|evidence)/[A-Za-z0-9_./-]+',path) and '..' not in Path(path).parts,'Unsafe source path')
            require(isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest),'Invalid source digest')
        result.update(values)
    require({'server/tutorial_arena.py','tio/roster_progression.py','tio/ability_progression.py','tio/services.py','tools/loopback_exchange.py','config/tutorial.json'}<=result.keys(),'Roster deployment coverage missing')
    return result


SNAPSHOT=OWNERSHIP+r'''
import hashlib,subprocess
from tio.battle_snapshot import loads
from tio.protocol.pet_info import decode_pet_info
from tio.weapon_proficiency import SAVED,number
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN');tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 def owned_rows(table,account):
  if table not in tables:return dict(rows=0,sha256=hashlib.sha256(b'[]').hexdigest())
  rows=sorted(map(repr,db.execute('SELECT * FROM "'+table+'" WHERE account=?',(account,))))
  return dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
 states=[]
 for account in names:
  character=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
  assert not ('character_identities' in tables and db.execute('SELECT 1 FROM character_identities WHERE login=?',(account,)).fetchone()),'Only ordinary primary characters allowed'
  wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone() if 'wallets' in tables else None
  pets=[]
  for identity,human,raw,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)) if 'owned_pets' in tables else []:
   f=decode_pet_info(raw,human_equipment=bool(human)).fields
   pets.append(dict(id=identity,human=bool(human),resource=f['0x8c446f'],name=f['0x8c4489'].decode('cp1251'),level=f['0x8c4aef'],xp=f['0x8c4b05'],hp=f['0x8c4ab1'],skills=[number(f[k]) for k in SAVED],packet_sha256=hashlib.sha256(raw).hexdigest(),inventory_sha256=hashlib.sha256(inventory).hexdigest()))
  tutorial=db.execute('SELECT step,match_id,completed,observed_events FROM character_tutorials WHERE account=?',(account,)).fetchone() if 'character_tutorials' in tables else None
  service=db.execute('SELECT level FROM paid_services WHERE account=? AND service=2',(account,)).fetchone() if 'paid_services' in tables else None
  protected={t:owned_rows(t,account) for t in ('battle_rewards','player_battle_statistics','soldier_ratings','experience_battle_audit','rank_battle_audit','player_statistics_baselines','achievement_counters','achievement_awards','achievement_prizes','soldier_ranks','ranked_players')}
  states.append(dict(account=account,character=character[0].decode('cp1251') if character else None,wallet=list(wallet) if wallet else None,pets=pets,tutorial=dict(zip(('step','match','completed','events'),tutorial)) if tutorial else None,roster_service=service[0] if service else 0,protected=protected))
 checkpoints=[]
 if 'battle_checkpoints' in tables:
  for account in names:
   row=db.execute('SELECT c.match_id,c.payload,c.status FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(account,)).fetchone()
   if not row:continue
   battle=loads(row[1])[0]['battle'];field=battle['field'];room=battle['room'];turn=battle['arena']._turns.get(room.room_id)
   assert battle.get('kind')=='tutorial' and {r[0] for r in battle['reward_roster'].values()}=={account},'Unrelated account or non-tutorial checkpoint'
   assert len(battle['humans'])==1 and len(battle['bots'])==1,'Private tutorial composition differs'
   checkpoints.append(dict(account=account,match=row[0],status=row[2],finished=battle['finished'],events=battle['tutorial_events'],player=battle['tutorial_player'],target=battle['tutorial_target'],turn=turn[0] if turn else None,loading=len(battle['arena']._loading[room.room_id]),blocked=list(field.blocked),width=field.width,height=field.height,ground_sha256=hashlib.sha256(battle['ground']).hexdigest(),actors=[dict(id=a.actor_id,owner=a.owner_id,x=a.x,y=a.y,hp=a.health,ap=a.action_points) for a in field._actors.values()]))
 foreign={}
 for table in sorted(tables-{'sqlite_sequence'}):
  quoted='"'+table.replace('"','""')+'"';columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
  column=next((c for c in ('account','login','owner') if c in columns),None)
  if column:
   rows=sorted(map(repr,db.execute('SELECT * FROM '+quoted+' WHERE "'+column+'" NOT IN (?,?)',names)))
   foreign[table]=dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
 global_tables=('territory_claims','territory_claim_history','mine_claims','mine_claim_history','warfare_events','warfare_matches','warfare_scores','ranked_matches')
 global_state={t:dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest()) for t in global_tables for rows in [sorted(map(repr,db.execute('SELECT * FROM "'+t+'"'))) if t in tables else []]}
 idle={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] if t in tables else 0 for t in ('battle_checkpoints','battle_settlement_jobs')}
 sources={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in data['source_hashes']};assert sources==data['source_hashes'],'Reviewed deployed source changed'
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0];assert integrity=='ok'
connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip()
print(json.dumps(dict(states=states,checkpoints=checkpoints,foreign=foreign,global_state=global_state,idle=idle,integrity=integrity,game_connections=connections,source_sha256=sources,service=service)))
'''


def status(fixture,hashes):
    return fixture.remote(SNAPSHOT,{**fixture.ownership_payload(),'source_hashes':hashes})


def one(replies,prefix):
    rows=[p for p in replies if p.startswith(prefix)];require(bool(rows),'Expected native reply '+prefix.hex());return rows[-1]


def matching_pet(replies,*,identity=None,name=None,resource=None):
    rows=[]
    for packet in replies:
        if packet[:1]!=b'\x66':continue
        pet=decode_pet_info(packet,human_equipment=True);fields=pet.fields
        if identity is not None and fields['0x8c43eb']!=identity:continue
        if name is not None and fields['0x8c4489']!=name:continue
        if resource is not None and fields['0x8c446f']!=resource:continue
        rows.append(pet)
    require(bool(rows),'Matching owned native pet reply missing');return rows[-1]


def scene(state,account):
    rows=[s for s in state['checkpoints'] if s['account']==account];require(len(rows)==1,'Expected one owned tutorial scene');return rows[0]


def actor(scene,identity):return next(a for a in scene['actors'] if a['id']==identity)


def wait_state(fixture,hashes,predicate,*,seconds=12):
    deadline=time.monotonic()+seconds
    while True:
        state=status(fixture,hashes)
        if predicate(state):return state
        require(time.monotonic()<deadline,'Owned state deadline exceeded');time.sleep(.15)


class RosterNetwork(TlsNetworkQA):
    def ask(self,index,packet,prefix):
        start=len(self.received[index]);peer=self.peers[index];peer.send(packet)
        peer.until(prefix,max_packets=4096);self.ping(peer)
        return self.received[index][start:]

    def ask_pet(self,index,packet,*,identity,name,resource,skill,value):
        """Wait for the requested actor/value, skipping unrelated async66 updates."""
        start=len(self.received[index]);peer=self.peers[index];peer.send(packet)
        for _ in range(4096):
            reply=peer.receive()
            if reply[:1]!=b'\x66':continue
            fields=decode_pet_info(reply,human_equipment=True).fields
            if (fields['0x8c43eb'],fields['0x8c4489'],fields['0x8c446f'])!=(identity,name,resource):continue
            if number(fields[SAVED[skill]])!=value:continue
            self.ping(peer);return self.received[index][start:]
        raise AssertionError('Matching native skill change reply missing')

    def attach(self,index,*,fresh=False):
        peer=self.handoff(self.begin(index));self.received[index]=[];original=peer.receive
        def receive():
            packet=original();self.received[index].append(packet);return packet
        peer.receive=receive;self.peers[index]=peer;records=self.case.character_screen(peer);name=self.fixture.names[index].encode()
        if fresh:
            require(not records,'Fresh empty character screen required')
            peer.send(encode_character_create(CharacterCreateRequest(name,0,(index+1,0,0,0))))
            require(peer.receive()==b'\x12\x05','Ordinary type1/type2 creation rejected');editing=decode_character_list(peer.receive())
            require(len(editing)==1 and editing[0].record_id==1 and editing[0].resource_type==index+1 and len(editing[0].optional_six)==6,'New free appearance step missing')
            peer.send(appearance_request(1,editing[0].optional_six));records=decode_character_list(peer.until(b'\x10'))
        require([(r.record_id,r.name_bytes) for r in records]==[(1,name)],'Only owned primary slot expected')
        peer.send(b'\x17\x01\0\0\0');require(peer.receive()[:1]==b'\x18','Owned selection rejected')
        peer.send(b'\x19');character=decode_mychar_info(peer.until(b'\x1a'));require((character.character_id,character.name_bytes)==(1,name),'MyCharInfo belongs to another slot')
        assets=decode_asset_count(peer.until(b'\xc8\x39'));peer.until(b'\x66');self.ping(peer)
        pet=matching_pet(self.received[index],identity=1,name=name,resource=index+1)
        require(pet.fields['0x8c4aef']==1 and pet.fields['0x8c4b05']==0,'Unexpected starter level/XP')
        return assets

    def detach(self,index):
        peer=self.peers.pop(index,None)
        if peer is not None:peer.sock.close()

    def services_xml(self,index):
        packet=next(p for p in self.received[index] if p.startswith(b'\xb9\x03services\0'))
        value=decode_shared_config_data(packet);raw=zlib.decompress(value.compressed_bytes);require(len(raw)==value.decompressed_size,'Services config length differs')
        root=ET.fromstring(raw);levels=[(int(e.get('val')),int(e.get('power'))) for e in root.find("service[@id='2']")]
        require(levels==[(1,1),(2,2),(3,3),(4,4),(5,5)],'Shared services config is limited to old roster tiers')
        return dict(network_delivered=True,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),roster_levels=levels)


def phase(label):print(json.dumps(dict(phase=label,credentials_printed=False)),flush=True)


def run(fixture,args,report,hashes):
    before=status(fixture,hashes);require(before['game_connections']==0 and not any(before['idle'].values()),'Players or retained battles present before QA')
    require(all(s['character'] is None and not s['pets'] for s in before['states']),'Fresh owned accounts required; never reset a partial QA')
    net=RosterNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        phase('ordinary_creation_and_automatic_tutorial')
        for index in (0,1):
            assets=net.attach(index,fresh=True);require([assets.credits,assets.gold]==[3000,0],'Starter wallet differs')
        created=status(fixture,hashes);report['creation']=dict(types=[1,2],appearance_completed=True,owned_primary_slots=True,starter_counts=[len(s['pets']) for s in created['states']],services_xml=[net.services_xml(i) for i in (0,1)])
        require(all([p['id'] for p in s['pets']]==[1,2,3] and all(p['level']==1 and p['xp']==0 for p in s['pets']) for s in created['states']),'Main plus two first-level starters required')
        scenes=[scene(created,n) for n in fixture.names];require(scenes[0]['match']!=scenes[1]['match'],'Accounts share a tutorial scene')
        require(all(s['tutorial']['events']==0 and s['tutorial']['match'] is not None for s in created['states']),'Fresh tutorial auto-start missing')
        original_profiles=[s['pets'] for s in created['states']];original_protected=[s['protected'] for s in created['states']]
        report['creation_profiles']=original_profiles
        for index in (0,1):net.command(index,b'\x36')
        state=wait_state(fixture,hashes,lambda s:all(scene(s,n)['turn']==actor(scene(s,n),scene(s,n)['player'])['owner'] for n in fixture.names))
        phase('accepted_movement_isolation_and_reconnect')
        a=scene(state,fixture.names[0]);player=actor(a,a['player']);move=encode_move_request(BattleMove(player['id'],((player['x'],player['y']+1),)))
        replies=net.command(0,move);require(any(p[:1]==b'\x3d' and decode_battle_move(p).actor_id==player['id'] for p in replies),'Native movement did not succeed')
        moved=status(fixture,hashes);require(moved['states'][0]['tutorial']['events']==1 and moved['states'][1]['tutorial']['events']==0,'Movement facts leaked to other account')
        report['isolated_tutorials']=dict(separate_match_ids=True,one_real_account_each=True,movement_private=True)
        first_match=a['match'];moved_actor=actor(scene(moved,fixture.names[0]),a['player']);net.detach(0)
        wait_state(fixture,hashes,lambda s:s['game_connections']==1)
        net.attach(0);resumed=status(fixture,hashes);a=scene(resumed,fixture.names[0]);require(a['match']==first_match and actor(a,a['player'])==moved_actor and a['events']==1,'Native reconnect lost scene/AP/movement facts')
        net.command(0,b'\x36');report['tutorial_reconnect']=dict(same_checkpoint=True,same_position_ap=True,progress_preserved=True)
        phase('native_end_turn_attacks_kill_and_zero_reward_completion')
        for index in (0,1):
            if index:
                b=scene(status(fixture,hashes),fixture.names[index]);p=actor(b,b['player'])
                net.command(index,encode_move_request(BattleMove(p['id'],((p['x'],p['y']+1),))))
            net.command(index,encode_end_turn())
            attacks=0;hits=0;summary=None
            for _ in range(40):
                current=status(fixture,hashes);owned=current['states'][index]
                if owned['tutorial']['completed']:break
                battle=scene(current,fixture.names[index]);p=actor(battle,battle['player']);target=actor(battle,battle['target'])
                if battle['turn']!=p['owner'] or p['ap']<3:
                    if battle['turn']==p['owner']:net.command(index,encode_end_turn())
                    time.sleep(.2);net.ping(net.peers[index]);continue
                replies=net.command(index,encode_attack_request(AttackRequest(p['id'],target['x'],target['y'])))
                # Shared hub broadcasts can arrive after the keepalive ACK.
                # Observe durable action facts on the next iteration and audit
                # all received native4B packets after terminal drainage.
                attacks+=1
                summaries=[p for p in replies if p[:1]==b'\x4c']
                if summaries:summary=summaries[-1]
            final=wait_state(fixture,hashes,lambda s:bool(s['states'][index]['tutorial']['completed']))
            require(final['states'][index]['tutorial']==dict(step=4,match=None,completed=1,events=15),'Tutorial completion differs from four accepted facts')
            net.ping(net.peers[index]);net.ping(net.peers[index])
            native_attacks=[decode_attack_result(packet) for packet in net.received[index] if packet[:1]==b'\x4b']
            require(native_attacks,'No native attack result observed')
            hits=sum(hit.damage>0 for attack in native_attacks for hit in attack.hits)
            if summary is None:
                rows=[p for p in net.received[index] if p[:1]==b'\x4c'];require(rows,'Native tutorial result missing');summary=rows[-1]
            require(len(summary)==29 and summary[3]==1 and not any(struct.unpack_from('<6I',summary,4)) and summary[28]==0,'Training granted a nonzero native reward')
            require(final['states'][index]['wallet']==[3000,0] and final['states'][index]['pets']==original_profiles[index] and final['states'][index]['protected']==original_protected[index],'Training mutated durable economy/progression/profile rewards')
            report.setdefault('tutorial_completion',[]).append(dict(account_index=index,attack_requests=attacks,native_4b_results=len(native_attacks),positive_hits=hits,events=15,native_4c_zero_rewards=True,wallet_unchanged=True,profiles_inventory_xp_unchanged=True,statistics_rewards_unchanged=True))
            net.command(index,b'\x2a\x01')
        city=wait_state(fixture,hashes,lambda s:not s['checkpoints'] and not any(s['idle'].values()))
        # Re-enter through the real character selector after native result
        # teardown, so subsequent services use the ordinary city session.
        for index in (0,1):net.detach(index)
        wait_state(fixture,hashes,lambda s:s['game_connections']==0)
        for index in (0,1):net.attach(index)
        phase('ordinary_random_hire_and_roster_service')
        replies=net.command(0,b'\x61');quote=one(replies,b'\x62');offers=decode_pet_shop(quote)
        require(one(net.command(0,b'\x61'),b'\x62')==quote,'Refreshing a random quote rerolled it')
        recruit=next(o for o in offers if o.resource_type in (1,2));require(recruit.price_credits==500 and recruit.candidate_id>=0x40000000 and recruit.optional_bytes is not None,'Actual human random hire quote invalid')
        replies=net.command(0,encode_hire_request(recruit.candidate_id));assets=decode_asset_count(one(replies,b'\xc8\x39'));hired=matching_pet(replies,identity=4,name=recruit.name,resource=recruit.resource_type)
        require(assets.credits==2500 and hired.fields['0x8c4489']==recruit.name and hired.fields['0x8c4aef']==1,'Native hire not charged/delivered as quoted')
        after_hire=status(fixture,hashes);require(len(after_hire['states'][0]['pets'])==4 and after_hire['states'][1]['pets']==city['states'][1]['pets'],'Hire affected foreign roster')
        report['random_hire']=dict(native_61_62_63=True,quoted_cost=500,new_pet_id=hired.fields['0x8c43eb'],stable_quote=True,delivered_random_name_appearance=True,other_account_isolated=True)
        catalog=decode_service_shop(one(net.ask(1,b'\xb1\x02',b'\xb1\x03'),b'\xb1\x03'));offer=next(o for o in catalog if o.unknown_u32==2)
        require(offer.options[0].unknown_u8==1 and offer.options[0].unknown_u32==2000,'Roster expansion quote differs')
        purchase=b'\xb1\x04\0'+struct.pack('<I',2)+b'\1'+struct.pack('<I',1)
        replies=net.command(1,purchase);require(decode_asset_count(one(replies,b'\xc8\x39')).credits==1000,'Expansion did not debit2000')
        net.command(1,purchase);expanded=status(fixture,hashes)
        require(expanded['states'][1]['roster_service']==1 and expanded['states'][1]['wallet']==[1000,0] and expanded['states'][0]['roster_service']==0,'Expansion replay/account binding differs')
        report['roster_expansion']=dict(native_b104=True,capacity_before=7,capacity_after=8,charged_credits=2000,replay_no_second_charge=True,other_account_isolated=True,higher_tiers='network XML proved; unaffordable on ordinary starter')
        phase('native_decreaseability_and_level1_perk_limit')
        name=expanded['states'][0]['pets'][0]['name']
        before_skill=number(matching_pet(net.received[0],identity=1,name=name.encode('cp1251'),resource=1).fields[SAVED[1]])
        require(before_skill>=5,'Starter native light skill too low for lawful decrease')
        replies=net.ask_pet(0,encode_proficiency_decrease(ProficiencyDecrease(name,'light')),identity=1,name=name.encode('cp1251'),resource=1,skill=1,value=before_skill-5)
        changed=matching_pet(replies,identity=1,name=name.encode('cp1251'),resource=1)
        require(number(changed.fields[SAVED[1]])==before_skill-5 and decode_asset_count(one(replies,b'\xc8\x39')).credits==1500,'Native skill decrease did not apply5/1000')
        after_skill=status(fixture,hashes);require(after_skill['states'][0]['pets'][0]['skills'][1]==before_skill-5 and after_skill['states'][1]==expanded['states'][1],'Skill decrease leaked to other account')
        learned=decode_abilities(one(net.command(0,b'\xc8\x12\x01\0\0\0'),b'\x80'))[1]
        require(not learned,'Level1 starter unexpectedly has learned perks')
        report['skill_decrease']=dict(native_console_chat21=True,skill='light',decreased=5,charged_credits=1000,other_account_isolated=True)
        report['forgetting']=dict(hosted_positive=False,reason='ordinary level1 starter has no learned perks; isolated/native proof retained')
        for index in (0,1):net.detach(index)
        wait_state(fixture,hashes,lambda s:s['game_connections']==0)
        for index,credits in ((0,1500),(1,1000)):
            require(net.attach(index).credits==credits,'Native relogin lost lawful wallet')
            rows=[p for p in net.received[index] if p[:1]==b'\x35'];require(not rows,'Completed tutorial restarted after relogin');net.detach(index)
        report['lawful_leave_and_relogin']=True
    finally:
        cleanup=[]
        for index in tuple(net.peers):
            try:net.command(index,b'\x2a\x01');cleanup.append(dict(account_index=index,native_leave_attempted=True))
            except Exception:cleanup.append(dict(account_index=index,native_leave_attempted=True,connection_unavailable=True))
        net.close();report['cleanup_attempts']=cleanup;report['tls_channels']=[c.metadata() for c in net.connections]
        try:
            released=wait_state(fixture,hashes,lambda s:s['game_connections']==0 and not any(s['idle'].values()),seconds=190)
            report['cleanup_owned_release']=dict(game_connections=released['game_connections'],retained_battles=released['idle']['battle_checkpoints'],settlement_jobs=released['idle']['battle_settlement_jobs'],integrity=released['integrity'])
        except Exception as cleanup_error:
            report['cleanup_error_type']=type(cleanup_error).__name__
    after=wait_state(fixture,hashes,lambda s:s['game_connections']==0 and not any(s['idle'].values()),seconds=190)
    require(after['global_state']==before['global_state'] and after['service']==before['service'],'Unrelated world or game service changed')
    require(all(after['foreign'].get(t)==v for t,v in before['foreign'].items()),'Pre-existing account rows changed')
    report.update(source_sha256=hashes,service_unchanged=True,existing_account_rows_preserved=True,global_claims_matches_unchanged=True,disconnected_game_connections=0,retained_battles=0,
        preservation=fixture.remote(PRESERVATION,fixture.ownership_payload()),passed=True)


def continue_owned(fixture,args,report,hashes):
    """Finish a preserved run after its two fresh tutorials and one lawful hire.

    No reset/reprovision/backfill: require the exact already-observed checkpoint
    completion/profile hashes and500-credit hire, then continue native actions.
    """
    prior_path=args.prior_report.resolve();prior_raw=prior_path.read_bytes();prior=json.loads(prior_raw)
    require(prior_path.parent==(ROOT/'reports/gameplay-completion/stage5-roster').resolve(),'Only this phase preserved evidence may be continued')
    require(len(prior.get('tutorial_completion',()))==2 and all(r['events']==15 and r['native_4c_zero_rewards'] and r['profiles_inventory_xp_unchanged'] and r['statistics_rewards_unchanged'] for r in prior['tutorial_completion']),'Both fresh tutorial completions must already be proven')
    require(prior.get('random_hire',{}).get('quoted_cost')==500 and prior.get('cleanup_owned_release',{}).get('retained_battles')==0,'Expected preserved500-credit hire and released scenes')
    before=status(fixture,hashes);require(before['game_connections']==0 and not any(before['idle'].values()),'Continuation requires idle hosted game')
    service_paid=before['states'][1]['roster_service']==1
    require([s['wallet'] for s in before['states']]==[[2500,0],[1000 if service_paid else 3000,0]] and [len(s['pets']) for s in before['states']]==[4,3] and before['states'][0]['roster_service']==0 and before['states'][1]['roster_service'] in (0,1) and all(s['tutorial']==dict(step=4,match=None,completed=1,events=15) for s in before['states']),'Partial run differs; never reset or repeat its paid actions')
    require([s['pets'][:3] for s in before['states']]==prior['creation_profiles'],'Original tutorial starter profiles changed before continuation')
    for field in ('creation','creation_profiles','isolated_tutorials','tutorial_reconnect','tutorial_completion','random_hire'):report[field]=prior[field]
    report['continued_evidence']=dict(path=str(prior_path.relative_to(ROOT)),sha256=hashlib.sha256(prior_raw).hexdigest(),fresh_tutorial_actions_repeated=False)
    net=RosterNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        phase('continue_owned_native_city_service_and_skill')
        for index in (0,1):
            require(net.attach(index).credits==before['states'][index]['wallet'][0],'Native city relogin wallet differs')
            require(not any(p[:1]==b'\x35' for p in net.received[index]),'Completed tutorial restarted')
        city_baseline=status(fixture,hashes)
        catalog=decode_service_shop(one(net.ask(1,b'\xb1\x02',b'\xb1\x03'),b'\xb1\x03'));offer=next(o for o in catalog if o.unknown_u32==2)
        require((offer.options[0].unknown_u8,offer.options[0].unknown_u32)==((2,5800) if service_paid else (1,2000)),'Actual expansion quote differs')
        purchase=b'\xb1\x04\0'+struct.pack('<I',2)+b'\1'+struct.pack('<I',1)
        replies=net.ask(1,purchase,b'\xb1\x01');require(decode_asset_count(one(replies,b'\xc8\x39')).credits==1000,'Expansion not charged2000')
        net.ask(1,purchase,b'\xb1\x01');expanded=status(fixture,hashes)
        require(expanded['states'][1]['roster_service']==1 and expanded['states'][1]['wallet']==[1000,0] and expanded['states'][0]==city_baseline['states'][0],'Expansion replay or account isolation differs')
        report['roster_expansion']=dict(native_b104=True,capacity_before=7,capacity_after=8,charged_credits=2000,replay_no_second_charge=True,continued_already_paid_service=service_paid,other_account_isolated=True,higher_tiers='network XML proved; unaffordable on ordinary starter')
        name=expanded['states'][0]['pets'][0]['name']
        previous=number(matching_pet(net.received[0],identity=1,name=name.encode('cp1251'),resource=1).fields[SAVED[1]])
        require(previous>=5,'Ordinary native light skill insufficient')
        replies=net.ask_pet(0,encode_proficiency_decrease(ProficiencyDecrease(name,'light')),identity=1,name=name.encode('cp1251'),resource=1,skill=1,value=previous-5)
        changed=matching_pet(replies,identity=1,name=name.encode('cp1251'),resource=1)
        require(number(changed.fields[SAVED[1]])==previous-5 and decode_asset_count(one(replies,b'\xc8\x39')).credits==1500,'Native decrease not5/1000')
        decreased=status(fixture,hashes);require(decreased['states'][0]['pets'][0]['skills'][1]==previous-5 and decreased['states'][1]==expanded['states'][1],'Decrease changed other account')
        require(not decode_abilities(one(net.ask(0,b'\xc8\x12\x01\0\0\0',b'\x80'),b'\x80'))[1],'Level1 main unexpectedly has learned perks')
        report['skill_decrease']=dict(native_console_chat21=True,skill='light',decreased=5,charged_credits=1000,other_account_isolated=True)
        report['forgetting']=dict(hosted_positive=False,reason='ordinary level1 starter has no learned perks; isolated/native proof retained')
        for index in (0,1):net.detach(index)
        wait_state(fixture,hashes,lambda s:s['game_connections']==0)
        for index,credits in ((0,1500),(1,1000)):
            require(net.attach(index).credits==credits,'Lawful paid wallet lost after relogin');net.detach(index)
        final=status(fixture,hashes);require(final['states']==decreased['states'],'Relogin changed service/skill/profile state')
        report['lawful_leave_and_relogin']=True
    finally:
        net.close();report['tls_channels']=[*prior['tls_channels'],*[c.metadata() for c in net.connections]]
        released=wait_state(fixture,hashes,lambda s:s['game_connections']==0 and not any(s['idle'].values()),seconds=190)
        report['cleanup_owned_release']=dict(game_connections=released['game_connections'],retained_battles=released['idle']['battle_checkpoints'],settlement_jobs=released['idle']['battle_settlement_jobs'],integrity=released['integrity'])
    require(released['service']==before['service'] and released['global_state']==before['global_state'],'Unrelated game service/world changed')
    require(all(released['foreign'].get(t)==v for t,v in before['foreign'].items()),'Foreign account rows changed during continuation')
    report.update(source_sha256=hashes,service_unchanged=True,existing_account_rows_preserved=True,global_claims_matches_unchanged=True,disconnected_game_connections=0,retained_battles=0,
        preservation=fixture.remote(PRESERVATION,fixture.ownership_payload()),passed=True)


def finish_owned(fixture,args,report,hashes):
    """Complete preserved evidence on the existing second pair, without resets.

    One earlier native decrease succeeded but the probe compared diagnostic
    stored10 to projected35. Confirm its durable30 without repeating it; use an
    ordinary starter mercenary with stored/native35 for an unambiguous proof.
    """
    prior_path=args.prior_report.resolve();prior_raw=prior_path.read_bytes();prior=json.loads(prior_raw)
    require(prior_path.parent==(ROOT/'reports/gameplay-completion/stage5-roster').resolve(),'Only this phase preserved evidence may be finished')
    require(prior.get('reason')=='Native decrease not5/1000' and len(prior.get('tutorial_completion',()))==2,'Expected preserved diagnostic baseline failure')
    require(all(r['events']==15 and r['native_4c_zero_rewards'] and r['profiles_inventory_xp_unchanged'] and r['statistics_rewards_unchanged'] for r in prior['tutorial_completion']),'Fresh tutorial proof missing')
    require(prior.get('random_hire',{}).get('quoted_cost')==500 and prior.get('roster_expansion',{}).get('replay_no_second_charge') is True and prior.get('cleanup_owned_release',{}).get('retained_battles')==0,'Paid hire/expansion evidence missing')
    require([pets[0]['name'] for pets in prior['creation_profiles']]==fixture.names,'Evidence belongs to another owned pair')
    before=status(fixture,hashes)
    require(before['game_connections']==0 and not any(before['idle'].values()),'Finish requires idle hosted game')
    require([s['wallet'] for s in before['states']]==[[1500,0],[1000,0]] and [s['roster_service'] for s in before['states']]==[0,1] and [len(s['pets']) for s in before['states']]==[4,3],'Existing paid state differs; never reset or repeat its paid actions')
    require(all(s['tutorial']==dict(step=4,match=None,completed=1,events=15) for s in before['states']) and all(p['level']==1 and p['xp']==0 for s in before['states'] for p in s['pets']),'Durable ordinary tutorial/LV1 state differs')
    require(before['states'][0]['pets'][0]['skills'][1]==30 and before['states'][0]['pets'][1]['skills'][1]==35,'Expected completed main decrease and untouched starter mercenary')
    require(before['states'][1]['pets']==prior['creation_profiles'][1] and before['states'][0]['pets'][1:3]==prior['creation_profiles'][0][1:3],'Unrelated initial starter profiles changed')
    for field in ('creation','creation_profiles','isolated_tutorials','tutorial_reconnect','tutorial_completion','random_hire','roster_expansion'):report[field]=prior[field]
    report['continued_evidence']=dict(path=str(prior_path.relative_to(ROOT)),sha256=hashlib.sha256(prior_raw).hexdigest(),fresh_tutorial_actions_repeated=False,earlier_failure_preserved=True)
    net=RosterNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        phase('verify_existing_paid_state_and_native_starter_decrease')
        for index in (0,1):
            require(net.attach(index).credits==before['states'][index]['wallet'][0],'Native existing wallet differs')
            require(not any(p[:1]==b'\x35' for p in net.received[index]),'Completed tutorial restarted')
        main=before['states'][0]['pets'][0]
        require(number(matching_pet(net.received[0],identity=1,name=main['name'].encode('cp1251'),resource=main['resource']).fields[SAVED[1]])==30,'Earlier native main decrease did not persist')
        baseline=status(fixture,hashes);pet=baseline['states'][0]['pets'][1];identity=pet['id'];name=pet['name'].encode('cp1251');resource=pet['resource']
        previous=number(matching_pet(net.received[0],identity=identity,name=name,resource=resource).fields[SAVED[1]])
        require(previous==35 and pet['skills'][1]==35,'Stored/native starter mercenary baseline differs')
        report['prior_main_decrease']=dict(raw_diagnostic_baseline=10,native_projection_initial=35,durable_native_after=30,already_charged_credits=1000,not_repeated=True,note='35 initial projection inferred from pinned proficiency normalization; this run directly observes durable30')
        replies=net.ask_pet(0,encode_proficiency_decrease(ProficiencyDecrease(pet['name'],'light')),identity=identity,name=name,resource=resource,skill=1,value=30)
        changed=matching_pet(replies,identity=identity,name=name,resource=resource)
        require(number(changed.fields[SAVED[1]])==30 and decode_asset_count(one(replies,b'\xc8\x39')).credits==500,'Native starter decrease is not35 to30 for1000')
        decreased=status(fixture,hashes);a=decreased['states'][0];old=baseline['states'][0]
        require(a['wallet']==[500,0] and a['pets'][1]['skills'][1]==30 and a['pets'][1]['packet_sha256']!=old['pets'][1]['packet_sha256'],'Durable starter decrease missing')
        require(a['pets'][1]['skills'][:1]+a['pets'][1]['skills'][2:]==old['pets'][1]['skills'][:1]+old['pets'][1]['skills'][2:] and {k:v for k,v in a['pets'][1].items() if k not in ('skills','packet_sha256')}=={k:v for k,v in old['pets'][1].items() if k not in ('skills','packet_sha256')},'Decrease changed other skill/inventory/XP/identity')
        require(a['pets'][:1]+a['pets'][2:]==old['pets'][:1]+old['pets'][2:] and {k:v for k,v in a.items() if k not in ('wallet','pets')}=={k:v for k,v in old.items() if k not in ('wallet','pets')} and decreased['states'][1]==baseline['states'][1],'Decrease affected another actor/account or progression reward')
        require(not decode_abilities(one(net.ask(0,b'\xc8\x12\x01\0\0\0',b'\x80'),b'\x80'))[1],'Level1 main unexpectedly has learned perks')
        report['skill_decrease']=dict(native_console_chat21=True,pet_id=identity,skill='light',native_before=previous,native_after=30,stored_before=35,stored_after=30,decreased=5,charged_credits=1000,other_account_isolated=True,other_actors_inventory_xp_rewards_unchanged=True)
        report['forgetting']=dict(hosted_positive=False,reason='ordinary level1 starter has no learned perks; isolated/native proof retained')
        for index in (0,1):net.command(index,b'\x2a\x01');net.detach(index)
        wait_state(fixture,hashes,lambda s:s['game_connections']==0)
        for index,credits in ((0,500),(1,1000)):
            require(net.attach(index).credits==credits,'Paid wallet did not persist across native relogin')
            require(not any(p[:1]==b'\x35' for p in net.received[index]),'Completed tutorial restarted after service/skill relogin')
            if index==0:require(number(matching_pet(net.received[0],identity=identity,name=name,resource=resource).fields[SAVED[1]])==30,'Native mercenary decrease lost after relogin')
            net.command(index,b'\x2a\x01');net.detach(index)
        final=wait_state(fixture,hashes,lambda s:s['game_connections']==0)
        require(final['states']==decreased['states'],'Relogin changed durable service/skill/progression state')
        report['lawful_leave_and_relogin']=True;report['final_owned_wallets']=[s['wallet'] for s in final['states']]
    finally:
        for index in tuple(net.peers):
            try:net.command(index,b'\x2a\x01')
            except Exception:pass
        net.close();report['tls_channels']=[*prior['tls_channels'],*[c.metadata() for c in net.connections]]
        released=wait_state(fixture,hashes,lambda s:s['game_connections']==0 and not any(s['idle'].values()),seconds=190)
        report['cleanup_owned_release']=dict(game_connections=released['game_connections'],retained_battles=released['idle']['battle_checkpoints'],settlement_jobs=released['idle']['battle_settlement_jobs'],integrity=released['integrity'])
    require(released['service']==before['service'] and released['global_state']==before['global_state'],'Unrelated game service/world changed')
    require(all(released['foreign'].get(t)==v for t,v in before['foreign'].items()),'Foreign account rows changed during finish')
    report.update(source_sha256=hashes,service_unchanged=True,existing_account_rows_preserved=True,global_claims_matches_unchanged=True,disconnected_game_connections=0,retained_battles=0,
        preservation=fixture.remote(PRESERVATION,fixture.ownership_payload()),passed=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare-owned','provision-owned','run','continue-owned','finish-owned'))
    p.add_argument('--prior-report',type=Path)
    p.add_argument('--fixture',type=Path);p.add_argument('--deployments',type=Path,default=ROOT/'reports/gameplay-completion');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--host',default='185.184.42.88');p.add_argument('--key',default=str(Path.home()/'.ssh/tio_server'));p.add_argument('--server-name',default='ti-reborn.com')
    p.add_argument('--login-port',type=int,default=29512);p.add_argument('--session-port',type=int,default=29513);p.add_argument('--loopback-session-port',type=int,default=28513);p.add_argument('--ca-file',type=Path)
    args=p.parse_args(argv)
    if args.output.exists():p.error('Preserve existing evidence; choose a fresh output')
    if args.action!='prepare-owned' and not args.fixture:p.error('Private prepared fixture required')
    if args.action in ('continue-owned','finish-owned') and not args.prior_report:p.error('Preserved --prior-report required')
    if any(not 1024<=port<=65535 for port in (args.login_port,args.session_port,args.loopback_session_port)):p.error('Invalid port')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),kind='two ordinary owned primary characters, hosted native TLS; no GUI',limitations=['no graphical clients','no administrative save/level/money/inventory writes','positive forgetting unavailable at ordinary LV1','higher roster tiers unaffordable on starter; shared XML and isolated native proof'])
    try:
        if args.action=='prepare-owned':
            fixture=Stage7Fixture.prepare(args.host,args.key);report.update(passed=True,prepared=True,accounts=fixture.names,credential_file=fixture.credential_path)
        else:
            fixture=Stage7Fixture.load(args.fixture);require(fixture.host==args.host and bool(fixture.backup)==(args.action in ('run','continue-owned','finish-owned')),'Fixture target/state differs');hashes=deployment_hashes(args.deployments)
            if args.action=='provision-owned':report.update(provision=fixture.provision(hashes),passed=True,credential_file=fixture.credential_path,accounts=fixture.names)
            elif args.action=='continue-owned':continue_owned(fixture,args,report,hashes)
            elif args.action=='finish-owned':finish_owned(fixture,args,report,hashes)
            else:run(fixture,args,report,hashes)
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__;report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
        if isinstance(error,AssertionError):report['reason']=str(error)[:200]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,graphical_clients_started=0)),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
