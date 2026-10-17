"""Read-only clan/world QA on the retained ordinary phase5/6 pair.

Run only after root's successful deployment notification and QA-slot release.
No provisioning, payments, uploads, settlement helpers, clock changes or save
edits. Native reads use verified TLS; SQL is read-only; credentials stay private.
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
from tools.verify_hosted_economy_completion import EconomyNetwork,deployment_hashes as economy_hashes,status as economy_status,one
from tools.verify_hosted_stage7 import Stage7Fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP,require
from tools.verify_game_tls_hosted import tls_context
from tio.protocol.binary import Reader
from tio.protocol.clan_crests import encode_request as crest_request,decode_content
from tio.protocol.clan_ratings import encode_request as clan_request
from tio.protocol.player_top100 import encode_request as top_request,decode_ratings,SORTS
from tio.protocol.shared_config import decode_shared_config_data


def deployment_hashes(directory,phase7,phase8=None):
    result=economy_hashes(directory,Path(directory)/'stage6-economy/deployment.json')
    previous=json.loads((Path(directory)/'stage6-economy/deployment.json').read_text())['timestamp_utc']
    for source in (phase7,phase8):
        if source is None:continue
        source=Path(source);proof=json.loads(source.read_text(encoding='utf8'))
        require(proof.get('source_parity') is True,'Successful deployed source parity required')
        stamp=proof.get('timestamp_utc');require(isinstance(stamp,str) and stamp>=previous,'Deployment proof order differs');previous=stamp
        values=proof.get('source_sha256');require(isinstance(values,dict) and 1<=len(values)<=512,'Bounded source proof required')
        runtime={}
        for path,digest in values.items():
            require(isinstance(path,str) and '..' not in Path(path).parts and isinstance(digest,str) and re.fullmatch('[0-9a-f]{64}',digest),'Unsafe source proof')
            if re.fullmatch(r'docs/[A-Za-z0-9_./-]+\.md',path):continue
            require(re.fullmatch(r'(?:tio|server|tools|config|evidence)/[A-Za-z0-9_./-]+',path),'Unsafe runtime path')
            runtime[path]=digest
        expected=json.loads((source.parent/'runtime-files.json').read_text())
        require(isinstance(expected,list) and len(expected)==len(set(expected)) and set(runtime)==set(expected),'Exact runtime release set differs')
        result.update(runtime)
    require({'server/clan_gameplay.py','tio/achievement_benefits.py','tio/clan_benefits.py','tio/protocol/clan_crests.py'}<=result.keys(),'Clan release coverage missing')
    if phase8 is not None:require({'server/world_runtime.py','tio/world_completion.py','tio/protocol/player_top100.py'}<=result.keys(),'World transport release coverage missing')
    return result


CENSUS=OWNERSHIP+r'''
import hashlib
from server.public_profile import read_profile
from tio.achievement_benefits import rating_bonus,influence_multiplier
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] if t in tables else 0 for t in ('clan_benefit_receipts','clan_crests','clan_crest_blobs','clan_weeks','clan_weekly_badges','clan_assault_medals','clan_assault_prizes','warfare_event_receipts')}
 crests=[]
 if 'clan_crest_blobs' in tables:
  from tio.clan_benefits import validate_crest
  for identity,digest,bmp in db.execute('SELECT id,digest,bmp FROM clan_crest_blobs ORDER BY id LIMIT 10'):
   assert validate_crest(bytes(bmp))==digest
   crests.append(dict(id=identity,sha256=digest,bytes=len(bmp)))
 missing_crest=db.execute('SELECT coalesce(max(id),0)+1 FROM clan_crest_blobs').fetchone()[0] if 'clan_crest_blobs' in tables else 1
 assert 1<=missing_crest<=0xffffffff
 eligible=legacy=0
 if 'warfare_event_receipts' in tables:
  for receipt, in db.execute('SELECT receipt FROM warfare_event_receipts'):
   body=json.loads(receipt)
   if body.get('benefits_version')==1:eligible+=1
   else:legacy+=1
 profiles=[]
 for account in names:
  p=read_profile('/var/lib/tio-server/reservation.sqlite3',account=account)
  assert p is not None
  profiles.append(dict(name=p.name.hex(),level=p.level,rating=p.rating,wins=p.wins,losses=p.losses,kills=p.kills,deaths=p.deaths,damage_dealt=p.damage_dealt,damage_received=p.damage_received,clan_name=p.clan_name.hex(),clan_crest=p.clan_crest_id,alliance_name=p.alliance_name.hex(),alliance_crest=p.alliance_crest_id,mercenaries=[dict(name=n.hex(),level=l,xp=x) for n,l,x,r in p.mercenaries],earned_rating_bonus=rating_bonus(db,account),earned_influence_multiplier=str(influence_multiplier(db,account))))
 tops={}
 if data['world']:
  from tio.world_completion import players,city_coefficients
  from tio.protocol.player_top100 import SORTS,encode_world_rows
  tops={str(s):encode_world_rows(s,players(db,sort=kind)).hex() for s,kind in SORTS.items()}
  coefficients={str(t):{k:str(v) for k,v in city_coefficients(t).items()} for t in (2,3,4,5,8,18)}
 else:coefficients={}
 print(json.dumps(dict(counts=counts,crests=crests,missing_crest=missing_crest,eligible_final_receipts=eligible,legacy_final_receipts=legacy,profiles=profiles,tops=tops,real_utc_coefficients=coefficients)))
'''


def census(fixture,*,world):return fixture.remote(CENSUS,{**fixture.ownership_payload(),'world':bool(world)})


def cstring(r,maximum=255):
    value=bytearray()
    while (c:=r.u8()):value.append(c);require(len(value)<=maximum,'Native string exceeds bound')
    return bytes(value)


ERROR_PREFIX=b'\xf0'+struct.pack('<I',394)


def native_error(packet):
    r=Reader(packet);require(r.read(5)==ERROR_PREFIX,'Expected native error394')
    require((r.u32(),r.u32())==(1,5),'Native error argument differs')
    units=[]
    while (value:=r.u16()):
        units.append(value);require(len(units)<=255,'Error text exceeds bound')
    r.finish();require(units,'Native error text missing')
    return struct.pack('<'+'H'*len(units),*units).decode('utf-16le')


def clan_info(packet):
    r=Reader(packet);require(r.u8()==0x54,'Expected login clan54')
    result=dict(id=r.u32(),name=cstring(r,32).hex(),leader=cstring(r,16).hex(),level=r.u8(),crest=r.u32(),capacity=r.u16(),capacity_copy=r.u16(),influence=r.u32())
    require(r.u8()==0 and result['capacity']==result['capacity_copy'],'Unsupported clan info branch');r.finish()
    if not result['id']:require(not any(result[k] for k in ('name','leader','level','crest','capacity','influence')),'Empty affiliation has nonempty fields')
    return result


def clan_page(packet,kind,selector):
    r=Reader(packet);require(r.read(3)==bytes((0x83,kind,selector)),'Wrong clan page');count=r.u32();require(count<=100,'Clan page exceeds100')
    rows=[]
    for _ in range(count):
        identity,name,leader=r.u32(),cstring(r),cstring(r);members,capacity,level=r.u16(),r.u16(),r.u8()
        crest,influence,rating,alliance,unknown3,unknown4=(r.u32() for _ in range(6))
        require(identity>0 and name and members<=capacity and not unknown3 and not unknown4,'Invalid public clan row')
        rows.append(dict(id=identity,crest=crest,influence=influence,rating=rating,alliance_crest=alliance))
    r.finish()
    if selector==0:require([(i['influence'],-i['id']) for i in rows]==sorted(((i['influence'],-i['id']) for i in rows),reverse=True),'Clan influence/tie order differs')
    else:require(not rows,'Unconfirmed clan TrueSkill was manufactured')
    return rows


def alliance_page(packet):
    r=Reader(packet);require(r.read(2)==b'\xaf\x0f','Wrong alliance response');count=r.u32();require(count<=100,'Alliance page exceeds100')
    for _ in range(count):
        require(r.u32()>0 and cstring(r),'Alliance identity/name invalid')
        require(r.u8() in (1,2),'Alliance level invalid');r.u32();r.u32();require(1<=r.u8()<=3,'Alliance cohort invalid');require(cstring(r),'Alliance leader missing')
    r.finish();return count


def public_profile(packet):
    r=Reader(packet);require(r.read(2)==b'\xa7\0','Wrong public profile');require(r.u32()>0,'Public profile ID invalid')
    name,level=cstring(r,16),r.u8();r.u32();clan,crest=cstring(r,32),r.u32();alliance,alliance_crest=cstring(r,32),r.u32();r.u8();r.u8()
    raw=[r.u32() for _ in range(11)];rating=raw[2] if raw[2]<1<<31 else raw[2]-(1<<32)
    for _ in range(3):
        length=0
        while r.u16():length+=1;require(length<=4096,'Public text exceeds bound')
    count=r.u8();require(count<=20,'Public roster exceeds bound');mercenaries=[]
    for _ in range(count):
        nick,lvl=cstring(r,64),r.u8();values=[r.u32() for _ in range(6)];mercenaries.append(dict(name=nick.hex(),level=lvl,xp=values[1]))
    r.u8();r.read(12);r.u8();r.u8();r.u32();require(r.u32() in (0,1,2,3),'Public league invalid');r.read(16);r.u8();r.finish()
    return dict(name=name.hex(),level=level,rating=rating,wins=raw[3],losses=raw[4],kills=raw[5],deaths=raw[6],damage_dealt=raw[7],damage_received=raw[8],clan_name=clan.hex(),clan_crest=crest,alliance_name=alliance.hex(),alliance_crest=alliance_crest,mercenaries=mercenaries)


def zones(packet):
    value=decode_shared_config_data(packet);require(value.name_bytes==b'zones' and value.decompressed_size<=1024*1024,'Bounded world zones required')
    dec=zlib.decompressobj();raw=dec.decompress(value.compressed_bytes,1024*1024+1)
    require(dec.eof and not dec.unused_data and not dec.unconsumed_tail and len(raw)==value.decompressed_size,'World config compression differs')
    from tools.prepare_world_completion_catalog import rows
    root=ET.fromstring(raw);ids=[int(t.get('id')) for t in root];require(ids==list(range(1,23)),'Native world town indexing/order differs');rows(raw,22)
    return dict(ids=sorted(ids),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))


def run(fixture,args,report,hashes):
    before=economy_status(fixture,hashes);require(before['connections']==0 and not any(before['idle'].values()),'Hosted QA slot is occupied')
    report['preflight_service']=before['service'];report['source_sha256']=hashes
    baseline=census(fixture,world=args.phase8 is not None);report['real_reward_census']=baseline['counts'];report['actual_new_final_receipts']=baseline['eligible_final_receipts'];report['legacy_final_receipts']=baseline['legacy_final_receipts']
    report['positive_capture_or_weekly_gameplay_observed']=False
    network=EconomyNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        for i in (0,1):
            assets=network.attach(i);require([assets.credits,assets.gold]==before['states'][i]['wallet'],'Native wallet differs')
        report['clan_pages']=[];report['profiles']=[];report['crests']=[]
        for i in (0,1):
            info=clan_info(one(network.received[i],b'\x54'))
            require(not baseline['profiles'][i]['clan_name'] and info['id']==0,'Preserved ordinary pair unexpectedly has a clan')
            report.setdefault('login_clan54',[]).append(dict(account=i,**info))
            for kind in range(3):
                for selector in range(2):
                    prefix=bytes((0x83,kind,selector));reply=network.ask_matching(i,clan_request(kind,selector),lambda p:p.startswith(prefix))
                    rows=clan_page(one(reply,prefix),kind,selector);report['clan_pages'].append(dict(account=i,kind=kind,selector=selector,count=len(rows)))
            reply=network.ask_matching(i,b'\xaf\x0e',lambda p:p.startswith(b'\xaf\x0f'));report.setdefault('alliance_pages',[]).append(dict(account=i,count=alliance_page(one(reply,b'\xaf\x0f'))))
            target=1-i;expected=baseline['profiles'][target];name=fixture.names[target].encode()
            reply=network.ask_matching(i,b'\x68\0'+name+b'\0',lambda p:p.startswith(b'\xa7\0') and public_profile(p)['name']==name.hex())
            actual=public_profile(one(reply,b'\xa7\0'));require(actual=={k:expected[k] for k in actual},'Native earned profile differs');report['profiles'].append(dict(viewer=i,subject=target,**actual))
            for crest in baseline['crests']:
                prefix=b'\x5a'+struct.pack('<I',crest['id']);reply=network.ask_matching(i,crest_request(crest['id']),lambda p:p.startswith(prefix));value=decode_content(one(reply,prefix))
                require(len(value.bmp)==crest['bytes'] and hashlib.sha256(value.bmp).hexdigest()==crest['sha256'],'Actual stored crest differs');report['crests'].append(dict(account=i,id=crest['id'],sha256=crest['sha256'],bytes=crest['bytes']))
            for retry in range(2):
                reply=network.ask_matching(i,crest_request(baseline['missing_crest']),lambda p:p.startswith(ERROR_PREFIX))
                message=native_error(one(reply,ERROR_PREFIX));require('не найдена' in message.casefold(),'Missing crest rejected for unexpected reason')
                require(not any(p.startswith(b'\x5a'+struct.pack('<I',baseline['missing_crest'])) for p in reply),'Missing crest manufactured BMP content')
                report.setdefault('missing_crest59',[]).append(dict(account=i,retry=retry,error_command=394,missing_id=baseline['missing_crest'],no_content=True))
            if args.phase8 is not None:
                report.setdefault('zones',[]).append(dict(account=i,**zones(one(network.received[i],b'\xb9\x03zones\0'))))
                for selector in SORTS:
                    time.sleep(.3) # Actual server standings rate limit is250ms.
                    prefix=bytes((0xa5,selector));reply=network.ask_matching(i,top_request(selector),lambda p:p.startswith(prefix));packet=one(reply,prefix)
                    require(decode_ratings(packet)==decode_ratings(bytes.fromhex(baseline['tops'][str(selector)])),'Authoritative public Top100 differs')
                    report.setdefault('top100',[]).append(dict(account=i,selector=selector,count=len(decode_ratings(packet)[1]),sha256=hashlib.sha256(packet).hexdigest()))
        report['crest_positive_gate']=None if baseline['crests'] else 'No actual stored crest; paid creation/upload is outside this read-only scenario'
        report['world_positive_gate']=None if args.phase8 is not None else 'Await actual successful phase8 deployment proof'
    finally:
        for i in tuple(network.peers):
            try:network.command(i,b'\x2a\x01')
            except Exception:pass
        network.close();report['tls_channels']=[c.metadata() for c in network.connections]
    deadline=time.monotonic()+190
    while True:
        after=economy_status(fixture,hashes)
        if after['connections']==0 and not any(after['idle'].values()):break
        require(time.monotonic()<deadline,'Owned disconnect cleanup deadline exceeded');time.sleep(.2)
    report['postflight_service']=after['service'];report['cleanup']=dict(connections=after['connections'],idle=after['idle'],integrity=after['integrity'])
    # Hash diffs identify ordinary background delivery without exposing private
    # bank commands/PINs or whole stored receipts in a public failure report.
    report['personal_state_deltas']=[dict(account=i,field=k,before_sha256=hashlib.sha256(json.dumps(a[k],sort_keys=True).encode()).hexdigest(),after_sha256=hashlib.sha256(json.dumps(b[k],sort_keys=True).encode()).hexdigest()) for i,(a,b) in enumerate(zip(before['states'],after['states'])) for k in a if a[k]!=b[k]]
    report['foreign_state_deltas']=[dict(table=k,before=v,after=after['foreign'].get(k)) for k,v in before['foreign'].items() if v!=after['foreign'].get(k)]
    require(not report['personal_state_deltas'] and not report['foreign_state_deltas'],'Readonly views changed saved personal/foreign state')
    require(after['payments']==before['payments'] and after['service']==before['service'],'Payment state or game service changed')
    report.update(passed=True,source_sha256=hashes,cleanup=dict(connections=after['connections'],idle=after['idle'],integrity=after['integrity']),protected_account_state_unchanged=True,service_unchanged=True,real_utc_coefficients=baseline['real_utc_coefficients'])
    report['clock_driven_world_state_changed']=after['claims']!=before['claims']


def self_test():
    from tio.protocol.clan_ratings import encode_ratings,ClanRating
    from tio.protocol.public_profile import encode_profile
    packet=encode_ratings(0,0,(ClanRating(1,b'One',b'Owner',1,7,1,10,crest_id=9),))
    require(clan_page(packet,0,0)[0]['crest']==9,'Crest conditional branch ignored')
    require(public_profile(encode_profile(1,b'Alice',1,'',rating=-3,mercenaries=((b'Alice',1,0,1),)))['rating']==-3,'Signed profile rating differs')
    require(not clan_page(encode_ratings(0,1,()),0,1),'Empty unconfirmed selector differs')
    for invalid in (packet[:-1],packet+bytes(1),b'\x83\0\0'+struct.pack('<I',101)):
        try:clan_page(invalid,0,0)
        except (ValueError,AssertionError):pass
        else:raise AssertionError('Malformed clan page accepted')
    return dict(passed=True,native_read_codecs=True,malformed_bounds_rejected=True,network_actions=0)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--self-test',action='store_true');p.add_argument('--fixture',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--deployments',type=Path,default=ROOT/'reports/gameplay-completion');p.add_argument('--phase7',type=Path,default=ROOT/'reports/gameplay-completion/stage7-clans/deployment.json');p.add_argument('--phase8',type=Path)
    p.add_argument('--host',default='185.184.42.88');p.add_argument('--server-name',default='ti-reborn.com');p.add_argument('--login-port',type=int,default=29512);p.add_argument('--session-port',type=int,default=29513);p.add_argument('--loopback-session-port',type=int,default=28513);p.add_argument('--ca-file',type=Path)
    args=p.parse_args(argv)
    if args.self_test:print(json.dumps(self_test()));return 0
    if not args.fixture or not args.output:p.error('Preserved private fixture and fresh output required')
    if args.output.exists():p.error('Preserve prior evidence; select fresh output')
    report=dict(passed=False,utc=datetime.now(timezone.utc).isoformat(),probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),kind='readonly clan/world native TLS, two retained ordinary accounts',limitations=['no graphical clients','no paid clan/crest/base actions','no synthetic score/time/weekly/capture rewards','positive weekly/capture gameplay not established by a read-only census'])
    try:
        hashes=deployment_hashes(args.deployments,args.phase7,args.phase8);fixture=Stage7Fixture.load(args.fixture)
        require(fixture.host==args.host and fixture.prefix=='qsfc5dfe28' and fixture.backup,'Retained designated ordinary pair required')
        run(fixture,args,report,hashes)
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__;report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
        if isinstance(error,AssertionError):report['reason']=str(error)[:200]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,graphical_clients_started=0)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
