"""Prepare reviewable 0.1.4 publication invocations locally; no remote action."""
from datetime import datetime,timezone
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE_HASH='61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f'
CANDIDATE_BYTES=118679712
REMOTE_CANDIDATE='/root/TIO-Launcher-0.1.4-'+CANDIDATE_HASH[:12]+'.exe'
BACKUP='/root/tio-before-launcher-opefu9a1'


def prepare(output):
    output=Path(output)
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    candidate=ROOT/'reports/login-incident/launcher-0.1.4/TIO Launcher.exe'
    if candidate.is_symlink() or candidate.stat().st_size!=CANDIDATE_BYTES or hashlib.sha256(candidate.read_bytes()).hexdigest()!=CANDIDATE_HASH:
        raise ValueError('Candidate differs from reviewed 0.1.4')
    helper=ROOT/'tools/publish_launcher_014_remote.py'
    source=helper.read_text(encoding='utf-8').replace('\r\n','\n');ast.parse(source)
    output.mkdir(parents=True)
    (output/helper.name).write_text(source,encoding='utf-8',newline='\n')
    scripts={}
    for action in ('inspect','apply'):
        arguments=['--'+action,'--backup',BACKUP,'--candidate',REMOTE_CANDIDATE,
                   '--sha256',CANDIDATE_HASH,'--bytes',str(CANDIDATE_BYTES)]
        script='import sys\nsys.argv='+repr(['launcher-014',*arguments])+'\nexec(compile('+repr(source)+", 'reviewed-launcher-014', 'exec'), {'__name__':'__main__'})\n"
        target=output/(action+'-remote.stdin.py');target.write_text(script,encoding='utf-8',newline='\n');scripts[action]=str(target.resolve())
    report={'schema':1,'version':'0.1.4','created_utc':datetime.now(timezone.utc).isoformat(),
            'backup':BACKUP,'candidate':str(candidate.resolve()),'candidate_sha256':CANDIDATE_HASH,
            'candidate_bytes':CANDIDATE_BYTES,'remote_candidate':REMOTE_CANDIDATE,
            'publisher_source':str(helper.resolve()),'publisher_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'stdin_scripts':scripts,'ssh_command':'/usr/bin/python3 -','remote_operations_executed':False,
            'changed_metadata_fields':['launcherVersion','launcherUrl','fileSizeBytes','updatedAt'],
            'immutable_url':'https://ti-reborn.com/downloads/TIO-Launcher-0.1.4.exe',
            'current_alias':'https://ti-reborn.com/downloads/TIO-Launcher.exe',
            'game_version_preserved':'2026.10.07.4','services_restarted':False,
            'localized_manual_replace_copy':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in (ROOT/'web/src/locales/en.json',ROOT/'web/src/locales/ru.json')}}
    (output/'package.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(prepare(parser.parse_args().output)))
