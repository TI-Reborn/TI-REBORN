"""Isolate a BA02 live projection candidate; never touch hosted/native clients."""
from pathlib import Path
import difflib,hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-original-names'
F=BASE.parent/'runtime-native-lobby-live-projection'
PINS={'server/team_arena.py':'629285f4eef601f873a2f95451c65690f701d5f1fd0302e680469aaccc9cfe24',
      'server/wager_arena.py':'c3e66966c03ebd87900fa6d654d206c503778f7409c82db82a98cf2a1d9e7271'}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def once(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new)
def main():
    assert not F.exists(),'Preserve prior candidate evidence'
    qualification=(BASE/'validation-final.json').read_bytes()
    assert sha(qualification)=='900f0bb127305420086cf7eaf111d4d5f27d84bddd8015c888c04db88e886382'
    F.mkdir();shutil.copytree(BASE/'isolated-runtime',F/'isolated-runtime');shutil.copytree(BASE/'qa-tests',F/'qa-tests')
    raws={name:(BASE/'runtime'/name).read_bytes() for name in PINS}
    assert {name:sha(raw) for name,raw in raws.items()}==PINS
    text=raws['server/team_arena.py'].decode('utf8')
    text=once(text,'ArenaRoom, encode_room_list)','ArenaRoom, encode_room_list, decode_room_list)')
    text=once(text,'        self.wager_listing_cache={}\n','        self.wager_listing_cache={}\n        self.arena_listing_cache={}\n')
    text=once(text,'    def battle_list_packet(self, owner):',
'''    def remember_arena_listing(self, owner, packet):
        """BA02 is a merge; retain IDs to send native BA06 deletions."""
        snapshot=(packet,frozenset(r.unknown_u32_00 for r in decode_room_list(packet)))
        self.arena_listing_cache[owner]=snapshot
        return snapshot

    def battle_list_packet(self, owner):''')
    text=once(text,'            if self.handle_wager(owner,packet):return True',
'''            if self.handle_wager(owner,packet):
                if packet==b'\\xba\\x01':
                    try:self.remember_arena_listing(owner,self.list_packet(owner))
                    except ValueError:pass
                return True''')
    text=once(text,"                if packet==b'\\xba\\x01':self.put(owner,self.list_packet(owner),self.battle_list_packet(owner));return True",
'''                if packet==b'\\xba\\x01':
                    listing=self.list_packet(owner)
                    self.put(owner,listing,self.battle_list_packet(owner))
                    self.remember_arena_listing(owner,listing)
                    return True''')
    text=once(text,'                if self.wager_listing_cache.get(owner)!=listing:',
'''                try:arena_listing=self.list_packet(owner)
                except ValueError:arena_listing=None
                previous=self.arena_listing_cache.get(owner)
                if arena_listing is not None and (previous is None or previous[0]!=arena_listing):
                    current_ids=frozenset(r.unknown_u32_00 for r in decode_room_list(arena_listing))
                    deleted=() if previous is None else sorted(previous[1]-current_ids)
                    self.put(owner,*(b'\\xba\\x06'+identity.to_bytes(4,'little') for identity in deleted),arena_listing)
                    self.remember_arena_listing(owner,arena_listing)
                if self.wager_listing_cache.get(owner)!=listing:''')
    text=once(text,'            if owner is not None and self.detach(session,owner):return True',
'''            if owner is not None:self.arena_listing_cache.pop(owner,None)
            if owner is not None and self.detach(session,owner):return True''')
    raws['server/team_arena.py']=text.encode('utf8')
    for name,raw in raws.items():
        path=F/'runtime'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        (F/'isolated-runtime'/name).write_bytes(raw)
        path=F/'qualified-source'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((BASE/'runtime'/name).read_bytes())
        diff=''.join(difflib.unified_diff((BASE/'runtime'/name).read_text(encoding='utf8').splitlines(True),raw.decode('utf8').splitlines(True),fromfile='qualified/'+name,tofile='candidate/'+name))
        (F/(Path(name).name+'.diff')).write_text(diff,encoding='utf8',newline='')
    report=dict(source_sha256=PINS,candidate_sha256={name:sha(raw) for name,raw in raws.items()},
                inherited_111_proof_sha256=sha(qualification),native_DLL_unchanged=True,
                scope='BA02 merge snapshot cache and BA06 deletion before BA02 on changed idle-city lists; initial BA01 cache and disconnect cleanup. C82C bytecache and all wire codecs unchanged.',
                published=False,hosted_modified=False)
    (F/'candidate.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report))
if __name__=='__main__':main()
