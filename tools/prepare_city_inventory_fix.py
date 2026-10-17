"""Freeze the observed fresh-city item decoder fix over the actual public tree."""
import hashlib,json,shutil
from pathlib import Path
from tools.deploy_gameplay_completion import ROOT

def main():
    base=ROOT/'reports/gameplay-completion/stage12-release'
    folder=ROOT/'reports/gameplay-completion/stage12-city-item-fix'
    if folder.exists():raise ValueError('Preserve previous release')
    shutil.copytree(base/'runtime',folder/'runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    name='tools/loopback_exchange.py';path=folder/'runtime'/name;before=path.read_bytes()
    marker=b'    def observe_game(self,game,reader,outbound):\n'
    if marker not in before:marker=marker.replace(b'\n',b'\r\n')
    if before.count(marker)!=1:raise ValueError('Observed public handler boundary changed')
    newline=b'\r\n' if marker.endswith(b'\r\n') else b'\n'
    raw=before.replace(marker,marker+b'        from tio.protocol.item_list import decode_item_list'+newline)
    compile(raw,name,'exec');path.write_bytes(raw)
    entries={name:dict(source='runtime/'+name,before=hashlib.sha256(before).hexdigest(),sha256=hashlib.sha256(raw).hexdigest())}
    for filename,value in [('candidate-manifest.json',dict(version=1,files=entries,local_private_contracts_included=False,reason='Observed UnboundLocalError on native city item action33 without prior mining/training')),
                           ('candidate-overrides.json',{name:'runtime/'+name}),('runtime-files.json',[name])]:
        (folder/filename).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(files=1,before=entries[name]['before'],after=entries[name]['sha256'])))

if __name__=='__main__':main()
