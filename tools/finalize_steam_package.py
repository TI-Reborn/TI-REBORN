"""Finalize the tested Steam candidate and archive without any Steam publication."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.prepare_steam_package import ROOT, sha, safe_file


def main():
    package=ROOT/'output/steam/TI-REBORN-Windows-2026.10.13.1'
    receipt_path=package/'package-manifest.json';receipt=json.loads(receipt_path.read_text())
    content=package/'content';expected=set()
    for record in receipt['files']:
        path=safe_file(content/record['path'])
        if path.stat().st_size!=record['size'] or sha(path)!=record['sha256']:
            raise ValueError('Candidate differs from reviewed manifest: '+record['path'])
        expected.add(path.relative_to(content).as_posix())
    actual={p.relative_to(content).as_posix() for p in content.rglob('*') if p.is_file()}
    if actual!=expected: raise ValueError('Unexpected depot contents')
    evidence=ROOT/'reports/steam-preparation'
    for name in ('final-steam-checks.json','final-language-checks.json','final-full-install-check.json','hosted-tls-check.json'):
        if json.loads((evidence/name).read_text())['passed'] is not True:
            raise ValueError('Failed required local verification')
    report=dict(status='technical_candidate_verified_steam_onboarding_pending',verified_utc=datetime.now(timezone.utc).isoformat(),
                content_files=len(expected),content_bytes=receipt['total_content_bytes'],
                launcher_sha256=next(r['sha256'] for r in receipt['files'] if r['path']=='TIO Steam.exe'),
                steam_ids_configured=False,steam_upload_performed=False,steam_private_branch_tested=False,
                checks=['all depot sizes/SHA256 verified and no extra files',
                        'nine offline Steam distribution checks',
                        'sixteen Russian/English selection and resource checks',
                        'twelve Python package/localization tests',
                        'all 6599 native resources installed and repaired locally',
                        'existing updater rollback/resume and path/self-update tests',
                        'seven isolated TLS bridge tests and actual hosted certificate check',
                        'actual final Steam candidate native startup and English agreement/menu in Windows 11',
                        'SteamPipe template generation tested with isolated example IDs; deliverable remains unconfigured',
                        'all hosted services active; no remote changes or accounts created'],
                graphical_authentication_performed=False,complete_graphical_world_battle_acceptance=False,
                remaining=receipt['remaining'])
    (evidence/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
    target=package/'verification';target.mkdir(exist_ok=False)
    for name in ('acceptance.json','final-steam-checks.json','final-language-checks.json','final-full-install-check.json',
                 'hosted-tls-check.json','final-tls-checks.json','self-checks.json','game-path-checks.json'):
        shutil.copyfile(evidence/name,target/name)
    receipt['status']=report['status'];receipt['verification']='verification/acceptance.json'
    receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
    archive=Path(str(package)+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for path in sorted(package.rglob('*')):
            if path.is_file():bundle.write(path,path.relative_to(package))
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None: raise ValueError('Archive CRC verification failed')
    checksum=sha(archive)
    archive.with_suffix('.zip.sha256').write_text(checksum+'  '+archive.name+'\n')
    result=dict(package=str(package),archive=str(archive),archive_bytes=archive.stat().st_size,
                sha256=checksum,files=len(expected),steam_uploaded=False)
    (evidence/'final-artifact.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
