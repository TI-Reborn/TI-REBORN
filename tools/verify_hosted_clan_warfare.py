"""Two ordinary new accounts: verified TLS, standings/profiles and denied rooms.

Prepare is local only. Provision explicitly backs up hosted SQLite and creates
only two fresh empty accounts. All subsequent server-side SQL is read-only;
characters are created by normal native commands. No level/money/clan/claim,
event-clock fixture or production battle is created by this verifier.
This is automated protocol evidence, not a graphical-client acceptance.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_hosted_economy_tls import EconomyNetwork,PROVISION_ECONOMY
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA,OWNERSHIP,PRESERVATION,require
from tools.verify_game_tls_hosted import tls_context
from tio.protocol.binary import Reader
from tio.protocol.clan_ratings import encode_request as ratings_request
from tio.protocol.assault import encode_request as assault_request,REQUEST_ROOMS
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.system_message import encode_shop_error

PRIVATE=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'TIO-emulator/clan-warfare-qa'
PORTS='( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'
PROVISION=PROVISION_ECONOMY.replace("names=[n for n,p in pairs]","names=[n for n,p in pairs]\nassert len(names)==2,'Exactly two ordinary accounts'")
PROVISION=PROVISION.replace("folder=pathlib.Path(tempfile.mkdtemp", "with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as guard:\n for table in ('battle_checkpoints','battle_settlement_jobs'):\n  assert not guard.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() or guard.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,'Battle/journal present before provisioning'\nfolder=pathlib.Path(tempfile.mkdtemp")

SNAPSHOT=OWNERSHIP+r'''
import hashlib,subprocess
from tio.protocol.pet_info import decode_pet_info
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 states=[]
 for n in names:
  wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(n,)).fetchone() if 'wallets' in tables else None
  pets=[]
  if 'owned_pets' in tables:
   for pet_id,human,packet in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(n,)):
    f=decode_pet_info(packet,human_equipment=bool(human)).fields
    pets.append(dict(id=pet_id,level=f['0x8c4aef'],xp=f['0x8c4b05']))
  states.append(dict(account=n,wallet=list(wallet) if wallet else None,pets=pets,
   character_count=db.execute('SELECT count(*) FROM characters WHERE account=?',(n,)).fetchone()[0],
   clan_member=bool(db.execute('SELECT 1 FROM clan_members WHERE account=?',(n,)).fetchone()) if 'clan_members' in tables else False))
 frozen={}
 for table in ('territory_claims','territory_claim_history','mine_claims','mine_claim_history','warfare_groups','warfare_group_members','warfare_matches','warfare_match_receipts','warfare_event_receipts','warfare_scores','warfare_clan_locks'):
  rows=sorted(map(repr,db.execute('SELECT * FROM '+table))) if table in tables else []
  frozen[table]=dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
 idle={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] if table in tables else 0 for table in ('battle_checkpoints','battle_settlement_jobs')}
 sources={n:hashlib.sha256(pathlib.Path(n).read_bytes()).hexdigest() for n in data['source_hashes']}
 assert sources==data['source_hashes'],'Reviewed deployed source changed'
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0];assert integrity=='ok'
connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
print(json.dumps(dict(states=states,global_claims_groups_matches=frozen,idle=idle,source_sha256=sources,integrity=integrity,game_connections=connections)))
'''


def deployment_hashes(path):
    proof=json.loads(Path(path).read_text(encoding='utf-8'))
    require(proof.get('source_parity') is True,'Successful source parity proof required')
    values=proof.get('source_sha256',{})
    paths=json.loads((ROOT/'reports/clan-warfare/runtime-files.json').read_text(encoding='utf-8'))
    require(set(values)==set(paths),'Exact full runtime source proof required')
    require(all(re.fullmatch('[0-9a-f]{64}',v) for v in values.values()),'Invalid reviewed source digest')
    require(all(hashlib.sha256((ROOT/n).read_bytes()).hexdigest()==v for n,v in values.items()),'Local runtime differs from deployed proof')
    return values


class WarfareFixture(FreshSurroundingsQA):
    @staticmethod
    def private_directory():
        require(not PRIVATE.is_symlink(),'Private directory cannot be a symlink')
        PRIVATE.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':
            from tools.offsite_backup_windows import _protect_directory
            _protect_directory(PRIVATE)
        else:PRIVATE.chmod(0o700)
        (PRIVATE/'.gitignore').write_text('*\n',encoding='utf-8')

    def save(self,pending=False):
        self.private_directory();path=PRIVATE/(self.prefix+('.pending.json' if pending else '.json'))
        require(not path.exists(),'Never overwrite a private fixture')
        with path.open('x',encoding='utf-8') as output:
            json.dump(dict(version=1,host=self.host,prefix=self.prefix,names=self.names,passwords=self.passwords,backup=self.backup,key=self.key),output)
        if os.name!='nt':path.chmod(0o600)
        self.credential_path=str(path);return path

    @classmethod
    def prepare(cls,host,key):
        prefix='qs'+secrets.token_hex(4)
        alphabet='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
        fixture=cls(host,prefix,[prefix+'a',prefix+'b'],[''.join(secrets.choice(alphabet) for _ in range(16)) for _ in range(2)],'',key)
        fixture.save(pending=True);return fixture

    @classmethod
    def load(cls,path):
        path=Path(path);require(not path.is_symlink(),'Private fixture cannot be a symlink')
        path=path.resolve();require(path.parent==PRIVATE.resolve(),'Dedicated private fixture required')
        cls.private_directory();data=json.loads(path.read_text(encoding='utf-8'))
        require(data.pop('version')==1,'Unexpected private fixture version')
        fixture=cls(**data,credential_path=str(path))
        require(re.fullmatch('qs[0-9a-f]{8}',fixture.prefix) and fixture.names==[fixture.prefix+'a',fixture.prefix+'b'] and len(fixture.passwords)==2,'Two owned QA identities required')
        return fixture

    def provision(self,hashes):
        require(not self.backup and self.credential_path.endswith('.pending.json'),'Provision a prepared empty pair once')
        result=self.remote(PROVISION,dict(prefix=self.prefix,pairs=list(zip(self.names,self.passwords)),source_hashes=hashes))
        self.backup=result['backup'];self.save();return result

    def status(self,hashes):return self.remote(SNAPSHOT,{**self.ownership_payload(),'source_hashes':hashes})


def cstring(reader,limit=255):
    value=bytearray()
    while (c:=reader.u8())!=0:
        value.append(c);require(len(value)<=limit,'Unbounded native string')
    return bytes(value)


def clan_page(packet,kind,selector):
    r=Reader(packet);require((r.u8(),r.u8(),r.u8())==(0x83,kind,selector),'Wrong native standings selector')
    count=r.u32();require(count<=100,'Unbounded native standings page')
    influence=[]
    for _ in range(count):
        r.u32();cstring(r);cstring(r);r.u16();r.u16();r.u8()
        crest,points,rating,alliance_crest,unknown3,unknown4=(r.u32() for _ in range(6))
        require(crest==alliance_crest==unknown3==unknown4==0,'Unexpected unimplemented crest fields')
        influence.append(points)
    r.finish()
    if selector==0:require(influence==sorted(influence,reverse=True),'Influence page is not sorted')
    else:require(count==0,'Unexpected unimplemented clan TrueSkill projection')
    return dict(kind=kind,selector=selector,count=count)


def alliance_page(packet):
    r=Reader(packet);require((r.u8(),r.u8())==(0xaf,15),'Missing alliance standings')
    count=r.u32();require(count<=100,'Unbounded alliance page')
    for _ in range(count):
        leading=r.u32();name=cstring(r);level=r.u8();crest=r.u32();r.u32();clans=r.u8();leader_name=cstring(r)
        require(leading>0 and name and level in (1,2) and crest==0 and 1<=clans<=3 and leader_name,'Invalid native alliance rating row')
    r.finish();return dict(count=count)


def own_profile(packet,name):
    r=Reader(packet);require((r.u8(),r.u8())==(0xa7,0),'Missing native public profile');identity=r.u32()
    require(identity>0 and cstring(r,16)==name and r.u8()==1,'Unexpected starter profile')
    r.u32();clan=cstring(r,32);clan_crest=r.u32();alliance=cstring(r,32);alliance_crest=r.u32()
    require(clan==alliance==b'' and clan_crest==alliance_crest==0,'Fresh profile contains invented affiliation')
    return dict(level=1,clan_name_empty=True,alliance_name_empty=True,clan_crest=0,alliance_crest=0)


def run(fixture,args,report,hashes):
    require(bool(fixture.backup),'Ownership-proven provisioned pair required')
    before=fixture.status(hashes);require(before['game_connections']==0 and not any(before['idle'].values()),'Players or retained battle present; abort QA')
    require(all(s['character_count']==0 for s in before['states']),'Fresh empty accounts required; no automatic reset')
    network=EconomyNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        for i in (0,1):network.attach(i,fresh=True)
        report['pages']=[];report['profiles']=[];report['room_query_rejections']=[]
        for i in (0,1):
            for kind in range(3):
                for selector in range(2):
                    replies=network.command(i,ratings_request(kind,selector))
                    pages=[p for p in replies if p[:3]==bytes((0x83,kind,selector))]
                    require(len(pages)==1,'One native standings response required')
                    report['pages'].append(dict(account=i,**clan_page(pages[0],kind,selector)))
            replies=network.command(i,b'\xaf\x0e');packets=[p for p in replies if p[:2]==b'\xaf\x0f']
            require(len(packets)==1,'One native alliance standings response required')
            report.setdefault('alliance_pages',[]).append(dict(account=i,**alliance_page(packets[0])))
            replies=network.command(i,b'\x68\0'+fixture.names[1-i].encode()+b'\0')
            packets=[p for p in replies if p[:2]==b'\xa7\0'];require(len(packets)==1,'One other-account public profile required')
            report['profiles'].append(dict(account=i,**own_profile(packets[0],fixture.names[1-i].encode())))
            replies=network.command(i,assault_request(REQUEST_ROOMS))
            require(encode_shop_error('Сначала перейдите на территорию штурма') in replies,'Starter-city assault room query must be denied')
            require(not any(p[:2] in (b'\xc8\x24',b'\xc8\x25',b'\xc8\x26') for p in replies),'Rejected room query created a group')
            report['room_query_rejections'].append(dict(account=i,native_request='C81F',reason='ordinary starter city, not assault territory'))
            wallets=[decode_asset_count(p) for p in network.received[i] if p[:2]==b'\xc8\x39']
            require(wallets and (wallets[-1].credits,wallets[-1].gold)==(3000,0),'Native starter money must be3000 credits/0Gold')
        online=fixture.status(hashes)
        require(online['game_connections']==2 and not any(online['idle'].values()),'Unexpected gameplay or retained battle appeared')
        require(online['global_claims_groups_matches']==before['global_claims_groups_matches'],'Read-only QA changed global claims/groups/matches')
        for state in online['states']:
            require(state['wallet']==[3000,0] and state['pets']==[dict(id=1,level=1,xp=0)] and not state['clan_member'] and state['character_count']==1,'Unexpected ordinary starter state')
        report['starter_wallets']=[[3000,0],[3000,0]];report['starter_levels']=[1,1]
        report['global_claims_groups_matches_unchanged']=True;report['source_sha256']=hashes
    finally:
        network.close();report['tls_channels']=[channel.metadata() for channel in network.connections]
    deadline=time.monotonic()+5
    while True:
        after=fixture.status(hashes)
        if after['game_connections']==0:break
        require(time.monotonic()<deadline,'Owned TLS disconnects did not finish');time.sleep(.1)
    require(not any(after['idle'].values()),'QA left a retained battle')
    report['preservation']=fixture.remote(PRESERVATION,fixture.ownership_payload())
    report['disconnected_game_connections']=0;report['passed']=True


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare-owned','provision-owned','run'))
    p.add_argument('--fixture',type=Path);p.add_argument('--deployment',type=Path,default=ROOT/'reports/clan-warfare/deployment.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--host',default='185.184.42.88')
    p.add_argument('--key',default=str(Path.home()/'.ssh/tio_server'));p.add_argument('--server-name',default='ti-reborn.com')
    p.add_argument('--login-port',type=int,default=29512);p.add_argument('--session-port',type=int,default=29513)
    p.add_argument('--loopback-session-port',type=int,default=28513);p.add_argument('--ca-file',type=Path)
    args=p.parse_args()
    if args.output.exists():p.error('Preserve existing evidence; choose a fresh output')
    if args.action!='prepare-owned' and not args.fixture:p.error('Prepared private --fixture required')
    if any(not 1024<=port<=65535 for port in (args.login_port,args.session_port,args.loopback_session_port)):p.error('Invalid port')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),kind='two ordinary accounts; native protocol over verified TLS',
        limitations=['no graphical clients started','no positive hosted assault or alliance purchase; eight-account scenarios run only in isolated candidate','C81F is a room query rejected by starter location, not a signup or a level test','clan TrueSkill selector1 intentionally empty; no invented clan-rating formula'])
    try:
        if args.action=='prepare-owned':
            fixture=WarfareFixture.prepare(args.host,args.key);report.update(passed=True,prepared=True,accounts=fixture.names,credential_file=fixture.credential_path)
        else:
            fixture=WarfareFixture.load(args.fixture);require(fixture.host==args.host,'Fixture belongs to another host');hashes=deployment_hashes(args.deployment)
            if args.action=='provision-owned':
                report['provision']=fixture.provision(hashes);report.update(passed=True,credential_file=fixture.credential_path,accounts=fixture.names)
            else:run(fixture,args,report,hashes)
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__
        report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,graphical_clients_started=0)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
