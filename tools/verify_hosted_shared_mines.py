"""Three owned ordinary protocol clients in one isolated production TLS mine.

Prepare is local-only. Explicit provisioning needs a pinned ingress lease,
consistent pre-account backup and exactly the three reserved new identities.
Normal character/shop/clan/travel/actions are exercised; only owned Lv4 access
is synthetic (XP7355, normal HP115). This never claims graphical-client proof.
"""
import argparse
import ast
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA,OWNERSHIP,PROVISION,require
from tools.verify_hosted_economy_tls import ECONOMY_SNAPSHOT
from tools.verify_game_tls_hosted import TlsNetworkQA,AuditedTlsSocket,tls_context,login_preface
from tio.appearance import encode_request as appearance_request
from tio.protocol.character_create import CharacterCreateRequest,encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.item_action import ItemAction,encode_item_action
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_position import BattlePositionRequest,encode_position_request
from tio.protocol.battle_loot import LootTransfer,encode_loot_transfer,decode_container
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.battle_ground import decode_battle_ground

PRIVATE=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'TIO-emulator/shared-mines-qa'
SOURCES=(
    'tio/mining.py','tio/mining_service.py','tio/mine_map.py','tools/mining_scene.py',
    'tio/mine_claims.py','tio/crystal_market.py','tio/clans.py','tio/protocol/mining.py',
    'server/mine_arena.py','server/team_arena.py','server/multi.py','server/battle_journal.py',
    'server/battle_reconnect.py','tio/battle_snapshot.py','tools/loopback_exchange.py','config/mining.json',
    'tio/battle_rewards.py','tio/arena_service.py','server/battle_events.py',
    'config/level_progression.json','config/world_encounters.json',
    'server/clan_service.py','tio/warehouse_service.py','tio/warehouse_queries.py',
)

def safe_assertion_diagnostic(exc,*,public_source=None):
    """Expose only assertion messages written literally in this public file."""
    if type(exc) is not AssertionError or len(exc.args)!=1 or not isinstance(exc.args[0],str):return {}
    source=Path(public_source or __file__).resolve()
    if source not in {Path(__file__).resolve(),ROOT/'tools/verify_hosted_mines_expiry.py'}:return {}
    tree=ast.parse(source.read_text(encoding='utf-8'))
    allowed=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
            index=1 if node.func.id=='require' else 0 if node.func.id=='AssertionError' else None
            if index is not None and len(node.args)>index and isinstance(node.args[index],ast.Constant):
                value=node.args[index].value
                if isinstance(value,str):allowed.add(value)
    if exc.args[0] not in allowed:return {}
    frames=[];tb=exc.__traceback__
    while tb:
        if Path(tb.tb_frame.f_code.co_filename).resolve()==source:
            frames.append(dict(file=source.relative_to(ROOT).as_posix(),line=tb.tb_lineno))
        tb=tb.tb_next
    return dict(assertion=exc.args[0],frames=frames)

# Prefix snippets take the same stdin object; no password/config text is
# emitted. Importing the verifier or exercising local fixtures is offline.
GATE_CHECK=r'''
import hashlib,subprocess,time
from datetime import datetime,timezone
gate=data['gate'];lease=pathlib.Path(gate['lease_path']).resolve()
assert lease.parent.parent==pathlib.Path('/root/tio-shared-mines-qa') and lease.name=='lease.json'
assert hashlib.sha256(lease.read_bytes()).hexdigest()==gate['lease_sha256'],'QA lease changed'
saved=json.loads(lease.read_text());assert saved['lease_id']==gate['lease_id']
assert datetime.now(timezone.utc)<datetime.fromisoformat(gate['deadline_utc']),'QA lease expired; keep ingress closed'
assert saved['deadline_utc']==gate['deadline_utc']
# The reviewed gate helper verifies exact expressions, port set and drop
# verdict; existence of a table alone cannot authorize gameplay/claims.
import runpy
helper=pathlib.Path(gate['helper_path']).resolve()
assert helper.parent==lease.parent and helper.name=='maintenance.py'
assert hashlib.sha256(helper.read_bytes()).hexdigest()==gate['helper_sha256'],'Maintenance helper changed'
_maintenance=runpy.run_path(str(helper))
_maintenance['verify_gate'](gate)
'''

PROVISION_MINES=PROVISION.replace("assert re.fullmatch(r'qs[0-9a-f]{8}',prefix) and 2<=len(pairs)<=8",
    "assert re.fullmatch(r'qs[0-9a-f]{8}',prefix) and len(pairs)==3\nassert all(re.fullmatch(r'[A-Za-z0-9]{12,16}',p) for n,p in pairs)"
).replace('( sport = :28512 or sport = :28513 )','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'
).replace('create(name,password,character=name)','create(name,password)'
).replace("data=json.load(sys.stdin);prefix=data['prefix'];pairs=data['pairs']",
    "data=json.load(sys.stdin)\n"+GATE_CHECK+"\nfor p,digest in data['source_hashes'].items():assert hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==digest\nprefix=data['prefix'];pairs=data['pairs']"
).replace('folder=pathlib.Path(tempfile.mkdtemp',
    "with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as live:\n for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):\n  if live.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():assert live.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,'Retained battle/outbox present'\nfolder=pathlib.Path(tempfile.mkdtemp")

LEVEL4_FIXTURE=OWNERSHIP+GATE_CHECK+r'''
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import decode_item_list
from tio.level_progression import FLOORS
assert FLOORS[3]==7355
assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip()
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE')
 for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):
  assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
 for n in names:
  assert db.execute('SELECT credits,gold FROM wallets WHERE account=?',(n,)).fetchone()==(3000,0)
  assert db.execute('SELECT count(*) FROM characters WHERE account=?',(n,)).fetchone()[0]==1
  assert db.execute('SELECT count(*) FROM owned_pets WHERE account=?',(n,)).fetchone()[0]==1
  for table in ('battle_rewards','experience_battle_audit','rank_battle_audit','item_repairs','achievement_awards'):
   if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():
    assert db.execute('SELECT count(*) FROM '+table+' WHERE account=?',(n,)).fetchone()[0]==0
  human,raw,inv=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()
  assert human==1
  pet=decode_pet_info(raw,human_equipment=True);f=dict(pet.fields)
  assert f['0x8c4aef']==1 and f['0x8c4b05']==f['0x8c4bd0']==0
  assert f['0x8c4a07']==f['0x8c4ab1']==100
  items=decode_item_list(inv)[1];assert len(items)==1 and items[0].template_id==301 and items[0].count==1
  assert not items[0].equipped and items[0].unknown_words==(300,300,300)
  f.update({'0x8c4aef':4,'0x8c4b05':7355,'0x8c4a07':115,'0x8c4ab1':115})
  patched=encode_pet_info(replace(pet,fields=f))
  assert set(k for k in f if f[k]!=pet.fields[k])=={'0x8c4aef','0x8c4b05','0x8c4a07','0x8c4ab1'}
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(patched,n))
  assert db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]==inv
 audit=dict(kind='Synthetic owned Lv4 access fixture; progression is not earned battle XP',
   names=names,level=4,xp=7355,max_hp=115,hp=115,wallets_and_items_unchanged=True)
 # Exclusive private audit prevents applying the fixture again after play.
 audit_path=folder/'mines-level4.json';assert not audit_path.exists()
 audit_path.write_text(json.dumps(audit));audit_path.chmod(0o600)
print(json.dumps(audit))
'''

