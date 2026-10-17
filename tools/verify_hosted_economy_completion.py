"""Ordinary shared economy QA on the preserved phase5 pair, over verified TLS.

No provisioning, administrative save changes, deployment, clock acceleration,
merchant calls or synthetic Gold. SQL is readonly. PIN and resumable paid-action
journal stay in the ACL-protected Stage7Fixture directory; raw commands never
enter output. Run only after root confirms the reviewed phase6 deployment.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_hosted_roster_completion import RosterNetwork,deployment_hashes as roster_hashes
from tools.verify_hosted_stage7 import Stage7Fixture
from tools.verify_hosted_arena_surroundings import OWNERSHIP,require
from tools.verify_game_tls_hosted import tls_context
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.binary import Reader,Writer
from tio.protocol.chat import text_read
from tio.protocol.item_list import decode_item_list
from tio.protocol.item_marks import metadata as mark_metadata
from tio.protocol.private_shops import text as market_text
from tio.protocol.sc_auction_view import decode as sc_decode,DAY_ZERO
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.mail import encode_page,encode_body_request,BodyRequest,decode_body,decode_post_warehouse
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer


def deployment_hashes(directory,phase6):
    result=roster_hashes(directory);proof=json.loads(Path(phase6).read_text(encoding='utf8'))
    require(proof.get('source_parity') is True,'Successful phase6 deployment parity required')
    previous=json.loads((Path(directory)/'stage5-roster/deployment.json').read_text(encoding='utf8'))['timestamp_utc']
    require(proof.get('timestamp_utc','')>=previous,'Phase6 proof predates roster deployment')
    values=proof.get('source_sha256');require(isinstance(values,dict) and 1<=len(values)<=512,'Bounded phase6 source proof required')
    runtime={}
    for path,digest in values.items():
        require(isinstance(path,str) and '..' not in Path(path).parts and re.fullmatch('[0-9a-f]{64}',digest),'Unsafe deployment source digest')
        if re.fullmatch(r'docs/[A-Za-z0-9_./-]+\.md',path):continue
        require(re.fullmatch(r'(?:tio|server|tools|config|evidence)/[A-Za-z0-9_./-]+',path),'Unsafe runtime source path')
        runtime[path]=digest
    expected=json.loads((Path(phase6).parent/'runtime-files.json').read_text(encoding='utf8'))
    require(set(runtime)==set(expected) and len(set(expected))==len(expected),'Exact phase6 runtime set differs')
    require({'server/bank_gameplay.py','server/economy_runtime.py','server/private_market.py','tio/sc_auction.py','tio/private_shops.py','tio/bank_economy.py','tio/protocol/sc_auction_view.py'}<=runtime.keys(),'Shared economy release coverage missing')
    result.update(runtime);return result


SNAPSHOT=OWNERSHIP+r'''
import hashlib,subprocess,time
from tio.protocol.item_list import decode_item_list
from tio.protocol.pet_info import decode_pet_info
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN');tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 def dictionaries(table,fields,where='',args=()):
  if table not in tables:return []
  columns=[r[1] for r in db.execute('PRAGMA table_info('+table+')')];assert set(fields)<=set(columns)
  return [dict(zip(fields,r)) for r in db.execute('SELECT '+','.join(fields)+' FROM '+table+where,args)]
 def digest(table,account):
  rows=sorted(map(repr,db.execute('SELECT * FROM '+table+' WHERE account=?',(account,)))) if table in tables else []
  return dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
 def item(row,place):
  return dict(id=row.instance_id,template=row.template_id,count=row.count,equipped=row.equipped,slot=row.slot,durability=list(row.unknown_words),enhance=list(row.unknown_bytes_03),marked=bool(row.unknown_bytes_02[2]),rented=bool(row.unknown_bytes_02[3]),place=place)
 states=[]
 for account in names:
  character=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(account,)).fetchone();assert character and bytes(character[0]).decode('ascii')==account
  assert db.execute('SELECT count(*) FROM characters WHERE account=?',(account,)).fetchone()[0]==1
  assert not db.execute('SELECT 1 FROM character_identities WHERE login=?',(account,)).fetchone()
  wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone();assert wallet
  inventory=[];pets=[]
  for identity,human,raw,items in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(account,)):
   f=decode_pet_info(raw,human_equipment=bool(human)).fields
   pets.append(dict(id=identity,level=f['0x8c4aef'],xp=f['0x8c4b05'],profile_sha256=hashlib.sha256(raw).hexdigest()))
   inventory.extend(item(i,identity) for i in decode_item_list(items)[1])
  for raw, in db.execute('SELECT item_packet FROM warehouse_items WHERE account=? ORDER BY instance_id',(account,)):
   inventory.extend(item(i,'warehouse') for i in decode_item_list(raw)[1])
  securities=db.execute('SELECT stocks,bonds FROM bank_securities WHERE account=?',(account,)).fetchone() if 'bank_securities' in tables else None
  awards=dictionaries('achievement_awards',('id','body'), ' WHERE account=? ORDER BY id',(account,));delivered=dictionaries('achievement_prizes',('id','position','delivered'),' WHERE account=?',(account,))
  achievement_credits=0
  for a in awards:
   body=json.loads(a.pop('body'));a['temporary_credits']=body.get('temporary_credits',0);a['metric']=body['metric']
   if any(p['id']==a['id'] and p['position']==len(body['prizes']) and p['delivered'] for p in delivered):achievement_credits+=a['temporary_credits']
  receipts=dictionaries('bank_economy_receipts',('operation','identity','request','receipt'),' WHERE account=? ORDER BY operation,identity',(account,))
  for r in receipts:r['request']=json.loads(r['request']);r['receipt']=json.loads(r['receipt'])
  shop=dictionaries('private_shops',('id','revision','signature','package'),' WHERE account=?',(account,))
  sales=[];orders=[]
  if shop:
   for position,raw,price in db.execute('SELECT position,item_packet,price_cents FROM private_shop_sales WHERE shop=? ORDER BY position',(shop[0]['id'],)):
    sales.append(dict(position=position,item=item(decode_item_list(raw)[1][0],'sale'),price_cents=price))
   orders=dictionaries('private_shop_orders',('position','template','quantity','price_cents','enhance','held'),' WHERE shop=? ORDER BY position',(shop[0]['id'],))
  marks=dictionaries('bank_item_marks',('id','owner','original_instance','holder','current_instance','template','expires','state','failures','locked_until'),' WHERE owner=? ORDER BY id',(account,))
  messages=dictionaries('mail_messages',('id','sender','recipient','state','credits','expires_at'),' WHERE recipient=? ORDER BY id',(account,));mail_items=[]
  for m in messages:
   for escrow,raw in db.execute('SELECT escrow_id,item_packet FROM mail_items WHERE message=?',(m['id'],)):
    mail_items.append(dict(message=m['id'],escrow=escrow,item=item(decode_item_list(raw)[1][0],'mail')))
  tutorial=db.execute('SELECT completed,observed_events FROM character_tutorials WHERE account=?',(account,)).fetchone()
  states.append(dict(account=account,wallet=list(wallet),securities=list(securities or (0,0)),pets=pets,items=sorted(inventory,key=lambda i:i['id']),tutorial=list(tutorial),achievement_credits=achievement_credits,awards=awards,bank_receipts=receipts,marks=marks,shop=shop[0] if shop else None,sales=sales,orders=orders,messages=messages,mail_items=mail_items,mail_receipts=dictionaries('mail_receipts',('message','action','payload'),' WHERE owner=? ORDER BY message,action',(account,)),sc_receipts=dictionaries('sc_auction_receipts',('request','fingerprint','result'),' WHERE account=? ORDER BY request',(account,)),private_receipts=dictionaries('private_shop_receipts',('request','fingerprint','result'),' WHERE account=? ORDER BY request',(account,)),protected={t:digest(t,account) for t in ('battle_rewards','player_battle_statistics','experience_battle_audit','rank_battle_audit','soldier_ratings')}))
 lots=dictionaries('sc_auction_lots',('id','offer_key','currency','price','fee','step','started','ends','extension','automatic','state','bidder','bids','message','expires_at'),' ORDER BY id')
 for row in lots:
  raw=db.execute('SELECT item_packet FROM sc_auction_lots WHERE id=?',(row['id'],)).fetchone()[0];row['prizes']=[item(i,'system_sc') for i in decode_item_list(raw)[1]]
 sc_history=dictionaries('sc_auction_history',('id','lot','account','action','amount','occurred','automatic'),' ORDER BY id')
 bots=dictionaries('sc_auction_bots',('lot','account','from_price','to_price','remaining','held'),' ORDER BY lot,account')
 foreign={}
 # Autonomous system SC history is expected to replenish/close on its normal
 # clock. Fingerprint only rows belonging to actual pre-existing real accounts.
 owners=({r[0] for r in db.execute('SELECT DISTINCT account FROM characters')}|{r[0] for r in db.execute('SELECT login FROM accounts')}) - set(names)
 for table in sorted(tables-{'sqlite_sequence'}):
  quoted='"'+table.replace('"','""')+'"';columns=[r[1] for r in db.execute('PRAGMA table_info('+quoted+')')]
  column=next((c for c in ('account','login','owner') if c in columns),None)
  if column:
   rows=sorted(repr(r) for r in db.execute('SELECT * FROM '+quoted) if r[columns.index(column)] in owners)
   foreign[table]=dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
 claims={t:dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest()) for t in ('territory_claims','territory_claim_history','mine_claims','mine_claim_history','warfare_events','warfare_matches','warfare_scores','ranked_matches') for rows in [sorted(map(repr,db.execute('SELECT * FROM '+t))) if t in tables else []]}
 payments={t:dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest()) for t in ('bank_payment_orders','bank_payment_events','bank_gold_payables') for rows in [sorted(map(repr,db.execute('SELECT * FROM '+t))) if t in tables else []]}
 sources={p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in data['source_hashes']};assert sources==data['source_hashes'],'Reviewed deployed source changed'
 policy=json.loads(pathlib.Path('config/bank_economy.json').read_text())['provider'];provider={k:policy[k] for k in ('enabled','type','currency','minor_units_per_gold','minimum_gold')}
 quotes=dictionaries('bank_quotes',('kind','price','period'),' ORDER BY kind');history=dictionaries('bank_quote_history',('id','kind','observed','price'),' ORDER BY id')
 idle={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] if t in tables else 0 for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')}
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0];assert integrity=='ok'
connections=len(subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
service=subprocess.check_output(['systemctl','show','tio-server','--property=MainPID,NRestarts,ExecMainStatus,ActiveState'],text=True).strip()
print(json.dumps(dict(states=states,lots=lots,bots=bots,sc_history=sc_history,quotes=quotes,quote_history=history,foreign=foreign,claims=claims,payments=payments,sources=sources,provider=provider,idle=idle,integrity=integrity,connections=connections,service=service,utc=int(time.time()))))
'''


def status(fixture,hashes):return fixture.remote(SNAPSHOT,{**fixture.ownership_payload(),'source_hashes':hashes})


def chat(text):
    require(len(text.encode('utf-16le'))<=400,'Bounded command required')
    return b'\x21\0'+text.encode('utf-16le')+b'\0\0'


def bank_lines(packets):
    rows=[]
    for packet in packets:
        if packet[:1]!=b'\x22':continue
        r=Reader(packet);r.u8();r.u32();channel=r.u8();name=bytearray()
        while (c:=r.u8()):name.append(c)
        value=text_read(r);r.finish()
        if bytes(name)==b'Bank':require(channel==4,'Bank response became public');rows.append(value)
    return rows


def traders(packet):
    r=Reader(packet);require(r.read(2)==b'\xae\x02','Expected actual trader list');count=r.u32();require(count<=100,'Trader list bound')
    rows=[]
    for _ in range(count):
        kind,identity=r.u8(),r.u32();name,signature=market_text(r),market_text(r);flag=r.u32();require(flag==1,'Trader conditional branch differs');rows.append(dict(kind=kind,id=identity,name=name,signature=signature))
    r.finish();return rows


def goods(packet):
    r=Reader(packet);require(r.u8()==0xae,'Expected private goods');op=r.u8();require(op in (4,5),'Wrong goods kind')
    identity,count=r.u32(),r.u32();require(count<=100,'Goods bound');rows=[]
    for _ in range(count):
        template,position,units=r.u32(),r.u32(),r.u32();price=struct.unpack('<f',r.read(4))[0]
        if op==4:enhance,cur,maximum,special=r.u8(),r.u16(),r.u16(),r.u8();flags=(enhance,cur,maximum,special)
        else:flags=(r.u8(),r.u8(),r.u8())
        rows.append(dict(template=template,position=position,count=units,price=price,flags=flags))
    r.finish();return identity,rows


def sc_rows(packet):
    op,rows=sc_decode(packet);require(op==1,'Expected SC catalogue');out=[]
    for raw,texts,prizes in rows:
        out.append(dict(id=struct.unpack_from('<I',raw)[0],state=raw[8],currency=raw[9],price=struct.unpack_from('<I',raw,16)[0],fee=struct.unpack_from('<I',raw,24)[0],step=struct.unpack_from('<I',raw,28)[0],remaining_ms=struct.unpack_from('<I',raw,40)[0],extension_ms=struct.unpack_from('<I',raw,48)[0],name=texts[1],personal=bool(raw[60]),bought=bool(raw[61]),automatic=bool(raw[73]),prizes=prizes))
    return out


def one(packets,prefix):
    rows=[p for p in packets if p.startswith(prefix)];require(rows,'Expected native response');return rows[-1]


def item(state,index,identity):return next(i for i in state['states'][index]['items'] if i['id']==identity)
def lot(state,identity):return next(i for i in state['lots'] if i['id']==identity)
def wallets(state):return [s['wallet'] for s in state['states']]
def credits(state,index):return state['states'][index]['wallet'][0]
def physical_count(state,template):return sum(i['count'] for s in state['states'] for i in s['items'] if i['template']==template)+sum(i['item']['count'] for s in state['states'] for i in s['sales'] if i['item']['template']==template)
def receipt(state,index,operation,key):return next((r for r in state['states'][index]['bank_receipts'] if (r['operation'],r['identity'])==(operation,key)),None)


class PrivateProgress:
    """Paid-action recovery lives beside private credentials, never in reports."""
    def __init__(self,fixture,hashes,*,resume):
        Stage7Fixture.private_directory();self.path=Path(fixture.credential_path).with_name(fixture.prefix+'.economy-progress.json')
        require(not self.path.is_symlink(),'Private progress must not be a symlink')
        if self.path.exists():
            require(resume,'Existing paid progress requires explicit --resume');self.value=json.loads(self.path.read_text(encoding='utf8'))
            require(self.value['accounts']==fixture.names and self.value['host']==fixture.host,'Progress ownership differs')
        else:
            require(not resume,'Resume progress missing');self.value=dict(version=1,accounts=fixture.names,host=fixture.host,pin=''.join(str(secrets.randbelow(10)) for _ in range(8)),actions={},facts={},base=None)
            self.save()
        require(re.fullmatch('[0-9]{8}',self.value['pin']) and self.value['version']==1,'Private PIN/progress shape invalid')
        self.value['current_source_hashes']=hashes

    def save(self):
        raw=json.dumps(self.value,separators=(',',':')).encode();require(len(raw)<=16*1024*1024,'Bounded private progress exceeded')
        temporary=self.path.with_suffix('.tmp');require(not temporary.exists() and not temporary.is_symlink(),'Private progress temporary exists')
        with temporary.open('xb') as f:f.write(raw)
        temporary.replace(self.path)


class EconomyNetwork(RosterNetwork):
    def attach(self,index,*,fresh=False):
        require(not fresh,'Never recreate owned phase5 characters')
        assets=super().attach(index)
        for packet in self.received[index]:
            if packet[:1]==b'\xf8':sc_decode(packet)
        require(not any(p[:1]==b'\x35' for p in self.received[index]),'Completed tutorial restarted')
        return assets

    def ask_matching(self,index,packet,predicate):
        """Async market pushes may precede the specific requested response."""
        start=len(self.received[index]);peer=self.peers[index];peer.send(packet);deadline=time.monotonic()+15
        for _ in range(4096):
            reply=peer.receive()
            if predicate(reply):self.ping(peer);return self.received[index][start:]
            require(time.monotonic()<deadline,'Matching native market reply deadline exceeded')
        raise AssertionError('Matching native market reply missing')

    def bank(self,index,text):
        start=len(self.received[index]);self.peers[index].send(chat(text))
        for _ in range(4096):
            p=self.peers[index].receive()
            if bank_lines((p,)):break
        else:raise AssertionError('Private bank reply missing')
        self.ping(self.peers[index]);self.ping(self.peers[index]);return self.received[index][start:]

    def projected_mark(self,index,identity,owner,*,present):
        start=len(self.received[index]);deadline=time.monotonic()+12
        self.command(index,b'\x2f\x03\0'+struct.pack('<3I',1,2,3));self.command(index,b'\x69\x01')
        while True:
            for packet in self.received[index][start:]:
                if packet[:1] not in (b'\x30',b'\x6a'):continue
                values=mark_metadata(packet)
                if present and identity in values:
                    name,seconds=values[identity]
                    require(name==owner and type(seconds)is int and 0<seconds<=86400,'Mark owner/time projection differs')
                    return dict(opcode=packet[0],owner_public_name=True,remaining_positive=True)
                if not present and identity not in values:
                    # Do not accept an unrelated empty segment: require this
                    # canonical packet to contain the reclaimed physical item.
                    try:
                        ids=[i.instance_id for i in decode_item_list(packet)[1]] if packet[0]==0x30 else []
                        if packet[0]==0x6a:
                            from tio.protocol.warehouse import decode_warehouse_list
                            ids=[i.instance_id for i in decode_warehouse_list(packet)[3]]
                    except ValueError:continue
                    if identity in ids:return dict(opcode=packet[0],marker_removed=True)
            require(time.monotonic()<deadline,'Matching projected mark metadata deadline exceeded')
            time.sleep(.15);self.ping(self.peers[index])


class Runner:
    def __init__(self,fixture,hashes,net,progress):self.fixture,self.hashes,self.net,self.progress=fixture,hashes,net,progress
    def state(self):return status(self.fixture,self.hashes)
    def key(self,name):return self.fixture.prefix+'-'+name+'-001'
    def execute(self,name,index,send,predicate,*,assets=True):
        actions=self.progress.value['actions'];old=actions.get(name)
        if old and old.get('done'):return old['after']
        before=old['before'] if old else self.state()
        if not old:actions[name]=dict(before=before,done=False);self.progress.save()
        current=self.state();recovered=bool(old and not name.endswith('replay') and predicate(before,current))
        start=len(self.net.received[index])
        if not recovered:send()
        deadline=time.monotonic()+15
        while True:
            after=self.state()
            if predicate(before,after):break
            require(time.monotonic()<deadline,'Durable ordinary action did not reach its expected state')
            self.net.ping(self.net.peers[index]);time.sleep(.15)
        packets=self.net.received[index][start:];native_assets=[]
        if assets and not recovered:
            expected=after['states'][index]
            while True:
                native_assets=[decode_asset_count(p) for p in self.net.received[index][start:] if p.startswith(b'\xc8\x39')]
                if any([a.credits,a.gold]==expected['wallet'] and [a.spectra_stock,a.spectra_bonds]==expected['securities'] for a in native_assets):break
                require(time.monotonic()<deadline,'Matching native wallet/securities reply missing')
                self.net.ping(self.net.peers[index])
        actions[name]=dict(before=before,after=after,done=True,recovered_paid_action_without_resend=recovered,native_opcodes=dict(Counter(p[:2].hex() if p[0] in (0xae,0xbd,0xc8,0xb7,0xf8) else p[:1].hex() for p in packets)),wallet_before=wallets(before),wallet_after=wallets(after),native_assets=[dict(credits=a.credits,gold=a.gold,stocks=a.spectra_stock,bonds=a.spectra_bonds) for a in native_assets])
        self.progress.save();phase(name);return after


def phase(name,**extra):print(json.dumps(dict(phase=name,credentials_printed=False,pin_printed=False,**extra)),flush=True)


def stocks(runner):
    net=runner.net;p=runner.progress
    for index in (0,1):
        start_other=len(net.received[1-index]);lines=bank_lines(net.bank(index,'!bank quotes'))
        require(len(lines)==4 and any('1 Gold = 100' in l for l in lines),'Native private bank quotes differ')
        net.ping(net.peers[1-index]);require(not bank_lines(net.received[1-index][start_other:]),'Bank reply leaked to another real account')
    current=runner.state();quote=next(q['price'] for q in current['quotes'] if q['kind']=='stocks')
    require(1<=quote<=500,'Observed stock quote exceeds bounded starter budget');p.value['facts']['stock_quote']=quote;p.save()
    for index,count in ((0,3),(1,2)):
        name='stocks-buy-'+str(index);key=runner.key(name);command=f'!bank stocks buy {count} {quote} {key}'
        bought=runner.execute(name,index,lambda i=index,c=command:net.bank(i,c),lambda b,a,i=index,n=count,k=key:receipt(a,i,'securities',k) is not None and credits(b,i)-credits(a,i)==n*quote and a['states'][i]['securities'][0]==b['states'][i]['securities'][0]+n and a['states'][1-i]==b['states'][1-i])
        runner.execute(name+'-replay',index,lambda i=index,c=command:net.bank(i,c),lambda b,a:wallets(a)==wallets(b) and [s['securities'] for s in a['states']]==[s['securities'] for s in b['states']])
        name='stocks-sell-'+str(index);key=runner.key(name);command=f'!bank stocks sell {count} {quote} {key}'
        runner.execute(name,index,lambda i=index,c=command:net.bank(i,c),lambda b,a,i=index,n=count,k=key:receipt(a,i,'securities',k) is not None and credits(a,i)-credits(b,i)==n*quote and a['states'][i]['securities'][0]==b['states'][i]['securities'][0]-n and a['states'][1-i]==b['states'][1-i])
        runner.execute(name+'-replay',index,lambda i=index,c=command:net.bank(i,c),lambda b,a:wallets(a)==wallets(b) and [s['securities'] for s in a['states']]==[s['securities'] for s in b['states']])
    lines=bank_lines(net.bank(0,'!bank history stocks'));require(any('котировок' in l for l in lines),'Real shared history not returned')
    for kind,command in (('convert',f'!bank convert 1 {runner.key("gold-reject")}'),('bonds',f'!bank bonds buy 1 1 {runner.key("bonds-reject")}')):
        before=runner.state();lines=bank_lines(net.bank(0,command));after=runner.state()
        require(lines and before['states']==after['states'] and before['payments']==after['payments'],'0Gold operation changed owned money/receipt/item state')
    p.value['facts']['zero_gold_conversion_bond_rejection']=True;p.value['facts']['private_bank_replies']=True;p.save()


def marked_lending(runner):
    net=runner.net;p=runner.progress;pin=p.value['pin'];facts=p.value['facts']
    for c in net.connections:c.audit.add_pattern(pin.encode());c.audit.add_pattern(pin.encode('utf-16le'))
    def purchase():net.command(0,encode_shop_purchase(ShopPurchase(1,0,1,1)))
    purchased=runner.execute('buy-mark-item',0,purchase,lambda b,a:physical_count(a,301)==physical_count(b,301)+1 and a['states'][0]['achievement_credits']-b['states'][0]['achievement_credits']==100 and credits(b,0)-credits(a,0)+a['states'][0]['achievement_credits']-b['states'][0]['achievement_credits']==150 and a['states'][1]==b['states'][1])
    if 'marked_instance' not in facts:
        before=runner.progress.value['actions']['buy-mark-item']['before'];known={i['id'] for i in before['states'][0]['items']}
        new=[i for i in purchased['states'][0]['items'] if i['id'] not in known and i['template']==301 and i['count']==1 and not i['equipped'] and not i['slot']]
        require(len(new)==1,'Lawfully bought ordinary mark item ambiguous');facts['marked_instance']=new[0]['id'];facts['item_basis']={k:new[0][k] for k in ('template','count','durability','enhance')};p.save()
    instance=facts['marked_instance'];key=runner.key('mark');command=f'!bank mark {instance} 1 {pin} {key}'
    marked=runner.execute('mark',0,lambda:net.bank(0,command),lambda b,a:receipt(a,0,'mark',key) is not None and credits(b,0)-credits(a,0)==100 and physical_count(a,301)==physical_count(b,301) and a['states'][1]==b['states'][1])
    mark=receipt(marked,0,'mark',key)['receipt']['mark_id'];facts['mark_id']=mark;p.save()
    if 'mark_projection' not in facts:facts['mark_projection']=net.projected_mark(0,instance,runner.fixture.names[0],present=True);p.save()
    runner.execute('mark-replay',0,lambda:net.bank(0,command),lambda b,a:wallets(a)==wallets(b) and a['states']==b['states'])
    key=runner.key('lend');command=f'!bank lend {mark} {runner.fixture.names[1]} {key}'
    lent=runner.execute('lend',0,lambda:net.bank(0,command),lambda b,a:receipt(a,0,'lend',key) is not None and next(m for m in a['states'][0]['marks'] if m['id']==mark)['holder']==runner.fixture.names[1] and physical_count(a,301)==physical_count(b,301) and wallets(a)==wallets(b))
    held=next(m for m in lent['states'][0]['marks'] if m['id']==mark)['current_instance'];facts['borrowed_instance']=held;p.save()
    if 'borrower_projection' not in facts:facts['borrower_projection']=net.projected_mark(1,held,runner.fixture.names[0],present=True);p.save()
    runner.execute('lend-replay',0,lambda:net.bank(0,command),lambda b,a:a['states']==b['states'])
    key=runner.key('reclaim');command=f'!bank reclaim {mark} {pin} {key} remove'
    reclaimed=runner.execute('reclaim',0,lambda:net.bank(0,command),lambda b,a:receipt(a,0,'reclaim',key) is not None and next(m for m in a['states'][0]['marks'] if m['id']==mark)['state']=='removed' and physical_count(a,301)==physical_count(b,301) and wallets(a)==wallets(b))
    returned=receipt(reclaimed,0,'reclaim',key)['receipt']['instance'];facts['returned_instance']=returned;p.save()
    require({k:item(reclaimed,0,returned)[k] for k in ('template','count','durability','enhance')}==facts['item_basis'],'Reclaim lost physical item metadata')
    if 'removed_projection' not in facts:facts['removed_projection']=net.projected_mark(0,returned,runner.fixture.names[0],present=False);p.save()
    runner.execute('reclaim-replay',0,lambda:net.bank(0,command),lambda b,a:a['states']==b['states'])
    require(all(pin not in text for i in (0,1) for text in bank_lines(net.received[i])),'Private PIN echoed by server')


def private_market(runner):
    net=runner.net;p=runner.progress;facts=p.value['facts'];instance=facts['returned_instance']
    packet=b'\xae\x08\0'+struct.pack('<III',1,instance,1)+struct.pack('<f',200.)
    published=runner.execute('ae-sale-publish',0,lambda:net.command(0,packet),lambda b,a:len(a['states'][0]['sales'])==1 and a['states'][0]['sales'][0]['item']['id']==instance and a['states'][0]['sales'][0]['price_cents']==20000 and physical_count(a,301)==physical_count(b,301) and wallets(a)==wallets(b))
    if runner.state()['states'][0]['sales']:
        query=net.ask_matching(1,b'\xae\x01\0'+struct.pack('<I',301),lambda p:p.startswith(b'\xae\x02') and any(r['name']==runner.fixture.names[0] for r in traders(p)));row=next(r for p in query if p.startswith(b'\xae\x02') for r in traders(p) if r['name']==runner.fixture.names[0]);shop=row['id'];facts['shop_id']=shop;p.save()
        opened=net.ask_matching(1,b'\xae\x03'+struct.pack('<I',shop),lambda p:p.startswith(b'\xae\x04') and goods(p)[0]==shop);_,rows=next(goods(p) for p in opened if p.startswith(b'\xae\x04') and goods(p)[0]==shop)
        require(len(rows)==1 and rows[0]['price']==200. and rows[0]['count']==1,'Native actual sale quote differs')
    else:require('shop_id' in facts,'Preserved native shop identity missing');shop=facts['shop_id']
    buy=b'\xae\x06'+struct.pack('<4I',shop,1,1,1)
    bought=runner.execute('ae-sale-buy',1,lambda:net.command(1,buy),lambda b,a:credits(a,0)-credits(b,0)==200 and credits(b,1)-credits(a,1)==200 and not a['states'][0]['sales'] and physical_count(a,301)==physical_count(b,301) and len(a['states'][1]['private_receipts'])==len(b['states'][1]['private_receipts'])+1)
    if 'market_bought_instance' not in facts:
        before=p.value['actions']['ae-sale-buy']['before'];known={i['id'] for i in before['states'][1]['items']};new=[i for i in bought['states'][1]['items'] if i['id'] not in known and i['template']==301]
        require(len(new)==1,'Actual market delivery not unique');facts['market_bought_instance']=new[0]['id'];p.save()
    runner.execute('ae-sale-replay',1,lambda:net.command(1,buy),lambda b,a:a['states']==b['states'],assets=False)
    order=b'\xae\x09'+struct.pack('<III',1,301,1)+struct.pack('<f',210.)+b'\0\0'
    funded=runner.execute('ae-order-publish',0,lambda:net.command(0,order),lambda b,a:len(a['states'][0]['orders'])==1 and a['states'][0]['orders'][0]['held']==210 and credits(b,0)-credits(a,0)==210 and a['states'][1]==b['states'][1] and physical_count(a,301)==physical_count(b,301))
    if runner.state()['states'][0]['orders']:
        query=net.ask_matching(1,b'\xae\x01\1'+struct.pack('<I',301),lambda p:p.startswith(b'\xae\x02') and any(r['name']==runner.fixture.names[0] and r['id']==shop for r in traders(p)));require(any(r['name']==runner.fixture.names[0] and r['id']==shop for p in query if p.startswith(b'\xae\x02') for r in traders(p)),'Funded buyer missing in native traders')
        opened=net.ask_matching(1,b'\xae\x03'+struct.pack('<I',shop),lambda p:p.startswith(b'\xae\x05') and goods(p)[0]==shop);_,rows=next(goods(p) for p in opened if p.startswith(b'\xae\x05') and goods(p)[0]==shop)
        require(len(rows)==1 and rows[0]['price']==210. and rows[0]['count']==1,'Native funded order quote differs')
    sell=b'\xae\x07'+struct.pack('<5I',shop,1,1,facts['market_bought_instance'],1)
    sold=runner.execute('ae-order-sell',1,lambda:net.command(1,sell),lambda b,a:credits(a,1)-credits(b,1)==210 and credits(a,0)==credits(b,0) and not a['states'][0]['orders'] and physical_count(a,301)==physical_count(b,301) and len(a['states'][1]['private_receipts'])==len(b['states'][1]['private_receipts'])+1)
    runner.execute('ae-order-replay',1,lambda:net.command(1,sell),lambda b,a:a['states']==b['states'],assets=False)
    facts['private_item_conservation']=True;facts['purchase_order_escrow_debited_once']=True;p.save()


def sc_auction(runner,args):
    net=runner.net;p=runner.progress;facts=p.value['facts']
    for index in (0,1):
        packets=net.ask(index,b'\xbd\x01\0\0\0',b'\xf8\x01\x01');rows=sc_rows(one(packets,b'\xf8\x01\x01'));require(rows,'Actual shared F8 catalogue empty')
    state=runner.state()
    if 'sc_lot' not in facts:
        select_deadline=time.monotonic()+60
        while True:
            eligible=[r for r in state['lots'] if r['state']=='active' and r['currency']=='credits' and r['automatic'] and r['bidder'] is None and r['bids']==0 and not any(b['lot']==r['id'] for b in state['bots']) and r['ends']-state['utc']>=30]
            if eligible:break
            require(time.monotonic()<select_deadline,'No unowned affordable automatic SC lot with safe native time left')
            for index in (0,1):net.ping(net.peers[index])
            time.sleep(1);state=runner.state()
        chosen=min(eligible,key=lambda r:r['ends']);require(chosen['ends']-state['utc']<=args.maximum_clock_wait,'Actual SC wait exceeds bounded policy')
        facts['sc_lot']=chosen['id'];facts['sc_start_price']=chosen['price'];facts['sc_fee']=chosen['fee'];facts['sc_initial_ends']=chosen['ends'];p.save()
    identity=facts['sc_lot'];fee=facts['sc_fee'];bid=b'\xbd\x06'+struct.pack('<I',identity)
    bid_after=runner.execute('sc-manual-bid',1,lambda:net.command(1,bid),lambda b,a:credits(b,1)-credits(a,1)==fee and lot(a,identity)['bids']==lot(b,identity)['bids']+1 and lot(a,identity)['bidder']==runner.fixture.names[1] and lot(a,identity)['price']==lot(b,identity)['price']+lot(b,identity)['step'] and lot(a,identity)['ends']==lot(b,identity)['ends']+lot(b,identity)['extension'])
    runner.execute('sc-unchanged-quote-replay',1,lambda:net.command(1,bid),lambda b,a:wallets(a)==wallets(b) and lot(a,identity)['bids']==lot(b,identity)['bids'] and len(a['states'][1]['sc_receipts'])==len(b['states'][1]['sc_receipts']))
    if not p.value['actions'].get('sc-bot-reserve',{}).get('done'):
        packets=net.ask_matching(0,b'\xbd\x14\0'+struct.pack('<I',identity),lambda p:p.startswith(b'\xf8\x01\x03') and sc_decode(p)[1][0]==identity);op,values=sc_decode(one(packets,b'\xf8\x01\x03'));require(op==3 and values[:2]==(identity,fee),'Native bot quote differs')
    # Native GUI sends FROM,N,TO. Three bids are reserved; with B leading,
    # only A is eligible at the last second, spends one, and wins. The other
    # two prepaid fees must return at ordinary authoritative closure.
    bot=b'\xbd\x14\1'+struct.pack('<4I',identity,0,3,0)
    held=runner.execute('sc-bot-reserve',0,lambda:net.command(0,bot),lambda b,a:credits(b,0)-credits(a,0)==3*fee and any(x['lot']==identity and x['account']==runner.fixture.names[0] and x['held']==3*fee and x['remaining']==3 for x in a['bots']))
    runner.execute('sc-bot-quote-replay',0,lambda:net.command(0,bot),lambda b,a:wallets(a)==wallets(b) and a['bots']==b['bots'] and len(a['states'][0]['sc_receipts'])==len(b['states'][0]['sc_receipts']))
    deadline=time.monotonic()+args.maximum_clock_wait;last_notice=0
    while True:
        state=runner.state();row=lot(state,identity)
        if row['state']!='active':break
        require(time.monotonic()<deadline,'Ordinary SC timer did not close within bounded wait')
        if time.monotonic()-last_notice>=20:phase('ordinary_sc_clock_wait',remaining_seconds=max(0,row['ends']-state['utc']));last_notice=time.monotonic()
        for index in (0,1):net.ping(net.peers[index])
        time.sleep(min(2,max(.1,row['ends']-state['utc'])))
    require(row['state'] in ('won','delivered') and row['bidder']==runner.fixture.names[0] and row['bids']==2,'Native paid manual/automatic SC winner differs')
    events=[e for e in state['sc_history'] if e['lot']==identity];automatic=[e for e in events if e['action']=='bid' and e['automatic']]
    require(len(automatic)==1 and automatic[0]['account']==runner.fixture.names[0] and any(e['action']=='bot_refund' and e['account']==runner.fixture.names[0] and e['amount']==2*fee for e in events) and not any(x['lot']==identity for x in state['bots']),'Unused prepaid bot fees not refunded once')
    facts['sc_closure']=dict(winner_real_account=0,paid_manual_bids=1,paid_automatic_bids=1,held=3*fee,spent=fee,refunded=2*fee,clock_accelerated=False,closed_utc=next(e['occurred'] for e in events if e['action']=='closed'),expiry=row['expires_at']);p.save()
    packets=net.ask(0,b'\xbd\x03'+struct.pack('<IH',identity,1),b'\xf8\x01\x02');op,history=sc_decode(one(packets,b'\xf8\x01\x02'));require(op==2 and history[0]==identity and sum(raw[8]==4 for raw,name in history[4])==2,'Actual native SC history omits paid bids')
    if not p.value['actions'].get('sc-claim',{}).get('done'):
        packets=net.ask(0,b'\xbd\x07'+struct.pack('<I',identity),b'\xf8\x01\x04');op,claim=sc_decode(one(packets,b'\xf8\x01\x04'));row=lot(runner.state(),identity)
        require(op==4 and claim[0]==identity and claim[2:]==(row['price'],0,1) and abs((claim[1]-DAY_ZERO)*86400-row['expires_at'])<.001,'Actual native claim price/expiry/payment availability differs')
    claim_packet=b'\xbd\x09'+struct.pack('<I',identity)+b'\1'
    claimed=runner.execute('sc-claim',0,lambda:net.command(0,claim_packet),lambda b,a:lot(a,identity)['state']=='delivered' and credits(b,0)-credits(a,0)==lot(b,identity)['price'] and len(a['states'][0]['messages'])==len(b['states'][0]['messages'])+1 and len(a['states'][0]['mail_items'])==len(b['states'][0]['mail_items'])+1)
    runner.execute('sc-claim-replay',0,lambda:net.command(0,claim_packet),lambda b,a:wallets(a)==wallets(b) and a['states'][0]['messages']==b['states'][0]['messages'] and a['states'][0]['mail_items']==b['states'][0]['mail_items'])
    message=lot(claimed,identity)['message'];facts['sc_message']=message;p.save()
    if 'sc_mail_escrow' not in facts:
        packets=net.ask(0,encode_body_request(BodyRequest(0,message)),b'\xb7\x7a');body=decode_body(one(packets,b'\xb7\x7a'));require(body.identity==message and len(body.items)==1 and body.sender=='SC Auction','Native winner mail not the exact system prize')
        facts['sc_mail_escrow']=body.items[0].identity;facts['sc_prize_template']=body.items[0].template;facts['sc_prize_count']=body.items[0].count;p.save()
    escrow=facts['sc_mail_escrow'];template=facts['sc_prize_template'];count=facts['sc_prize_count']
    packet=encode_warehouse_transfer(WarehouseTransfer(3,1,(),((escrow,count),)))
    received=runner.execute('sc-mail-withdraw',0,lambda:net.command(0,packet),lambda b,a:physical_count(a,template)-physical_count(b,template)==count and not any(m['message']==message for m in a['states'][0]['mail_items']) and next(m for m in a['states'][0]['messages'] if m['id']==message)['state']=='claimed' and any(r['action']=='items:'+str(escrow) for r in a['states'][0]['mail_receipts']) and wallets(a)==wallets(b))
    runner.execute('sc-mail-withdraw-replay',0,lambda:net.command(0,packet),lambda b,a:a['states']==b['states'])
    facts['sc_mail_delivery_once']=True;facts['real_seven_day_expiry_positive']=False;p.save()


def run(fixture,args,report,hashes):
    require(fixture.prefix=='qsfc5dfe28','Only the parent-designated untouched phase5 pair is authorized')
    progress=PrivateProgress(fixture,hashes,resume=args.resume);before=status(fixture,hashes)
    require(before['connections']==0 and not any(before['idle'].values()),'Other players or retained battles present')
    require(all(s['tutorial']==[1,15] and len(s['pets'])==3 and all(p['level']==1 and p['xp']==0 for p in s['pets']) for s in before['states']),'Preserved ordinary phase5 completion differs')
    if progress.value['base'] is None:
        require(wallets(before)==[[3000,0],[3000,0]] and all(not s['marks'] and not s['bank_receipts'] and not s['sales'] and not s['orders'] and not s['messages'] for s in before['states']),'Fresh economics baseline differs; never reset owned accounts')
        progress.value['base']=before;progress.save()
    base=progress.value['base'];require(before['claims']==base['claims'] and before['payments']==base['payments'],'Foreign claims/payment baseline changed')
    require(before['provider']==dict(enabled=False,type='stripe_checkout',currency='eur',minor_units_per_gold=1,minimum_gold=50),'Expected explicit disabled merchant policy differs')
    net=EconomyNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    runner=Runner(fixture,hashes,net,progress)
    try:
        for index in (0,1):
            assets=net.attach(index);require([assets.credits,assets.gold]==before['states'][index]['wallet'],'Native ordinary wallet binding differs')
        require(runner.state()['connections']==2,'Only two actual owned TLS sessions expected')
        stocks(runner);marked_lending(runner);private_market(runner);sc_auction(runner,args)
        final=runner.state()
        require(all(s['wallet'][1]==0 and s['securities']==[0,0] and not s['sales'] and not s['orders'] for s in final['states']),'Unexpected Gold/paper/market escrow remains')
        require([s['pets'] for s in final['states']]==[s['pets'] for s in base['states']] and [s['protected'] for s in final['states']]==[s['protected'] for s in base['states']],'Economy altered unrelated LV/XP/battle rewards')
        for index in (0,1):net.command(index,b'\x2a\x01');net.detach(index)
        deadline=time.monotonic()+12
        while status(fixture,hashes)['connections']:
            require(time.monotonic()<deadline,'Owned city sockets did not release');time.sleep(.2)
        for index in (0,1):
            assets=net.attach(index);require([assets.credits,assets.gold]==final['states'][index]['wallet'],'Native relogin lost persisted lawful balance');net.command(index,b'\x2a\x01');net.detach(index)
        after=runner.state();require(after['states']==final['states'],'Native relogin changed shared economy/profile/receipts')
        report.update(facts=progress.value['facts'],actions={k:{f:v[f] for f in ('done','recovered_paid_action_without_resend','wallet_before','wallet_after','native_assets','native_opcodes')} for k,v in progress.value['actions'].items()},final_wallets=wallets(final),source_sha256=hashes,provider=after['provider'],signed_payment_orders_events_unchanged=after['payments']==base['payments'],lawful_relogin=True)
    finally:
        for index in tuple(net.peers):
            try:net.command(index,b'\x2a\x01')
            except Exception:pass
        net.close();report['tls_channels']=[c.metadata() for c in net.connections]
        deadline=time.monotonic()+190
        while True:
            released=runner.state()
            if released['connections']==0 and not any(released['idle'].values()):break
            require(time.monotonic()<deadline,'Owned sockets/checkpoints cleanup deadline exceeded');time.sleep(.2)
        report['cleanup']=dict(connections=released['connections'],idle=released['idle'],integrity=released['integrity'])
        report['completed_actions']=list(progress.value['actions']);report['resumable_private_progress']=str(progress.path)
    require(released['claims']==base['claims'] and released['payments']==base['payments'] and released['service']==before['service'],'Unrelated claims/payments/game service changed')
    require(all(released['foreign'].get(t)==v for t,v in base['foreign'].items()),'Pre-existing real account rows changed')
    report.update(passed=True,existing_real_account_rows_preserved=True,claims_service_unchanged=True,merchant_calls=0,synthetic_gold=0)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--resume',action='store_true')
    p.add_argument('--phase6-deployment',type=Path,default=ROOT/'reports/gameplay-completion/stage6-economy/deployment.json');p.add_argument('--deployments',type=Path,default=ROOT/'reports/gameplay-completion')
    p.add_argument('--host',default='185.184.42.88');p.add_argument('--server-name',default='ti-reborn.com');p.add_argument('--ca-file',type=Path)
    p.add_argument('--login-port',type=int,default=29512);p.add_argument('--session-port',type=int,default=29513);p.add_argument('--loopback-session-port',type=int,default=28513);p.add_argument('--maximum-clock-wait',type=int,default=420)
    args=p.parse_args(argv)
    if args.output.exists():p.error('Preserve existing evidence; choose a fresh output')
    if not 60<=args.maximum_clock_wait<=600:p.error('Ordinary clock wait must be60..600seconds')
    if any(not 1024<=v<=65535 for v in (args.login_port,args.session_port,args.loopback_session_port)):p.error('Invalid port')
    report=dict(passed=False,observed_utc=datetime.now(timezone.utc).isoformat(),kind='two ordinary hosted accounts over verified native TLS; no GUI',probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),limitations=['no graphical clients; F8 is explicitly emulator protocol','no real merchant credentials/payment; Gold/bonds positive covered only in isolated signed tests','seven-day claim and one-day mark expiry cannot elapse in bounded hosted QA; authoritative expiry fields and isolated tests distinguish them','no clock, save, level, money or inventory administrative writes'])
    try:
        fixture=Stage7Fixture.load(args.fixture);require(fixture.host==args.host and fixture.backup,'Authorized preserved hosted fixture required')
        hashes=deployment_hashes(args.deployments,args.phase6_deployment);run(fixture,args,report,hashes)
    except BaseException as error:
        import traceback
        report['error_type']=type(error).__name__;report['error_locations']=[dict(file=Path(f.filename).name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)]
        if isinstance(error,AssertionError):report['reason']=str(error)[:200]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,pin_printed=False,graphical_clients_started=0)),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
