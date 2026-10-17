"""Original mine GUI caller, deployment reader and known-mine writer.

Execute the actual selected-item caller95b91e..95b943→9595f0→6585cc.
Unrelated UI setup before that block and packet transport are isolated.
658e70 is the unmodified typed C8/3F reader;95c0e4 native branches are
executed through their first destination. No drawing or real client claim.
"""
from dataclasses import asdict
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX
from verify_known_mines_native import run as known
from verify_weapon_consume_native import run as consume
from verify_attack_native import response as attack_response
from tio.protocol.battle_attack import AttackResult,AttackHit
from tio.protocol.battle_mines import *


def deploy(value):
    u=emulator();parent=DATA+0x6000;frame=STACK+0x7000;owners=DATA+0x7000;actor=DATA+0x7100;out=DATA+0x1000
    put32(u,frame+8,parent);put32(u,parent-4,0);put32(u,parent-8,value.x);put32(u,parent-12,value.y)
    put32(u,0xac618c,owners);put32(u,owners,actor);put32(u,actor+0x28,value.actor_id)
    # TSItem.Id+28 is independently proven by verify_item_policy_native.
    put32(u,0xad05f8+0x28,value.instance_id);put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    calls=[]
    def hook(uc,address,size,user):
        if address in (0x629764,0x629938):calls.append(hex(address));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EBP,frame)
    u.emu_start(0x95b91e,0x95b948,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==0x95b948
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==encode_mine_deploy(value);assert calls==['0x629764','0x629938']
    return dict(fields=asdict(value),packet_hex=packet.hex(),selected_instance_read='ad05f8+28',native_call='95b943→9595f0→6585cc')


def deployed(value):
    packet=encode_mine_deployed(value);u=emulator();obj=DATA+0x2000
    u.mem_write(DATA,packet[2:]);put32(u,0xacd0e8,DATA)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x658e70,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP;assert get32(u,0xacd0e8)-DATA==20
    assert [get32(u,obj+i) for i in (0,8,0x10,0x18)]==[value.actor_id,value.x,value.y,value.template_id]
    assert bytes(u.mem_read(obj+0x1d,1))==bytes((value.state,))
    expected={1:0x95c102,3:0x95c201,4:0x95c21d}.get(value.state,0x95c2fc)
    u.reg_write(UC_X86_REG_EBX,obj);u.reg_write(UC_X86_REG_EBP,STACK+0x7000)
    u.reg_write(UC_X86_REG_EAX,obj)
    # Restore a direct block entry stack, getter returns to original branch.
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.emu_start(0x95c0e4,expected,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==expected
    return dict(fields=asdict(value),packet_hex=packet.hex(),reader='658e70',consumed=20,ui_branch=hex(expected))


def main():
    import xml.etree.ElementTree as ET
    xml=ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()
    node=xml.find("item[@id='323']/for/consume")
    assert (int(node.get('id')),int(node.get('amount')))==(317,1)
    report=dict(binary_sha256=EXPECTED_SHA,method=__doc__,
        deployment_requests=[deploy(MineDeploy(17,1001,2,3)),deploy(MineDeploy(0x40000001,0x12345678,255,256))],
        deployment_results=[deployed(MineDeployed(17,2,3,321,state)) for state in (1,3,4)],
        known_mines=[known([]),known([(2,3,321,0),(4,5,325,1)])],
        mine_attacks=[attack_response(AttackResult(17,(2,3),(3,3),321,(AttackHit(18,80,120),),mine_state=state)) for state in (1,255)],
        launcher_consumption=consume(317,1))
    (ROOT/'evidence/special_items_native.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Original mineGUI deployment2 / ackreader+branches3 / knownminewriters2 / optionalmine4B2 / launcherconsume1: 10 cases PASS')


if __name__=='__main__':main()