CLAIM_OPERATION=OWNERSHIP+GATE_CHECK+r'''
from tio.mine_claims import MineClaimsStore
assert data['action'] in ('set','clear')
assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).strip()
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT id,leader FROM clans WHERE name=?',(data['clan'].encode(),)).fetchone()
 assert row and row[1]==names[0]
 clan=row[0];members=[r[0] for r in db.execute('SELECT account FROM clan_members WHERE clan_id=?',(clan,))]
 assert set(members)=={names[0],names[2]},'QA clan must contain only miner/defender'
store=MineClaimsStore('/var/lib/tio-server/reservation.sqlite3');before=store.freeze(13)
if data['action']=='set':
 assert before['owner_clan'] is None and before['tax_percent']==0,'Never replace an existing owner'
 after=_maintenance['claim_for_qa'](data['gate'],clan,tax_percent=10)
 (folder/'mines-claim.json').write_text(json.dumps(dict(before=before,after=after)))
 (folder/'mines-claim.json').chmod(0o600)
else:
 audit=json.loads((folder/'mines-claim.json').read_text());assert before==audit['after'] and before['owner_clan']==clan
 # Gate lifecycle helper owns audited clear and admission reopening. This
 # verifier deliberately never removes firewall/startup protection itself.
 raise ValueError('Use reviewed finish_maintenance only after successful owned cleanup')
print(json.dumps(dict(before=before,after=after,clan=clan,audit_retained=True)))
'''

OWNED_STATUS=OWNERSHIP+r'''
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 locations=[dict(account=n,town=(db.execute('SELECT town_id FROM character_locations WHERE account=?',(n,)).fetchone() or [3])[0]) for n in names]
 clan_row=db.execute('SELECT id FROM clans WHERE leader=?',(names[0],)).fetchone()
 clan=clan_row[0] if clan_row else None
 amounts={n:(db.execute('SELECT amount FROM crystal_wallets WHERE account=?',(n,)).fetchone() or [0])[0] for n in names}
 amounts['clan']=(db.execute('SELECT amount FROM clan_crystals WHERE clan_id=?',(clan,)).fetchone() or [0])[0] if clan else 0
 receipt_rows=db.execute('SELECT receipt_json FROM mine_crystal_extractions WHERE extractor IN (?,?,?)',names).fetchall()
 members=[dict(account=a,identity=i,permissions=p) for a,i,p in db.execute('SELECT account,id,permissions FROM clan_members WHERE clan_id=?',(clan,))] if clan else []
 assert all(m['account'] in (names[0],names[2]) for m in members)
 counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')}
 print(json.dumps(dict(locations=locations,clan=clan,members=members,amounts=amounts,receipts=[json.loads(r[0]) for r in receipt_rows],durable=counts)))
'''

OWNED_PRESERVED=OWNERSHIP+r'''
# SQLite compares old/non-owned rows internally. Python receives only counts,
# never other players' names, hashes, saves, wallets or row values.
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('BEGIN')
 db.execute('ATTACH DATABASE ? AS prior',('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',))
 checked={}
 for table, in db.execute("SELECT name FROM prior.sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
  quoted='"'+table.replace('"','""')+'"'
  cols=[r[1] for r in db.execute('PRAGMA prior.table_info('+quoted+')')]
  key=next((c for c in ('account','login') if c in cols),None)
  if key is None:continue
  columns=','.join('"'+c.replace('"','""')+'"' for c in cols)
  current='SELECT '+columns+' FROM main.'+quoted+' WHERE "'+key+'" NOT IN (?,?,?)'
  old='SELECT '+columns+' FROM prior.'+quoted
  removed=db.execute('SELECT count(*) FROM ('+old+' EXCEPT '+current+')',names).fetchone()[0]
  changed=db.execute('SELECT count(*) FROM ('+current+' EXCEPT '+old+')',names).fetchone()[0]
  assert removed==changed==0,'Existing account rows changed'
  checked[table]=db.execute('SELECT count(*) FROM prior.'+quoted).fetchone()[0]
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 print(json.dumps(dict(integrity='ok',existing_account_rows_preserved=checked)))
'''


def preflight_forwards(gate,*,hostname='ti-reborn.com',ca_file=None):
    """Certificate + endpoint bootstrap before any account creation.

    Sends no login, password, game admission or client callback. This proves
    the configured SSH channels are alive and ordered rather than trusting
    their readiness JSON alone.
    """
    from test_server_deployment import Peer
    from tio.protocol.transport import decode_initial_challenge
    from tools.verify_game_tls_hosted import read_exact
    forward=gate['forwarding']
    require(forward['host']=='127.0.0.1' and forward['remote_login_port']==29512 and
            forward['remote_session_port']==29513,'Expected SSH loopback forwards to both production TLS ports')
    ports=[forward[p] for p in ('login_port','session_port')]
    require(len(set(ports))==2 and all(type(p) is int and 1024<=p<=65535 for p in ports),'Distinct dynamic forwarded ports required')
    context=tls_context(cafile=ca_file);channels=[]
    for kind,port in zip(('login','mode1'),ports):
        channel=AuditedTlsSocket(('127.0.0.1',port),hostname,context)
        try:
            if kind=='login':
                channel.sendall(login_preface(forward['session_port']))
                decode_initial_challenge(Peer(channel).receive())
            else:require(read_exact(channel,11)[:3]==b'\x0b\0\x09','Wrong forwarded native mode1 endpoint')
            channels.append(dict(channel=kind,certificate_and_bootstrap_verified=True,
                                 intentionally_closed_before_account_authentication=True,tls=channel.metadata()))
        finally:channel.close()
    return channels

MINE_SNAPSHOT=OWNERSHIP+r'''
import hashlib
from contextlib import closing
from tio.battle_snapshot import loads
from tio.protocol.item_list import decode_item_list
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
 db.execute('BEGIN')
 rows=db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c '
   'JOIN battle_checkpoint_members m USING(match_id) WHERE m.account IN ('+','.join('?' for _ in names)+')',names).fetchall()
 if not rows:raise ValueError('No owned mining checkpoint')
 if len({r[0] for r in rows})!=1:raise ValueError('Owned accounts split across checkpoints')
 objects=loads(rows[0][1]);battle=objects[0]['battle']
 roster={owner:r[0] for owner,r in battle['reward_roster'].items()}
 if not set(roster.values())<=set(names):raise ValueError('Foreign participant; no gameplay allowed')
 field=battle['field'];mine=field.mining
 if battle.get('kind')!='mine' or not mine.shared:raise ValueError('Not a shared mine')
 members=db.execute('SELECT account,owner_id FROM battle_checkpoint_members WHERE match_id=?',(battle['match_id'],)).fetchall()
 if not set(n for n,_ in members)<=set(names):raise ValueError('Foreign durable owner; no gameplay allowed')
 turn=battle['arena']._turns.get(battle['room'].room_id)
 actors=[]
 for a in field._actors.values():
  account=roster.get(a.owner_id)
  raw=field.combat.inventories.get(a.actor_id)
  actors.append(dict(id=a.actor_id,owner=a.owner_id,account=account,team=field.teams[a.owner_id],
    storage_id=field.combat.storage_ids.get(a.actor_id),x=a.x,y=a.y,hp=a.health,max_hp=a.max_health,
    ap=a.action_points,sight=a.sight_radius,
    inventory=[dict(id=i.instance_id,template=i.template_id,count=i.count,equipped=i.equipped)
               for i in decode_item_list(raw)[1]] if raw else []))
 out=dict(match=battle['match_id'],kind=battle['kind'],town=battle['city_id'],width=field.width,height=field.height,
  ground_sha256=hashlib.sha256(battle['ground']).hexdigest(),blocked=list(field.blocked),
  participants=roster,members=members,actors=actors,bots=len(battle['bots']),
  mode=field.battle_mode,turn=turn[0] if turn else None,loading_complete=battle['arena']._loading[battle['room'].room_id]==set(battle['room'].members),
  active=list(battle['mine_active']),claim=battle['mine_claim'],
  can_quit=battle.get('mine_can_quit',{}),
  bot_patrol_regions={i:list(cells) for i,cells in field.bot_patrol_regions.items()},
  transparent_obstacles=list(field.transparent_obstacles),
  crates=[list(p) for p,items in field.loot.boxes.items()
          if any(i.template_id==52 and i.count==0 for i in items)],
  loot=[dict(x=p[0],y=p[1],items=[dict(id=i.instance_id,template=i.template_id,count=i.count)
       for i in items]) for p,items in field.loot.boxes.items()],
  mining=dict(shared=mine.shared,roles=mine.roles,round=mine.round,last_tick=mine.last_tick,
   lift_blocked_until=mine.lift_blocked_until,owner_deadlines=mine.exit_blocked_until_by_owner,
   exited=list(mine.exited),extracted=mine.extracted_amounts,raider_entries=list(mine.raider_entries),
   total=mine.total,lift=list(mine.layout.lift),raider_exits=list(mine.layout.raider_exits),
   deposits=[dict(id=d.identity,x=d.position[0],y=d.position[1],initial=d.initial,left=d.left,
     extracted=d.extracted,carried=d.carried,installed=d.drill is not None) for d in mine.deposits.values()]),
  foreign_checkpoint_rows=db.execute('SELECT count(*) FROM battle_checkpoint_members WHERE account NOT IN ('+','.join('?' for _ in names)+')',names).fetchone()[0])
 print(json.dumps(out))
'''


