"""Read deployed sources and remove only appended Team/Wall Name decorations."""
from pathlib import Path
import ast,difflib,hashlib,json,re,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote,INSPECT
BASE=ROOT/'reports/gameplay-completion/legacy-status-20261011/runtime-native-lobby-departure'
OUT=BASE.parent/'runtime-native-lobby-original-names'
PINS={'server/team_arena.py':'21ac51dfa56a8f868e222ab6b07725b03777dd4b63859d454c6cc37827f1c761',
      'server/wager_arena.py':'a26bd6a66968492e12cbe9747662beb85a6741ca77d53a03ea68256a3401a99e'}
def sha(data):return hashlib.sha256(data).hexdigest()

def changes(name,text):
    if name=='server/team_arena.py':
        snippets=[("""            state='поиск' if r.searching else 'занято' if len(r.members)>=r.capacity else 'свободно'
            suffix=f' · {state} {len(r.members)}/{r.capacity}'.encode('cp1251')
            name=self.players[r.captain].probe_character_name[:255-len(suffix)]+suffix
""","            name=self.players[r.captain].probe_character_name\n"),
        ("""            occupied=room.searching or len(room.members)>=room.capacity
            state='поиск' if room.searching else 'занято' if occupied else 'свободно'
            suffix=f' · {state} {len(room.members)}/{room.capacity}'.encode('cp1251')
            name=self.players[room.captain].probe_character_name[:255-len(suffix)]+suffix
""","            name=self.players[room.captain].probe_character_name\n")]
    else:
        old="""                occupied=r.starts_at is not None or len(r.members)>=r.capacity
                state='занято' if occupied else 'свободно'
                suffix=f' · {state} {len(r.members)}/{r.capacity}'.encode('cp1251')
                name=name[:255-len(suffix)]+suffix
"""
        assert text.count(old)==2
        snippets=[(old,'')]
    for old,new in snippets:
        assert text.count(old)==(2 if name=='server/wager_arena.py' else 1)
        text=text.replace(old,new)
    return text

def qa_text(path):
    """Replace name assertions with exact captain equality, retaining all state checks."""
    text=path.read_text(encoding='utf8');tree=ast.parse(text);lines=text.splitlines(keepends=True);edits=[]
    for node in ast.walk(tree):
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
        for sub in ast.walk(node):
            if not isinstance(sub,ast.Expr) or not isinstance(sub.value,ast.Call):continue
            call=sub.value
            if not isinstance(call.func,ast.Attribute) or not call.func.attr.startswith('assert'):continue
            before=''.join(lines[sub.lineno-1:sub.end_lineno])
            if not any(word in before for word in ('свободно','занято','поиск')):continue
            # Public Name remains the exact original captain, including long bytes.
            if 'long_' in node.name or 'truncation' in node.name:
                target='name';expected="self.sessions[0].probe_character_name"
            elif 'rows[1].name' in before:target='rows[1].name';expected="b'bob'"
            elif 'rows[0].name' in before:target='rows[0].name';expected="b'alice'"
            elif 'row.creator_name' in before:target='row.creator_name';expected="b'alice'"
            elif 'record.creator_name' in before:target='record.creator_name';expected="b'alice'"
            elif 'records[0].creator_name' in before:target='records[0].creator_name';expected="b'alice'"
            elif 'self.listed()[0].creator_name' in before:target='self.listed()[0].creator_name';expected="b'alice'"
            elif 'self.listing()[0].creator_name' in before:target='self.listing()[0].creator_name';expected="b'alice'"
            elif 'row.name' in before:target='row.name';expected="b'alice'"
            else:raise AssertionError((path.name,node.name,before))
            edits.append((sub.lineno-1,sub.end_lineno,' '*sub.col_offset+f'self.assertEqual({target},{expected})\n'))
    for start,end,new in sorted(edits,reverse=True):lines[start:end]=[new]
    result=''.join(lines);compile(result,str(path),'exec');return result,len(edits)

def main():
    assert sha((BASE/'validation-final.json').read_bytes())=='bad17bc2b4c30bb58f88960f7c5e2ca0bf6717331cf337adc839ee59c207e697'
    actual=remote(INSPECT,{'files':list(PINS)})
    OUT.mkdir(parents=True,exist_ok=True);before={};after={}
    for name,expected in PINS.items():
        raw=actual[name]['source'].encode('utf8');assert actual[name]['sha256']==expected==sha(raw)
        assert raw==(BASE/'runtime'/name).read_bytes()==(BASE/'isolated-runtime'/name).read_bytes()
        old=raw.decode('utf8');new=changes(name,old);candidate=new.encode('utf8');compile(candidate,name,'exec')
        for sub,data in (('deployed-source',raw),('runtime',candidate)):
            target=OUT/sub/name;target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():assert target.read_bytes()==data
            else:target.write_bytes(data)
        before[name]=expected;after[name]=sha(candidate)
        (OUT/(Path(name).stem+'.diff')).write_text(''.join(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),fromfile='actual deployed '+expected,tofile='plain original captain Name only')),encoding='utf8')
    stage=OUT/'isolated-runtime'
    if not stage.exists():shutil.copytree(BASE/'isolated-runtime',stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in PINS:(stage/name).write_bytes((OUT/'runtime'/name).read_bytes())
    qa=OUT/'qa-tests';qa.mkdir(exist_ok=True);expectations={}
    for name in ('test_native_arena_group_rows.py','test_native_team_lobby_list.py','test_native_wager_lobby_captions.py'):
        text,count=qa_text(stage/'tests'/name);(qa/name).write_text(text,encoding='utf8');expectations[name]=dict(exact_captain_name_assertions=count,source_sha256=sha((stage/'tests'/name).read_bytes()),adjusted_qa_sha256=sha((qa/name).read_bytes()))
    (qa/'test_native_lobby_departure_tcp.py').write_bytes((ROOT/'tools/test_native_lobby_departure_tcp.py').read_bytes())
    modules=sorted(set(re.findall(r'\((test_[^.]+)\.',(BASE/'isolated-tests-final.log').read_text())))
    report=dict(passed=True,source_sha256=before,candidate_sha256=after,source_runtime=str(BASE/'isolated-runtime'),test_modules=modules,
                actual_hosted_source_read=True,read_only_remote_inspection=True,inherited_111_proof_sha256=sha((BASE/'validation-final.json').read_bytes()),
                name_expectation_updates=expectations,isolated_runtime_tests_unchanged=True,
                only_new_change='Remove appended status/count from Team/Wall ordinary and Wager modes1/4 BA02/C82C creator Name; all slots/status/departure27/admission untouched',
                hosted_modified=False,hosted_player_data_opened=False,published=False)
    (OUT/'candidate.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps(report))
if __name__=='__main__':main()
