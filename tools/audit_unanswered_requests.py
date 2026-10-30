"""Audit saved post-auth client requests and replay selected gaps in a temp DB.

Never replays captured mutations. Replay allowlist contains only the requests
listed below. Production database, client and server sources are untouched.
Counts describe saved historical logs, not unique sessions or live traffic.
"""
import contextlib,io,json,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.loopback_exchange import LoopbackExchange
from tio.protocol.transport import InitialCipher,InitialFrameReader,encode_initial_frame

CASES={
    '7600000000':'Gold purchase quote; handled',
    '820000':'Clan ratings/list subsystem; exact mode pending',
    'a405':'Player ratings',
    'af0e':'Alliance subsystem; exact request meaning pending',
    'b5010050726f62654e657700':'Achievements for ProbeNew',
    'b70d0100':'Mail subsystem; exact request meaning pending',
    'b804':'Marked items list C8/29; empty until marker ownership service exists',
    'b809':'Assault clan ranking B8/0A; not a warehouse operation',
    'b811':'Asset refresh C8/39; clears warehouse waiting',
    'c101':'Bond config request sent on Engine.EnterWorld; hosted securities_service replies C1/02',
    'c501':'Equipment templates',
    '5003':'Town/panel notification; roster refresh only after battle completion',
    '6901':'Clan warehouse; empty kind1 plus access unavailable',
    '6902':'Clan safe; empty kind2 plus access unavailable',
    '6903':'Postbox B7/75; empty until mail attachments exist',
    'b102':'Service catalog: empty configured response',
    'ba01':'Local fallback; hosted TeamArena intercepts real room browser',
    '70':'Control: ping',
}


def key(packet):
    return packet[:4] if int(packet[:2],16)>=0xaf else packet[:2]


def observations():
    stats={};files=[]
    for folder in ('data','evidence'):
        for path in sorted((ROOT/folder).glob('*.log')):
            if 'test' in path.stem or path.stem in ('recovery-focused','door-focused'):continue
            if path.stat().st_size>20_000_000:continue
            content=path.read_text(encoding='utf-8-sig',errors='replace')
            if '\0' in content[:100]:content=path.read_text(encoding='utf-16',errors='replace')
            saved=[];printed=[]
            for number,line in enumerate(content.splitlines(),1):
                if 'packets_hex' not in line and 'game_request' not in line:continue
                try:obj=json.loads(line)
                except ValueError:continue
                if isinstance(obj,list):
                    for event in obj:
                        if event.get('direction')=='C2S' and event.get('stage')=='after_auth2':
                            saved.extend((p,number) for p in event.get('packets_hex',()))
                elif isinstance(obj,dict) and obj.get('event')=='game_request':
                    printed.append((obj['plain_hex'],number))
            rows=saved or printed # avoid counting the same run's two log formats twice
            if rows:files.append(str(path.relative_to(ROOT)))
            for packet,number in rows:
                if not packet:continue
                row=stats.setdefault(key(packet),{'count':0,'files':set(),'variants':set(),'example':packet,
                    'source':str(path.relative_to(ROOT)),'line':number})
                row['count']+=1;row['files'].add(str(path.relative_to(ROOT)));row['variants'].add(packet)
    for row in stats.values():
        row['files']=sorted(row['files']);row['variants']=sorted(row['variants'])
    return files,dict(sorted(stats.items()))


class Wire:
    def __init__(self,packet):
        self.frames=iter((encode_initial_frame(packet,InitialCipher('C2S')),b''))
        self.reader=InitialFrameReader(InitialCipher('S2C'));self.replies=[]
    def recv(self,size):return next(self.frames)
    def settimeout(self,value):pass
    def sendall(self,data):self.replies.extend(p.hex() for p in self.reader.feed(data))


def replay(packet):
    with tempfile.TemporaryDirectory(prefix='tio-request-audit-') as tmp:
        exchange=LoopbackExchange(Path(tmp)/'events.json',database=Path(tmp)/'audit.db',
                                 open_town_probe=True,owned_pet_probe=True,observation_seconds=0)
        exchange.probe_character_id=1;exchange.probe_character_name=b'ProbeNew'
        wire=Wire(bytes.fromhex(packet))
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exchange.observe_game(wire,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C'))
        finally:exchange.stop();exchange.finish()
        return wire.replies


if __name__=='__main__':
    files,seen=observations();results=[]
    for packet,description in CASES.items():
        replies=replay(packet)
        results.append({'request':packet,'description':description,'replies':replies,
                        'observed':packet in seen.get(key(packet),{}).get('variants',())})
    assert results[-1]['replies']==['9e'],'Ping control failed'
    output={'scope':__doc__,'log_files':files,'observed':seen,'replay':results}
    (ROOT/'evidence/unanswered_requests_audit.json').write_text(json.dumps(output,indent=2)+'\n',encoding='utf-8')
    print('Historical logs:',len(files),'request families:',len(seen))
    for row in results:print(row['request'],row['replies'] or 'NO RESPONSE',row['description'])
