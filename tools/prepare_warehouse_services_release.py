"""Freeze warehouses/services over reviewed shops; preserve unrelated local work."""
from datetime import datetime,timezone
import hashlib,json,shutil
from pathlib import Path
from tools.deploy_gameplay_completion import valid_path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports/gameplay-completion/stage10-shops-r2'
WAREHOUSE=ROOT/'reports/gameplay-followup/stage3-warehouses'
SERVICES=ROOT/'reports/gameplay-followup/stage3-services'
SOCIAL=ROOT/'reports/gameplay-followup/stage3-social'
FOLDER=ROOT/'reports/gameplay-completion/stage11-warehouse-services-r6'

def replace(value,old,new):
    if value.count(old)!=1:raise ValueError('Public integration boundary changed')
    return value.replace(old,new)

def main():
    if (FOLDER/'candidate-manifest.json').exists():raise ValueError('Preserve prior release')
    shutil.copytree(BASE/'runtime',FOLDER/'runtime',ignore=shutil.ignore_patterns('__pycache__'))
    overrides=json.loads((BASE/'candidate-overrides.json').read_text(encoding='utf-8'));files={}
    def install(name,raw,before):
        target=FOLDER/'runtime'/name;target.parent.mkdir(parents=True,exist_ok=True)
        if name.endswith('.py'):compile(raw,name,'exec')
        else:json.loads(raw)
        target.write_bytes(raw);digest=hashlib.sha256(raw).hexdigest()
        files[name]=dict(source='runtime/'+name,sha256=digest,before=files.get(name,{}).get('before',before));overrides[name]='runtime/'+name
    pins_raw=(WAREHOUSE/'source-pins.json').read_bytes()
    if hashlib.sha256(pins_raw).hexdigest()!='0fac34c8913f92b0a7858cf427d7f418df19cb345bd64d206e20a183e36a6264':raise ValueError('Warehouse proof changed')
    pins=json.loads(pins_raw)
    for name,row in pins.items():
        prior=FOLDER/'runtime'/name
        if hashlib.sha256(prior.read_bytes()).hexdigest()!=row['source_sha256']:raise ValueError('Warehouse public base changed')
        raw=(WAREHOUSE/'runtime'/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['candidate_sha256']:raise ValueError('Warehouse candidate changed')
        install(name,raw,row['source_sha256'])
    raw=(ROOT/'tio/warehouse_completion.py').read_bytes()
    if hashlib.sha256(raw).hexdigest()!='cd36b1ae9a3eb6efc116c507234d85d95798b0cfd7200cc77a61d6bb29b209a3':raise ValueError('Warehouse helper changed')
    install('tio/warehouse_completion.py',raw,None)
    name='tio/clan_benefits.py';raw=(FOLDER/'runtime'/name).read_bytes();value=raw.decode('utf-8').replace('\r\n','\n')
    value=replace(value,"ET.parse(ROOT/'config/battle_item_catalog_extension.xml')","ET.parse(ROOT/'evidence/items_diagnostic.xml')")
    install(name,value.encode(),files[name]['before'])
    pins_raw=(SOCIAL/'source-pins.json').read_bytes()
    if hashlib.sha256(pins_raw).hexdigest()!='e659436abf3177c826c7884b6442784292e1a0a4aa0de69bc8986c8d261e97a9':raise ValueError('Social proof changed')
    for name,row in json.loads(pins_raw).items():
        if name=='server/economy_runtime.py':continue
        if hashlib.sha256((FOLDER/'runtime'/name).read_bytes()).hexdigest()!=row['source_sha256']:raise ValueError('Social public base differs')
        raw=(SOCIAL/'runtime'/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['candidate_sha256']:raise ValueError('Social source differs')
        install(name,raw,row['source_sha256'])
    social=json.loads((SOCIAL/'validation.json').read_text(encoding='utf-8'))
    for name in ('tio/social_completion.py','server/social_commands.py','config/social_completion.json'):
        raw=(ROOT/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=social['files'][name]:raise ValueError('Social helper differs')
        install(name,raw,None)
    proof=json.loads((SERVICES/'validation.json').read_text(encoding='utf-8'))
    if not proof['passed'] or proof['tests']!=33 or not proof['source_unchanged']:raise ValueError('Services focused proof required')
    for name,digest in proof['source_sha256'].items():
        raw=(SERVICES/'runtime'/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Services candidate changed')
        if (FOLDER/'runtime'/name).exists():raise ValueError('Services expected new file')
        install(name,raw,None)
    for name in ('server/city_services.py','server/services_runtime.py'):
        install(name,(ROOT/name).read_bytes(),None)
    name='server/city_http.py';raw=(FOLDER/'runtime'/name).read_bytes();prior=hashlib.sha256(raw).hexdigest();value=raw.decode('utf-8').replace('\r\n','\n')
    value=replace(value,"if self.path not in ('/v1/city/status', '/v1/city/action'):","if self.path not in ('/v1/city/status', '/v1/city/action', '/v2/services/status', '/v2/services/action'):")
    value=replace(value,"result=service.operations.status(data) if self.path=='/v1/city/status' else service.operations.action(data)","""if self.path.startswith('/v2/services/'):
                        from .services_runtime import service as services
                        manager=services(service.router)
                        result=manager.status(data) if self.path.endswith('/status') else manager.action(data)
                    else:result=service.operations.status(data) if self.path=='/v1/city/status' else service.operations.action(data)""")
    install(name,value.encode(),prior)
    name='server/bank_gateway.py';raw=(FOLDER/'runtime'/name).read_bytes();prior=hashlib.sha256(raw).hexdigest();value=raw.decode('utf-8').replace('\r\n','\n')
    value=replace(value,"def forward_city(data, endpoint):","def forward_city(data, endpoint,*,services=False):")
    value=replace(value,"Request('http://127.0.0.1:8083/v1/city/'+endpoint", "Request('http://127.0.0.1:8083/'+('v2/services/' if services else 'v1/city/')+endpoint")
    value=replace(value,"def city_payload(action=False):","def city_payload(action=False,*,services=False):")
    value=replace(value,"try:data=validate_payload(decode_json(raw),action=action)","""try:
            if services:
                from .city_services import validate
                data=validate(decode_json(raw),action=action)
            else:data=validate_payload(decode_json(raw),action=action)""")
    marker="    @app.post('/v1/clan/status')"
    extra="""    @app.post('/v2/services/status')
    def services_status():return forward_city(city_payload(services=True),'status',services=True)

    @app.post('/v2/services/action')
    def services_action():return forward_city(city_payload(action=True,services=True),'action',services=True)

"""
    value=replace(value,marker,extra+marker);install(name,value.encode(),prior)
    name='server/economy_runtime.py';raw=(FOLDER/'runtime'/name).read_bytes();prior=hashlib.sha256(raw).hexdigest();value=raw.decode('utf-8').replace('\r\n','\n')
    value=replace(value,"        self.auction.tick()","        self.auction.tick()\n        from .services_runtime import tick as services_tick\n        services_tick(router)")
    value=replace(value,"    return bool(words and words[0] in ('!bank','!sc','!base','!assault'))","    return bool(words and words[0] in ('!bank','!sc','!base','!assault','/changename'))")
    value=replace(value,"'!assault','/changename'","'!assault','/changename','!clan'")
    value=replace(value,"            if text.strip().casefold().split(maxsplit=1)[:1]==['!assault']:","""            if text.startswith('/changename '):
                from .services_runtime import native
                return native(session,command=text)
            if text.strip().casefold().split(maxsplit=1)[:1]==['!clan']:
                from .social_commands import command
                return command(db,session,text,city_idle=allowed)
            if text.strip().casefold().split(maxsplit=1)[:1]==['!assault']:""")
    install(name,value.encode(),prior)
    name='tools/loopback_exchange.py';raw=(FOLDER/'runtime'/name).read_bytes();prior=hashlib.sha256(raw).hexdigest();value=raw.decode('utf-8').replace('\r\n','\n')
    value=replace(value,"                            reply=self.hiring.dismiss(self.account,decode_dismiss_request(packet))","                            from server.services_runtime import native\n                            replies=native(self,pet_id=decode_dismiss_request(packet))")
    value=replace(value,"                            replies=(reply,)+tuple(r[2] for r in OwnedPetStore(self.database).list(self.account))\n                            self.events.append({'event':'dismiss_committed'","                            self.events.append({'event':'dismiss_scheduled'")
    install(name,value.encode(),prior)
    for filename,content in (('candidate-manifest.json',dict(version=1,utc=datetime.now(timezone.utc).isoformat(),files=files,local_private_contracts_included=False)),('candidate-overrides.json',overrides),('runtime-files.json',sorted(files))):
        (FOLDER/filename).write_text(json.dumps(content,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(frozen_files=len(files),services_version=2,city_version1_unchanged=True)))

if __name__=='__main__':main()
