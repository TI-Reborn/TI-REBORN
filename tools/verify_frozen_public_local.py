"""Run explicit tests against an immutable public runtime with disposable saves."""
import argparse,hashlib,json,shutil,subprocess,sys,tempfile
from pathlib import Path
from tools.deploy_gameplay_completion import ROOT

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,required=True);parser.add_argument('--suite',action='append',required=True);parser.add_argument('--test-source',action='append',default=[]);parser.add_argument('--test-artifact',action='append',default=[]);parser.add_argument('--output',default='local-integration-validation.json');args=parser.parse_args()
    folder=args.folder.resolve();target=folder/args.output
    if not folder.is_relative_to(ROOT/'reports/gameplay-completion') or target.exists() or Path(args.output).name!=args.output:raise ValueError('Preserve bounded report')
    manifest=json.loads((folder/'candidate-manifest.json').read_text(encoding='utf-8'))
    hashes={n:hashlib.sha256((folder/r['source']).read_bytes()).hexdigest() for n,r in manifest['files'].items()}
    if any(hashes[n]!=r['sha256'] for n,r in manifest['files'].items()):raise ValueError('Frozen candidate changed')
    with tempfile.TemporaryDirectory(prefix='tio-public-focused-') as temp:
        stage=Path(temp);shutil.copytree(folder/'runtime',stage,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT/'tests',stage/'tests',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
        for value in args.test_artifact:
            source=(ROOT/value).resolve()
            if len(Path(value).parts)!=2 or not value.startswith('evidence/') or source.suffix!='.json' or not source.is_relative_to(ROOT/'evidence') or source.is_symlink():raise ValueError('Explicit public evidence JSON required')
            raw=source.read_bytes();json.loads(raw)
            (stage/value).write_bytes(raw)
        for value in args.test_source:
            source=ROOT/value
            if source.suffix!='.py' or not source.resolve().is_relative_to(ROOT/'reports'):raise ValueError('Explicit report test only')
            raw=source.read_text(encoding='utf-8')
            # The delivered report-local test resolves ../runtime. Its copied
            # equivalent must resolve this installed public tree instead.
            boundary="RUNTIME = Path(__file__).resolve().parents[1] / 'runtime'"
            if boundary in raw:raw=raw.replace(boundary,"RUNTIME = Path(__file__).resolve().parents[1]")
            # Report-local combat cases refer to their neighbouring public tree.
            raw=raw.replace("HERE/'runtime'","HERE")
            raw=raw.replace("HERE/'runtime/","HERE/'")
            (stage/'tests'/source.name).write_text(raw,encoding='utf-8')
        script="import sys,unittest;sys.path[:0]=['tests','tools'];r=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames("+repr(args.suite)+"));sys.exit(not r.wasSuccessful())"
        done=subprocess.run([sys.executable,'-X','utf8','-c',script],cwd=stage,capture_output=True,text=True,timeout=180)
    unchanged=all(hashlib.sha256((folder/r['source']).read_bytes()).hexdigest()==hashes[n] for n,r in manifest['files'].items())
    result=dict(passed=done.returncode==0 and unchanged,source_unchanged=unchanged,source_sha256=hashes,output=(done.stdout+done.stderr)[-20000:],hosted_data_accessed=False,graphical_client_acceptance=False)
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');print(json.dumps(dict(passed=result['passed'],output=result['output'][-4500:])))
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