class MinesFixture(FreshSurroundingsQA):
    gate=None

    @staticmethod
    def prepare_private_directory():
        require(not PRIVATE.is_symlink(),'Private directory cannot be a symlink')
        PRIVATE.mkdir(parents=True,exist_ok=True)
        if os.name=='nt':
            from tools.offsite_backup_windows import _protect_directory
            _protect_directory(PRIVATE)
        else:PRIVATE.chmod(0o700)
        (PRIVATE/'.gitignore').write_text('*\n',encoding='utf-8')

    def save_private(self,*,pending=False):
        # ACL validation happens before the first remote account mutation.
        self.prepare_private_directory()
        path=PRIVATE/(self.prefix+('.pending.json' if pending else '.json'))
        require(not path.exists(),'Never overwrite a private fixture')
        with path.open('x',encoding='utf-8') as out:
            out.write(json.dumps(dict(version=1,host=self.host,prefix=self.prefix,names=self.names,
                passwords=self.passwords,backup=self.backup,key=self.key))+'\n')
        if os.name!='nt':path.chmod(0o600)
        self.credential_path=str(path)
        return path

    @classmethod
    def prepare_owned(cls,host,participants=3,*,key=None):
        require(participants==3,'Exactly three accounts; never reuse two-account provisioning')
        cls.prepare_private_directory()
        prefix='qs'+secrets.token_hex(4)
        alphabet='ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
        fixture=cls(host,prefix,[prefix+c for c in 'abc'],
                    [''.join(secrets.choice(alphabet) for _ in range(16)) for _ in range(3)],'',
                    key or str(Path.home()/'.ssh/tio_server'))
        fixture.save_private(pending=True)
        return fixture

    def provision(self,gate,*,hostname='ti-reborn.com',ca_file=None):
        require(not self.backup and self.credential_path.endswith('.pending.json'),'Provision one prepared fresh fixture only')
        require(gate['accounts']==self.names,'Gate must pin this exact three-account set before account creation')
        self.gate=gate
        self.remote("import json,pathlib,sys\ndata=json.load(sys.stdin)\n"+GATE_CHECK+
                    "\nprint(json.dumps(dict(isolated=True)))\n",{'gate':gate})
        preflight=preflight_forwards(gate,hostname=hostname,ca_file=ca_file)
        # No gameplay frame/authentication was sent. Give the bootstrap-only
        # sockets a bounded opportunity to disappear before PROVISION's ss0.
        time.sleep(.2)
        result=self.remote(PROVISION_MINES,dict(prefix=self.prefix,pairs=list(zip(self.names,self.passwords)),
            gate=gate,source_hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}))
        self.backup=result['backup'];self.save_private()
        # Keep pending evidence. A failed remote step never causes automatic
        # reprovision/reset of accounts or loss of their already saved secrets.
        return dict(result,forward_preflight=preflight)

    @classmethod
    def load_private(cls,path):
        path=Path(path).resolve()
        require(path.parent==PRIVATE.resolve() and not path.is_symlink(),'Dedicated mines CurrentUser credential path required')
        cls.prepare_private_directory()
        data=json.loads(path.read_text(encoding='utf-8'))
        require(data.pop('version')==1,'Unsupported mines fixture')
        fixture=cls(**data,credential_path=str(path))
        require(re.fullmatch(r'qs[0-9a-f]{8}',fixture.prefix) and
                fixture.names==[fixture.prefix+c for c in 'abc'] and len(fixture.passwords)==3,
                'Exactly three fresh proven-owned accounts required')
        return fixture

    def snapshot_economy(self):
        return self.remote(ECONOMY_SNAPSHOT,{**self.ownership_payload(),'sources':list(SOURCES)})

    def snapshot_mine(self):
        return self.remote(MINE_SNAPSHOT,self.ownership_payload())

    def status(self):return self.remote(OWNED_STATUS,self.ownership_payload())
    def preservation(self):return self.remote(OWNED_PRESERVED,self.ownership_payload())

    def guard_gate(self):
        require(self.gate is not None,'Operator ingress isolation proof required')
        return self.remote(OWNERSHIP+GATE_CHECK+"\nprint(json.dumps(dict(isolated=True)))\n",
                           {**self.ownership_payload(),'gate':self.gate})

    def apply_level4(self):
        self.guard_gate()
        return self.remote(LEVEL4_FIXTURE,{**self.ownership_payload(),'gate':self.gate})

    def claim_operation(self,action):
        self.guard_gate()
        return self.remote(CLAIM_OPERATION,{**self.ownership_payload(),'gate':self.gate,
                                          'action':action,'clan':self.prefix})

    def guard_connections(self,expected):
        require(type(expected) is int and 0<=expected<=3,'Invalid owned socket budget')
        return self.remote(OWNERSHIP+r'''
import subprocess
all_rows=subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines()
tls_rows=subprocess.check_output(['ss','-Htn','state','established','( sport = :29513 )'],text=True).splitlines()
if len(all_rows)!=data['expected'] or len(tls_rows)!=data['expected']:
 raise ValueError('Unexpected public game connection; stop own QA actions')
print(json.dumps(dict(owned_sessions=len(tls_rows),other_game_connections=0)))
''',{**self.ownership_payload(),'expected':expected})


