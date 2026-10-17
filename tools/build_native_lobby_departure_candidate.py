"""Isolate actual-hosted Team/Wall BA02 candidate plus native27 departure fix."""
from pathlib import Path
import difflib,hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-list'
OUT=BASE.parent/'runtime-native-lobby-departure'
TEAM_SHA='ebe6fd67775dbb387996f62b59e780f38fb8f709f99389cbe2147e38a3a39b39'
WAGER_SHA='694c6fd7051fe9616440b2f6bc803bf17466e137f878c5c564757b00d9b459ba'
OLD='''        remaining={r.identity:r for member in affected if (r:=self.lobbies.room(member)) is not None}
        for room in remaining.values():self.notify(room)
'''
NEW='''        remaining={r.identity:r for member in affected if (r:=self.lobbies.room(member)) is not None}
        # Native25 merges slots even with flag0; absent members are not erased.
        # Native27 removes the public member ID already shown to each survivor.
        departed=tuple(member for member in affected if self.lobbies.room(member) is None)
        for room in remaining.values():
            for member in room.members:
                for removed in departed:self.put(member,b'\\x27'+removed.to_bytes(4,'little'))
            self.notify(room)
'''
WAGER_OLD='''        if self.wager_lobbies.rooms.get(room.identity) is room: self.wager_notify(room)
        return True
'''
WAGER_NEW='''        if self.wager_lobbies.rooms.get(room.identity) is room:
            if room.mode in (1,4):
                # Native Team/Wall25 merges; explicitly clear departed slots first.
                for member in room.members:self.put(member,b'\\x27'+chosen.to_bytes(4,'little'))
            self.wager_notify(room)
        return True
'''
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
 original=(BASE/'runtime/server/team_arena.py').read_bytes()
 wager=(BASE/'runtime/server/wager_arena.py').read_bytes()
 assert sha(original)==TEAM_SHA and sha(wager)==WAGER_SHA
 text=original.decode('utf8');assert text.count(OLD)==1
 candidate=text.replace(OLD,NEW).encode('utf8')
 wager_text=wager.decode('utf8');assert wager_text.count(WAGER_OLD)==1
 wager_candidate=wager_text.replace(WAGER_OLD,WAGER_NEW).encode('utf8')
 OUT.mkdir(parents=True,exist_ok=True);target=OUT/'runtime/server/team_arena.py';target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():assert target.read_bytes()==candidate,'Immutable candidate differs'
 else:target.write_bytes(candidate)
 wager_target=target.with_name('wager_arena.py')
 if wager_target.exists():assert wager_target.read_bytes()==wager_candidate,'Immutable Wager candidate differs'
 else:wager_target.write_bytes(wager_candidate)
 (OUT/'team_arena.diff').write_text(''.join(difflib.unified_diff(text.splitlines(keepends=True),candidate.decode().splitlines(keepends=True),fromfile='BA02 candidate ebe6',tofile='BA02 plus ordinary departure27')),encoding='utf8')
 (OUT/'wager_arena.diff').write_text(''.join(difflib.unified_diff(wager_text.splitlines(keepends=True),wager_candidate.decode().splitlines(keepends=True),fromfile='BA02 candidate694',tofile='BA02 plus Team/Wall departure27')),encoding='utf8')
 stage=OUT/'isolated-runtime'
 if not stage.exists():shutil.copytree(BASE/'isolated-runtime',stage)
 (stage/'server/team_arena.py').write_bytes(candidate)
 (stage/'server/wager_arena.py').write_bytes(wager_candidate)
 report=dict(source_sha256=TEAM_SHA,candidate_sha256=sha(candidate),candidate_bytes=len(candidate),hosted_team_baseline_sha256='9f2303a8331c8bae0faa46b558a3884070ce2df0c658913a8f1b44ccf38ed773',wager_source_sha256=WAGER_SHA,wager_candidate_sha256=sha(wager_candidate),source_runtime=str(BASE/'isolated-runtime'),inherited_93_test_proof_sha256=sha((BASE/'validation-final.json').read_bytes()),only_new_change='Team/Wall leave/kick/disconnect survivors receive native27/public departed owner ID before unchanged native25 update; Wager modes other than1/4 unchanged',published=False,hosted_modified=False,hosted_player_data_opened=False)
 (OUT/'candidate.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
