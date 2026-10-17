"""Exact candidate tutorial ground/chat/result and original action ABI proof.

Original x86 readers/writers execute. Strings/allocation/UI/transport helpers
are isolated; every visited instruction in the original image is compared with
the exact candidate. This does not claim GUI acceptance or original quest ACK
dialogue/network trigger reconstruction.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI
from types import SimpleNamespace
import verify_cities_native as cities
import verify_social_native as social
import verify_attack_native as attack
import verify_end_turn_native as end
from server.tutorial_arena import tutorial_map
from tio.roster_progression import TUTORIAL_TIPS
from tio.protocol.chat import encode_message
from tio.protocol.battle_over import encode_battle_over
from tio.protocol.battle_attack import AttackRequest

CLIENT=ROOT/'reports/gameplay-completion/stage3-items/client/candidate/silver.dll'
CLIENT_SHA='2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f'
original=pefile.PE(data=BINARY.read_bytes()).get_memory_mapped_image()
raw=CLIENT.read_bytes();assert hashlib.sha256(raw).hexdigest()==CLIENT_SHA
candidate_image=pefile.PE(data=raw).get_memory_mapped_image();runs=[]


def candidate():
    u=emulator();u.mem_map(0xc17000,0x6000);u.mem_write(0x400000,candidate_image);visited=set();runs.append(visited)
    def parity(uc,address,size,user):
        if DATA<=address<DATA+0x10000:return  # Explicit isolated writer transport callback.
        offset=address-0x400000
        assert 0<=offset and offset+size<=len(original),hex(address)
        assert bytes(uc.mem_read(address,size))==original[offset:offset+size],hex(address)
        visited.add(address)
    u.hook_add(UC_HOOK_CODE,parity);return u


def result():
    u=candidate();packet=encode_battle_over(1,credits=0,rental_tax=0,soldiers=())
    u.mem_write(DATA,packet[1:]);cursor=DATA+0x1000;obj=DATA+0x2000
    put32(u,cursor,DATA);put32(u,0xac6200,obj);put32(u,0xac5d58,DATA+0x3000)
    u.reg_write(UC_X86_REG_EBP,STACK+0x7000);u.reg_write(UC_X86_REG_ESI,cursor)
    def hook(uc,address,size,user):
        if address==0x7660e4:return_from_stub(uc)
        elif address==0x66754c:uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
        elif address==0x95e747:uc.reg_write(UC_X86_REG_EIP,0x95e78b)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x95e55e,0x95ea7d,count=2000)
    assert get32(u,cursor)-DATA==len(packet)-1
    assert u.mem_read(obj+8,1)[0]==1 and get32(u,obj+24)==0 and get32(u,obj+28)==0
    return dict(consumed=len(packet)-1,result=1,credits=0,rental_tax=0,experience_records=0)


def main():
    cities.emulator=candidate;cities.generate_map=lambda *a,**k:SimpleNamespace(arena=tutorial_map())
    ground=cities.run('tutorial',0);assert (ground['width'],ground['height'])==(48,48)
    social.emulator=candidate;chats=[]
    for text in (*TUTORIAL_TIPS,'Вводная миссия завершена. Нажмите «Завершить», чтобы вернуться в город.'):
        parsed=social.run(encode_message(3,b'Training',text));assert (parsed['channel'],parsed['name'],parsed['text'])==(3,'Training',text)
        chats.append(parsed)
    attack.emulator=candidate;request=attack.request(AttackRequest(0x40000001,13,4))
    end.emulator=candidate;endturn=end.run(actors=((0x40000001,1,0),))
    report=dict(status='PASS',method=__doc__,candidate_sha256=CLIENT_SHA,original_sha256=EXPECTED_SHA,
        ground=ground,hints=chats,attack_request=request,end_turn=endturn,zero_reward_result=result(),
        original_instruction_parity_counts=[len(r) for r in runs],
        original_intro_source='base/quest/tut_1000.xml and maps/tutorial.s; ack dialogue/network trigger not recovered',
        limitations=['No actual Windows GUI','No original quest/dialogue script reproduction','Hosted real-client integration belongs to root'])
    (ROOT/'evidence/tutorial_native.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Tutorial exact candidate: ground1/chat5/attack request1/endturn1/zero-reward result1 =9 cases PASS')


if __name__=='__main__':main()
