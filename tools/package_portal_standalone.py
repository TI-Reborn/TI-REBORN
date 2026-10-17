"""Package a portable Next standalone with its installed runtime dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from collections import deque

def package(web,build,output):
    web=web.resolve();source=web/build/'standalone'
    if output.exists():raise ValueError('Preserve the existing release archive')
    with tempfile.TemporaryDirectory(prefix='tio-portal-release-') as folder:
        stage=Path(folder)
        shutil.copytree(source,stage,dirs_exist_ok=True)
        shutil.copytree(web/build/'static',stage/build/'static',dirs_exist_ok=True)
        shutil.copytree(web/'public',stage/'public',dirs_exist_ok=True)
        # Next's Windows trace can omit pure JS dependencies that resolve via
        # the parent workspace. Package the installed production closure too.
        pending=deque((name,web,stage) for name in json.loads((web/'package.json').read_text(encoding='utf-8'))['dependencies'])
        installed={};seen=set()
        while pending:
            name,parent,target_parent=pending.popleft()
            if '..' in Path(name).parts or name.startswith(('/', '\\')):raise ValueError('Unsafe dependency')
            candidates=[ancestor/'node_modules'/name for ancestor in (parent,*parent.parents) if ancestor.is_relative_to(web)]
            module=next((p for p in candidates if (p/'package.json').is_file()),None)
            if module is None:raise ValueError('Missing installed production dependency: '+name)
            module=module.resolve()
            if not module.is_relative_to(web/'node_modules'):raise ValueError('Dependency outside installed tree')
            # pnpm links point into its versioned store. Preserve the Node
            # namespace in the portable release, rather than the store path.
            target_candidates=[ancestor/'node_modules'/name for ancestor in (target_parent,*target_parent.parents)
                               if ancestor.is_relative_to(stage)]
            visible=next((p for p in target_candidates if p in installed),None)
            if visible is not None and installed[visible]==module:continue
            target=target_candidates[0]
            if target in installed:raise ValueError('Conflicting direct dependency: '+name)
            installed[target]=module;seen.add(module)
            shutil.copytree(module,target,dirs_exist_ok=True)
            manifest=json.loads((module/'package.json').read_text(encoding='utf-8'))
            pending.extend((name,module,target) for name in manifest.get('dependencies',{}))
        def filtered(member):
            return None if any(part.startswith('.env') for part in Path(member.name).parts) else member
        output.parent.mkdir(parents=True,exist_ok=True)
        with tarfile.open(output,'w:gz',dereference=True) as archive:
            for p in sorted(stage.iterdir()):archive.add(p,arcname=p.name,filter=filtered)
    with tarfile.open(output) as archive:
        members=archive.getnames()
        if not any(n.endswith('node_modules/@swc/helpers/package.json') for n in members):raise ValueError('Missing portable Next helper')
        if any(any(p.startswith('.env') for p in Path(n).parts) for n in members):raise ValueError('Environment in archive')
    return dict(archive=str(output),sha256=hashlib.sha256(output.read_bytes()).hexdigest(),bytes=output.stat().st_size,
        production_packages=len(seen),environment_files_excluded=True,windows_parent_dependency_fallback_removed=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web',type=Path,default=Path('web'))
    parser.add_argument('--build-dir',default='.next')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.build_dir.startswith('.next') or Path(args.build_dir).name!=args.build_dir:parser.error('Invalid build directory')
    print(json.dumps(package(args.web,args.build_dir,args.output)))

if __name__=='__main__':main()