class MinesNetwork(TlsNetworkQA):
    """TLS transport supporting all three private secrets and strict population."""
    def connect(self,port,*,label):
        patterns=[v.encode(e) for v in self.fixture.names+self.fixture.passwords for e in ('utf-8','utf-16-le')]
        channel=AuditedTlsSocket((self.host,port),self.hostname,self.context,patterns=patterns)
        channel.channel['channel']=label
        self.connections.append(channel)
        return channel

    def begin(self,index):
        # Production socket/gate checks precede the new login socket. Native
        # population includes that authenticated mode0 identity, so the third
        # account legitimately advertises population3 (the older tool is2).
        require(index in (0,1,2),'Expected three owned accounts')
        self.fixture.guard_gate()
        self.fixture.guard_connections(len(self.peers))
        from test_server_deployment import Peer
        from tio.protocol.transport import (decode_initial_challenge,expected_reply_fields,
            InitialReply,encode_initial_reply,decode_initial_completion)
        from tio.protocol.login import BasicLoginRequest,encode_basic_login_request,transform_auth_value
        from tio.protocol.server_list import ServerListRequest,encode_server_list_request,decode_server_list
        from tio.protocol.server_login import ServerLoginRequest,encode_server_login_request
        connection=self.connect(self.login_port,label='login');connection.sendall(login_preface(self.local_session_port))
        peer=Peer(connection);fields=expected_reply_fields(decode_initial_challenge(peer.receive()))
        peer.send(encode_initial_reply(InitialReply(*fields,0,bytes(3))))
        token=decode_initial_completion(peer.receive()).unknown_u32_01
        request=encode_basic_login_request(BasicLoginRequest(self.fixture.names[index].encode(),
            self.fixture.passwords[index].encode(),transform_auth_value(token)))
        connection.capture_next_write=True;peer.send(request)
        require(peer.receive()==b'\x04\0','TLS account login failed')
        peer.send(encode_server_list_request(ServerListRequest(0,0,b'')))
        entries=decode_server_list(peer.receive()).entries
        require(len(entries)==1,'Exactly one shared backend required')
        entry=entries[0]
        require(entry.address_octets==socket.inet_aton('127.0.0.1') and
                entry.unknown_u16_01==self.local_session_port,'Incorrect own loopback TLS handoff route')
        require(entry.unknown_u16_02<=3,'Unexpected foreign population')
        peer.send(encode_server_login_request(ServerLoginRequest(1,bytes(8))))
        require(peer.receive()==b'\x08\0','TLS handoff preparation failed')
        connection.close()
        return fields[1],token

    def command(self,index,packet):
        self.fixture.guard_gate()
        self.fixture.guard_connections(len(self.peers))
        return super().command(index,packet)

    def poll_batch(self):
        # One exact isolation/socket guard for this bounded read/ping batch;
        # every action packet still uses command() and its own full guard.
        self.fixture.guard_gate()
        self.fixture.guard_connections(len(self.peers))
        return [super(MinesNetwork,self).command(i,b'\x70') for i in tuple(self.peers)]

    def attach(self,index,*,fresh=False):
        peer=self.handoff(self.begin(index));self.received[index]=[]
        receive=peer.receive
        def record():
            packet=receive();self.received[index].append(packet);return packet
        peer.receive=record;self.peers[index]=peer
        records=self.case.character_screen(peer)
        if fresh:
            require(records==(),'Fresh account already has a character')
            sex=index%2+1
            peer.send(encode_character_create(CharacterCreateRequest(self.fixture.names[index].encode(),0,(sex,0,0,0))))
            require(peer.receive()==b'\x12\x05','Normal character creation failed')
            require(decode_character_list(peer.receive())[0].resource_type==sex,'Character resource mismatch')
            peer.send(bytes.fromhex('1701000000'))
            require(peer.receive()==b'\x12\x05' and peer.receive()[0]==0x10,'Missing first appearance menu')
            initial=bytes((sex,5 if sex==1 else 12,1 if sex==1 else 0,3,0,0))
            peer.send(appearance_request(1,initial));peer.until(b'\x10')
        else:
            require(len(records)==1 and records[0].name_bytes==self.fixture.names[index].encode(),'Saved owned character missing')
        peer.send(bytes.fromhex('1701000000'))
        packet=peer.receive()
        if packet[0]==0x18:
            peer.send(b'\x19');peer.until(b'\x66')
        else:
            # Durable reconnect sends the existing shared scene directly.
            require(packet[0] in (0x35,0x3b,0x30,0x34,0x3a,0x66,0xc8,0xf0),'Unexpected saved scene route')
            if packet!=b'\x41':peer.until(b'\x41',max_packets=4096)
        self.ping(peer)
        return peer

    def drop(self,index):
        self.peers.pop(index).sock.close()
        # Only our own channel is closed; checkpoint remains authoritative.

    def audit(self):
        return [c.metadata() for c in self.connections]


def validate_shared_snapshot(state,names,*,require_roles=True):
    require(len(names)==3 and len(set(names))==3,'Expected three distinct owned names')
    require(state['kind']=='mine' and state['mode']==7 and state['mining']['shared'], 'Private mine cannot pass shared acceptance')
    roster={int(o):n for o,n in state['participants'].items()}
    require(set(roster.values())<=set(names) and state['foreign_checkpoint_rows']==0,'Foreign participant or retained battle')
    if require_roles:
        require(set(roster.values())==set(names) and len(roster)==3,'All three humans must inhabit one match')
    roles={int(o):r for o,r in state['mining']['roles'].items()}
    require(set(roles)==set(roster),'Missing frozen human role')
    if require_roles:require(sorted(roles.values())==[1,2,3],'Miner, raider and defender required')
    require((state['width'],state['height'])==(60,60),'Wrong original mine dimensions')
    require(state['bots']==1,'One authoritative mutant group required')
    actors=state['actors'];humans=[a for a in actors if a['account'] is not None]
    require(len({a['id'] for a in actors})==len(actors),'Actor identity collision')
    require({a['owner'] for a in humans}<=set(roster),'Foreign real human actor')
    if require_roles:require({a['owner'] for a in humans}==set(roster),'Missing real human actor')
    require(all(a['account']==roster[a['owner']] and a['storage_id']==1 for a in humans),'Shared IDs must map to each own starter pet1')
    require(all(a['team']==(1 if roles[a['owner']]==2 else 0) for a in humans),'Miner/defender alliance or raider side incorrect')
    npc=[a for a in actors if a['account'] is None]
    require(len(npc)==10 and all(a['team']==2 for a in npc),'Mutants cannot replace human adversaries')
    deposits=state['mining']['deposits']
    require(len(deposits) in (2,3) and sum(d['initial'] for d in deposits)==state['mining']['total'],'Invalid shared deposit capacity')
    return dict(match=state['match'],humans=len(roster),mutants=len(npc),roles=roles,
                actor_ids=[a['id'] for a in humans],ground_sha256=state['ground_sha256'])


def validate_reconnect(before,after,names):
    validate_shared_snapshot(before,names);validate_shared_snapshot(after,names)
    for key in ('match','town','ground_sha256','participants','claim'):
        require(before[key]==after[key],'Reconnect replaced '+key)
    for key in ('roles','lift_blocked_until','owner_deadlines','raider_entries','total'):
        require(before['mining'][key]==after['mining'][key],'Reconnect changed frozen mining '+key)
    # AP/round may legitimately advance during a live reconnect. Never assert
    # frozen clocks or hide a turn's authentic state change.
    old={a['id']:a for a in before['actors']};new={a['id']:a for a in after['actors']}
    require(set(old)==set(new),'Reconnect regenerated actors')
    for identity,a in old.items():
        if a['account'] is not None:
            require(all(a[k]==new[identity][k] for k in ('owner','account','storage_id','x','y','hp','inventory')),
                    'Reconnect changed owned actor or inventory')
    return dict(match=before['match'],same_actor_ids=True,same_lift_deadline=True)


