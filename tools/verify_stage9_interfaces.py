"""Verify the frozen public candidate in a disposable, isolated local tree."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-completion/stage9-interfaces'
SUITES=('test_assault_location_admission','test_assault_arena',
        'test_world_core_integration.WorldSceneCoreTests','test_assault_public',
        'test_assault_interface_integration','test_clan_rating_crests',
        'test_economy_runtime','test_night_vision_state','test_battle_item_visuals',
        'test_battle_item_effects','test_battle_doors','test_battle_turn_regressions',
        'test_clan_crest_gateway','test_bank_gateway')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='local-validation.json')
    parser.add_argument('--folder',type=Path,default=FOLDER)
    args=parser.parse_args()
    folder=args.folder.resolve()
    if folder not in (FOLDER,ROOT/'reports/gameplay-completion/stage9-interfaces-revision2'):
        raise ValueError('Expected one of the two reviewed interface revisions')
    if Path(args.output).name!=args.output or not args.output.endswith('.json'):
        raise ValueError('Expected a plain JSON evidence filename')
    target=folder/args.output
    if target.exists():raise ValueError('Preserve the previous verification evidence')
    manifest=json.loads((folder/'candidate-manifest.json').read_text(encoding='utf-8'))
    hashes={}
    for name,row in manifest['files'].items():
        raw=(folder/row['source']).read_bytes();hashes[name]=hashlib.sha256(raw).hexdigest()
        if hashes[name]!=row['sha256']:raise ValueError('Frozen candidate changed: '+name)
    with tempfile.TemporaryDirectory(prefix='tio-stage9-local-') as temporary:
        stage=Path(temporary)
        shutil.copytree(folder/'runtime',stage,dirs_exist_ok=True)
        shutil.copytree(ROOT/'tests',stage/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        # Existing source-scope tests require their immutable public artifact.
        fixtures={}
        for name in ('evidence/owned_pet_trial.json','evidence/battle_item_native.json',
                     'config/battle_item_catalog_extension.xml'):
            path=stage/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,path)
            fixtures[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        suites=SUITES+(('test_private_market','test_private_market_refresh') if len(manifest['files'])==10 else ())
        script="import sys,unittest;sys.path[:0]=['tests','tools'];s=unittest.defaultTestLoader.loadTestsFromNames("+repr(suites)+");r=unittest.TextTestRunner(verbosity=1).run(s);sys.exit(not r.wasSuccessful())"
        process=subprocess.run([str(ROOT/'data/registration-check-env/Scripts/python.exe'),'-X','utf8','-c',script],
            cwd=stage,capture_output=True,text=True,encoding='utf-8',timeout=180)
    unchanged=all(hashlib.sha256((folder/manifest['files'][name]['source']).read_bytes()).hexdigest()==digest
                  for name,digest in hashes.items())
    result=dict(passed=process.returncode==0 and unchanged,source_unchanged=unchanged,
                utc=datetime.now(timezone.utc).isoformat(),source_sha256=hashes,
                suites=suites,output=process.stdout+process.stderr,exit_code=process.returncode,
                public_test_fixture_sha256=fixtures,
                public_candidate_only=True,hosted_runtime_modified=False,hosted_database_accessed=False)
    target.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_sha256','suites')}))
    return 0 if result['passed'] else 1


if __name__=='__main__':sys.exit(main())
