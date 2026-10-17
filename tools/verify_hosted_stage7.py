"""Two owned new accounts: ordinary characters/mail/standings over strict TLS.

Prepare is local. Explicit provisioning backs up the actual hosted database
and adds only two empty Accounts records. Character creation, transfers,
claims and queries then use ordinary native packets. All remote SQL after
provisioning is read-only, ownership-checked and bounded to the created pair.
No levels, money, inventory, ratings or combat fixtures are administratively
assigned. Importing this module or running its unit tests contacts no VPS.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_game_tls_hosted import TlsNetworkQA,tls_context
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA,OWNERSHIP,require
from tools.verify_hosted_clan_warfare import PROVISION
from tio.appearance import encode_request as appearance_request
from tio.protocol.character_create import CharacterCreateRequest,encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.world_bootstrap import decode_mychar_info
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.pet_info import decode_pet_info
from tio.protocol import mail

PRIVATE=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'TIO-emulator/stage7-qa'
MAIL_CURRENCY=0xffff0001
GLOBAL_TABLES=('territory_claims','territory_claim_history','mine_claims','mine_claim_history',
 'warfare_groups','warfare_group_members','warfare_matches','warfare_match_receipts',
 'warfare_event_receipts','warfare_scores','warfare_clan_locks','ranked_players','ranked_matches',
 'team_rating_teams','team_rating_values','team_rating_archives','team_ranked_matches','team_ranked_opponents')

SNAPSHOT=OWNERSHIP+r'''
import hashlib,subprocess
from tio.protocol.pet_info import decode_pet_info
from tio.character_identity import alias
owned=[owner for n in names for owner in (n,alias(n,2))]
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 states=[]
 for n in names:
  slots=[]
  mappings=db.execute('SELECT slot,owner FROM character_identities WHERE login=? ORDER BY slot',(n,)).fetchall() if 'character_identities' in tables else []
  assert all(slot==2 and owner==alias(n,2) for slot,owner in mappings),'Only ordinary owned secondary slot is allowed'
  for slot,owner in ((1,n),(2,alias(n,2))):
   character=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(owner,)).fetchone() if 'characters' in tables else None
   wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(owner,)).fetchone() if 'wallets' in tables else None
   pets=[]
   if 'owned_pets' in tables:
    for pet_id,human,raw in db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(owner,)):
     f=decode_pet_info(raw,human_equipment=bool(human)).fields
     pets.append(dict(id=pet_id,level=f['0x8c4aef'],xp=f['0x8c4b05']))
   slots.append(dict(slot=slot,owner=owner,name=character[0].decode('ascii') if character else None,wallet=list(wallet) if wallet else None,pets=pets))
  states.append(dict(account=n,slots=slots))
 frozen={}
 for table in data['global_tables']:
  rows=sorted(map(repr,db.execute('SELECT * FROM '+table))) if table in tables else []
  frozen[table]=dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
 own_mail=[]
 if 'mail_messages' in tables:
  for row in db.execute('SELECT id,sender,recipient,subject,body,credits,fee,state FROM mail_messages WHERE sender IN (?,?,?,?) OR recipient IN (?,?,?,?) ORDER BY id',owned+owned):
   own_mail.append(dict(zip(('id','sender','recipient','subject','body','credits','fee','state'),row)))
 claim_count=db.execute("SELECT count(*) FROM mail_receipts WHERE action='claimed' AND owner IN (?,?,?,?)",owned).fetchone()[0] if 'mail_receipts' in tables else 0
 idle={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] if table in tables else 0 for table in ('battle_checkpoints','battle_settlement_jobs')}
 sources={name:hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest() for name in data['source_hashes']}
 assert sources==data['source_hashes'],'Reviewed stage7 sources changed'
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0];assert integrity=='ok'
connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
print(json.dumps(dict(states=states,global_state=frozen,own_mail=own_mail,own_claim_count=claim_count,idle=idle,source_sha256=sources,integrity=integrity,game_connections=connections)))
'''

PRESERVATION=OWNERSHIP+r'''
from tio.character_identity import alias
owned=[owner for n in names for owner in (n,alias(n,2))]
with sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True) as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 old.execute('BEGIN');db.execute('BEGIN');checked={}
 for table, in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
  quoted='"'+table.replace('"','""')+'"';columns=[r[1] for r in old.execute('PRAGMA table_info('+quoted+')')]
  account=next((column for column in ('account','login','owner') if column in columns),None)
  if account:
   args=names if account=='login' else owned
   query='SELECT * FROM '+quoted+' WHERE "'+account+'" NOT IN ('+','.join('?' for _ in args)+')'
   before=set(map(repr,old.execute('SELECT * FROM '+quoted)));after=set(map(repr,db.execute(query,args)))
   assert before==after,'Foreign account rows changed in '+table
   checked[table]=len(before)
  elif table in ('mail_messages','mail_requests','mail_receipts'):
   account='sender' if 'sender' in columns else 'owner';args=owned
   query='SELECT * FROM '+quoted+' WHERE "'+account+'" NOT IN ('+','.join('?' for _ in args)+')'
   before=set(map(repr,old.execute('SELECT * FROM '+quoted)));after=set(map(repr,db.execute(query,args)))
   assert before==after,'Foreign mail rows changed in '+table
   checked[table]=len(before)
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?,?,?)',owned).fetchone()
print(json.dumps(dict(integrity='ok',existing_account_rows_preserved=checked)))
'''


def deployment_hashes(path):
    proof=json.loads(Path(path).read_text(encoding='utf-8'))
    require(proof.get('source_parity') is True,'Successful reviewed deployment source parity required')
    values=proof.get('source_sha256',{})
    paths=json.loads((ROOT/'reports/stage7/runtime-files.json').read_text(encoding='utf-8'))
    require(isinstance(values,dict) and 1<=len(values)<=256 and len(set(paths))==len(paths) and set(values)==set(paths),'Exact bounded stage7 runtime source proof required')
    for name,digest in values.items():
        require(isinstance(name,str) and re.fullmatch(r'(?:tio|server|tools|config|evidence)/[A-Za-z0-9_./-]+',name) and '..' not in Path(name).parts,'Unsafe runtime path')
        require(re.fullmatch('[0-9a-f]{64}',digest) and hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,'Local/deployed reviewed source mismatch')
    return values


class Stage7Fixture(FreshSurroundingsQA):
    @staticmethod
    def private_directory():
        require(not PRIVATE.is_symlink(),'Private directory cannot be a symlink');PRIVATE.mkdir(parents=True,exist_ok=True)
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
        prefix='qs'+secrets.token_hex(4);alphabet='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
        fixture=cls(host,prefix,[prefix+'a',prefix+'b'],[''.join(secrets.choice(alphabet) for _ in range(16)) for _ in range(2)],'',key)
        fixture.save(pending=True);return fixture

    @classmethod
    def load(cls,path):
        path=Path(path);require(not path.is_symlink(),'Private fixture cannot be a symlink');path=path.resolve()
        require(path.parent==PRIVATE.resolve(),'Dedicated private fixture required');cls.private_directory()
        data=json.loads(path.read_text(encoding='utf-8'));require(data.pop('version')==1,'Unexpected fixture version')
        fixture=cls(**data,credential_path=str(path))
        require(re.fullmatch('qs[0-9a-f]{8}',fixture.prefix) and fixture.names==[fixture.prefix+'a',fixture.prefix+'b'] and len(fixture.passwords)==2,'Exactly two owned QA identities required')
        require(all(isinstance(value,str) and len(value)==16 and value.isascii() for value in fixture.passwords),'Bounded ordinary passwords required')
        return fixture

    def provision(self,hashes):
        require(not self.backup and self.credential_path.endswith('.pending.json'),'Provision a prepared empty pair only once')
        result=self.remote(PROVISION,dict(prefix=self.prefix,pairs=list(zip(self.names,self.passwords)),source_hashes=hashes))
        self.backup=result['backup'];self.save();return result

    def status(self,hashes):
        return self.remote(SNAPSHOT,{**self.ownership_payload(),'source_hashes':hashes,'global_tables':GLOBAL_TABLES})


class Stage7Network(TlsNetworkQA):
    def attach(self,index,*,fresh=False,slot=2):
        peer=self.handoff(self.begin(index));self.received[index]=[];original=peer.receive
        def receive():
            packet=original();self.received[index].append(packet);return packet
        peer.receive=receive;self.peers[index]=peer;records=self.case.character_screen(peer)
        expected=[(s,(self.fixture.names[index]+('' if s==1 else '2')).encode()) for s in (1,2)]
        if fresh:
            require(not records,'Fresh account already has characters')
            for identity,name in expected:
                peer.send(encode_character_create(CharacterCreateRequest(name,0,(index+1,0,0,0))))
                require(peer.receive()==b'\x12\x05','Normal character creation failed')
                editing=decode_character_list(peer.receive())
                require([(r.record_id,r.name_bytes) for r in editing]==[(identity,name)] and len(editing[0].optional_six)==6,'Only new slot must be exposed in free appearance editor')
                peer.send(appearance_request(identity,editing[0].optional_six));records=decode_character_list(peer.until(b'\x10'))
        require([(r.record_id,r.name_bytes) for r in records]==expected,'Two normal owned character slots required')
        peer.send(b'\x17'+slot.to_bytes(4,'little'));require(peer.receive()[:1]==b'\x18','Native slot selection failed')
        peer.send(b'\x19');character=decode_mychar_info(peer.until(b'\x1a'))
        require((character.character_id,character.name_bytes)==expected[slot-1],'Selected MyCharInfo is not requested slot')
        assets=decode_asset_count(peer.until(b'\xc8\x39'));pet=decode_pet_info(peer.until(b'\x66'),human_equipment=True)
        require(pet.fields['0x8c4489']==expected[slot-1][1] and pet.fields['0x8c4aef']==1 and pet.fields['0x8c4b05']==0,'Selected native starter pet is wrong')
        self.ping(peer);return assets

    def detach(self,index):
        peer=self.peers.pop(index,None)
        if peer is not None:peer.sock.close()


def _one(replies,prefix):
    rows=[p for p in replies if p.startswith(prefix)];require(len(rows)==1,'Exactly one native response expected: '+prefix.hex());return rows[0]


def wait_connections(fixture,hashes,count):
    deadline=time.monotonic()+5
    while True:
        state=fixture.status(hashes)
        require(not any(state['idle'].values()),'QA encountered a retained battle or reward job')
        if state['game_connections']==count:return state
        require(time.monotonic()<deadline,'Owned connection release did not finish');time.sleep(.1)


def run(fixture,args,report,hashes):
    require(bool(fixture.backup),'Ownership-proven provisioned pair required')
    before=fixture.status(hashes)
    require(before['game_connections']==0 and not any(before['idle'].values()),'Players or retained battles present; abort QA')
    require(all(slot['name'] is None for state in before['states'] for slot in state['slots']),'Fresh empty accounts required; never reset existing QA')
    net=Stage7Network(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    transfer=10;subject='Stage7 owned QA';body='Offline text and credits'
    rules=json.loads((ROOT/'config/mail.json').read_text(encoding='utf-8'))
    fee=rules['base_credit_fee']+math.ceil(transfer*rules['money_fee_percent']/100)
    try:
        for index in (0,1):
            assets=net.attach(index,fresh=True,slot=2)
            require((assets.credits,assets.gold)==(3000,0),'Native secondary starter money must be3000/0')
        created=fixture.status(hashes)
        for state in created['states']:
            require([s['wallet'] for s in state['slots']]==[[3000,0],[3000,0]],'Ordinary primary/secondary starters required')
            require(all(s['pets']==[dict(id=1,level=1,xp=0)] for s in state['slots']),'Ordinary slot starters required')
        net.detach(1);wait_connections(fixture,hashes,1)
        recipient=(fixture.names[1]+'2').encode()
        draft=mail.DraftRequest(0,recipient,subject,body,((MAIL_CURRENCY,transfer),))
        replies=net.command(0,mail.encode_draft(draft));quote=mail.decode_body(_one(replies,b'\xb7\x7a'))
        require(quote.identity==0 and quote.price==fee and quote.subject==subject and quote.body==body,'Native draft quote did not retain text/fee')
        quoted=fixture.status(hashes);require(quoted['states'][0]['slots'][1]['wallet']==[3000,0] and not quoted['own_mail'],'Draft cannot debit or deliver')
        replies=net.command(0,mail.encode_recalculate(0,True));quote=mail.decode_body(_one(replies,b'\xb7\x7a'))
        require(quote.identity==0 and quote.price==fee,'Native recalculation quote mismatch')
        final=mail.encode_body_request(mail.BodyRequest(1,0,subject,body))
        replies=net.command(0,final)
        sent=fixture.status(hashes);require(len(sent['own_mail'])==1,'Finalize must create one ordinary offline letter')
        message=sent['own_mail'][0]['id'];require(sent['states'][0]['slots'][1]['wallet']==[3000-transfer-fee,0],'Sender debit must equal transfer plus quoted fee')
        net.command(0,final)
        retried=fixture.status(hashes);require(retried['own_mail']==sent['own_mail'] and retried['states'][0]['slots'][1]['wallet']==sent['states'][0]['slots'][1]['wallet'],'Repeated finalize changed transfer')
        require(net.attach(1,slot=2).credits==3000,'Offline recipient must receive only on claim')
        rows=mail.decode_list(_one(net.command(1,mail.encode_page(1)),b'\xb7\x79'))[2]
        require(len(rows)==1 and rows[0].identity==message and rows[0].subject==subject,'Recipient inbox missing offline letter')
        letter=mail.decode_body(_one(net.command(1,mail.encode_body_request(mail.BodyRequest(0,message))),b'\xb7\x7a'))
        require(letter.subject==subject and letter.body==body,'Delivered offline text changed')
        claim=mail.encode_body_request(mail.BodyRequest(1,message));net.command(1,claim);claimed=fixture.status(hashes)
        require(claimed['states'][1]['slots'][1]['wallet']==[3000+transfer,0] and claimed['own_claim_count']==1,'Ordinary claim must credit once')
        net.command(1,claim);repeated=fixture.status(hashes)
        require(repeated['states'][1]['slots'][1]['wallet']==[3000+transfer,0] and repeated['own_claim_count']==1,'Repeated claim credited twice')
        for text in ('!teamrating','!seasons'):
            replies=net.command(0,b'\x21\0'+text.encode('utf-16-le')+bytes(2))
            require(any(p.startswith(b'\x22') and b'TIO\0' in p for p in replies),'Native standings command did not return private chat')
            time.sleep(.55)
        report.update(starter_wallets=[[3000,0]]*4,mail_transfer=transfer,mail_fee=fee,mail_message_id=message,
            draft_no_debit=True,finalize_replay_once=True,offline_text_delivery=True,claim_replay_once=True,native_standings_commands=['!teamrating','!seasons'])
        net.detach(0);net.detach(1);wait_connections(fixture,hashes,0)
        require(net.attach(1,slot=2).credits==3000+transfer,'Secondary relogin lost mail balance')
        net.detach(1);wait_connections(fixture,hashes,0)
        for index in (0,1):
            assets=net.attach(index,slot=1);require((assets.credits,assets.gold)==(3000,0),'Primary slot changed with secondary transfer')
            net.detach(index);wait_connections(fixture,hashes,0)
        report.update(secondary_relogin_preserved=True,primary_slots_unchanged=True)
    finally:
        net.close();report['tls_channels']=[connection.metadata() for connection in net.connections]
    after=wait_connections(fixture,hashes,0)
    require(after['global_state']==before['global_state'],'QA changed unrelated claims/battles/ratings')
    require(all(s['pets']==[dict(id=1,level=1,xp=0)] for state in after['states'] for s in state['slots']),'QA unexpectedly changed level or XP')
    report.update(source_sha256=hashes,global_claims_battles_ratings_unchanged=True,
        preservation=fixture.remote(PRESERVATION,fixture.ownership_payload()),disconnected_game_connections=0,passed=True)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare-owned','provision-owned','run'))
    p.add_argument('--fixture',type=Path);p.add_argument('--deployment',type=Path,default=ROOT/'reports/stage7/deployment.json')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--host',default='185.184.42.88')
    p.add_argument('--key',default=str(Path.home()/'.ssh/tio_server'));p.add_argument('--server-name',default='ti-reborn.com')
    p.add_argument('--login-port',type=int,default=29512);p.add_argument('--session-port',type=int,default=29513)
    p.add_argument('--loopback-session-port',type=int,default=28513);p.add_argument('--ca-file',type=Path)
    args=p.parse_args(argv)
    if args.output.exists():p.error('Preserve existing evidence; choose a fresh output')
    if args.action!='prepare-owned' and not args.fixture:p.error('Prepared private --fixture required')
    if any(not 1024<=port<=65535 for port in (args.login_port,args.session_port,args.loopback_session_port)):p.error('Invalid port')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),kind='two ordinary accounts; native Stage7 protocol over verified TLS',
        limitations=['no graphical clients started','no hosted combat or seasonal rating award; two accounts cannot form a 2x2 match','no mail item fixture or administrative money/level writes'])
    try:
        if args.action=='prepare-owned':
            fixture=Stage7Fixture.prepare(args.host,args.key);report.update(passed=True,prepared=True,accounts=fixture.names,credential_file=fixture.credential_path)
        else:
            fixture=Stage7Fixture.load(args.fixture);require(fixture.host==args.host,'Fixture belongs to another host');hashes=deployment_hashes(args.deployment)
            if args.action=='provision-owned':
                report['provision']=fixture.provision(hashes);report.update(passed=True,credential_file=fixture.credential_path,accounts=fixture.names)
            else:run(fixture,args,report,hashes)
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__;report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,graphical_clients_started=0)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
