"""Strict owned-copy sync and attach-only adapter for launcher 0.1.4.

No startup on import or in check-only. Attach never starts an alternate socket,
modifies auth results, injects packets or edits configuration. The original
native credential adapter is explicitly not proof of the graphical login UI.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import queue
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import hosted_graphical_qa_bridge as original
from tools import hosted_tls_graphical_qa as tls_original
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA,OWNERSHIP
from deploy import client_battle_items as nvg

FOLDER=ROOT/'reports/gameplay-followup/stage1-interfaces/graphical-adapter'
QA_BASE=ROOT/'reports/arena-surroundings-implementation/client-qa'
SOURCE=FOLDER/'source'
FIXTURE=Path(r'C:\Users\jundu\AppData\Local\TIO-emulator\stage7-qa\qsfc5dfe28.json')
MARKER='.tio-owned-qa'
CREATOR='tools/prepare_hosted_graphical_qa.py'
ORIGIN='https://185.184.42.88/updates/'
MANIFEST5_SHA='e13099fab0a9683f16a93b01924993418db245b6a3ef36772c270e0d689bffaf'
CANDIDATE_SHA='c712f60caf98356f5958ee7df0710c126df5a266c9f41319074771f419c88664'
CANDIDATE=ROOT/'reports/gameplay-followup/stage1-interfaces/nvg/candidate/silver.dll'
LAUNCHER=SOURCE/'TIO-Launcher-0.1.4.exe'
LAUNCHER_SHA='61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f'
LAUNCHER_BYTES=118679712
BRIDGE_PY_SHA='18039c85532ef2a03442a842a71dc72d481fea2ef0775c8c3e02ab85f36188a5'
BRIDGE_JS_SHA='3582f954569f623faa4573c7ce557fd5dbfdee920cb29e8911dc5c22d4e45fd5'
TLS_PY_SHA='45c174cac7de68070d3cede98ecbe4e1e179cfdfa34595202305c5ca60699399'
BINARIES={'ti.exe','orange.dll','silver.dll','gold.dll','ode.dll','d3dx9_26.dll'}
CONFIGS={'base/autoexec.cfg','base/config.cfg'}


def require(value,message):
    if not value:raise ValueError(message)


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def dependency_guards():
    for name,expected in (('hosted_graphical_qa_bridge.py',BRIDGE_PY_SHA),
                          ('hosted_graphical_qa_bridge.js',BRIDGE_JS_SHA),
                          ('hosted_tls_graphical_qa.py',TLS_PY_SHA)):
        require(digest(ROOT/'tools'/name)==expected,'Established graphical bridge source changed')


def safe_path(root,relative):
    root=Path(root).absolute();p=PurePosixPath(relative)
    require(not p.is_absolute() and p.parts and relative==p.as_posix(),'Invalid relative path')
    for part in p.parts:
        require(re.fullmatch(r'[A-Za-z0-9_ .()\-]+',part) and part not in ('.','..')
                and not part.endswith(('.',' ')) and not re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',part,re.I),
                'Unsafe client path')
    target=root.joinpath(*p.parts)
    require(target.resolve().is_relative_to(root.resolve()),'Client path escaped owned copy')
    current=target
    while True:
        require(not current.is_symlink() and not (hasattr(current,'is_junction') and current.is_junction()),
                'Client path contains a filesystem link')
        if current==root:break
        current=current.parent
        require(current.parent!=current or current==root,'Client path is outside owned copy')
    # Also forbid linked ancestors of the root itself.
    for parent in root.parents:
        require(not parent.is_symlink() and not (hasattr(parent,'is_junction') and parent.is_junction()),
                'Owned copy ancestor contains a filesystem link')
    return target


def own_copy(root):
    root=Path(root).absolute()
    require(root in tuple((QA_BASE/('game-'+c)).absolute() for c in ('a','b')),
            'Only the two specified owned game-a/game-b directories are accepted')
    marker=safe_path(root,MARKER)
    require(root.is_dir() and marker.is_file(),'Existing dedicated ownership marker is required')
    require(marker.stat().st_size<=4096,'Invalid ownership marker size')
    value=json.loads(marker.read_text(encoding='utf-8'))
    require(value==dict(schema=1,creator=CREATOR,root=str(root)),'Ownership marker differs')
    for relative in ('login.ini','base/login.ini'):
        require(not safe_path(root,relative).exists(),'Inherited login.ini is forbidden')
    return root


def native_guards(root,*,allow_legacy=False):
    """Keep all original full-span and relocation-aware live entry guards."""
    import pefile
    dependency_guards();root=own_copy(root)
    for name in ('ti.exe','orange.dll'):
        require(digest(safe_path(root,name))==original.HASHES[name],'Unsupported native module')
    data=safe_path(root,'silver.dll').read_bytes();sha=hashlib.sha256(data).hexdigest()
    if sha==nvg.NVG_BASE_SHA:require(len(data)==nvg.NVG_BASE_BYTES,'Published DLL size differs')
    elif sha==CANDIDATE_SHA:
        require(len(data)==7765504 and nvg.patch_nvg(data)==data,'F9 candidate restoration proof failed')
    elif allow_legacy:original.validate_native_binary('silver.dll',data)
    else:raise ValueError('Only exact published .5 or reviewed F9 .6 DLL is accepted')
    for name in ('autoexec.cfg','config.cfg'):
        text=safe_path(root,'base/'+name).read_text(encoding='cp1251')
        addresses=re.findall(r'^\s*orange_addr\s+(\S+)',text,re.M);ports=re.findall(r'^\s*orange_port\s+(\S+)',text,re.M)
        require(addresses and set(addresses)=={'185.184.42.88'} and ports and set(ports)=={'28512'},
                'Seed config must keep the owned hosted endpoint')
    pe=pefile.PE(data=data);rows=[]
    try:
        for name,va,size,expected in original.SPANS:
            span=pe.get_data(va-0x400000,size)
            require(len(span)==size and hashlib.sha256(span).hexdigest()==expected,'Native full function span changed')
            relocations=[]
            for block in getattr(pe,'DIRECTORY_ENTRY_BASERELOC',()):
                for entry in block.entries:
                    offset=entry.rva-(va-0x400000)
                    if 0<=offset<12:
                        require(entry.type==3 and offset+4<=12,'Unsupported native entry relocation')
                        relocations.append(offset)
            rows.append(dict(name=name,va=va,entry12=span[:12].hex(),entry_relocations=relocations))
    finally:pe.close()
    return rows


def private_fixture(path=FIXTURE):
    path=Path(path).absolute()
    require(path==FIXTURE.absolute() and not path.is_symlink(),'Only the retained private stage7 fixture is accepted')
    require(path.is_file() and path.stat().st_size<=16384,'Private fixture is unavailable')
    value=json.loads(path.read_text(encoding='utf-8'))
    require(set(value)=={'version','host','prefix','names','passwords','backup','key'} and value['version']==1,
            'Unsupported private fixture structure')
    require(value['host']=='185.184.42.88' and re.fullmatch(r'qs[0-9a-f]{8}',value['prefix']),
            'Unexpected private fixture target')
    require(value['names']==[value['prefix']+'a',value['prefix']+'b'] and len(value['passwords'])==2,
            'Private fixture must contain the retained owned pair')
    require(all(isinstance(p,str) and re.fullmatch(r'[!-~]{12,64}',p) for p in value['passwords']),
            'Unsupported private fixture password format')
    require(re.fullmatch(r'/root/tio-before-surroundings-qa-[A-Za-z0-9_-]+',value['backup']) and
            Path(value['key']).absolute()==Path(r'C:\Users\jundu\.ssh\tio_server').absolute(),
            'Private fixture ownership provenance differs')
    return FreshSurroundingsQA(**{k:v for k,v in value.items() if k!='version'},credential_path=str(path))


def https(url,limit):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.load_default_certs()
    require(context.keylog_filename is None,'TLS key logging must stay disabled')
    request=urllib.request.Request(url,headers={'User-Agent':'Tionline-Stage9-Owned-GUI-QA/1.0','Cache-Control':'no-cache'})
    with urllib.request.urlopen(request,context=context,timeout=30) as response:
        require(response.geturl()==url,'Unexpected public download redirect')
        data=response.read(limit+1)
    require(len(data)<=limit,'Public resource exceeds its size limit')
    return data


def validate_manifest(raw):
    require(len(raw)<=8*1024*1024,'Manifest exceeds its size limit')
    value=json.loads(raw)
    baseline=(SOURCE/'manifest-2026.10.08.5.json').read_bytes()
    require(hashlib.sha256(baseline).hexdigest()==MANIFEST5_SHA,'Pinned public .5 manifest changed')
    expected=json.loads(baseline)
    if value.get('version')=='2026.10.08.6':
        expected['version']='2026.10.08.6'
        row=next(r for r in expected['files'] if r['path']=='silver.dll')
        row.update(sha256=CANDIDATE_SHA,size=7765504)
    require(json.dumps(value,sort_keys=True,separators=(',',':'))==json.dumps(expected,sort_keys=True,separators=(',',':')),
            'Manifest differs from exact public .5 or reviewed one-DLL .6 release')
    require(type(value['schema']) is int and value['schema']==1 and len(value['files'])==6330,'Unexpected public manifest schema/count')
    seen=set()
    for row in value['files']:
        relative=row['path'];p=PurePosixPath(relative)
        require(relative.lower() not in seen,'Duplicate public resource')
        require(relative.lower() in BINARIES or len(p.parts)>1 and p.parts[0]=='base','Unexpected public root')
        safe_path(SOURCE/'path-validation',relative)
        require(p.name.lower() not in ('login.ini','skillbar.dat','log.txt','log_old.txt') and not p.name.lower().startswith('notes-'),
                'Manifest contains private player data')
        seed=row.get('seed',False)
        require(type(seed) is bool and seed==(relative.lower() in CONFIGS),'Seed policy differs')
        require(type(row['size']) is int and 0<=row['size']<=512*1024*1024 and re.fullmatch('[a-f0-9]{64}',row['sha256']),
                'Invalid public resource size/hash')
        seen.add(relative.lower())
    return value


def matches(path,row):
    return path.is_file() and path.stat().st_size==row['size'] and digest(path)==row['sha256']


def no_running_copy(root):
    code="@(Get-Process ti -ErrorAction SilentlyContinue | Select-Object Id,Path) | ConvertTo-Json -Compress"
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],capture_output=True,text=True,timeout=15)
    require(result.returncode==0,'Cannot verify owned client is stopped')
    rows=json.loads(result.stdout or '[]');rows=rows if isinstance(rows,list) else [rows]
    require(not any(row.get('Path') and Path(row['Path']).absolute()==(root/'ti.exe').absolute() for row in rows),
            'Refuse to synchronize a running owned game copy')


def atomic_write(target,data):
    target.parent.mkdir(parents=True,exist_ok=True)
    handle,name=tempfile.mkstemp(prefix='.stage9-',dir=target.parent);temporary=Path(name)
    try:
        with os.fdopen(handle,'wb') as stream:stream.write(data)
        os.replace(temporary,target)
    finally:
        if temporary.exists():temporary.unlink()


def synchronize(copies,profile,*,check_only=True):
    require(profile in ('published5','candidate6'),'Invalid client profile')
    require(copies and len(set(copies))==len(copies) and set(copies)<={'a','b'},'Invalid owned copy selection')
    roots=[own_copy(QA_BASE/('game-'+copy)) for copy in copies]
    # Authenticate the current base before downloading or staging any updates.
    for root in roots:native_guards(root,allow_legacy=True)
    raw=https(ORIGIN+'manifest.json',8*1024*1024);manifest=validate_manifest(raw)
    candidate_data=CANDIDATE.read_bytes() if profile=='candidate6' else None
    if candidate_data is not None:
        require(hashlib.sha256(candidate_data).hexdigest()==CANDIDATE_SHA and nvg.patch_nvg(candidate_data)==candidate_data,
                'Reviewed F9 candidate changed')
    require(profile!='published5' or manifest['version']=='2026.10.08.5','Public manifest already moved to .6; select candidate6')
    plans=[];seeds={};verified={}
    for root in roots:
        seeds[str(root)]={r:digest(safe_path(root,r)) for r in CONFIGS}
        changes=[]
        for row in manifest['files']:
            target=safe_path(root,row['path'])
            if row.get('seed',False):continue
            effective=dict(row)
            if candidate_data is not None and row['path']=='silver.dll':effective.update(sha256=CANDIDATE_SHA,size=len(candidate_data))
            if matches(target,effective):verified[effective['sha256']]=target
            else:changes.append(effective)
        plans.append((root,changes))
    result=dict(check_only=check_only,profile=profile,public_version=manifest['version'],manifest_files=6330,
                manifest_sha256=hashlib.sha256(raw).hexdigest(),copies=[dict(copy=r.name,changed_paths=[row['path'] for row in rows]) for r,rows in plans],
                seed_configurations_preserved=True,personal_files_copied=0,graphical_clients_started=0,remote_mutations=0,credentials_printed=False)
    if check_only:return result
    for root in roots:no_running_copy(root)
    backup=FOLDER/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    for root,changes in plans:
        for row in changes:
            target=safe_path(root,row['path'])
            if target.exists():
                saved=safe_path(backup/root.name,row['path']);saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(target,saved)
            if row['path']=='silver.dll' and candidate_data is not None:data=candidate_data
            elif row['sha256'] in verified:data=verified[row['sha256']].read_bytes()
            else:data=https(ORIGIN+'blobs/'+row['sha256'],row['size'])
            require(len(data)==row['size'] and hashlib.sha256(data).hexdigest()==row['sha256'],'Public blob or owned source differs')
            # Atomic pathname replacement also avoids modifying a hardlinked asset.
            atomic_write(target,data);verified[row['sha256']]=target
        require(all(digest(safe_path(root,r))==h for r,h in seeds[str(root)].items()),'Seed configuration changed')
        native_guards(root)
        for row in manifest['files']:
            if row.get('seed',False):continue
            expected=dict(row)
            if candidate_data is not None and row['path']=='silver.dll':expected.update(sha256=CANDIDATE_SHA,size=len(candidate_data))
            require(matches(safe_path(root,row['path']),expected),'Final owned resource verification failed')
    result['backup']=str(backup);return result


def launcher_guard(path=LAUNCHER):
    path=Path(path).absolute()
    require(path==LAUNCHER.absolute() and not path.is_symlink(),'Only the verified report-source launcher is accepted')
    require(safe_path(FOLDER,'source/TIO-Launcher-0.1.4.exe')==path,'Launcher source escaped adapter')
    require(path.is_file() and path.stat().st_size==LAUNCHER_BYTES and digest(path)==LAUNCHER_SHA,'Published launcher 0.1.4 pin differs')
    return path


def readiness(path,root,launcher):
    root=own_copy(root);launcher=launcher_guard(launcher);path=Path(path).absolute()
    allowed=FOLDER/'readiness'
    require(path.is_relative_to(allowed.absolute()) and not path.is_symlink(),'Readiness file must belong to stage9 adapter')
    path=safe_path(allowed,path.relative_to(allowed.absolute()).as_posix())
    require(path.stat().st_size<=4096,'Readiness file exceeds its limit')
    value=json.loads(path.read_text(encoding='utf-8'))
    require(set(value)<={'Pid','BridgePid','LoginPort','SessionPort','EndpointCertificatesValidated','Error'} and
            value.get('Error') is None and value.get('EndpointCertificatesValidated') is True,'Certificate preflight is unconfirmed')
    require(all(type(value.get(k)) is int for k in ('Pid','BridgePid','LoginPort','SessionPort')),'Invalid readiness integers')
    require(value['Pid']>0 and value['BridgePid']>0 and value['Pid']!=value['BridgePid'],'Invalid owned PIDs')
    require(all(1024<=value[k]<=65535 for k in ('LoginPort','SessionPort')) and value['LoginPort']!=value['SessionPort'],
            'Invalid owned listener ports')
    code=(f"$gameInfo=Get-Process -Id {value['Pid']} -ErrorAction Stop; "
          f"$bridgeInfo=Get-Process -Id {value['BridgePid']} -ErrorAction Stop; "
          f"$listeners=Get-NetTCPConnection -State Listen -LocalPort {value['LoginPort']},{value['SessionPort']} -ErrorAction Stop; "
          "[pscustomobject]@{Game=$gameInfo.Path;Bridge=$bridgeInfo.Path;Listeners=@($listeners | Select-Object LocalAddress,LocalPort,OwningProcess)} | ConvertTo-Json -Depth 5 -Compress")
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],capture_output=True,text=True,timeout=20)
    require(result.returncode==0,'Cannot verify live owned TLS bridge')
    actual=json.loads(result.stdout)
    require(Path(actual['Game']).absolute()==(root/'ti.exe').absolute() and Path(actual['Bridge']).absolute()==launcher,
            'Readiness PID belongs to another executable')
    listeners=actual['Listeners']
    require(len(listeners)==2 and {r['LocalPort'] for r in listeners}=={value['LoginPort'],value['SessionPort']} and
            all(r['LocalAddress']=='127.0.0.1' and r['OwningProcess']==value['BridgePid'] for r in listeners),'Listener ownership differs')
    return value


def native_source(login_port,session_port):
    dependency_guards()
    require(type(login_port) is int and type(session_port) is int and 1024<=login_port<=65535 and
            1024<=session_port<=65535 and login_port!=session_port,'Invalid native TLS route ports')
    source=tls_original.native_source(login_port,session_port)
    before='0x8b,0x44,0x24,0x18,0x83,0xf8,0,0xb8'
    require(source.count(before)==1,'Established 40-byte route guard changed')
    # The sole guard amendment is the official .014 CMP AL,0 byte-width fix.
    return source.replace(before,'0x8b,0x44,0x24,0x18,0x80,0xf8,0,0xb8')


def redact(value,fixture):
    secrets=tuple(fixture.names)+tuple(fixture.passwords)
    if isinstance(value,dict):return {k:redact(v,fixture) for k,v in value.items() if k.lower() not in ('login','password','username','credentials')}
    if isinstance(value,list):return [redact(v,fixture) for v in value]
    if isinstance(value,str) and any(secret in value for secret in secrets):return '<redacted>'
    return value


class Attached(original.HostedGraphicalQaBridge):
    """Attach only; use original callbacks and exact production TLS route."""
    def __init__(self,root,credentials,ready,*,on_event=None,auto_select=False):
        import frida
        self.root=own_copy(root);guards=native_guards(self.root)
        require(credentials.get('fresh_qa') is True and re.fullmatch(r'qs[a-f0-9]{8}[ab]',credentials.get('login','')),
                'Only retained owned fixture credentials are accepted')
        require(re.fullmatch('[!-~]{12,64}',credentials.get('password','')),'Invalid private QA credential format')
        self.pid,self.bridge_pid=ready['Pid'],ready['BridgePid'];self.events=[];self._runtime_errors=[]
        self._on_event,self.window_script,self.closed=on_event,None,False
        self.device=frida.get_local_device();self.session=self.device.attach(self.pid)
        self.script=self.session.create_script(native_source(ready['LoginPort'],ready['SessionPort']))
        def receive(message,data):
            if message.get('type')!='send':
                self._runtime_errors.append(message.get('type','unknown'))
                self._record(dict(event='bridge_runtime_error',type=message.get('type','unknown')));return
            payload=message.get('payload')
            if isinstance(payload,dict):self._record(payload)
        try:
            self.script.on('message',receive);self.script.load()
            self.script.exports_sync.initialize(dict(executable=str(self.root/'ti.exe'),silver_path=str(self.root/'silver.dll'),
                entry_guards=guards,login=credentials['login'],password=credentials['password'],auto_select=auto_select,
                loopback_login_port=ready['LoginPort'],loopback_session_port=ready['SessionPort']))
            from tools.window_compat import install
            self.window_script=install(self.session,receive)
        except BaseException:
            self.closed=True
            try:self.session.detach()
            except Exception:pass
            raise
        self._record(dict(event='owned_tls_client_attached',pid=self.pid,bridge_pid=self.bridge_pid,
                          auth_button_graphically_tested=False))


def observe(args):
    fixture=private_fixture(args.fixture);ready={}
    for copy in args.copies:
        root=own_copy(QA_BASE/('game-'+copy));native_guards(root)
        path=getattr(args,'status_'+copy)
        require(path is not None,'Each selected copy requires its own readiness file')
        ready[copy]=readiness(path,root,args.launcher)
    require(len({v['Pid'] for v in ready.values()})==len(ready) and len({v['BridgePid'] for v in ready.values()})==len(ready),
            'Owned clients and bridges must be independent processes')
    if args.check_only:return dict(check_only=True,own_clients_verified=len(ready),credentials_printed=False,attached=0)
    # Read-only salted credential/backup proof before any private heap allocation.
    require(fixture.remote(OWNERSHIP+'\nprint(json.dumps(dict(owned=True)))',fixture.ownership_payload())=={'owned':True},
            'Retained hosted QA ownership is unconfirmed')
    run=FOLDER/'runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');run.mkdir(parents=True)
    events=run/'events.jsonl';controls=run/'controls.jsonl';controls.write_text('',encoding='utf-8')
    attached={};commands=queue.Queue();offset=0
    def record(value):
        value=redact(dict(utc=datetime.now(timezone.utc).isoformat(),**value),fixture)
        with events.open('a',encoding='utf-8') as stream:stream.write(json.dumps(value,ensure_ascii=True)+'\n')
        print(json.dumps(value,ensure_ascii=True),flush=True)
    def reader():
        for line in sys.stdin:
            try:commands.put(json.loads(line))
            except Exception:commands.put({'action':'invalid'})
    threading.Thread(target=reader,daemon=True).start()
    try:
        for copy,value in ready.items():
            index=ord(copy)-ord('a')
            credentials=dict(login=fixture.names[index],password=fixture.passwords[index],fresh_qa=True)
            attached[copy]=Attached(QA_BASE/('game-'+copy),credentials,value,auto_select=args.auto_select,
                on_event=lambda event,copy=copy:record(dict(copy=copy,**event)))
            credentials.clear()
        record(dict(event='ready_for_graphical_acceptance',control_file=str(controls),run_dir=str(run),
                    native_clients=len(attached),authentication_ui_tested=False,graphical_acceptance_complete=False))
        until=time.monotonic()+args.seconds
        while time.monotonic()<until:
            with controls.open(encoding='utf-8') as stream:
                stream.seek(offset)
                while True:
                    line=stream.readline()
                    if not line or not line.endswith('\n'):break
                    try:commands.put(json.loads(line))
                    except Exception:commands.put({'action':'invalid'})
                    offset=stream.tell()
            try:command=commands.get(timeout=.25)
            except queue.Empty:continue
            if not isinstance(command,dict) or set(command)-{'action','copy','label'}:
                record(dict(event='invalid_control'));continue
            action=command.get('action');copy=command.get('copy','a')
            if action=='release':break
            if copy not in attached:record(dict(event='invalid_copy'));continue
            client=attached[copy]
            if action=='close-client':client.release(cleanup=True);del attached[copy];record(dict(event='own_client_closed',copy=copy))
            elif action in ('connect','connect-progress'):
                result=client.start_connect_with_progress() if action=='connect-progress' else client.start_connect()
                record(dict(event='connect_returned',copy=copy,result=result))
            elif action=='selectserver':record(dict(event='selection_returned',copy=copy,result=client.select_server()))
            elif action=='status':record(dict(event='status',copy=copy,state=client.status()))
            elif action=='mark':
                label=command.get('label','');require(re.fullmatch('[a-z0-9-]{1,64}',label),'Invalid public visual label')
                record(dict(event='visual_stage',copy=copy,label=label))
            else:record(dict(event='invalid_control'))
    finally:
        for client in attached.values():client.release(cleanup=args.cleanup)
        record(dict(event='adapter_released',own_clients_terminated=args.cleanup,
                    hosted_checkpoints_modified=False,graphical_acceptance_complete=False))
    return dict(run_dir=str(run),graphical_acceptance_complete=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    check=sub.add_parser('check');check.add_argument('--copies',nargs='+',choices=('a','b'),default=['a','b'])
    check.add_argument('--fixture',type=Path,default=FIXTURE);check.add_argument('--allow-legacy-before-sync',action='store_true')
    sync=sub.add_parser('sync');sync.add_argument('--copies',nargs='+',choices=('a','b'),default=['a','b'])
    sync.add_argument('--profile',choices=('published5','candidate6'),default='published5');sync.add_argument('--check-only',action='store_true')
    attach=sub.add_parser('attach');attach.add_argument('--copies',nargs='+',choices=('a','b'),default=['a','b'])
    attach.add_argument('--fixture',type=Path,default=FIXTURE);attach.add_argument('--launcher',type=Path,default=LAUNCHER)
    attach.add_argument('--status-a',type=Path);attach.add_argument('--status-b',type=Path)
    attach.add_argument('--check-only',action='store_true');attach.add_argument('--auto-select',action='store_true')
    attach.add_argument('--seconds',type=int,default=1800);attach.add_argument('--cleanup',action='store_true')
    args=parser.parse_args(argv)
    require(len(set(args.copies))==len(args.copies),'Duplicate copy selection')
    if args.action=='check':
        private_fixture(args.fixture)
        result=dict(check_only=True,copies=[dict(copy=c,full_native_functions=len(native_guards(QA_BASE/('game-'+c),
                    allow_legacy=args.allow_legacy_before_sync))) for c in args.copies],credentials_printed=False,
                    graphical_clients_started=0,sockets_opened=0)
    elif args.action=='sync':result=synchronize(args.copies,args.profile,check_only=args.check_only)
    else:
        require(1<=args.seconds<=7200,'Observation interval must be 1..7200 seconds');result=observe(args)
    print(json.dumps(result,ensure_ascii=True));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        # Exception text/Frida arguments can contain private credential values.
        print(json.dumps(dict(event='stage9_graphical_adapter_failed',error_type=type(error).__name__)),file=sys.stderr)
        raise SystemExit(1)
