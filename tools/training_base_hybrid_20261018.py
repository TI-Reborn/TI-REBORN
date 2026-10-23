"""Seven TLS peers support one separately controlled native graphical QA owner."""
import json,socket,ssl,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import verify_training_base_20261018_hosted as qa
def main():
    data=json.loads(qa.PRIVATE.read_text());names=data['names'];passwords=data['passwords'];peers={}
    case=qa.MultiAccountTests();case.clients=[];tls=qa.GameTLSTests();tls.case=case;context=ssl.create_default_context()
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def command(index,packet=None,expected=None):
        p=peers[index]
        if packet is not None:p.send(packet)
        p.send(b'\x70');received=[];fenced=False;deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            reply=p.receive();received.append(reply);fenced|=reply==b'\x9e'
            if reply.startswith(b'\xf0\x8a\x01\0\0'):raise AssertionError('Own QA request rejected')
            if fenced and (expected is None or any(x.startswith(expected) for x in received)):return received
        raise AssertionError('Native response deadline')
    report=dict(native_graphical_clients=1,tls_protocol_clients=7,steps=[])
    try:
        group=int(sys.argv[1],0)
        for i in range(1,8):
            peer=tls.handoff(tls.begin(names[i],39000+i,password=passwords[i]));case.enter(peer,names[i]);peers[i]=peer
        for i in (1,2,3):command(i,qa.encode_request(qa.JOIN_ROOM,group),b'\xc8\x24')
        replies=command(4,qa.encode_request(qa.CREATE_ROOM),b'\xc8\x24')
        other=next(qa.room_state(x)['id'] for x in replies if qa.room_state(x))
        for i in (5,6,7):command(i,qa.encode_request(qa.JOIN_ROOM,other),b'\xc8\x24')
        for i in range(1,8):command(i,qa.encode_request(qa.SET_READY,1),b'\xc8\x24')
        command(4,qa.encode_request(qa.START_ROOM),b'\xc8\x24')
        report['steps'].append('seven peers joined and readied; second group queued')
        print(json.dumps(dict(stage='ready for native owner Ready/Start',groups=[group,other])),flush=True)
        for line in sys.stdin:
            op=line.strip()
            if op=='status':
                for i in peers:command(i)
                value=qa.remote(qa.STATE,names)
                print(json.dumps(value),flush=True)
            elif op=='load':
                value=qa.remote(qa.STATE,names);assert len(value['battles'])==1
                match=value['battles'][0]['match']
                if match not in data['matches']:data['matches'].append(match);qa.PRIVATE.write_text(json.dumps(data))
                for i in peers:command(i,b'\x36')
                report['steps'].append('seven native loading acknowledgements sent')
                print(json.dumps(dict(stage='native battle loading requested',match=match)),flush=True)
            elif op=='finish':
                for i in peers:command(i,b'\x2a\x01')
                report['steps'].append('protocol peers left battlefield')
                print(json.dumps(dict(stage='protocol peers left')),flush=True)
            elif op=='stop':break
    finally:
        for channel in case.clients:
            try:channel.close()
            except OSError:pass
        (qa.REPORT/'hybrid-verification.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':main()
