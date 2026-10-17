"""Run original skill-grid click and Learn-button logic (8AE5C4, 8AD160).

Only parent-window coordinates and managed list allocation/clear are stubbed.
Hit testing, rank prerequisites, actor-level gate and button writes run as x86.
No Frida patches or purchases are made in the player's running game.
"""
from verify_auth_native import *
from tio.protocol.binary import Reader
from contextlib import closing
import sqlite3


def entries_from_packet(packet):
    r=Reader(packet);assert r.u8()==0xaa;r.u32()
    entries=[(r.u32(),r.u8(),r.u8(),r.u8(),r.u32(),r.u32()) for _ in range(r.u16())]
    r.finish();return entries


def click_case(entries,ability,actor_level=1,required=1):
    u=emulator();window=DATA+0x1000;rows=DATA+0x2000
    levels=DATA+0x6000;detail=DATA+0x7000;selected=DATA+0x8000
    learn=DATA+0x9000;forget=DATA+0xa000
    put32(u,window+0x288,rows);put32(u,rows-4,len(entries))
    for i,(aid,rank,learned,need,price,refund) in enumerate(entries):
        p=rows+i*0x348;put32(u,p+8,aid);put32(u,p+0x310,price)
        u.mem_write(p+0x31e,bytes([rank]));u.mem_write(p+0x324,bytes([learned,need]))
    needs=sorted({e[3] for e in entries});ids=list(dict.fromkeys(e[0] for e in entries))
    put32(u,levels-4,len(needs));put32(u,window+0x280,levels)
    for i,need in enumerate(needs):put32(u,levels+i*4,need)
    put32(u,window+0x284,actor_level)
    for address,value in [(0xacfa60,detail),(0xacfa68,learn),(0xacfa6c,forget)]:put32(u,address,value)
    result={}
    def hook(uc,address,size,user):
        if address in (0xa4211c,0xa42140):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0x8b0190:return_from_stub(uc)
        elif address==0x40d5a4:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),selected);put32(uc,selected-4,1)
            return_from_stub(uc)
        elif address==0x8ad160:
            p=uc.reg_read(UC_X86_REG_EAX)
            result.update(id=get32(uc,p+8),rank=uc.mem_read(p+0x31e,1)[0])
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,window);u.reg_write(UC_X86_REG_EDX,0)
    u.reg_write(UC_X86_REG_ECX,21+48*ids.index(ability))
    put32(u,u.reg_read(UC_X86_REG_ESP)+4,1+48*needs.index(required))
    u.emu_start(0x8ae5c4,STOP,count=40000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    result['learn_enabled']=bool(u.mem_read(learn+0x4a,1)[0])
    return result


if __name__=='__main__':
    import tempfile
    from tio.ability_learning import AbilityLearning
    from tio.owned_pets import OwnedPetStore
    from tio.wallets import WalletStore
    from tio.protocol.pet_info import decode_pet_info,encode_pet_info
    from tio.protocol.item_list import encode_item_list
    from tio.protocol.abilities import encode_ability_request
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'state.sqlite3';store=OwnedPetStore(path)
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        pet=decode_pet_info(template,human_equipment=True)
        pet.fields.update({'0x8c43eb':1,'0x8c446f':6,'0x8c4aef':1})
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',('test',1,1,encode_pet_info(pet),encode_item_list(1,())))
        WalletStore(path).ensure('test')
        with closing(sqlite3.connect(path)) as db,db:db.execute('UPDATE wallets SET credits=1000000')
        service=AbilityLearning.from_workspace(path,ROOT);results=[]
        initial=entries_from_packet(service.tree('test',1))
        # Captured original client ordering with the previous all-ranks AA reply.
        old=[(aid,r,0,1,100,0) for aid in (20,21,22) for r in (3,4,1,2)]
        assert click_case(old,20)=={'id':20,'rank':3,'learn_enabled':False}
        for rank in range(1,5):
            pet.fields['0x8c4aef']=rank
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE owned_pets SET pet_packet=?',(encode_pet_info(pet),))
            for ability in (20,21,22):
                rows=entries_from_packet(service.tree('test',1))
                assert len(rows)==16
                for future in range(rank+1,5):
                    locked=click_case(rows,ability,rank,future)
                    assert locked=={'id':ability,'rank':future,'learn_enabled':False},locked
                result=click_case(rows,ability,rank,rank)
                assert result=={'id':ability,'rank':rank,'learn_enabled':True},result
                service.handle('test',encode_ability_request(1,ability));results.append(result)
                updated=entries_from_packet(service.tree('test',1))
                assert not click_case(updated,ability,rank,rank)['learn_enabled']
        assert not click_case(initial,24,1,2)['learn_enabled']
        assert click_case(initial,24,2,2)['learn_enabled']
        saved=AbilityLearning.from_workspace(path,ROOT).state.read('test',1)[1]
        assert {(e.ability_id,e.level) for e in saved}=={(20,4),(21,4),(22,4)}
        # One open window, then only purchase replies: no further A9/list calls.
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('DELETE FROM ability_states')
        rows=entries_from_packet(service.tree('test',1))
        for rank in range(1,5):
            for ability in (20,21,22):
                assert click_case(rows,ability,4,rank)['learn_enabled']
                replies=service.handle('test',encode_ability_request(1,ability))
                rows=entries_from_packet(replies[1])
                assert not click_case(rows,ability,4,rank)['learn_enabled']
        assert {(e.ability_id,e.level) for e in service.state.read('test',1)[1]}=={(20,4),(21,4),(22,4)}
    (ROOT/'evidence/miner_learning_ui_native.json').write_text(json.dumps({'method':__doc__,'sha256':EXPECTED_SHA,'clicks':results,'status':'PASS'},indent=2)+'\n')
    print('Original skill-grid clicks and Learn button: 12 miner ranks, level gates and consecutive purchases without reopening PASS')
