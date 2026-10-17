"""Build an owned public-only client and read the hidden launcher probe.

No authentication, account data, UI automation, native calls or memory writes.
The original launcher performs its own hidden loader probe and automatically
terminates its own game. Observation uses query/read-only Windows handles.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path,PurePosixPath
import shutil
import struct
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_texture_quality as q
from tools.inspect_native_tls_route import api,modules,ProcessEntry,Region,stamp

FOLDER=ROOT/'reports/gameplay-completion/legacy-lobbies-20261011/textures/runtime-qa-revision2'
ORIGIN='https://185.184.42.88/updates/'
LAUNCHER=ROOT/'reports/launcher-self-update/revision2/release/TIO Launcher.exe'
LAUNCHER_SHA='d135224ae3803dfcaaaa3602cc2a1cfabe042a03a3c30238b81ddf4a1996dda8'
CANDIDATE=ROOT/'reports/gameplay-completion/legacy-lobbies-20261011/textures/candidate-final/silver.dll'
CANDIDATE_SHA='4897eb6d6af6beb587fc9b303dc6911519d90b3414ae8cca8fd1ffb698c1f082'
BASELINE=ROOT/'reports/gameplay-completion/legacy-lobbies-20261011/client/source/manifest.json'
SOURCES=[ROOT/'reports/new-player/client-a',ROOT/'reports/new-player/client-b',
         ROOT/'reports/global-map-integration-20261010/client/candidate',
         ROOT/'reports/battle-icon-centering-20261010/client/assets',
         ROOT/'reports/arena-surroundings-implementation/client-qa/game-a',
         ROOT/'reports/arena-surroundings-implementation/client-qa/game-b']


def require(ok,message):
    if not ok:raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def fetch(url):
    with urllib.request.urlopen(url,timeout=45) as response:return response.read()


def prepare():
    require(not FOLDER.exists(),'Preserve prior runtime evidence; use the already prepared owned root')
    manifest_raw=fetch(ORIGIN+'manifest.json');manifest=json.loads(manifest_raw)
    original=json.loads(BASELINE.read_text(encoding='utf-8'))
    known={r['path']:r for r in original['files']}
    current={r['path']:r for r in manifest['files']}
    require(len(current)==len(known)==6567,'Public file inventory changed')
    require({n:r for n,r in current.items() if n!='silver.dll'}=={n:r for n,r in known.items() if n!='silver.dll'},'Public release differs outside the reviewed Silver candidate')
    require(current['silver.dll']['sha256'] in (q.BASE_SHA,CANDIDATE_SHA),'Public Silver identity changed')
    require(LAUNCHER.stat().st_size==118745248 and digest(LAUNCHER)==LAUNCHER_SHA,'Launcher 0.1.6 identity differs')
    require(digest(CANDIDATE)==CANDIDATE_SHA,'Final candidate identity differs')
    FOLDER.mkdir(parents=True);game=FOLDER/'client';game.mkdir()
    (FOLDER/'public-manifest.json').write_bytes(manifest_raw)
    def one(record):
        relative=record['path'];parts=PurePosixPath(relative).parts
        require(parts and not PurePosixPath(relative).is_absolute() and '..' not in parts,'Unsafe public client path')
        lower=parts[-1].lower()
        require(lower not in ('login.ini','skillbar.dat') and not lower.startswith('notes-') and Path(lower).suffix not in ('.log','.bak','.dmp'),'Personal data in public manifest refused')
        # The fresh root is exclusively created above and never populated from
        # directory trees. Validate the lexical path before parallel mkdir;
        # resolving a not-yet-existing path concurrently is unreliable on NT.
        target=game.joinpath(*parts);require(target.is_relative_to(game),'Owned client target escaped')
        target.parent.mkdir(parents=True,exist_ok=True)
        if relative=='silver.dll':shutil.copyfile(CANDIDATE,target);return 'reviewed_candidate'
        # Configuration/autoexec always come from the public clean seed blobs.
        if not record.get('seed',False):
            for source in SOURCES:
                existing=source.joinpath(*parts)
                if existing.is_file() and existing.stat().st_size==record['size'] and digest(existing)==record['sha256']:
                    shutil.copyfile(existing,target);return 'verified_public_cache'
        raw=fetch(ORIGIN+'blobs/'+record['sha256'])
        require(len(raw)==record['size'] and q.sha(raw)==record['sha256'],'Public immutable blob failed integrity: '+relative)
        target.write_bytes(raw);return 'https_public_seed' if record.get('seed',False) else 'https_immutable_blob'
    with ThreadPoolExecutor(max_workers=8) as pool:origins=list(pool.map(one,manifest['files']))
    for relative,record in current.items():
        expected=CANDIDATE_SHA if relative=='silver.dll' else record['sha256']
        require(digest(game/relative)==expected,'Prepared client integrity differs: '+relative)
    marker=dict(schema=1,creator='tools/verify_texture_quality_runtime.py',root=str(game),utc=datetime.now(timezone.utc).isoformat(),candidate_sha256=CANDIDATE_SHA)
    (game/'.tio-owned-qa').write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8')
    require(not (game/'login.ini').exists() and not (game/'base/login.ini').exists(),'Personal login copied')
    proof=dict(passed=True,manifest_sha256=q.sha(manifest_raw),public_version=manifest['version'],records=len(current),candidate_sha256=CANDIDATE_SHA,
               origins={origin:origins.count(origin) for origin in sorted(set(origins))},player_files_copied=0,public_seeds_fresh=True,
               launcher_sha256=LAUNCHER_SHA,launcher_bytes=118745248,client_root=str(game))
    (FOLDER/'preparation.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof),flush=True)
    return game


def children(k,parent):
    k.Process32FirstW.argtypes=k.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)]
    snap=k.CreateToolhelp32Snapshot(2,0)
    require(snap not in (None,ctypes.c_void_p(-1).value),'Process metadata snapshot failed')
    found=[]
    try:
        row=ProcessEntry();row.size=ctypes.sizeof(row)
        if k.Process32FirstW(snap,ctypes.byref(row)):
            while True:
                if row.parent==parent and row.name.lower()=='ti.exe':found.append(row.pid)
                if not k.Process32NextW(snap,ctypes.byref(row)):break
    finally:k.CloseHandle(snap)
    return found


def observe(k,pid,game):
    handle=k.OpenProcess(0x1010,False,pid)
    require(handle,'Cannot open own hidden game read-only')
    try:
        k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        path=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(path))
        require(k.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(length)),'Cannot query own hidden game path')
        require(Path(path.value).resolve()==(game/'ti.exe').resolve(),'Child PID belongs to another client')
        mapped=modules(k,pid)
        if 'silver.dll' not in mapped:return None
        silver=mapped['silver.dll'];require(silver['path']==(game/'silver.dll').resolve(),'Silver mapping belongs to another client')
        require(silver['image_size']==q.REGION+q.SIZE,'Mapped Silver image size differs')
        def read(at,count):
            raw=ctypes.create_string_buffer(count);got=ctypes.c_size_t()
            require(k.ReadProcessMemory(handle,at,raw,count,ctypes.byref(got)) and got.value==count,'Read-only texture runtime observation failed')
            return raw.raw
        base=silver['base'];state,error,original_protection=struct.unpack('<III',read(base+q.STATE,12))
        signature=read(base+q.SIGNATURE_RVA,len(q.SIGNATURE));require(signature==q.SIGNATURE,'Mapped texture runtime signature differs')
        hooks=[]
        for address,wrapper,_ in q.SETTERS:
            raw=read(address,6)
            target=address+5+struct.unpack_from('<i',raw,1)[0] if raw[0]==0xe9 else None
            hooks.append(dict(address=hex(address),bytes=raw.hex(),target=hex(target) if target else None,
                              expected=hex(base+wrapper-q.IMAGE_BASE),matches=target==base+wrapper-q.IMAGE_BASE and raw[5]==0x90))
        region=Region();require(k.VirtualQueryEx(handle,q.PAGE,ctypes.byref(region),ctypes.sizeof(region))==ctypes.sizeof(region),'Page protection observation failed')
        return dict(pid=pid,creation_time_windows=stamp(k,handle),silver_base=hex(base),mapped_image_size=hex(silver['image_size']),state=state,error=error,
                    original_protection=hex(original_protection),current_page_protection=hex(region.protect),protection_restored=region.protect==original_protection,
                    hooks=hooks,read_only_rights='0x1010',credentials_read=False,memory_written=False)
    finally:k.CloseHandle(handle)


def active_children(k,parent):
    result=[]
    for pid in children(k,parent):
        handle=k.OpenProcess(0x1000,False,pid)
        if not handle:continue
        try:
            status=wintypes.DWORD()
            if k.GetExitCodeProcess(handle,ctypes.byref(status)) and status.value==259:result.append(pid)
        finally:k.CloseHandle(handle)
    return result


def run(game,*,suffix=''):
    require(digest(game/'silver.dll')==CANDIDATE_SHA,'Owned candidate changed before launch')
    probe_path=FOLDER/(suffix+'launcher-probe.json')
    result_path=FOLDER/(suffix+'native-runtime-proof.json')
    require(not probe_path.exists() and not result_path.exists(),'Preserve preceding probe results')
    k=api();samples=[];errors=[];owned_pids=set()
    # The launcher CLI itself uses STARTUPINFO SW_HIDE and auto-terminates its
    # exclusively owned game in its finally block. No UI helper is involved.
    process=subprocess.Popen([str(LAUNCHER),'--tls-native-probe',str(game),str(probe_path)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    started=time.monotonic()
    while process.poll() is None and time.monotonic()-started<45:
        for pid in children(k,process.pid):
            owned_pids.add(pid)
            try:
                sample=observe(k,pid,game)
                if sample and (not samples or sample['state']!=samples[-1]['state']):samples.append(sample)
            except (ValueError,OSError) as error:
                if str(error) not in errors:errors.append(str(error))
        time.sleep(0.025)
    if process.poll() is None:
        # Terminate only the launcher instance created above. Its own Job
        # Object closes the game and no unrelated process is targeted.
        process.terminate()
    stdout,stderr=process.communicate(timeout=10)
    launcher=json.loads(probe_path.read_text(encoding='utf-8')) if probe_path.exists() else None
    # Toolhelp can retain a just-terminated process entry while its final OS
    # cleanup is pending. Confirm running status and allow that bounded drain.
    cleanup_started=time.monotonic()
    surviving=active_children(k,process.pid)
    while surviving and time.monotonic()-cleanup_started<2:
        time.sleep(0.025)
        surviving=active_children(k,process.pid)
    success=[s for s in samples if s['state']==1 and s['error']==0 and s['protection_restored'] and all(h['matches'] for h in s['hooks'])]
    result=dict(passed=process.returncode==0 and bool(launcher and launcher.get('passed')) and bool(success) and not surviving,
                kind='Actual launcher 0.1.6 hidden owned native startup; read-only texture runtime inspection',
                candidate_sha256=CANDIDATE_SHA,launcher_sha256=LAUNCHER_SHA,launcher_pid=process.pid,owned_game_pids=sorted(owned_pids),
                launcher_exit_code=process.returncode,launcher_probe=launcher,samples=samples,observation_errors=errors,
                all_owned_games_automatically_closed=not surviving,remaining_owned_pids=surviving,
                stdout=stdout.decode('utf-8','replace'),stderr=stderr.decode('utf-8','replace'),
                auth_or_gameplay=False,desktop_automation=False,graphical_appearance_verified=False,player_data_used=False)
    result_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('passed','owned_game_pids','launcher_exit_code','all_owned_games_automatically_closed','observation_errors')}),flush=True)
    return result


if __name__=='__main__':
    game=prepare()
    if not run(game)['passed']:sys.exit(1)
