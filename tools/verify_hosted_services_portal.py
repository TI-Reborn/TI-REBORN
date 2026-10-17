"""Check the published portal anonymously over trusted HTTPS and local health."""
import json
import ssl,urllib.request
from pathlib import Path
from urllib.error import HTTPError
from tools.deploy_stage4_economy import remote

ROOT=Path(__file__).resolve().parents[1]
def fetch_portal(path,maximum):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT);context.load_default_certs();context.keylog_filename=None
    request=urllib.request.Request('https://185.184.42.88/'+path,headers={'User-Agent':'TIO-hosted-verification'})
    with urllib.request.urlopen(request,context=context,timeout=15) as response:
        raw=response.read(maximum+1)
        if len(raw)>maximum:raise ValueError('Bounded portal response required')
        return raw
CODE=r'''
import json,subprocess,urllib.request
from pathlib import Path
current=Path('/opt/tio-portal/current').resolve()
if current!=Path('/opt/tio-portal/releases/tireborn-20261008-services-ratings'):raise RuntimeError('Published portal differs')
with urllib.request.urlopen('http://127.0.0.1:3000/api/health',timeout=5) as r:health=json.load(r)
routes=json.loads((current/'.next-interfaces-20261008/server/app-paths-manifest.json').read_text())
expected=('/[locale]/services/page','/[locale]/ratings/page','/api/services/status/route','/api/services/action/route','/api/ratings/status/route')
if any(n not in routes for n in expected):raise RuntimeError('Published route missing')
state=subprocess.check_output(['systemctl','show','tio-portal','-p','MainPID','-p','NRestarts','-p','ExecMainStatus','-p','ActiveState'],text=True).strip()
print(json.dumps(dict(release=str(current),health=health['status'],service=state,expected_routes_present=True)))
'''
def main():
    folder=ROOT/'reports/gameplay-followup/stage34-portal-integration';target=folder/'hosted-routes-verification.json'
    if target.exists():raise ValueError('Preserve verification')
    hosted=remote(CODE,{});rows=[]
    # Use the actual portal path with ordinary certificate verification.
    for name in ('api/health','ru/services','en/services','ru/ratings','en/ratings'):
        raw=fetch_portal(name,4*1024*1024)
        rows.append(dict(path='/'+name,bytes=len(raw),returned=True))
    for name in ('api/services/status','api/ratings/status','api/city/status'):
        try:fetch_portal(name,256*1024)
        except HTTPError as error:
            if error.code!=401:raise
            rows.append(dict(path='/'+name,unauthenticated_status=error.code))
        else:raise RuntimeError('Anonymous protected endpoint accepted')
    report=dict(passed=hosted['health']=='ok',hosted=hosted,https=rows,authenticated_graphical_portal_acceptance=False)
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],routes=len(rows),trusted_https=True)))
if __name__=='__main__':main()
