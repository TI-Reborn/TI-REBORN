"""Hidden scheduled-job wrapper with a credential-free local status record."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def checked_result(data):
    if (not isinstance(data,dict) or data.get('status') not in ('captured','skipped')
            or data.get('scope')!='platform' or data.get('integrity')!='ok'
            or not isinstance(data.get('verified_restore'),list)
            or not {'in-memory SQLite','remote isolated PostgreSQL'} <= set(data['verified_restore'])
            or not isinstance(data.get('path'),str) or not data['path']):
        raise ValueError('Incomplete verified platform result')
    return {key:data[key] for key in ('status','scope','path','encrypted_bytes','accounts',
             'portal_tables','portal_rows','integrity','verified_restore','pruned') if key in data}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--if-due',action='store_true')
    parser.add_argument('--retention-days',type=int,default=31)
    args=parser.parse_args()
    folder=Path(os.environ['LOCALAPPDATA'])/'TIO-emulator/backups'
    folder.mkdir(parents=True,exist_ok=True)
    status_file=folder/'scheduled-status.json'
    previous={}
    if status_file.is_file():
        try:previous=json.loads(status_file.read_text(encoding='utf-8'))
        except (ValueError,OSError):pass
    if not isinstance(previous,dict):previous={}
    record={'last_attempt_utc':datetime.now(timezone.utc).isoformat(),
            'last_success_utc':previous.get('last_success_utc'),'scope':'platform'}
    python=Path(sys.executable)
    if os.name=='nt' and python.name.lower()=='pythonw.exe':python=python.with_name('python.exe')
    command=[str(python),str(Path(__file__).with_name('offsite_backup_windows.py')),
             '--retention-days',str(args.retention_days)]
    if args.if_due:command.append('--if-due')
    exit_code=1
    try:
        result=subprocess.run(command,capture_output=True,timeout=3300,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if result.returncode:
            record.update(status='failed',error='backup_process_failed',exit_code=result.returncode)
        else:
            data=checked_result(json.loads(result.stdout.decode('utf-8').strip()))
            record['result']=data
            record['status']=data['status']
            if record['status']=='captured':record['last_success_utc']=datetime.now(timezone.utc).isoformat()
            exit_code=0
    except Exception as error:
        record.update(status='failed',error=type(error).__name__)
    finally:
        descriptor,pending=tempfile.mkstemp(prefix='.scheduled-status-',suffix='.pending',dir=folder)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as output:
                json.dump(record,output,indent=2);output.write('\n');output.flush();os.fsync(output.fileno())
            os.replace(pending,status_file)
        finally:
            Path(pending).unlink(missing_ok=True)
    if sys.stdout is not None:print(json.dumps(record))
    return exit_code


if __name__=='__main__':raise SystemExit(main())
