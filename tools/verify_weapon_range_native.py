"""Execute original weapon XML stores, range damage and accuracy in silver.dll.

Only XML integer lookup, item metadata lookup, dog identity and no-limit flag lookup are
stubbed. All numeric operations, Single rounding and integer conversions are
original x86 instructions. This does not simulate server random rolls.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_FPCW
import xml.etree.ElementTree as ET
from tio.weapons import WeaponCatalog
from tio.weapon_proficiency import damage_endpoint


def verify():
    u=emulator();frame=STACK+0x7000;table=DATA+0x1000;out=DATA+0xa000
    u.reg_write(UC_X86_REG_FPCW,0x1332)  # Delphi extended precision, nearest.
    put32(u,0xac637c,DATA+0x9000);put32(u,DATA+0x9000,table)
    put32(u,DATA+12,0)
    current={}
    def hook(uc,address,size,user):
        if address==0x680974:
            assert uc.reg_read(UC_X86_REG_EDX)==0xa74d38
            uc.reg_write(UC_X86_REG_EAX,current['fade']);return_from_stub(uc)
        elif address in (0xa7b030,0xa7b458):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0xa86888:
            uc.reg_write(UC_X86_REG_EAX,int(current['dog']));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    items={int(i.get('id')):i for i in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()}
    catalog=WeaponCatalog();cases=[]
    for identity,w in catalog.weapons.items():
        item=items[identity];source=catalog.sources[identity]
        u.mem_write(table,bytes(0x800))
        for stat,offset,size in (('accuracy',0x140,4),('accuracyGain',0x64d,1)):
            value=float(item.find(f"for/add[@stat='{stat}']").get('val'))
            u.mem_write(frame-0x3f0,b'\x03add')
            u.mem_write(frame-0x2f0,bytes([len(stat)])+stat.encode())
            u.mem_write(frame-0x148,struct.pack('<f',value))
            u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EBX,DATA)
            u.emu_start(0xa72752,0xa72c22,count=2000)
            actual=int.from_bytes(u.mem_read(table+offset,size),'little')
            expected=int(source.get('accuracy' if stat=='accuracy' else 'accuracy_gain_amount',100 if stat=='accuracy' else 0))
            assert actual==expected,(identity,stat,actual,expected)
        current['fade']=int(item.find("value[@key='damageFade']").get('val'))
        u.reg_write(UC_X86_REG_EBX,DATA)
        u.emu_start(0xa71ca2,0xa71cca,count=100)
        assert int.from_bytes(u.mem_read(table+0x136,2),'little')==int(source.get('damage_fade',100))
        u.mem_write(table+0x138,struct.pack('<HH',w.min_range,w.max_range))
        u.mem_write(table+0x12c,bytes([7 if source.get('weaponAttack')=='Minigun' else 0]))
        for distance in range(w.max_range+1):
            for enhancement in (0,3,25):
                u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EBX,0)
                u.reg_write(UC_X86_REG_EDI,out)
                put32(u,frame+0x10,out+4);put32(u,frame-8,distance)
                u.mem_write(out,struct.pack('<ff',w.damage_base+enhancement,w.damage_base+w.damage_random+enhancement))
                u.emu_start(0xa7a576,0xa7a67f,count=1000)
                damage=struct.unpack('<ff',u.mem_read(out,8))
                expected=catalog.distance_damage(identity,distance,enhancement)
                assert damage==expected,(identity,distance,enhancement,damage,expected)
                if source.get('weaponAttack') in ('Bullet','None'):
                    u.mem_write(frame-0x14,struct.pack('<f',35))
                    u.emu_start(0xa7a826,0xa7a890,count=1000)
                    skilled=struct.unpack('<ff',u.mem_read(out,8))
                    assert skilled==tuple(damage_endpoint(v,35) for v in expected),(identity,distance,skilled)
            u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
            u.reg_write(UC_X86_REG_EAX,DATA+0xe000);u.reg_write(UC_X86_REG_EDX,distance)
            u.emu_start(0xa7ad00,STOP,count=1000)
            accuracy=u.reg_read(UC_X86_REG_EAX)
            assert accuracy==catalog.accuracy(identity,distance),(identity,distance,accuracy,catalog.accuracy(identity,distance))
            cases.append(dict(id=identity,distance=distance,accuracy=accuracy,base_damage=catalog.distance_damage(identity,distance)))
    bonus_cases=[]
    for perk,kind,dog,value,expected in ((10,2,False,10,10),(10,3,False,10,0),
                                       (17,3,False,15,15),(17,4,False,15,0),
                                       (18,2,True,20,20),(18,2,False,20,0)):
        actor=DATA+0xb000;row=DATA+0xc000
        put32(u,actor+0x304,row);put32(u,row-4,1)
        put32(u,row+8,perk);put32(u,row+0x320,value)
        u.mem_write(table+0x120,struct.pack('<H',kind));current['dog']=dog
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.reg_write(UC_X86_REG_EAX,actor);u.reg_write(UC_X86_REG_EDX,0)
        u.emu_start(0xa83c38,STOP,count=1000)
        result=u.reg_read(UC_X86_REG_EAX)
        assert result==expected,(perk,kind,dog,result)
        bonus_cases.append(dict(perk=perk,weapon_type=kind,dog=dog,value=value,result=result))
    report=dict(sha256=EXPECTED_SHA,method=__doc__,weapon_count=len(catalog.weapons),
                damage_checks=len(cases)*3,accuracy_checks=len(cases),cases=cases,bonus_cases=bonus_cases)
    (ROOT/'evidence/weapon_range_native.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"Original XML {len(catalog.weapons)} weapons; range damage {len(cases)*3}, accuracy {len(cases)}, perk bonuses6: PASS")


if __name__=='__main__':verify()