def validate_lift_lock(admission,locked,unlocked):
    mine=admission['mining'];roles={int(o):r for o,r in mine['roles'].items()}
    deadline=mine['lift_blocked_until']
    require(deadline==mine['round']+5,'Raider admission must lock five full mining rounds')
    for state in (locked,unlocked):
        require(state['match']==admission['match'],'Lift test crossed matches')
        require(state['mining']['lift_blocked_until']==deadline,'Poll/action/reconnect refreshed lift deadline')
        require(all(int(d)==deadline for o,d in state['mining']['owner_deadlines'].items() if roles[int(o)] in (1,3)), 'All miner/defender exits must share lock')
    require(locked['mining']['round']<deadline and not locked['mining']['exited'],'Early lift extraction')
    require(unlocked['mining']['round']>=deadline,'Lift did not complete five rounds')
    return dict(admission_round=mine['round'],blocked_until_round=deadline,full_rounds=5)


def validate_receipt(receipt,before,after,*,miner,defender,raider):
    require(receipt['extractor'] in (miner,defender,raider),'Foreign crystal extractor')
    gross=receipt['gross'];tax=receipt['tax'];payouts=receipt['payouts']
    require(type(gross) is int and 0<gross<=1000 and type(tax) is int,'Invalid first-band extraction')
    require(set(payouts)<={miner,defender,raider} and all(type(v) is int and v>=0 for v in payouts.values()),'Foreign/invalid crystal payout')
    require(gross==tax+sum(payouts.values()),'Crystal creation/loss in settlement')
    if receipt['extractor']==raider:
        require(tax==0 and payouts=={raider:gross},'Raider should receive untaxed loot')
    else:
        require(tax==gross*10//100 and payouts=={miner:gross//2,defender:gross-tax-gross//2},'Frozen10% escorted extraction mismatch')
    require(after['clan']-before['clan']==tax,'Clan tax was not conserved')
    require(all(after[n]-before[n]==payouts.get(n,0) for n in (miner,defender,raider)),'Persisted personal crystal gains differ from receipt')
    return dict(gross=gross,tax=tax,payouts=payouts,conserved=True)


def validate_wire_ground(packets,sha256):
    require(len(packets)==3 and len(set(packets))==1,'Three clients must receive identical native ground bytes')
    require(hashlib.sha256(packets[0]).hexdigest()==sha256,'Wire map differs from checkpoint')
    ground=decode_battle_ground(packets[0])
    require((ground.width,ground.height)==(60,60),'Invalid native mine ground')
    return dict(identical_clients=3,width=60,height=60,sha256=sha256)


def one_actor(state,name):
    actors=[a for a in state['actors'] if a['account']==name and a['hp']>0]
    require(len(actors)==1,'One living ordinary owned fighter required')
    return actors[0]


def current_extraction_receipts(status,match,extractor):
    # Earlier empty missions legitimately persist zero-gross receipts. Those
    # cannot make the current player's lift movement loop stop prematurely.
    return [r for r in status['receipts'] if r['match_id']==match and r['extractor']==extractor]


def source_guard(fixture):
    actual=fixture.snapshot_economy()
    hashes=actual['source_hashes']
    expected={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES}
    require(hashes==expected and actual['integrity']=='ok','Deploy reviewed shared-mine candidate before QA')
    return actual


def close_all(net):
    net.close();net.peers.clear()
    # TCP closes are asynchronous; bounded read-only retries do not create
    # additional accounts or conceal an unrelated connection.
    for attempt in range(10):
        try:return net.fixture.guard_connections(0)
        except RuntimeError:
            if attempt==9:raise
            time.sleep(.3)


def make_network(fixture,args):
    proof=fixture.gate
    forwarding=proof['forwarding']
    require(forwarding['host']=='127.0.0.1' and
        forwarding['remote_login_port']==29512 and forwarding['remote_session_port']==29513,
        'Only reviewed loopback SSH forwards to production gameplay TLS are allowed')
    for field in ('login_port','session_port'):
        require(type(forwarding[field]) is int and 1024<=forwarding[field]<=65535,'Invalid forwarded TLS port')
    return MinesNetwork(fixture,'127.0.0.1',args.server_name,forwarding['login_port'],forwarding['session_port'],
                        tls_context(cafile=args.ca_file),local_session_port=forwarding['session_port'])


def setup_owned(fixture,args,report):
    before=source_guard(fixture)
    require(all(s['characters']==0 and not s['pets'] and not s['receipts'] and s['checkpoints']==0
                for s in before['states']),'Setup accepts only this newly provisioned untouched trio')
    net=make_network(fixture,args)
    try:
        for i in range(3):net.attach(i,fresh=True)
        onboarding=source_guard(fixture)['states']
        for state in onboarding:
            require(state['wallet']==[3000,0] and len(state['pets'])==1,'Starter wallet or roster mismatch')
            pet=state['pets'][0]
            require(pet['level']==1 and pet['xp']==0 and pet['hp']==pet['max_hp']==100 and
                    len(pet['items'])==1 and pet['items'][0]['template']==301,'Normal starter character mismatch')
        report['ordinary_onboarding']=onboarding
    finally:close_all(net)
    report['synthetic_level4']=fixture.apply_level4()
    net=make_network(fixture,args)
    try:
        for i in range(3):net.attach(i)
        leveled=fixture.snapshot_economy()['states']
        for i,state in enumerate(leveled):
            pet=state['pets'][0]
            require((pet['level'],pet['xp'],pet['hp'],pet['max_hp'])==(4,7355,115,115),'Synthetic access fixture was altered')
            packets=net.command(i,encode_shop_purchase(ShopPurchase(1,0,3,1)))
            debit=[decode_asset_count(p).credits for p in packets if p[:2]==b'\xc8\x39']
            require(debit and debit[0]==2950,'Normal50-credit ammo purchase missing')
            net.command(i,encode_item_action(ItemAction(1,pet['items'][0]['id'],4)))
            net.command(i,b'\x50\3')
        net.command(0,b'\x52'+fixture.prefix.encode()+b'\0')
        net.command(0,b'\x5b'+fixture.names[2].encode()+b'\0')
        net.command(2,b'\x5d\1')
        status=fixture.status()
        require(status['clan'] and {m['account'] for m in status['members']}=={fixture.names[0],fixture.names[2]},
                'Native clan creation/invitation/acceptance failed')
        report['ordinary_clan']=status
        # Straight Reservation->checkpoint13 remains in the overlapping
        # configured safe margins; no DB travel or encounter suppression.
        for i in range(3):net.command(i,b'\x1b'+struct.pack('<ii',-170,-274))
        until=time.monotonic()+45
        while time.monotonic()<until:
            for i in range(3):net.command(i,b'\x70')
            status=fixture.status()
            if all(r['town']==13 for r in status['locations']):break
            time.sleep(.5)
        require(all(r['town']==13 for r in status['locations']),'Normal map travel did not reach checkpoint13')
        bought=fixture.snapshot_economy()['states']
        for s in bought:
            p=s['pets'][0]
            require(s['wallet']==[3050,0] and s['achievement_credits']==100 and p['hp']==p['max_hp']==115 and
                    p['xp']==7355 and any(i['template']==3 and i['count']==50 for i in p['items']) and
                    any(i['template']==301 and i['equipped'] for i in p['items']),'Normal supplies/achievement/health mismatch')
        report['normal_supplies_and_travel']=bought
        report['setup_tls']=net.audit()
    finally:close_all(net)
    report['claim']=fixture.claim_operation('set')
    report['setup_complete']=True


class MineDriver:
    """Bounded real C2S turns/actions driven by read-only owned checkpoint QA.

    Uses no callbacks, damage injection, DB coordinates, invulnerability or
    fabricated loot. Conservative route failure leaves an honest failed test.
    """
    def __init__(self,net,fixture):
        from tools.shared_mines_route import RouteCache
        self.net,self.fixture,self.ended=net,fixture,0
        self.cache=RouteCache()

    def state(self):
        self.fixture.guard_gate()
        state=self.fixture.snapshot_mine()
        validate_shared_snapshot(state,self.fixture.names)
        require(all(one_actor(state,n)['hp']>0 for n in self.fixture.names),'Owned human died before acceptance')
        return state

    def poll(self):
        self.net.poll_batch()

    def owner_turn(self,index,*,ap=1):
        for _ in range(240):
            self.poll();state=self.state();actor=one_actor(state,self.fixture.names[index])
            if state['turn']==actor['owner'] and actor['ap']>=ap:return state
            own=next((i for i,n in enumerate(self.fixture.names)
                      if any(a['owner']==state['turn'] and a['account']==n for a in state['actors'])),None)
            if own is not None:
                self.net.command(own,encode_end_turn());self.ended+=1
                require(self.ended<=160,'Bounded mine turn budget exceeded')
            else:time.sleep(.08)
        raise AssertionError('No bounded ordinary human turn')

    def to(self,index,goals,*,radius=0):
        from tools.shared_mines_route import plan_route
        for _ in range(120):
            state=self.state()
            actor=one_actor(state,self.fixture.names[index])
            plan=plan_route(state,actor['owner'],goals,interaction_radius=radius,cache=self.cache)
            # Already at the goal: movement needs no AP or turn. Waiting for
            # another turn here could cross the authoritative lift deadline.
            if not plan.path:return state
            state=self.owner_turn(index,ap=2)
            actor=one_actor(state,self.fixture.names[index])
            plan=plan_route(state,actor['owner'],goals,interaction_radius=radius,cache=self.cache)
            if not plan.path:return state
            steps=plan.prefix(actor['ap'],reserve=1)
            require(steps,'No legal AP movement prefix')
            self.net.command(index,encode_move_request(BattleMove(actor['id'],steps)))
            after=self.state();moved=one_actor(after,self.fixture.names[index])
            require((moved['x'],moved['y'])==steps[-1] and moved['ap']<actor['ap'],'Native move was rejected')
        raise AssertionError('Bounded route exceeded')

    def round(self,target):
        last=None
        for _ in range(240):
            self.poll();state=self.state();last=state
            if state['mining']['round']>=target:return state
            owner=next((i for i,n in enumerate(self.fixture.names)
                        if any(a['owner']==state['turn'] and a['account']==n for a in state['actors'])),None)
            if owner is not None:
                self.net.command(owner,encode_end_turn());self.ended+=1
                require(self.ended<=160,'Bounded mine turn budget exceeded')
            else:time.sleep(.08)
        raise AssertionError('Mine round did not advance')


def cleanup_owned(net,fixture):
    fixture.guard_gate()
    status=fixture.status()
    if status['durable']['battle_checkpoints']:
        state=fixture.snapshot_mine()
        # Presence of a foreign participant forbids every action other than
        # closing our own sockets. No checkpoint deletion/recovery write.
        validate_shared_snapshot(state,fixture.names,require_roles=False)
    for i in tuple(net.peers):
        net.command(i,b'\x2a\1')
        net.command(i,b'\x2a\1')
        net.command(i,b'\x50\x0d')
    close_all(net)
    final=fixture.status()
    require(not any(final['durable'].values()),'Retained battle/jobs remain; keep maintenance gate closed')
    return dict(all_owned_sockets_closed=True,durable=final['durable'],gate_left_closed=True)


def battle_attempt(fixture,args,report):
    source_guard(fixture);fixture.guard_gate();fixture.guard_connections(0)
    initial=fixture.status()
    require(initial['clan'] and not any(initial['durable'].values()) and
            all(r['town']==13 for r in initial['locations']) and not any(r['gross'] for r in initial['receipts']),
            'Run accepts the once-prepared owned trio before any mining receipt')
    original_hp={n:(s['pets'][0]['hp'],s['pets'][0]['max_hp']) for n,s in zip(fixture.names,fixture.snapshot_economy()['states'])}
    net=make_network(fixture,args);started=False
    try:
        for i in range(3):net.attach(i)
        for i,role in ((0,1),(2,3),(1,2)):
            net.command(i,bytes((0xb0,0x14,role)))
            require(b'\x41' in net.received[i],'Native mine scene missing')
        admission=fixture.snapshot_mine()
        report['admission']=validate_shared_snapshot(admission,fixture.names)
        require(admission['claim']['owner_clan']==initial['clan'] and admission['claim']['tax_percent']==10,
                'Battle did not freeze the owned QA claim')
        grounds=[next(p for p in net.received[i] if p[:1]==b'\x35') for i in range(3)]
        report['native_ground']=validate_wire_ground(grounds,admission['ground_sha256'])
        for i in range(3):
            require(b'\xb2\x0a\1' in net.received[i],'Native mining scene flag not delivered')
            net.command(i,b'\x36')
        started=True;driver=MineDriver(net,fixture)
        report['stage']='early_lift'
        # Probe immediately after Loaded. Miner/defender normally spawn at the
        # actual lift; Leave does not require movement AP or an active turn.
        from tools.shared_mines_route import UnsafeRouteError
        try:
            at_lift=driver.to(0,admission['mining']['lift'])
            if at_lift['mining']['round']<admission['mining']['lift_blocked_until']:
                response=net.command(0,b'\x2a\1');still=driver.state()
                require(any(p[:1]==b'\xf0' for p in response) and not still['mining']['exited'],
                        'Early native lift Leave must be rejected without settlement')
                report['native_lift_early']=dict(round=still['mining']['round'],blocked_leave=True,empty_drill_probe=True)
            else:
                report['native_lift_early']=dict(window_missed=True,blocked_leave_exercised=False)
        except UnsafeRouteError:
            report['native_lift_early']=dict(route_refused=True,blocked_leave_exercised=False)
        report['stage']='five_round_lift'
        # Five complete global rounds, with all three human turns and one
        # authoritative mutant group. Polls and commands cannot extend it.
        locked=driver.round(admission['mining']['lift_blocked_until']-1)
        unlocked=driver.round(admission['mining']['lift_blocked_until'])
        report['five_round_lift']=validate_lift_lock(admission,locked,unlocked)
        if report['native_lift_early'].get('blocked_leave'):
            require(b'\xb2\x16\1' in net.received[0],'Native CanQuit did not unlock at the actual empty lift')
            report['native_lift_early']['native_can_quit_unlocked']=True
        report['stage']='reconnect'
        before=driver.owner_turn(2)
        net.drop(2);time.sleep(.5)
        net.attach(2);net.command(2,b'\x36')
        after=driver.state()
        report['reconnect']=validate_reconnect(before,after,fixture.names)
        require(next(p for p in net.received[2] if p[:1]==b'\x35')==grounds[2],'Reconnect wire map changed')
        report['stage']='route_preflight'
        from tools.shared_mines_route import plan_mission,plan_route,UnsafeRouteError
        try:
            mission=plan_mission(after,one_actor(after,fixture.names[0])['owner'],cache=driver.cache)
        except UnsafeRouteError:
            # At most three ordinary NEW missions, never regenerate a retained
            # map or change seed/health/positions. All zero-gross receipts and
            # cleanup remain visible in the acceptance report.
            report['route_refusal']=True
            report['cleanup']=cleanup_owned(net,fixture)
            final=fixture.snapshot_economy()['states'];status=fixture.status()
            require(all((s['pets'][0]['hp'],s['pets'][0]['max_hp'])==original_hp[n]
                        for n,s in zip(fixture.names,final)) and not any(r['gross'] for r in status['receipts']),
                    'Retry requires unchanged normal HP and no extraction')
            fixture.guard_gate();fixture.guard_connections(0)
            report['retry_safe']=True;report['battle_tls']=net.audit()
            return
        report['route_preflight']=dict(crate=mission.crate.goal,deposit=mission.deposit.goal,
            exit=mission.exit.goal,steps=mission.steps,safety_model=mission.crate.safety_model)
        report['stage']='human_combat'
        # Genuine human combat at a conservative adjacent reachable cell.
        miner=one_actor(after,fixture.names[0])
        near=driver.to(1,[(miner['x'],miner['y'])],radius=1)
        attacker=one_actor(near,fixture.names[1]);victim=one_actor(near,fixture.names[0])
        driver.poll()
        from tio.protocol.battle_soldier import decode_battle_soldier
        observed=[]
        for viewer in range(3):
            snapshots={}
            for p in net.received[viewer]:
                if p[:1]==b'\x3b' and int.from_bytes(p[1:5],'little') in (attacker['id'],victim['id']):
                    soldier=decode_battle_soldier(p,human_equipment=True);snapshots[soldier.soldier_id]=soldier.position
            observed.append(dict(account=fixture.names[viewer],visible_actor_ids=[i for i,p in snapshots.items() if p!=(255,255)]))
        require(attacker['id'] in observed[0]['visible_actor_ids'] and victim['id'] in observed[1]['visible_actor_ids'],
                'Humans must genuinely see each other; hidden255 snapshots are not visibility proof')
        report['native_visibility']=observed
        damage=0;attempts=0
        for _ in range(6):
            state=driver.owner_turn(1,ap=5)
            a=one_actor(state,fixture.names[1]);v=one_actor(state,fixture.names[0])
            packets=net.command(1,encode_attack_request(AttackRequest(a['id'],v['x'],v['y'])))
            attempts+=1
            for p in packets:
                if p[:1]==b'\x4b':
                    hit=decode_attack_result(p)
                    if hit.actor_id==a['id']:damage+=sum(h.damage for h in hit.hits if h.actor_id==v['id'])
            if damage:break
        require(damage>0,'Real raider->miner attack did not cause damage')
        report['human_combat']=dict(attacker=a['id'],victim=v['id'],damage=damage,shots=attempts)
        # Ordinary loot/open/install/pickup chain. Each phase follows a fresh
        # checkpoint path and validates actual server inventory/AP updates.
        report['stage']='ordinary_mining'
        state=driver.state();miner=one_actor(state,fixture.names[0]);candidates=[]
        for crate in state['loot']:
            if any(i['template']==52 and i['count']==0 for i in crate['items']):
                try:
                    route=plan_route(state,miner['owner'],[(crate['x'],crate['y'])],interaction_radius=1,cache=driver.cache)
                    candidates.append((route.steps,crate))
                except UnsafeRouteError:pass
        require(candidates,'No conservative ordinary route to drill crate')
        crate=min(candidates,key=lambda p:p[0])[1]
        driver.to(0,[(crate['x'],crate['y'])],radius=1)
        state=driver.owner_turn(0,ap=4);miner=one_actor(state,fixture.names[0])
        packets=net.command(0,encode_position_request(BattlePositionRequest(miner['id'],crate['x'],crate['y'])))
        contents=[decode_container(p) for p in packets if p[:1]==b'\x47']
        require(contents,'Native crate contents missing')
        drills=[i for i in contents[-1][3] if i.template_id==52 and i.count==0]
        require(drills,'Fresh normal empty drill missing')
        drill=drills[0]
        net.command(0,encode_loot_transfer(LootTransfer(miner['id'],crate['x'],crate['y'],(),((drill.instance_id,0),))))
        state=driver.state();miner=one_actor(state,fixture.names[0])
        require(any(i['id']==drill.instance_id and i['template']==52 and i['count']==0 for i in miner['inventory']),
                'Ordinary zero-count drill transfer failed')
        deposits=[(d['x'],d['y']) for d in state['mining']['deposits'] if d['left'] and not d['installed']]
        driver.to(0,deposits,radius=1)
        state=driver.owner_turn(0,ap=2);miner=one_actor(state,fixture.names[0])
        net.command(0,encode_item_action(ItemAction(miner['id'],drill.instance_id,255)))
        installed=driver.state();generation=installed['mining']['round']
        deposits=[d for d in installed['mining']['deposits'] if d['installed']]
        require(len(deposits)==1,'Native installation did not install one owned drill')
        deposit=deposits[0]
        driver.round(generation+2)
        state=driver.owner_turn(0,ap=2);miner=one_actor(state,fixture.names[0])
        d=next(d for d in state['mining']['deposits'] if d['id']==deposit['id'])
        require(d['extracted']>=101,'Two genuine drill rounds must supply odd101-crystal test')
        net.command(0,b'\xb0\x15'+struct.pack('<IBBI',miner['id'],d['x'],d['y'],101))
        picked=driver.state();miner=one_actor(picked,fixture.names[0])
        require(any(i['template']==52 and i['count']==101 for i in miner['inventory']),'Native crystal pickup failed')
        report['ordinary_mining']=dict(drill_id=drill.instance_id,deposit_id=d['id'],installed_round=generation,
                                       pickup_round=picked['mining']['round'],carried=101)
        before_crystals=fixture.status()['amounts']
        # Exit may settle/remove miner immediately on the final native step;
        # use a separate bounded driver instead of reading a removed actor.
        exits=picked['mining']['lift']
        for _ in range(120):
            status=fixture.status()
            if current_extraction_receipts(status,admission['match'],fixture.names[0]):break
            state=driver.owner_turn(0,ap=2);miner=one_actor(state,fixture.names[0])
            route=plan_route(state,miner['owner'],exits,cache=driver.cache)
            require(route.path,'Nonempty carried drill at a valid lift should settle')
            steps=route.prefix(miner['ap'],reserve=1)
            net.command(0,encode_move_request(BattleMove(miner['id'],steps)))
        status=fixture.status()
        receipts=current_extraction_receipts(status,admission['match'],fixture.names[0])
        require(len(receipts)==1,'One actual owned mine extraction receipt required')
        report['crystal_conservation']=validate_receipt(receipts[0],before_crystals,status['amounts'],
            miner=fixture.names[0],raider=fixture.names[1],defender=fixture.names[2])
        report['receipt']=receipts[0]
        report['cleanup']=cleanup_owned(net,fixture)
        report['battle_tls']=net.audit()
        report['passed']=True
    finally:
        # Failed acceptance never deletes checkpoints or silently unclaims a
        # mine. Keep failclosed maintenance for reviewed ordinary cleanup.
        net.close();net.peers.clear()
        report.setdefault('cleanup',dict(own_sockets_closed=True,gate_left_closed=True,ordinary_cleanup_verified=False))


def battle_owned(fixture,args,report):
    report['attempts']=[]
    prior={r['match_id'] for r in fixture.status()['receipts']}
    require(len(prior)<3,'Three ordinary missions already used; no extra mission allowed')
    report['prior_zero_gross_missions']=len(prior)
    for ordinal in range(len(prior)+1,4):
        attempt=dict(ordinal=ordinal,passed=False)
        report['attempts'].append(attempt)
        battle_attempt(fixture,args,attempt)
        if attempt['passed']:
            report.update({k:v for k,v in attempt.items() if k!='ordinal'})
            verify_clan_safe(fixture,args,report)
            return
        require(attempt.get('retry_safe') and attempt['cleanup']['all_owned_sockets_closed'],
                'Failed mission cannot be retried without ordinary cleanup proof')
    raise AssertionError('Three ordinary missions provided no conservative mining route; no positive tax proof')


def verify_clan_safe(fixture,args,report):
    from tio.clans import CRYSTAL_MONEY_ID,WITHDRAW_CRYSTALS,DEFAULT_RIGHTS
    net=make_network(fixture,args)
    try:
        for i in range(3):net.attach(i)
        before=fixture.status();defender=next(m for m in before['members'] if m['account']==fixture.names[2])
        require(before['amounts']['clan']==10 and not defender['permissions']&WITHDRAW_CRYSTALS,
                'Real101 extraction tax and ordinary default permissions required')
        packets=net.command(2,b'\x69\2')
        projected=[decode_warehouse_list(p) for p in packets if p[:1]==b'\x6a']
        crystals=[i for kind,_,_,items in projected if kind==2 for i in items if i.template_id==51]
        require(len(crystals)==1 and crystals[0].instance_id==CRYSTAL_MONEY_ID and crystals[0].count==10,
                'Clan tax must project usable native warehouse item51')
        take=encode_warehouse_transfer(WarehouseTransfer(2,1,(),((CRYSTAL_MONEY_ID,1),)))
        packets=net.command(2,take);denied=fixture.status()
        require(denied['amounts']==before['amounts'] and any(p[:1]==b'\xf0' for p in packets),
                'Member without262144 must not withdraw clan crystals')
        net.command(0,b'\x98'+struct.pack('<IIB',defender['identity'],DEFAULT_RIGHTS|WITHDRAW_CRYSTALS,0))
        granted=fixture.status();member=next(m for m in granted['members'] if m['account']==fixture.names[2])
        require(member['permissions']&WITHDRAW_CRYSTALS,'Native ordinary permission grant failed')
        net.command(2,encode_warehouse_transfer(WarehouseTransfer(2,1,(),((CRYSTAL_MONEY_ID,3),))))
        withdrawn=fixture.status()
        require(withdrawn['amounts']['clan']==7 and
                withdrawn['amounts'][fixture.names[2]]==before['amounts'][fixture.names[2]]+3,
                'Usable clan crystal withdrawal did not conserve balances')
        net.command(2,encode_warehouse_transfer(WarehouseTransfer(2,1,((CRYSTAL_MONEY_ID,1),),())))
        deposited=fixture.status()
        require(deposited['amounts']['clan']==8 and
                deposited['amounts'][fixture.names[2]]==before['amounts'][fixture.names[2]]+2 and
                sum(deposited['amounts'].values())==101,'Native crystal redeposit lost/created currency')
        for i in range(3):net.command(i,b'\x2a\1')
        replay=fixture.status()
        require(replay['amounts']==deposited['amounts'] and replay['receipts']==deposited['receipts'],
                'Finish replay awarded the extraction twice')
        close_all(net)
        net=make_network(fixture,args)
        for i in range(3):net.attach(i)
        relog=fixture.status()
        require(relog['amounts']==deposited['amounts'] and relog['receipts']==deposited['receipts'],
                'Crystal settlement/permissions changed after relog')
        report['clan_safe']=dict(native_template=51,denied_without_permission=True,permission=262144,
            withdrawal=3,redeposit=1,conserved_total=101,relogin_same_balances=True,finish_replay_no_award=True,
            final_balances=relog['amounts'])
        report['safe_tls']=net.audit()
        report['cleanup']=cleanup_owned(net,fixture)
    finally:net.close();net.peers.clear()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--prepare-owned',action='store_true',help='Local private credentials/name reservation; no network')
    actions.add_argument('--provision-owned',action='store_true',help='Explicit fresh trio creation, normal setup and battle')
    actions.add_argument('--run',action='store_true',help='Run once-prepared trio; no account/stat creation')
    actions.add_argument('--cleanup-only',action='store_true',help='Normal own TLS Leave/Finish only; keep maintenance gate')
    actions.add_argument('--inspect-only',action='store_true',help='Owned read-only state; no game connections/admission')
    parser.add_argument('--fixture',type=Path)
    parser.add_argument('--gate',type=Path,help='Reviewed maintenance isolation and SSH forward proof')
    parser.add_argument('--setup-only',action='store_true')
    parser.add_argument('--host',default='185.184.42.88',help='SSH inspection/provision host, never the forwarded TLS name')
    parser.add_argument('--server-name',default='ti-reborn.com',help='Strict production TLS hostname/SNI')
    parser.add_argument('--ca-file',type=Path,help='Only for local TLS fixture self-tests')
    parser.add_argument('--key',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/shared-mines/owned-readonly-state.json')
    args=parser.parse_args()
    target=args.output.resolve()
    require(target.parent==ROOT/'reports/shared-mines' and not target.exists(),'Preserve previous reports')
    require(args.server_name=='ti-reborn.com' or args.ca_file,'Do not substitute production certificate identity')
    require(not args.setup_only or args.provision_owned,'Setup-only is an explicit fresh provisioning phase')
    report=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),passed=False,
                kind='Automated three-account native protocol TLS QA; graphical clients not exercised',
                limitations=['Lv4 access is synthetic owned fixture, not earned progression',
                    'No hosted process crash/restart or external plaintext-wire capture by this verifier',
                    'Maintenance gate is never removed by this verifier'])
    error=None
    try:
        if args.prepare_owned:
            require(args.fixture is None and args.gate is None,'Prepare generates new local credentials only')
            fixture=MinesFixture.prepare_owned(args.host,key=str(args.key) if args.key else None)
            report.update(accounts=fixture.names,private_fixture=fixture.credential_path,prepared_local_only=True,passed=True)
        else:
            require(args.fixture is not None,'A previously prepared private fixture is required')
            fixture=MinesFixture.load_private(args.fixture)
            report.update(accounts=fixture.names,private_fixture=fixture.credential_path,pre_provision_backup=fixture.backup)
            if args.inspect_only:
                require(fixture.backup,'Only proven-owned provisioned accounts may be inspected')
                report.update(economy=source_guard(fixture),status=fixture.status(),passed=True)
            else:
                require(args.gate is not None,'Pinned operational isolation proof required')
                gate=json.loads(args.gate.read_text(encoding='utf-8'))
                require(gate['version']==1 and gate['accounts']==fixture.names,
                        'Ingress lease must pin exactly this reserved trio')
                fixture.gate=gate
                report['gate']=dict(lease_id=gate['lease_id'],lease_sha256=gate['lease_sha256'],
                                    deadline_utc=gate['deadline_utc'],ssh_forwarded_tls=True)
                if args.provision_owned:
                    report['provision']=fixture.provision(gate,hostname=args.server_name,ca_file=args.ca_file)
                    report['pre_provision_backup']=fixture.backup;report['private_fixture']=fixture.credential_path
                    setup_owned(fixture,args,report)
                    if args.setup_only:report['passed']=True
                    else:battle_owned(fixture,args,report)
                elif args.cleanup_only:
                    source_guard(fixture);fixture.guard_gate()
                    net=make_network(fixture,args)
                    try:
                        for i in range(3):net.attach(i)
                        report['cleanup']=cleanup_owned(net,fixture);report['passed']=True
                    finally:net.close()
                else:battle_owned(fixture,args,report)
            if report.get('passed'):report['preservation']=fixture.preservation()
    except Exception as exc:
        # Remote exception text and input can contain private evidence. Only
        # public literal assertions from this owned source may be disclosed.
        report['passed']=False;report['error_type']=type(exc).__name__;error=exc
        report.update(safe_assertion_diagnostic(exc))
    finally:
        report['finished_utc']=datetime.now(timezone.utc).isoformat()
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf-8') as out:out.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],accounts=len(report.get('accounts',[])),
                         setup_complete=report.get('setup_complete',False),report=str(target))))
    if error:raise SystemExit(1)


if __name__=='__main__':main()
