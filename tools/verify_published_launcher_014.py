"""Read-only trusted HTTPS proof of both reviewed 0.1.4 downloads and metadata."""
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import ssl
import urllib.request

ORIGIN='https://ti-reborn.com'
EXPECTED='61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f'
EXPECTED_BYTES=118679712
VERSIONED='/downloads/TIO-Launcher-0.1.4.exe'


def fetch(path,context,binary=False):
    request=urllib.request.Request(ORIGIN+path,headers={'Cache-Control':'no-cache','Pragma':'no-cache','User-Agent':'TIO-reviewed-launcher-014-QA'})
    with urllib.request.urlopen(request,context=context,timeout=120) as response:
        if response.status!=200:raise ValueError('Public endpoint did not return200')
        digest=hashlib.sha256();count=0;chunks=[]
        for chunk in iter(lambda:response.read(1024*1024),b''):
            count+=len(chunk)
            if count>(200*1024*1024 if binary else 2*1024*1024):raise ValueError('Public response exceeds bound')
            digest.update(chunk)
            if not binary:chunks.append(chunk)
        record={'status':response.status,'bytes':count,'sha256':digest.hexdigest(),'url':response.url,
                'content_type':response.headers.get('Content-Type'),'cache_control':response.headers.get('Cache-Control')}
        if not response.url.startswith(ORIGIN+'/'):raise ValueError('Public endpoint redirected outside expected HTTPS origin')
        return record,b''.join(chunks)


def verify(require_copy=False):
    context=ssl.create_default_context();context.keylog_filename=None
    downloads={}
    for path in (VERSIONED,'/downloads/TIO-Launcher.exe?verify='+EXPECTED[:12]):
        record,_=fetch(path,context,True)
        record['matches_reviewed_candidate']=record['sha256']==EXPECTED and record['bytes']==EXPECTED_BYTES
        if not record['matches_reviewed_candidate']:raise ValueError('Public launcher differs from reviewed candidate')
        downloads[path]=record
    metadata_record,raw=fetch('/api/client/version',context)
    metadata=json.loads(raw)
    if (metadata.get('launcherVersion')!='0.1.4' or metadata.get('launcherUrl')!=VERSIONED
            or metadata.get('fileSizeBytes')!=EXPECTED_BYTES or metadata.get('gameVersion')!='2026.10.07.4'):
        raise ValueError('Public launcher metadata differs from reviewed publication')
    pages={}
    for locale in ('en','ru'):
        record,raw=fetch('/'+locale+'/download',context)
        html=raw.decode('utf-8')
        record.update({'version_014_visible':'0.1.4' in html,'versioned_download_visible':VERSIONED in html,
                       'manual_replace_covers_013':'0.1.3' in html})
        if not record['version_014_visible'] or not record['versioned_download_visible']:
            raise ValueError('Public download page is missing current version or exact download link')
        if require_copy and not record['manual_replace_covers_013']:
            raise ValueError('Localized manual replacement note is not published')
        pages[locale]=record
    return {'status':'passed','verified_utc':datetime.now(timezone.utc).isoformat(),
            'trusted_https':True,'tls_key_logging':False,'downloaded_executables_saved':False,
            'reviewed_sha256':EXPECTED,'reviewed_bytes':EXPECTED_BYTES,'downloads':downloads,
            'public_metadata':metadata,'metadata_response':metadata_record,'download_pages':pages,
            'guide_copy_required':require_copy}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--require-guide-copy',action='store_true');args=parser.parse_args()
    if args.report.exists() or args.report.is_symlink():raise FileExistsError('Refusing to replace existing evidence')
    data=verify(args.require_guide_copy);args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x',encoding='utf-8') as output:output.write(json.dumps(data,indent=2)+'\n')
    print(json.dumps(data))
