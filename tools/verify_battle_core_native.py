"""Check original x86 chat readers and attack writers, with documented UI stubs."""
from verify_attack_native import response,AttackResult,AttackHit,ROOT,EXPECTED_SHA
from verify_social_native import run
from tio.protocol.chat import encode_message
import json


def main():
    chats=[]
    for channel in (3,4):
        text='Проверка боевого чата'
        result=run(encode_message(channel,b'Alice',text))
        assert (result['channel'],result['name'],result['text'])==(channel,'Alice',text)
        chats.append(result)
    attacks=[response(AttackResult(3,(2,2),(5,2),314,
                (AttackHit(5,20,80),AttackHit(6,40,60,flags=4)),flags=4)),
             response(AttackResult(3,(2,2),(5,2),304,(AttackHit(5,0,100,flags=2),),flags=2))]
    result={'binary_sha256':EXPECTED_SHA,'passed':True,'chat':chats,'attacks':attacks,
        'scope':'Original x86 UTF16/scalar chat readers and complete 4B writers; ANSI strings, allocation and UI stubbed. No graphical-client validation.',
        'sender_echo':'Original chat_net_research.asm 9FF605..9FF60D calls local battle display before sending; server does not echo battle text to sender.'}
    (ROOT/'evidence/battle-core-native.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Original battle chat3/4 and multi-target/critical/miss attack4B: PASS')


if __name__=='__main__':main()
