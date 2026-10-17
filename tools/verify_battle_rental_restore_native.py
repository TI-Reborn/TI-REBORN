"""Original3B default gear vs original30 rental/upgrade readers in Unicorn.

Actor equipment/UI allocation uses trace_battle_soldier_native stubs. Native
3B item creation and30 field getters execute; no live process is modified.
"""
from verify_auth_native import *
from trace_battle_soldier_native import trace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tools.battle_actor_fixture import actor_packet


if __name__=='__main__':
    p=decode_pet_info(bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
    p.fields['0x8c43eb']=1;p.fields['0x8c4aef']=4
    gear=ItemRecord(1117,304,bytes(2),1,1,16,(1000,)*3,b'\x0a\0\0\1',9371,b'\x14\0\0')
    inventory=encode_item_list(1,(gear,))
    snapshot=actor_packet(encode_pet_info(p),1,inventory)
    read=trace(body=snapshot[1:],human=True,equipment=True)
    weapon=next(row for row in read['equipment_calls'] if row['slot_mask']==16)
    assert weapon['template_id']==304 and weapon['effective_upgrade']==0
    u=emulator();obj=DATA+0x2000;body=inventory[10:]
    u.mem_write(DATA,body);put32(u,0xacd0e8,DATA)
    def hook(uc,address,size,user):
        if address==0x40b09c:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    def run(address):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(address,STOP,count=5000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        return u.reg_read(UC_X86_REG_EAX)
    run(0x63bd38)
    assert get32(u,0xacd0e8)==DATA+len(body)
    restored=dict(effective=run(0x63c958),real=run(0x63cbc4)&255,
                  rented=run(0x63ca78)&255,seconds=run(0x63cb60))
    assert restored==dict(effective=10,real=20,rented=1,seconds=9371),restored
    (ROOT/'evidence/battle_rental_restore_native.json').write_text(json.dumps(
        dict(method=__doc__,sha256=EXPECTED_SHA,snapshot=weapon,restored=restored,status='PASS'),indent=2)+'\n')
    print('Native3B resets upgrade; full30 restores effective10/real20/rental/time PASS')
