"""Freeze reviewed shops over the published city runtime, excluding local contracts."""
from datetime import datetime,timezone
import hashlib,json,shutil
from pathlib import Path
from tools.deploy_gameplay_completion import valid_path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports/gameplay-completion/stage9-city'
DELIVERY=ROOT/'reports/gameplay-followup/stage2-shops'
FOLDER=ROOT/'reports/gameplay-completion/stage10-shops-r2'

def replace_once(value,old,new):
    if value.count(old)!=1:raise ValueError('Reviewed protocol boundary changed')
    return value.replace(old,new)

def main():
    if (FOLDER/'candidate-manifest.json').exists():raise ValueError('Preserve prior revision')
    proof=json.loads((DELIVERY/'validation.json').read_text(encoding='utf-8'))
    if proof['automated_tests']['test_shop_completion']['status']!='PASS':raise ValueError('Focused proof required')
    before=json.loads((DELIVERY/'source-manifest.json').read_text(encoding='utf-8'))['source_sha256']
    shutil.copytree(BASE/'runtime',FOLDER/'runtime',ignore=shutil.ignore_patterns('__pycache__'))
    overrides={name:value for name,value in json.loads((BASE/'candidate-overrides.json').read_text(encoding='utf-8')).items() if valid_path(name)}
    source_map={n:ROOT/n for n in ('tio/shop_completion.py','config/shop_completion.json')}
    source_map.update({n:DELIVERY/'runtime'/n for n in ('tio/shop.py','tio/sc_shop.py')})
    files={}
    for name,source in source_map.items():
        raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        if digest!=proof['files'][source.relative_to(ROOT).as_posix()]:raise ValueError('Frozen shop source changed')
        old=FOLDER/'runtime'/name
        if name in before and hashlib.sha256(old.read_bytes()).hexdigest()!=before[name]:raise ValueError('Public shop base differs')
        target=FOLDER/'runtime'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        files[name]=dict(source='runtime/'+name,sha256=digest,before=before.get(name));overrides[name]='runtime/'+name
    name='tools/loopback_exchange.py';target=FOLDER/'runtime'/name
    raw=target.read_bytes();prior=hashlib.sha256(raw).hexdigest()
    if prior!='ca4db94bb36fa04857f55f585d9a2448e2c6b7a50fd5275e0e01a809c93b7d63':raise ValueError('Published protocol source differs')
    value=raw.decode('utf-8').replace('\r\n','\n')
    value=replace_once(value,"if packet[:1]==b'\\x73':reply=self.catalogs.item_shop(packet[1],discounted=discounted)","if packet[:1]==b'\\x73':reply=ShopStore(self.database,self.catalogs).catalog(self.account,packet[1],discounted=discounted)")
    value=replace_once(value,"reply=self.catalogs.premium_shop(decode_premium_request(packet),discounted=discounted)","reply=ShopStore(self.database,self.catalogs).catalog(self.account,decode_premium_request(packet),gold=True,discounted=discounted)")
    old="""                            self.owned_inventory=result.inventory
                            for reply in (result.inventory,encode_asset_count(result.assets)):
                                game.sendall(encode_reply(reply,outbound))
                                self.events.append({'direction':'S2C','stage':'shop_purchase_update','plain_hex':reply.hex()})"""
    new="""                            self.owned_inventory=result.inventory
                            from tio.premium import current
                            from tio.protocol.premium_shop import decode_premium_purchase
                            category=(decode_premium_purchase(packet)[1] if packet[:1]==b'\\x78'
                                      else decode_shop_purchase(packet).category)
                            refreshed=store.catalog(self.account,category,gold=packet[:1]==b'\\x78',
                                                    discounted=bool(current(self.database,self.account)[0]))
                            for reply in (result.inventory,encode_asset_count(result.assets),refreshed):
                                game.sendall(encode_reply(reply,outbound))
                                self.events.append({'direction':'S2C','stage':'shop_purchase_update','plain_hex':reply.hex()})"""
    value=replace_once(value,old,new);compile(value,name,'exec');target.write_text(value,encoding='utf-8',newline='\n')
    files[name]=dict(source='runtime/'+name,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),before=prior)
    overrides[name]='runtime/'+name
    for filename,content in (('candidate-manifest.json',dict(version=1,utc=datetime.now(timezone.utc).isoformat(),files=files,local_private_contracts_included=False)),('candidate-overrides.json',overrides),('runtime-files.json',sorted(files))):
        (FOLDER/filename).write_text(json.dumps(content,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(frozen_files=len(files),private_contracts_included=False)))

if __name__=='__main__':main()
