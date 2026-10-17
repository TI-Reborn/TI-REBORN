"""Run the merged portal only in a copied tree, without env files or databases."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/gameplay-followup/stage34-portal-integration'
WEB=ROOT/'web'
CONFIG=('package.json','pnpm-lock.yaml','pnpm-workspace.yaml','tsconfig.json','next.config.ts','prisma.config.ts')
EXCLUDED={'tests/auth-db.test.ts':'Requires configured PostgreSQL credentials and launches a separate DB-backed auth integration; no secrets or databases used in this task'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))
def pins(folder,*,assets=False):
    paths=[]
    for name in ('src','tests',*(('public','prisma') if assets else ())):
        paths.extend(p for p in (folder/name).rglob('*') if p.is_file())
    paths.extend(folder/name for name in CONFIG if (folder/name).is_file())
    return {p.relative_to(folder).as_posix():sha(p) for p in sorted(paths)}
def env():
    value={key:os.environ[key] for key in ('PATH','SystemRoot','WINDIR','COMSPEC','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA') if key in os.environ}
    value.update(NEXT_TELEMETRY_DISABLED='1',SITE_URL='https://portal.example',NEXT_DIST_DIR='.next-interfaces-20261008')
    return value


def command(arguments,cwd,environment,folder,label,budget):
    log=folder/(label+'.log');start=time.monotonic();print(json.dumps(dict(starting=label,budget_seconds=budget)),flush=True)
    timed_out=False
    with log.open('w',encoding='utf-8') as output:
        process=subprocess.Popen(arguments,cwd=cwd,env=environment,stdout=output,stderr=subprocess.STDOUT)
        try:code=process.wait(timeout=budget)
        except subprocess.TimeoutExpired:
            timed_out=True;process.kill();code=process.wait(timeout=10)
    result=dict(check=label,command=[Path(arguments[0]).name,*arguments[1:]],exit_code=code,timed_out=timed_out,
                seconds=round(time.monotonic()-start,3),log=log.name,log_sha256=sha(log))
    print(json.dumps(result),flush=True);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('name',choices=('validation1','validation2','final'))
    args=parser.parse_args();folder=REPORT/args.name
    if folder.exists():raise ValueError('Preserve previous integration proof')
    folder.mkdir();sys.stdout.reconfigure(encoding='utf-8')
    node=shutil.which('node');modules=WEB/'node_modules'
    if not node or not modules.is_dir():raise ValueError('Existing dependency runtime required')
    baseline=pins(WEB,assets=True);patches=read(REPORT/'reviewed-hunks.json')['hunks']
    scoped=pins(REPORT/'runtime/web');checks=[];compiled={};source_unchanged=False
    with tempfile.TemporaryDirectory(prefix='verify-',dir=REPORT) as name:
        target=Path(name)/'web';target.mkdir()
        for directory in ('src','tests','public','prisma'):
            shutil.copytree(WEB/directory,target/directory,ignore=shutil.ignore_patterns('__pycache__'))
        for name in CONFIG:shutil.copyfile(WEB/name,target/name)
        (target/'next-env.d.ts').write_text('/// <reference types="next" />\n/// <reference types="next/image-types/global" />\n',encoding='utf-8')
        shutil.copytree(REPORT/'runtime/web',target,dirs_exist_ok=True)
        for name,entry in patches.items():
            destination=target/name.removeprefix('web/')
            if sha(destination)!=entry['before_sha256']:raise ValueError('Navigation baseline changed')
            content=destination.read_bytes().decode('utf-8')
            for edit in entry.get('edits',[dict(before=entry.get('before'),after=entry.get('after'))]):
                if content.count(edit['before'])!=1:raise ValueError('Ambiguous reviewed patch')
                content=content.replace(edit['before'],edit['after'])
            destination.write_bytes(content.encode('utf-8'))
            if sha(destination)!=entry['after_sha256']:raise ValueError('Reviewed patch differs')
        before=pins(target,assets=True)
        # Only this temporary junction is removed. Its dependency target stays intact.
        junction=target/'node_modules'
        ps=lambda value:"'"+str(value).replace("'","''")+"'"
        subprocess.run(['powershell','-NoProfile','-Command','New-Item -ItemType Junction -Path '+ps(junction)+' -Target '+ps(modules)+' | Out-Null'],check=True,capture_output=True)
        try:
            selected=sorted(path.relative_to(target).as_posix() for path in (target/'tests').glob('*.test.ts') if path.relative_to(target).as_posix() not in EXCLUDED)
            checks.append(command([node,str(modules/'tsx/dist/cli.mjs'),'--test',*selected],target,env(),folder,'portal-tests',60))
            checks.append(command([node,str(modules/'typescript/bin/tsc'),'--noEmit','--incremental','false'],target,env(),folder,'typescript',60))
            if all(c['exit_code']==0 for c in checks):
                environment=env();environment['NODE_ENV']='production'
                checks.append(command([node,str(modules/'next/dist/bin/next'),'build','--webpack'],target,environment,folder,'next-build',180))
                if checks[-1]['exit_code']==0:
                    output=target/'.next-interfaces-20261008'
                    paths=read(output/'server/app-paths-manifest.json')
                    required=('/[locale]/services/page','/[locale]/ratings/page','/api/services/status/route','/api/services/action/route','/api/ratings/status/route','/[locale]/city/page','/[locale]/assault/page')
                    if not all(name in paths for name in required):raise ValueError('Required portal routes missing from full build')
                    compiled={name:dict(output=paths[name],sha256=sha(output/'server'/paths[name])) for name in required}
                    (folder/'app-paths-manifest.json').write_text(json.dumps(paths,indent=2)+'\n',encoding='utf-8')
                    (folder/'routes-manifest.json').write_bytes((output/'routes-manifest.json').read_bytes())
                    compiled['standalone']=(output/'standalone').is_dir()
            after=pins(target,assets=True)
            # Next appends its generated type directories to the temporary compiler
            # configuration. All source, tests, public assets and schemas stay pinned.
            expected=dict(before);expected['tsconfig.json']=after['tsconfig.json']
            source_unchanged=expected==after
            (folder/'source-pins.json').write_text(json.dumps(dict(baseline=baseline,scoped=scoped,isolated=before,
                temporaryCompilerConfigBefore=before['tsconfig.json'],temporaryCompilerConfigAfter=after['tsconfig.json']),indent=2)+'\n',encoding='utf-8')
        finally:
            if not junction.resolve().is_relative_to(modules.resolve()):raise ValueError('Unexpected dependency junction target')
            junction.rmdir()
    shared_unchanged=baseline==pins(WEB,assets=True);scoped_unchanged=scoped==pins(REPORT/'runtime/web')
    text=(folder/'portal-tests.log').read_text(encoding='utf-8',errors='replace')
    counts={key:int(match.group(1)) if (match:=re.search(r'\b'+key+r' (\d+)\b',text)) else None for key in ('tests','pass','fail','skipped')}
    passed=(len(checks)==3 and all(c['exit_code']==0 and not c['timed_out'] for c in checks)
            and counts['fail']==0 and counts['skipped']==0 and source_unchanged and shared_unchanged and scoped_unchanged)
    proof=dict(version=1,utc=datetime.now(timezone.utc).isoformat(),passed=passed,checks=checks,testCounts=counts,
               selectedTestModules=selected,excludedTestModules=EXCLUDED,compiledRoutes=compiled,
               isolatedSourceUnchanged=source_unchanged,sharedWebUnchanged=shared_unchanged,scopedSourceUnchanged=scoped_unchanged,
               envFilesCopied=False,secretsUsed=False,databasesUsed=False,hostedChanges=False,graphicalAcceptance=False,
               buildDistDir='.next-interfaces-20261008',buildTree='Temporary isolated tree removed after evidence capture')
    (folder/'validation.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:proof[key] for key in ('passed','testCounts','isolatedSourceUnchanged','sharedWebUnchanged','scopedSourceUnchanged')}))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
