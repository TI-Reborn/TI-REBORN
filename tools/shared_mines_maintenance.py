"""Fail-closed, lease-owned ingress isolation for three fresh mining QA accounts.

This program runs on the Linux host as an authorized operator. Activation is
explicit; importing it or asking for --help performs no remote operation. It
never restores a database, deletes accounts or replaces the UFW ruleset.

Before activation choose the three fresh usernames and two local SSH-forward
ports. Use the returned proof for every fixture mutation and claim assignment.
Normal release requires clients to Finish and close their connections first.
The independent 20-minute watchdog can gracefully stop only an objectively
QA-only game service, preserve its committed rewards, clear this lease's exact
claim and reopen ingress. Any foreign/raced/unfinished state leaves the gate
closed with an attention receipt. A persistent lease-owned ExecStartPre drop-in
prevents a reboot (which loses transient nft rules) from exposing a saved QA
claim. Manual fallback is to finish only these QA accounts and retry release;
never flush the firewall, wipe checkpoints wholesale or restore player data.
"""
from contextlib import closing,contextmanager
from datetime import datetime,timezone
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import uuid

CODE_ROOT=Path('/opt/tio-emulator')
DB=Path('/var/lib/tio-server/reservation.sqlite3')
PRIVATE=Path('/root/tio-shared-mines-qa')
DROPINS=Path('/etc/systemd/system/tio-server.service.d')
PORTS=(28512,28513,29512,29513)
TTL=1200
SERVICE='tio-server'
TABLE_PREFIX='tio_mines_qa_'
VERIFY_GATE="""from pathlib import Path
import hashlib,runpy
helper=Path(proof['helper_path'])
expected=Path('/root/tio-shared-mines-qa')/proof['lease_id']/'maintenance.py'
if helper!=expected or helper.is_symlink():raise ValueError('Unexpected QA helper path')
if hashlib.sha256(helper.read_bytes()).hexdigest()!=proof['helper_sha256']:raise ValueError('QA helper checksum changed')
runpy.run_path(str(helper))['verify_gate'](proof)
"""


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def sha(raw):return hashlib.sha256(raw).hexdigest()
def command(*args,input=None):
    return subprocess.run(args,input=input,text=True,capture_output=True,check=True,timeout=150).stdout.strip()


def gate_program(table):
    return {'nftables':[
        {'add':{'table':{'family':'inet','name':table}}},
        {'add':{'chain':{'family':'inet','table':table,'name':'ingress','type':'filter','hook':'input','prio':-300,'policy':'accept'}}},
        {'add':{'rule':{'family':'inet','table':table,'chain':'ingress','expr':gate_expr()}}}]}


def gate_expr():
    return [{'match':{'op':'!=','left':{'meta':{'key':'iifname'}},'right':'lo'}},
            {'match':{'op':'==','left':{'payload':{'protocol':'tcp','field':'dport'}},'right':{'set':list(PORTS)}}},
            {'drop':None}]


def gate_shape(data,table):
    values=data.get('nftables',[])
    if any(set(v) not in ({'metainfo'},{'table'},{'chain'},{'rule'}) for v in values):raise ValueError('Unexpected QA gate object')
    tables=[v['table'] for v in values if 'table' in v]
    chains=[v['chain'] for v in values if 'chain' in v]
    rules=[v['rule'] for v in values if 'rule' in v]
    if len(tables)!=1 or len(chains)!=1 or len(rules)!=1:raise ValueError('QA gate must have exactly one table, chain and rule')
    t,c,r=tables[0],chains[0],rules[0]
    if set(t)!={'family','name','handle'} or set(c)!={'family','table','name','handle','type','hook','prio','policy'} or set(r)!={'family','table','chain','handle','expr'}:
        raise ValueError('Unexpected QA gate flags or attributes')
    if t.get('family')!='inet' or t.get('name')!=table:raise ValueError('Wrong QA gate table')
    if any(c.get(k)!=v for k,v in dict(family='inet',table=table,name='ingress',type='filter',hook='input',prio=-300,policy='accept').items()):
        raise ValueError('QA ingress chain changed')
    if any(r.get(k)!=v for k,v in dict(family='inet',table=table,chain='ingress',expr=gate_expr()).items()):
        raise ValueError('QA ingress rule changed')
    handles={k:v.get('handle') for k,v in (('table',t),('chain',c),('rule',r))}
    if any(type(v) is not int or v<=0 for v in handles.values()):raise ValueError('Invalid QA gate handles')
    return handles


