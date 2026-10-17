"""Prepare locally, then test an owned copy of hosted code with a pinned overlay.

The run command creates an isolated directory and disposable SQLite fixtures.
It never starts/stops a hosted service or reads/writes hosted player data.
Evidence is copied into the candidate; no symlink points into production.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
MODULES=('test_alliances','test_alliance_service','test_clan_ratings',
    'test_clan_warfare_protocol','test_territories','test_assault_arena',
    'test_battle_failure_isolation','test_mine_claims_and_tax',
    'test_shared_mine_arena','test_clans','test_public_profile')
COPY_DIRS=('tio','server','tools','config','evidence')
MAX_TOTAL=512*1024*1024
MAX_FILES=20000


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative_name(name):
    p=PurePosixPath(name)
    if not isinstance(name,str) or '\\' in name or p.is_absolute() or p.as_posix()!=name or '..' in p.parts:
        raise ValueError('Unsafe candidate member')
    return p


def prepare(files_path,output):
    from tools.deploy_clan_warfare import ALLOWED,validate_candidate
    selected=json.loads(Path(files_path).read_text(encoding='utf-8'))
    if not isinstance(selected,list) or len(selected)!=len(set(selected)) or not selected or not set(selected)<=ALLOWED:
        raise ValueError('Unexpected runtime selection')
    selected=sorted(selected)
    entries={}
    for name in selected:
        relative_name(name)
        raw=(ROOT/name).read_bytes();validate_candidate(name,raw)
        entries[name]=hashlib.sha256(raw).hexdigest()
    tests=sorted(p for p in (ROOT/'tests').rglob('*.py') if '__pycache__' not in p.parts)
    members=selected+[p.relative_to(ROOT).as_posix() for p in tests]
    if len(members)!=len(set(members)):raise ValueError('Duplicate candidate member')
    payload={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in members}
    output=Path(output).resolve()
    if not output.is_relative_to((ROOT/'reports/clan-warfare').resolve()) or output.exists():
        raise ValueError('Use a fresh clan-warfare report directory')
    output.mkdir(parents=True)
    bundle=output/'candidate.tar.gz'
    with tarfile.open(bundle,'w:gz') as tar:
        for name in members:
            raw=(ROOT/name).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=payload[name]:raise RuntimeError('Source changed while preparing candidate')
            info=tarfile.TarInfo(name);info.size=len(raw);info.mode=0o600
            tar.addfile(info,io.BytesIO(raw))
    manifest=dict(version=1,runtime_sha256=entries,member_sha256=payload,
        bundle_sha256=digest(bundle),modules=list(MODULES),kind='isolated candidate; no hosted gameplay')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return dict(runtime_files=len(entries),test_files=len(tests),bundle=str(bundle),manifest=str(output/'manifest.json'))


def copy_production(production,candidate):
    """Only code/config/fixture trees; reject every symlink before copying."""
    production=Path(production).resolve();candidate=Path(candidate).resolve()
    if candidate.is_relative_to(production) or production.is_relative_to(candidate):raise ValueError('Overlapping copy roots')
    total=count=0
    for tree in COPY_DIRS:
        source=production/tree
        if not source.is_dir() or source.is_symlink():raise ValueError('Missing or linked production fixture tree')
        for base,dirs,files in os.walk(source,followlinks=False):
            base=Path(base)
            for name in dirs+files:
                if (base/name).is_symlink():raise ValueError('Production symlink cannot become candidate evidence')
            dirs[:]=[d for d in dirs if d not in ('__pycache__','.venv')]
            for name in files:
                if name.endswith(('.pyc','.pyo')):continue
                path=base/name
                if not path.is_file():raise ValueError('Non-regular production fixture')
                total+=path.stat().st_size;count+=1
                if total>MAX_TOTAL or count>MAX_FILES:raise ValueError('Candidate copy exceeds reviewed bounds')
                target=candidate/path.relative_to(production)
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    return dict(files=count,bytes=total,evidence='actual copied files; no production symlinks')


def extract_pinned(bundle,candidate,manifest):
    expected=manifest['member_sha256'];candidate=Path(candidate).resolve()
    if digest(bundle)!=manifest['bundle_sha256']:raise ValueError('Candidate archive checksum changed')
    with tarfile.open(bundle) as tar:
        rows=tar.getmembers()
        names=[row.name for row in rows]
        if len(names)!=len(set(names)) or set(names)!=set(expected) or len(rows)>MAX_FILES:
            raise ValueError('Candidate archive membership changed')
        for row in rows:
            relative_name(row.name)
            if not row.isfile() or row.size<0 or row.size>MAX_TOTAL:raise ValueError('Non-regular candidate member')
            target=candidate/row.name
            if not target.resolve().is_relative_to(candidate):raise ValueError('Candidate target escapes owned directory')
            if any(p.is_symlink() for p in (target,*target.parents)):raise ValueError('Linked candidate target')
        if sum(row.size for row in rows)>MAX_TOTAL:raise ValueError('Candidate archive exceeds reviewed bounds')
        for row in rows:
            raw=tar.extractfile(row).read()
            if hashlib.sha256(raw).hexdigest()!=expected[row.name]:raise ValueError('Candidate member checksum changed')
            target=candidate/row.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for name,value in manifest['runtime_sha256'].items():
        if expected.get(name)!=value or digest(candidate/name)!=value:raise ValueError('Runtime candidate source differs from manifest')


def run(bundle,manifest_path,*,production=Path('/opt/tio-emulator'),work_parent=Path('/root')):
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest.get('version')!=1 or manifest.get('modules')!=list(MODULES):raise ValueError('Unexpected candidate test contract')
    runtime=manifest['runtime_sha256']
    for name in runtime:relative_name(name)
    before={n:digest(production/n) if (production/n).exists() else None for n in runtime}
    candidate=Path(tempfile.mkdtemp(prefix='tio-clan-warfare-candidate-',dir=work_parent))
    copied=copy_production(production,candidate)
    extract_pinned(bundle,candidate,manifest)
    program="import sys,unittest;from pathlib import Path;root=Path.cwd();sys.path[:0]=[str(root),str(root/'tests'),str(root/'tools')];suite=unittest.defaultTestLoader.loadTestsFromNames("+repr(list(MODULES))+ ");r=unittest.TextTestRunner(verbosity=1).run(suite);raise SystemExit(not r.wasSuccessful())"
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(candidate)}
    env.pop('PYTHONSTARTUP',None)
    result=subprocess.run([str(production/'.venv/bin/python'),'-c',program],cwd=candidate,
        env=env,capture_output=True,text=True,timeout=900)
    after={n:digest(production/n) if (production/n).exists() else None for n in runtime}
    actual={n:digest(candidate/n) for n in runtime}
    report=dict(passed=result.returncode==0 and before==after and actual==runtime,candidate=str(candidate),copied=copied,
        runtime_sha256=actual,runtime_source_parity=actual==runtime,production_selected_sources_unchanged=before==after,
        modules=list(MODULES),tests_stdout=result.stdout,tests_stderr=result.stderr,
        limitation='Automated eight-account fixtures and protocol tests; no graphical clients or hosted battle',
        production_data_access='none; code/config/evidence copies only')
    (candidate/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('--files',type=Path,default=ROOT/'reports/clan-warfare/runtime-files.json')
    q.add_argument('--output',type=Path,required=True)
    q=sub.add_parser('run');q.add_argument('--bundle',type=Path,required=True);q.add_argument('--manifest',type=Path,required=True)
    args=p.parse_args()
    result=prepare(args.files,args.output) if args.action=='prepare' else run(args.bundle,args.manifest)
    print(json.dumps(result,indent=2));return 0 if result.get('passed',True) else 1


if __name__=='__main__':raise SystemExit(main())
