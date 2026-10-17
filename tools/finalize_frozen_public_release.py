"""Create a root-reviewed net release without changing the delivered freeze."""
import argparse,hashlib,json,shutil
from pathlib import Path
from tools.deploy_gameplay_completion import ROOT,valid_path,validate

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--folder',required=True,type=Path)
    parser.add_argument('--manifest',default='net-manifest.json')
    parser.add_argument('--manifest-sha256',required=True)
    args=parser.parse_args();source=args.source.resolve();folder=args.folder.resolve()
    if not source.is_relative_to(ROOT/'reports') or not folder.is_relative_to(ROOT/'reports/gameplay-completion') or folder.exists():raise ValueError('Preserve reviewed freezes and previous releases')
    manifest_path=source/args.manifest
    if Path(args.manifest).name!=args.manifest or sha(manifest_path)!=args.manifest_sha256:raise ValueError('Reviewed manifest changed')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'));files=manifest['files']
    if not files or not all(valid_path(n) for n in files):raise ValueError('Expected scoped runtime sources')
    proof=json.loads((source/'validation.json').read_text(encoding='utf-8'))
    if not proof.get('passed') or not proof.get('source_unchanged'):raise ValueError('Exact frozen validation required')
    hashes={}
    for name,row in files.items():
        path=(source/row['source']).resolve()
        if not path.is_relative_to(source/'runtime') or path.is_symlink():raise ValueError('Unsafe source')
        raw=path.read_bytes();validate(name,raw);digest=hashlib.sha256(raw).hexdigest()
        if digest!=row['sha256'] or proof['source_sha256'].get(name)!=digest:raise ValueError('Validation/source pin mismatch: '+name)
        hashes[name]=digest
    shutil.copytree(source/'runtime',folder/'runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name,content in [('candidate-manifest.json',manifest),('candidate-overrides.json',{n:'runtime/'+n for n in files}),('runtime-files.json',sorted(files)),('validation.json',dict(proof,source_sha256=hashes)),('root-review.json',dict(source=str(source.relative_to(ROOT)),manifest_sha256=args.manifest_sha256,files=len(files),local_player_data_uploaded=False))]:
        (folder/name).write_text(json.dumps(content,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(folder=str(folder.relative_to(ROOT)),net_files=len(files),source_unchanged=True)))

if __name__=='__main__':main()
