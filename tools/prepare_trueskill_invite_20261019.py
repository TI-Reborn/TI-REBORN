"""Apply bounded party integration to the actual inspected multiplayer runtime."""
import difflib,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
WORK=ROOT/'work/trueskill-invite-20261019';OUT=ROOT/'reports/trueskill-invite-20261019'
FILES=('server/ranked_party.py','tio/protocol/ranked_party.py','server/ranked_arena.py','server/team_arena.py')
def once(source,old,new):
    assert source.count(old)==1,old
    return source.replace(old,new)

def main():
    review={};diff=[]
    for name in FILES:
        path=WORK/'baseline'/name;before=path.read_bytes() if path.exists() else None
        source=(before or b'').decode().replace('\r\n','\n')
        if name.endswith('ranked_party.py'):source=(ROOT/name).read_text(encoding='utf-8')
        elif name=='server/ranked_arena.py':
            source=once(source,"            if packet==b'\\xc6\\x23':", "            if packet==b'\\xc6\\x23':\n                from .ranked_party import party,cancel,notify\n                group=party(self,owner)\n                if group is not None and owner not in self.battles and owner not in self.results:\n                    if any(o in self.ranked_waiting for o in group.members):\n                        cancel(self,group);notify(self,group)\n                    elif owner in group.tickets:\n                        group.tickets.pop(owner,None);notify(self,group)\n                    return True")
            source=once(source,'            prior=self.ranked_waiting.get(owner)', '            from .ranked_party import submit\n            if submit(self,owner,ticket):return True\n            prior=self.ranked_waiting.get(owner)')
            source=once(source,'            self.ranked_waiting.pop(owner,None)\n            self.put(owner,encode_shop_error', '            from .ranked_party import party,cancel,notify\n            group=party(self,owner)\n            if group is not None:cancel(self,group);notify(self,group)\n            else:self.ranked_waiting.pop(owner,None)\n            self.put(owner,encode_shop_error')
            source=once(source,'        # Prefer the closest current rating, then queue age.', '        from .ranked_party import units\n        candidates=units(self,candidates)\n        # Prefer the closest current rating, then queue age.')
            source=once(source,'        tickets=tuple(t for group in groups for t in group)', '        groups=tuple(tuple(t for unit in group for t in getattr(unit,\'members\',(unit,))) for group in groups)\n        tickets=tuple(t for group in groups for t in group)')
            source=once(source,'        self.start_match(proposal,seats,teams,bots,lambda:[self.ranked_waiting.pop(t.character_id,None) for t in tickets])', '        from .ranked_party import consumed\n        self.start_match(proposal,seats,teams,bots,lambda:consumed(self,tickets))')
        else:
            source=once(source,'            return self.mine_waiting(owner) or owner in self.ranked_waiting', "            return owner in getattr(self,'ranked_parties',{}) or self.mine_waiting(owner) or owner in self.ranked_waiting")
            source=once(source,"            if self.handle_wager(owner,packet):", "            from .ranked_party import handle as handle_party,party\n            if handle_party(self,owner,packet):return True\n            if party(self,owner) is not None and (packet[:1] in (b'\\xba',b'\\x29') or packet[:2]==b'\\xc8\\x2b'):\n                self.put(owner,encode_shop_error('Сначала выйдите из группы TrueSkill'));return True\n            if self.handle_wager(owner,packet):")
            source=once(source,'            if owner is not None:self.arena_listing_cache.pop(owner,None)', '            if owner is not None:\n                from .ranked_party import leave as leave_party\n                leave_party(self,owner)\n                self.arena_listing_cache.pop(owner,None)')
        raw=source.encode();dest=WORK/'candidate'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
        review[name]=dict(before=hashlib.sha256(before).hexdigest() if before is not None else None,after=hashlib.sha256(raw).hexdigest())
        diff.extend(difflib.unified_diff((before or b'').decode().replace('\r\n','\n').splitlines(True),source.splitlines(True),fromfile='hosted-before/'+name,tofile='candidate/'+name))
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2));(OUT/'server-changes.diff').write_text(''.join(diff),encoding='utf-8')
    print(json.dumps(dict(files=list(FILES),hosted_baseline=True)))

if __name__=='__main__':main()
