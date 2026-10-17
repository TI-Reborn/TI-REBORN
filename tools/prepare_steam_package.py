"""Build an isolated SteamPipe Windows package from the verified public client.

Only public manifest files enter the depot. Never copies player logins, server
databases, credentials or the repository. Does not log in or upload to Steam.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ORIGIN='https://185.184.42.88/updates/'
BINARIES={'ti.exe','silver.dll','orange.dll','gold.dll','ode.dll','d3dx9_26.dll'}
SEEDS={'base/config.cfg','base/autoexec.cfg'}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_manifest(manifest):
    if manifest.get('schema') != 1 or not isinstance(manifest.get('version'),str):
        raise ValueError('Invalid public manifest')
    files=manifest.get('files')
    if not isinstance(files,list) or not 1<=len(files)<=20000: raise ValueError('Invalid file count')
    seen=set()
    for record in files:
        name=record.get('path',''); parts=PurePosixPath(name).parts
        if (not name or name != PurePosixPath(name).as_posix() or PurePosixPath(name).is_absolute()
            or not parts or name.lower() in seen or not (name in BINARIES or len(parts)>1 and parts[0]=='base')):
            raise ValueError('Invalid depot path: '+name)
        if any(not re.fullmatch(r'[A-Za-z0-9_ .()\-]+',p) or p in ('.','..') or p.endswith(('.', ' '))
               or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',p,re.I) for p in parts):
            raise ValueError('Unsafe depot path')
        leaf=parts[-1].lower()
        if (leaf in {'login.ini','skillbar.dat','steam_appid.txt'} or leaf.startswith('notes-')
            or Path(leaf).suffix in {'.log','.bak','.dmp','.sqlite','.sqlite3','.db','.pdb'}):
            raise ValueError('Private or development data in manifest')
        if (type(record.get('size')) is not int or not 0<=record['size']<=512*1024*1024
            or not isinstance(record.get('sha256'),str) or not re.fullmatch('[0-9a-f]{64}',record['sha256'])
            or type(record.get('seed',False)) is not bool or record.get('seed',False)!=(name in SEEDS)):
            raise ValueError('Invalid file identity/seed policy')
        seen.add(name.lower())
    if not BINARIES|SEEDS <= seen: raise ValueError('Incomplete native client')
    return files


def safe_file(path):
    for component in (path,*path.parents):
        if component.is_symlink() or (hasattr(component,'is_junction') and component.is_junction()):
            raise ValueError('Linked package/cache/source path')
    return path


def stage_runtime_notices(content):
    assets=json.loads((ROOT/'launcher/obj/project.assets.json').read_text(encoding='utf-8'))
    downloads=assets['project']['frameworks']['net10.0-windows']['downloadDependencies']
    folders=[Path(p) for p in assets['packageFolders']]
    result=[]
    for package,notice_names in (
        ('Microsoft.NETCore.App.Runtime.win-x64',('LICENSE.TXT','THIRD-PARTY-NOTICES.TXT')),
        ('Microsoft.WindowsDesktop.App.Runtime.win-x64',('LICENSE',))):
        dependency=next(d for d in downloads if d['name']==package)
        version=dependency['version'].strip('[]').split(',')[0].strip()
        for name in notice_names:
            source=next((p/package.lower()/version/name for p in folders if (p/package.lower()/version/name).is_file()),None)
            if source is None: raise ValueError('Runtime redistribution notice missing')
            relative='Notices/'+package+'/'+name
            target=content/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            result.append(dict(path=relative,size=target.stat().st_size,sha256=sha(target),component_version=version))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=safe_file(args.output.absolute())
    if output.exists(): raise FileExistsError('Use a new output directory')
    cache=ROOT/'reports/steam-preparation'
    cache.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(ORIGIN+'manifest.json',timeout=30) as response: raw=response.read(8*1024*1024+1)
    if len(raw)>8*1024*1024: raise ValueError('Manifest size bound exceeded')
    manifest=json.loads(raw); files=validate_manifest(manifest)
    digest=hashlib.sha256(raw).hexdigest()
    manifest_path=cache/('manifest-'+digest+'.json')
    if manifest_path.exists() and manifest_path.read_bytes()!=raw: raise ValueError('Changed snapshot')
    manifest_path.write_bytes(raw)
    game=output/'content/Game';game.mkdir(parents=True)
    sources=[ROOT/'reports/english-localization/client-qa/game-a',ROOT/'assets/english-localization/runtime']
    blob_cache=cache/'public-blobs';blob_cache.mkdir(exist_ok=True)

    def stage(record):
        name=record['path'];checksum=record['sha256'];size=record['size']
        target=safe_file(game/name);target.parent.mkdir(parents=True,exist_ok=True)
        candidates=[] if name in SEEDS else [source/name for source in sources]
        candidates.append(blob_cache/checksum)
        source=None
        for candidate in candidates:
            safe_file(candidate)
            if candidate.is_file() and candidate.stat().st_size==size and sha(candidate)==checksum:
                source=candidate;break
        if source is None:
            source=blob_cache/checksum; pending=source.with_suffix('.part')
            with urllib.request.urlopen(ORIGIN+'blobs/'+checksum,timeout=90) as response,pending.open('wb') as stream:
                remaining=size
                while chunk:=response.read(1024*1024):
                    remaining-=len(chunk)
                    if remaining<0: raise ValueError('Oversized public blob')
                    stream.write(chunk)
            if remaining or sha(pending)!=checksum: raise ValueError('Public blob checksum failed')
            pending.replace(source)
        shutil.copyfile(source,target)
        if target.stat().st_size!=size or sha(target)!=checksum: raise ValueError('Staged content changed')
        return dict(path='Game/'+name,size=size,sha256=checksum)

    with ThreadPoolExecutor(max_workers=8) as pool: records=list(pool.map(stage,files))
    print('Verified and staged',len(records),'public client files',flush=True)
    publish=cache/('launcher-'+digest[:12]);publish.mkdir(exist_ok=False)
    subprocess.run(['dotnet','publish',str(ROOT/'launcher/TioLauncher.csproj'),'-c','Release','-r','win-x64',
                    '--self-contained','true','-p:PublishSingleFile=true','-p:SteamDistribution=true',
                    '-p:SteamManifestPath='+str(manifest_path),'-o',str(publish)],check=True)
    executable=publish/'TIO Steam.exe';shutil.copyfile(executable,output/'content/TIO Steam.exe')
    records.append(dict(path='TIO Steam.exe',size=executable.stat().st_size,sha256=sha(executable)))
    records.extend(stage_runtime_notices(output/'content'))
    shutil.copytree(ROOT/'steam/templates',output/'scripts')
    shutil.copytree(ROOT/'steam/docs',output/'docs')
    shutil.copyfile(manifest_path,output/'public-client-manifest.json')
    for name in ('configure.ps1','upload.ps1','verify-package.ps1'):
        shutil.copyfile(ROOT/'steam'/name,output/name)
    receipt=dict(schema=1,status='prepared_without_steam_ids',created_utc=datetime.now(timezone.utc).isoformat(),
                 client_version=manifest['version'],public_manifest_sha256=digest,
                 launch_executable='TIO Steam.exe',launch_arguments='',platform='Windows x64',
                 steam_app_id=None,steam_depot_id=None,steam_upload_performed=False,
                 files=records,total_content_bytes=sum(r['size'] for r in records),
                 remaining=['Steamworks AppID/DepotID','Rights to original client/assets',
                            'Steam Wallet or disabled external payment path for Steam players',
                            'Store artwork/gameplay screenshots/trailer and content survey',
                            'Clean Windows install and actual Steam private-branch multiplayer acceptance'])
    (output/'package-manifest.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    archive=Path(str(output)+'.zip')
    if archive.exists(): raise FileExistsError('Archive already exists')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file():bundle.write(path,path.relative_to(output))
    (archive.with_suffix('.zip.sha256')).write_text(sha(archive)+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps(dict(package=str(output),archive=str(archive),files=len(records),
                          content_bytes=receipt['total_content_bytes'],zip_bytes=archive.stat().st_size,
                          sha256=sha(archive),steam_uploaded=False)))


if __name__=='__main__':main()