def firewall_digest(data,exclude=None):
    """Ignore traffic counters, retain every foreign firewall rule and handle."""
    def clean(value):
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ('packets','bytes')}
        return value
    values=[]
    for entry in data.get('nftables',[]):
        if 'metainfo' in entry:continue
        item=next(iter(entry.values()))
        if exclude and isinstance(item,dict) and (item.get('table')==exclude or 'table' in entry and item.get('name')==exclude):continue
        values.append(clean(entry))
    return sha(canonical(values).encode())


class Maintenance:
    def __init__(self,*,database=DB,private=PRIVATE,dropins=DROPINS,runner=command,clock=time.time,
                 source=None,strict_private=True):
        self.database,self.private,self.dropins=Path(database),Path(private),Path(dropins)
        self.run,self.clock=runner,clock
        self.source=Path(source) if source else Path(__file__)
        self.strict_private=strict_private

    @contextmanager
    def lock(self):
        import fcntl
        self.private.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.private_directory(self.private)
        lock=self.private/'maintenance.lock'
        if lock.is_symlink():raise ValueError('Unexpected QA lock path')
        with lock.open('a') as handle:
            os.chmod(lock,0o600)
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

    def private_directory(self,path):
        path=Path(path)
        if path.is_symlink() or not path.is_dir():raise ValueError('Unexpected QA private directory')
        if self.strict_private and (path.stat().st_uid!=0 or path.stat().st_mode&0o077):raise ValueError('QA directory must be private root-owned data')

    def private_file(self,path):
        path=Path(path)
        self.private_directory(self.private);self.private_directory(path.parent)
        if path.is_symlink() or path.parent.parent!=self.private or not path.is_file():raise ValueError('Unexpected QA lease path')
        if self.strict_private and (path.stat().st_uid!=0 or path.stat().st_mode&0o077):raise ValueError('QA lease must be private root-owned data')
        return path

    def write(self,path,value,*,exclusive=False):
        raw=(canonical(value)+'\n').encode() if isinstance(value,dict) else value
        if exclusive:
            with Path(path).open('xb') as out:out.write(raw)
            os.chmod(path,0o600)
        else:
            temp=Path(str(path)+'.tmp')
            with temp.open('xb') as out:out.write(raw)
            os.chmod(temp,0o600);os.replace(temp,path)

    def table(self,name):return json.loads(self.run('nft','-j','list','table','inet',name))
    def rules(self):return json.loads(self.run('nft','-j','list','ruleset'))
    def state(self,folder):return json.loads(self.private_file(folder/'state.json').read_text())

    def load(self,proof,*,expired=False,releasing=False):
        if not isinstance(proof,dict) or proof.get('version')!=1:raise ValueError('Invalid QA isolation proof')
        lease_id=proof.get('lease_id','')
        if len(lease_id)!=32 or any(c not in '0123456789abcdef' for c in lease_id):raise ValueError('Invalid QA lease ID')
        path=self.private/lease_id/'lease.json'
        if str(path)!=proof.get('lease_path'):raise ValueError('Unexpected QA lease reference')
        raw=self.private_file(path).read_bytes()
        if sha(raw)!=proof.get('lease_sha256'):raise ValueError('QA lease checksum changed')
        lease=json.loads(raw);folder=path.parent;state=self.state(folder)
        if lease['lease_id']!=lease_id or proof.get('gate_table')!=TABLE_PREFIX+lease_id or proof.get('accounts')!=lease['accounts']:
            raise ValueError('QA proof identity changed')
        if proof.get('deadline_utc')!=lease['deadline_utc'] or proof.get('forwarding')!=lease['forwarding']:
            raise ValueError('QA proof deadline or forwards changed')
        if state['status'] not in ('isolated','cleaning','attention'):raise ValueError('QA isolation is not active')
        if not expired and self.clock()>=lease['deadline']:raise ValueError('QA maintenance lease expired')
        release_retry=releasing and state.get('phase')=='releasing'
        if release_retry:
            with closing(sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('BEGIN');self.pending(db,lease['accounts'],idle=True)
                if self.claim_now(db)!=state.get('claim') or state['claim']['owner_clan']is not None or state['claim']['tax_percent']:
                    raise ValueError('Incomplete release cannot expose a QA claim')
        rules=self.rules()
        present=any(v.get('table',{}).get('name')==proof['gate_table'] for v in rules.get('nftables',[]))
        if present:
            if gate_shape(self.table(proof['gate_table']),proof['gate_table'])!=state['gate_handles']:raise ValueError('QA gate handles changed')
        elif not release_retry:raise ValueError('QA ingress gate missing')
        helper=folder/'maintenance.py'
        if proof.get('helper_path')!=str(helper) or proof.get('helper_sha256')!=lease['helper_sha256']:
            raise ValueError('QA helper proof changed')
        if sha(self.private_file(helper).read_bytes())!=lease['helper_sha256']:raise ValueError('Pinned QA cleanup helper changed')
        dropin=self.dropins/lease['dropin_name']
        if dropin.is_symlink() or (dropin.exists() and sha(dropin.read_bytes())!=lease['dropin_sha256']) or not dropin.exists() and not release_retry:
            raise ValueError('QA boot-start guard changed')
        if firewall_digest(rules,exclude=proof['gate_table'])!=lease['firewall_sha256']:
            raise ValueError('Foreign firewall configuration changed')
        return lease,folder,state

    def connections(self):
        text=self.run('ss','-Htn','state','established','( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )')
        rows=text.splitlines()
        if len(rows)>6:raise ValueError('Unexpected number of game connections during three-account QA')
        for row in rows:
            peer=row.split()[-1].rsplit(':',1)[0].strip('[]')
            if not ipaddress.ip_address(peer).is_loopback:raise ValueError('Foreign game connection detected')
        return rows

    def claim_now(self,db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='mine_claims'").fetchone():return dict(location=13,owner_clan=None,tax_percent=0,revision=0)
        row=db.execute('SELECT owner_clan,tax_percent,revision FROM mine_claims WHERE location=13').fetchone()
        return dict(location=13,owner_clan=row[0] if row else None,tax_percent=row[1] if row else 0,revision=row[2] if row else 0)

    def binding(self,lease,folder,db):
        path=folder/'claim-binding.json'
        binding=json.loads(self.private_file(path).read_text()) if path.exists() else None
        current=self.claim_now(db)
        if binding is None:
            if current!=lease['initial_claim']:raise ValueError('Checkpoint claim changed outside this lease')
            return None
        assigned=binding['assigned_claim']
        from tio.mine_claims import validate_claim
        validate_claim(assigned)
        if assigned!=dict(lease['initial_claim'],owner_clan=binding['clan_id'],tax_percent=assigned['tax_percent'],revision=lease['initial_claim']['revision']+1):
            raise ValueError('QA claim binding changed')
        self.safe_clan(db,binding['clan_id'],lease['accounts'])
        cleared=dict(assigned,owner_clan=None,tax_percent=0,revision=assigned['revision']+1)
        if current==assigned:
            expected_actor='qa:'+lease['lease_id']
        elif current==cleared:
            expected_actor='qa-cleanup:'+lease['lease_id']
        elif current==lease['initial_claim']:
            return binding  # Assignment was interrupted before DB commit.
        else:raise ValueError('QA checkpoint ownership raced cleanup')
        row=db.execute('SELECT actor,owner_clan,tax_percent FROM mine_claim_history WHERE location=13 AND revision=?',(current['revision'],)).fetchone()
        if row!=(expected_actor,current['owner_clan'],current['tax_percent']):raise ValueError('QA claim history changed')
        return binding

    def pending(self,db,accounts,*,idle=False,claim=None):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_failure_audit'").fetchone() and db.execute('SELECT 1 FROM battle_failure_audit WHERE resolved=0 LIMIT 1').fetchone():
            raise ValueError('Unresolved battle failure requires manual review')
        for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs'):
            if db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() and idle and db.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone():
                raise ValueError('Unfinished battle or result prevents opening QA ingress')
        if idle:return
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_checkpoints'").fetchone():
            from tio.battle_snapshot import loads
            matches=set()
            for match,payload,checksum,status in db.execute('SELECT match_id,payload,checksum,status FROM battle_checkpoints'):
                if status not in ('active','finished'):raise ValueError('Quarantined QA checkpoint requires manual review')
                matches.add(match)
                if sha(payload.encode())!=checksum:raise ValueError('Battle checkpoint checksum changed')
                data,_=loads(payload)
                if data.get('kind')!='shared' or data['battle'].get('kind')!='mine' or data['battle']['city_id']!=13:
                    raise ValueError('Foreign battle detected during QA isolation')
                if (status=='finished')!=bool(data['battle'].get('finished')):raise ValueError('QA checkpoint status disagrees with battle')
                if data['battle']['match_id']!=match or claim is None or data['battle'].get('mine_claim')!=claim:raise ValueError('QA battle claim or identity changed')
                names={v['account'] for v in data['sessions'].values()}
                bound={a:o for a,o in db.execute('SELECT account,owner_id FROM battle_checkpoint_members WHERE match_id=?',(match,))}
                expected={data['sessions'][o]['account']:o for o in data['retained']}
                if not names or not names<=set(accounts) or not expected or bound!=expected:raise ValueError('Foreign checkpoint ownership detected')
                if status=='finished' and any(not db.execute('SELECT 1 FROM battle_rewards WHERE match_id=? AND account=?',(match,a)).fetchone() for a in expected):
                    raise ValueError('Owned QA result lacks its committed receipt')
            if db.execute('SELECT 1 FROM battle_checkpoint_members WHERE match_id NOT IN (SELECT match_id FROM battle_checkpoints) LIMIT 1').fetchone():raise ValueError('Orphan checkpoint account binding')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_settlement_jobs'").fetchone():
            for match,account,payload in db.execute('SELECT match_id,account,payload FROM battle_settlement_jobs'):
                report=json.loads(payload)
                extraction=report['kwargs'].get('mine_extraction',{})
                if account not in accounts or extraction.get('extractor')!=account or claim is None or extraction.get('claim')!=claim:
                    raise ValueError('Foreign settlement detected during QA isolation')
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_checkpoints'").fetchone() and match not in matches:
                    raise ValueError('QA settlement lacks its owned checkpoint')

    def safe_clan(self,db,clan,accounts):
        row=db.execute('SELECT leader FROM clans WHERE id=?',(clan,)).fetchone()
        members={r[0] for r in db.execute('SELECT account FROM clan_members WHERE clan_id=?',(clan,))}
        if row is None or row[0] not in accounts or row[0] not in members or not members<=set(accounts):
            raise ValueError('QA claim clan has foreign ownership or members')

    def proof(self,folder):return json.loads(self.private_file(folder/'proof.json').read_text())

    def activate(self,accounts,login_port,session_port):
        if len(accounts)!=3 or len(set(accounts))!=3:
            raise ValueError('Specify exactly three fresh QA usernames')
        from server.accounts import identity
        for name in accounts:identity(name)
        if any(type(p)is not int or not 1024<=p<=65535 for p in (login_port,session_port)) or login_port==session_port:
            raise ValueError('Use distinct local SSH-forward ports')
        with self.lock():
            if not self.database.is_file():raise ValueError('Hosted database missing')
            if self.connections():raise ValueError('Game connections must be idle before QA isolation')
            rules=self.rules()
            if any(v.get('table',{}).get('name','').startswith(TABLE_PREFIX) for v in rules.get('nftables',[])):
                raise ValueError('A previous QA ingress gate still exists')
            with closing(sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)) as db:
                db.execute('BEGIN');self.pending(db,accounts,idle=True)
                initial=self.claim_now(db)
                if initial['owner_clan']is not None or initial['tax_percent']:raise ValueError('Mine13 must initially be unowned')
                if not 0<=initial['revision']<=0xfffffffd:raise ValueError('Checkpoint revision lacks room for assignment and cleanup')
                if db.execute('SELECT 1 FROM accounts WHERE login IN (?,?,?)',tuple(accounts)).fetchone():raise ValueError('QA accounts must be fresh before isolation')
            lease_id=uuid.uuid4().hex;folder=self.private/lease_id;folder.mkdir(mode=0o700)
            table=TABLE_PREFIX+lease_id;helper=folder/'maintenance.py';source=self.source.read_bytes()
            dropin_name='90-qa-'+lease_id+'.conf'
            dropin=b'[Service]\nExecStartPre=+/usr/bin/python3 '+str(helper).encode()+b' boot-check --lease '+str(folder/'lease.json').encode()+b'\n'
            deadline=self.clock()+TTL
            lease=dict(version=1,lease_id=lease_id,accounts=list(accounts),deadline=deadline,
                deadline_utc=datetime.fromtimestamp(deadline,timezone.utc).isoformat(),
                forwarding=dict(host='127.0.0.1',login_port=login_port,session_port=session_port,remote_login_port=29512,remote_session_port=29513),
                initial_claim=initial,firewall_sha256=firewall_digest(rules),helper_sha256=sha(source),
                dropin_name=dropin_name,dropin_sha256=sha(dropin),watchdog_unit='tio-mines-qa-'+lease_id)
            self.write(helper,source,exclusive=True);self.write(folder/'lease.json',lease,exclusive=True)
            proof=dict(version=1,lease_id=lease_id,lease_path=str(folder/'lease.json'),
                lease_sha256=sha((folder/'lease.json').read_bytes()),gate_table=table,accounts=list(accounts),
                helper_path=str(helper),helper_sha256=lease['helper_sha256'],deadline_utc=lease['deadline_utc'],forwarding=lease['forwarding'])
            self.write(folder/'proof.json',proof,exclusive=True)
            self.write(folder/'state.json',dict(status='preparing',gate_handles=None),exclusive=True)
            try:
                self.dropins.mkdir(parents=True,exist_ok=True);self.write(self.dropins/dropin_name,dropin,exclusive=True)
                self.run('systemctl','daemon-reload')
                # A timer can always find its immutable proof, even if adding
                # the gate fails. Failed activation rolls back only this lease.
                self.run('systemd-run','--unit='+lease['watchdog_unit'],'--on-active='+str(TTL)+'s','--timer-property=AccuracySec=1s',
                    '--property=Type=oneshot','/usr/bin/python3',str(helper),'watchdog','--lease',str(folder/'lease.json'))
                if self.connections():raise ValueError('A game connection raced QA activation; no QA claim may be assigned')
                self.run('nft','-j','-f','-',input=canonical(gate_program(table)))
                handles=gate_shape(self.table(table),table)
                self.write(folder/'state.json',dict(status='isolated',gate_handles=handles))
                # The public gate is closed now; a pre-existing battle/account
                # racing activation must be noticed before any QA claim exists.
                with closing(sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)) as db:
                    db.execute('BEGIN');self.pending(db,accounts,idle=True)
                    if self.claim_now(db)!=initial:raise ValueError('Checkpoint raced QA activation')
                    if db.execute('SELECT 1 FROM accounts WHERE login IN (?,?,?)',tuple(accounts)).fetchone():raise ValueError('QA account raced activation')
                if self.connections():raise ValueError('A game connection raced QA activation')
                self.load(proof)
                return proof
            except Exception as error:
                try:self.abort_activation(lease,folder,proof)
                except Exception as rollback_error:
                    self.write(folder/'state.json',dict(status='attention',gate_handles=self.state(folder).get('gate_handles'),
                        error_type=type(error).__name__,rollback_error_type=type(rollback_error).__name__))
                raise

    def abort_activation(self,lease,folder,proof):
        """Restore availability only before a QA claim has ever been assigned."""
        with closing(sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            if self.claim_now(db)!=lease['initial_claim'] or (folder/'claim-binding.json').exists():raise ValueError('Activation rollback cannot release a QA claim')
        rules=self.rules();table=proof['gate_table']
        if firewall_digest(rules,exclude=table)!=lease['firewall_sha256']:raise ValueError('Foreign firewall changed during activation')
        # Only a fresh UUID table created by this activation may be removed.
        if any(v.get('table',{}).get('name')==table for v in rules.get('nftables',[])):
            self.run('nft','delete','table','inet',table)
        dropin=self.dropins/lease['dropin_name']
        if dropin.exists():
            if dropin.is_symlink() or sha(dropin.read_bytes())!=lease['dropin_sha256']:raise ValueError('Activation boot guard changed')
            dropin.unlink();self.run('systemctl','daemon-reload')
        self.run('systemctl','stop',lease['watchdog_unit']+'.timer')
        self.write(folder/'state.json',dict(status='activation-aborted',gate_handles=None))

    def claim(self,proof,clan,tax_percent=10):
        with self.lock():
            lease,folder,state=self.load(proof)
            if state['status']!='isolated':raise ValueError('QA claim requires an isolated active lease')
            if type(clan)is not int or clan<=0 or type(tax_percent)is not int or not 0<=tax_percent<=10:raise ValueError('Invalid QA claim request')
            from tio.db_transaction import transaction
            from tio.mine_claims import MineClaimsStore
            with transaction(self.database) as db:
                self.pending(db,lease['accounts'],idle=True);self.safe_clan(db,clan,lease['accounts'])
                if db.execute('SELECT COUNT(*) FROM accounts WHERE login IN (?,?,?)',tuple(lease['accounts'])).fetchone()[0]!=3:raise ValueError('All three fresh QA accounts must exist')
                if self.claim_now(db)!=lease['initial_claim']:raise ValueError('Checkpoint claim changed before QA assignment')
                binding=dict(clan_id=clan,assigned_claim=dict(lease['initial_claim'],owner_clan=clan,tax_percent=tax_percent,revision=lease['initial_claim']['revision']+1))
                self.write(folder/'claim-binding.json',binding,exclusive=True)
                result=MineClaimsStore(self.database).admin_set_claim(13,clan,tax_percent=tax_percent,
                    expected_revision=lease['initial_claim']['revision'],actor='qa:'+lease['lease_id'],reason='Isolated three-account acceptance')
                if result!=binding['assigned_claim']:raise ValueError('Unexpected QA claim receipt')
            return result

    def clear(self,lease,folder):
        from tio.db_transaction import transaction
        from tio.mine_claims import MineClaimsStore
        with transaction(self.database) as db:
            self.pending(db,lease['accounts'],idle=True);binding=self.binding(lease,folder,db);current=self.claim_now(db)
            if current==lease['initial_claim']:return current  # No claim assigned.
            if binding is None:raise ValueError('QA claim binding missing')
            cleared=dict(binding['assigned_claim'],owner_clan=None,tax_percent=0,revision=binding['assigned_claim']['revision']+1)
            if current==cleared:
                actor=db.execute('SELECT actor FROM mine_claim_history WHERE location=13 AND revision=?',(current['revision'],)).fetchone()
                if actor!=('qa-cleanup:'+lease['lease_id'],):raise ValueError('Checkpoint was cleared by another operation')
                return current
            if current!=binding['assigned_claim']:raise ValueError('QA checkpoint ownership raced cleanup')
            return MineClaimsStore(self.database).admin_set_claim(13,None,tax_percent=0,
                expected_revision=current['revision'],actor='qa-cleanup:'+lease['lease_id'],reason='End isolated three-account acceptance')

    def finish(self,proof,*,watchdog=False):
        with self.lock():
            try:lease,folder,state=self.load(proof,expired=watchdog,releasing=True)
            except Exception as error:
                # A bad proof must never overwrite another lease's status. A
                # genuine lease whose firewall/guard disappeared gets attention.
                try:
                    folder=self.private/proof['lease_id'];path=self.private_file(folder/'lease.json')
                    if str(path)==proof['lease_path'] and sha(path.read_bytes())==proof['lease_sha256']:
                        prior=self.state(folder)
                        if prior['status'] in ('isolated','cleaning','attention'):
                            self.write(folder/'state.json',dict(prior,status='attention',error_type=type(error).__name__))
                except Exception:pass
                raise
            try:
                self.write(folder/'state.json',dict(state,status='cleaning'))
                with closing(sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)) as db:
                    db.execute('BEGIN');binding=self.binding(lease,folder,db)
                    self.pending(db,lease['accounts'],idle=not watchdog,claim=binding['assigned_claim'] if binding else None)
                connections=self.connections()
                if not watchdog and connections:raise ValueError('Close QA client connections before release')
                if watchdog and state.get('phase')!='releasing':
                    # No foreign checkpoint/outbox/socket is permitted at this
                    # point. A graceful stop preserves only these QA reports.
                    self.run('systemctl','stop',SERVICE)
                    if self.run('systemctl','show',SERVICE,'-p','ActiveState','--value')!='inactive':raise ValueError('Game service did not stop cleanly')
                    if self.connections():raise ValueError('Game connections survived graceful QA stop')
                    with closing(sqlite3.connect(self.database)) as db,db:
                        db.execute('BEGIN IMMEDIATE');self.binding(lease,folder,db)
                        self.pending(db,lease['accounts'],claim=binding['assigned_claim'] if binding else None)
                        self.remove_finished_qa_checkpoints(db,lease['accounts'])
                cleared=self.clear(lease,folder)
                if cleared['owner_clan']is not None or cleared['tax_percent']:raise ValueError('QA checkpoint was not cleared')
                if watchdog and state.get('phase')!='releasing':
                    self.run('systemctl','start',SERVICE)
                    if self.run('systemctl','show',SERVICE,'-p','ActiveState','--value')!='active':raise ValueError('Game service failed to restart behind the gate')
                # Revalidate independent state before reopening any game port.
                self.load(proof,expired=True,releasing=True)
                with closing(sqlite3.connect(self.database.as_uri()+'?mode=ro',uri=True)) as db:
                    db.execute('BEGIN');self.pending(db,lease['accounts'],idle=True)
                    if self.claim_now(db)!=cleared:raise ValueError('Checkpoint changed after clear')
                if self.connections():raise ValueError('A game connection raced QA release')
                # The running watchdog must not stop itself before release.
                self.run('systemctl','stop',lease['watchdog_unit']+'.timer')
                state=dict(state,status='cleaning',phase='releasing',claim=cleared)
                self.write(folder/'state.json',state)
                dropin=self.dropins/lease['dropin_name']
                if dropin.exists():
                    if sha(dropin.read_bytes())!=lease['dropin_sha256']:raise ValueError('Boot guard changed before cleanup')
                    dropin.unlink();self.run('systemctl','daemon-reload')
                if any(v.get('table',{}).get('name')==proof['gate_table'] for v in self.rules().get('nftables',[])):
                    self.run('nft','delete','table','inet',proof['gate_table'])
                self.write(folder/'state.json',dict(state,status='released',claim=cleared,watchdog=watchdog))
                return dict(status='released',claim=cleared,database_restored=False,only_owned_gate_removed=True)
            except Exception as error:
                self.write(folder/'state.json',dict(state,status='attention',error_type=type(error).__name__))
                raise

    def remove_finished_qa_checkpoints(self,db,accounts):
        """After service stop, drop only paid, finished QA result-window metadata."""
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_checkpoints'").fetchone():return
        from tio.battle_snapshot import loads
        from tio.battle_checkpoints import delete
        for match,payload in db.execute('SELECT match_id,payload FROM battle_checkpoints').fetchall():
            data,_=loads(payload);battle=data['battle']
            names={data['sessions'][o]['account'] for o in data['retained']}
            if not battle['finished'] or not names or not names<=set(accounts):raise ValueError('Owned QA battle still unfinished after graceful stop')
            if any(not db.execute('SELECT 1 FROM battle_rewards WHERE match_id=? AND account=?',(match,a)).fetchone() for a in names):
                raise ValueError('Owned QA result lacks its committed receipt')
            delete(db,match)


