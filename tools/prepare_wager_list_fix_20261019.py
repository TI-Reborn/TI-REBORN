"""Small list-delivery changes on the freshly inspected server, preserving gameplay."""
import difflib,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
WORK=ROOT/'work/wager-list-fix-20261019';OUT=ROOT/'reports/wager-list-fix-20261019'
FILES=('server/wager_arena.py','server/team_arena.py','tio/protocol/wagers.py')

def once(source,old,new):
    assert source.count(old)==1,old
    return source.replace(old,new)

def main():
    review={};diff=[]
    for name in FILES:
        before=(WORK/'baseline'/name).read_bytes();source=before.decode().replace('\r\n','\n')
        local=(ROOT/name).read_text(encoding='utf-8')
        if name=='server/wager_arena.py':
            start=local.index('    def push_battle_listing(');end=local.index('    def cancel_wager_start(',start)
            source=once(source,'    def cancel_wager_start(',local[start:end]+'    def cancel_wager_start(')
            source=once(source,"            elif packet == b'\\xba\\x01': self.put(owner,self.list_packet(owner),self.wager_list_packet(owner))",
                "            elif packet == b'\\xba\\x01':\n                self.put(owner,self.list_packet(owner))\n                self.push_battle_listing(owner,self.battle_list_packet(owner),reset=True)")
        elif name=='server/team_arena.py':
            source=once(source,'                    self.put(owner,listing,self.battle_list_packet(owner))',
                '                    self.put(owner,listing)\n                    self.push_battle_listing(owner,self.battle_list_packet(owner),reset=True)')
            source=once(source,'                if self.wager_listing_cache.get(owner)!=listing:\n                    self.put(owner,listing);self.wager_listing_cache[owner]=listing',
                '                self.push_battle_listing(owner,listing)')
        else:
            start=local.index('def encode_room_removed(');end=local.index('def _identity(',start)
            source=once(source,'def _identity(',local[start:end]+'def _identity(')
        raw=source.encode();path=WORK/'candidate'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        review[name]=dict(before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(raw).hexdigest())
        diff.extend(difflib.unified_diff(before.decode().replace('\r\n','\n').splitlines(True),source.splitlines(True),fromfile='hosted-before/'+name,tofile='candidate/'+name))
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2));(OUT/'server-changes.diff').write_text(''.join(diff),encoding='utf-8')
    print(json.dumps(dict(files=list(FILES),hosted_baseline=True)))

if __name__=='__main__':main()
