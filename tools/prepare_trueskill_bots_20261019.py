"""Bounded edits on inspected hosting; retain all newer hosted TrueSkill rules."""
import difflib,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/trueskill-bots-20261019';OUT=ROOT/'reports/trueskill-bots-20261019'
FILES=('server/ranked_bots.py','server/ranked_arena.py','server/team_arena.py')

def once(source,old,new):
    assert source.count(old)==1,old
    return source.replace(old,new)

def common(name,source):
    source=source.replace('\r\n','\n')
    if name=='server/ranked_arena.py':
        source=once(source,'        score=lambda t:ranked.skill(*ranked.snapshot(self.players[t.character_id].database,self.players[t.character_id].account))',
            "        scores={}\n        def score(t):\n            if t.character_id not in scores:\n                s=self.players[t.character_id]\n                scores[t.character_id]=ranked.skill(*ranked.snapshot(s.database,s.account))\n            return scores[t.character_id]")
        anchor='        proposal=SimpleNamespace(mode=21,'
        source=once(source,anchor,'        from .ranked_bots import fill_seats\n        bots=fill_seats(self,seats,teams)\n'+anchor)
        source=source.replace('mode=21,soldiers=','mode=21,soldiers=4 if bots else ')
        source=once(source,'self.start_match(proposal,seats,teams,set(),','self.start_match(proposal,seats,teams,bots,')
        source=once(source,"if 'ranked_winner' not in battle:return None", "if battle.get('bots') or 'ranked_winner' not in battle:return None")
    elif name=='server/team_arena.py':
        source=once(source,"if points is not None and points.outcome(field) is not None:",
            "if points is not None and (battle.get('ranked_winner') is not None or points.outcome(field) is not None):")
        source=once(source,"winner=battle['points'].outcome(battle['field'])",
            "winner=battle.get('ranked_winner',battle['points'].outcome(battle['field']))")
        source=once(source,'if bot and first.mode in (0,1,4) and not wagering}',
            'if bot and first.mode in (0,1,4,21) and not wagering}')
        guard=next(line.strip() for line in source.splitlines() if 'if bots or len(seats)' in line)
        source=once(source,guard,
            "if any(not any(s[1]==side and not s[5] for s in seats) for side in (0,1)):\n                raise ValueError('Ranked matches require real accounts on both sides')")
        anchor="            battle['ranked_teams']=tuple(tuple("
        line=next(s for s in source.splitlines() if s.startswith(anchor))
        source=once(source,line,line.replace('for o in team)','for o in team if o not in bots)'))
        anchor='        battle[\'return_towns\']='
        source=once(source,anchor,"        if first.mode==21 and bots:\n            from .ranked_bots import patrol\n            patrol(field,battle['points'])\n"+anchor)
        source=once(source,'for o in order}\n                self.put(owner,encode_accepted',
            'for o in order if o not in bots}\n                ratings.update((o,0) for o in bots)\n                self.put(owner,encode_accepted')
        source=once(source,"            self.put(owner,*self.team_rating_announcements(battle,owner))",
            "            if first.mode==21 and bots:\n                from tio.protocol.chat import encode_system_message\n                self.put(owner,encode_system_message(0,b'TIO','Свободные места заполнены ботами. Этот бой не изменяет TrueSkill.'))\n            self.put(owner,*self.team_rating_announcements(battle,owner))")
        source=once(source,"            self.announce_turn(battle,owner,40)\n            play_turn(",
            "            self.announce_turn(battle,owner,40)\n            if points is not None:battle['point_turn_pending']=True\n            play_turn(")
    elif name=='tio/team_scene.py':
        source=once(source,'    deployment_size=max(3,len(seats)//2*size)',
            '    deployment_size=(max(3,max(sum(len(s[4].actors) for s in seats if s[1]==side)\n        for side in {s[1] for s in seats})) if ranked else max(3,len(seats)//2*size))')
    return source

def main():
    review={};patch=[]
    for name in FILES:
        before=(WORK/'baseline'/name).read_bytes() if (WORK/'baseline'/name).exists() else None
        source=(ROOT/name).read_text(encoding='utf-8') if before is None else before.decode()
        if name=='server/ranked_arena.py':
            start=source.index('            # Explicit low-population policy:');end=source.index('        tickets=tuple',start)
            source=source[:start]+"            from .ranked_bots import incomplete_groups\n            groups=incomplete_groups(states,score)\n            if groups is None:return\n"+source[end:]
        if before is not None:source=common(name,source)
        after=source.encode();dest=WORK/'candidate'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(after)
        review[name]=dict(before=hashlib.sha256(before).hexdigest() if before is not None else None,after=hashlib.sha256(after).hexdigest())
        patch.extend(difflib.unified_diff((before.decode().replace('\r\n','\n') if before else '').splitlines(True),source.splitlines(True),fromfile='hosted-before/'+name,tofile='candidate/'+name))
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2));(OUT/'server-changes.diff').write_text(''.join(patch),encoding='utf-8')
    # Apply only shared bounded edits to the older local checkout as well.
    for name in (*FILES[1:],'tio/team_scene.py'):
        path=ROOT/name;raw=path.read_bytes();backup=WORK/'local-before'/name
        if not backup.exists():
            backup.parent.mkdir(parents=True,exist_ok=True);backup.write_bytes(raw)
        original=backup.read_bytes();updated=common(name,original.decode()).encode()
        assert raw in (original,updated),'Local file changed after preparation: '+name
        path.write_bytes(updated)
    print(json.dumps(dict(files=list(FILES),hosted_baseline=True,local_preimages_saved=True)))

if __name__=='__main__':main()