def verify_gate(proof):
    if str(CODE_ROOT) not in sys.path:sys.path.insert(0,str(CODE_ROOT))
    lease,_,state=Maintenance().load(proof)
    if state['status']!='isolated':raise ValueError('QA fixture changes require an isolated active lease')
    return dict(status='isolated',lease_id=lease['lease_id'],accounts=lease['accounts'],deadline_utc=lease['deadline_utc'])


def claim_for_qa(proof,clan_id,tax_percent=10):
    if str(CODE_ROOT) not in sys.path:sys.path.insert(0,str(CODE_ROOT))
    return Maintenance().claim(proof,clan_id,tax_percent)
def finish_maintenance(proof,watchdog=False):
    if str(CODE_ROOT) not in sys.path:sys.path.insert(0,str(CODE_ROOT))
    return Maintenance().finish(proof,watchdog=watchdog)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('action',choices=('activate','verify','finish','watchdog','boot-check'))
    p.add_argument('--accounts',nargs=3);p.add_argument('--local-login-port',type=int);p.add_argument('--local-session-port',type=int)
    p.add_argument('--proof',type=Path);p.add_argument('--lease',type=Path)
    args=p.parse_args(argv)
    if os.name!='posix' or os.geteuid()!=0:p.error('Maintenance actions run as the authorized Linux host operator')
    sys.path.insert(0,str(CODE_ROOT));m=Maintenance()
    if args.action=='activate':
        if args.accounts is None or args.local_login_port is None or args.local_session_port is None:p.error('Activation requires the exact fresh accounts and local forward ports')
        result=m.activate(args.accounts,args.local_login_port,args.local_session_port)
    else:
        proof=json.loads(args.proof.read_text()) if args.proof else m.proof(m.private_file(args.lease).parent) if args.lease else None
        if proof is None:p.error('Specify --proof or this lease\'s --lease')
        if args.action=='verify':result=verify_gate(proof)
        elif args.action in ('finish','watchdog'):result=m.finish(proof,watchdog=args.action=='watchdog')
        else:
            state=m.state(Path(proof['lease_path']).parent)
            m.load(proof,expired=state['status']=='cleaning')
            return 0
    print(canonical(result));return 0


if __name__=='__main__':raise SystemExit(main())
