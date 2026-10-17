"""Read real rank packets through original silver.dll 66/3B handlers in Unicorn.

Uses the existing explicit runtime/UI/resource stubs; not an in-game UI test.
"""
import json
from trace_pet_info_native import trace, ROOT, EXPECTED_SHA
from trace_battle_soldier_native import trace as battle_trace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.ranks import project,rank_id
from battle_actor_fixture import actor_packet


def main():
    cases=[]
    for human in (True,False):
        baseline=trace(human=human,new_slot=True,appearance=True)
        packet=b'\x66'+bytes.fromhex(baseline['body_hex'])
        pet=decode_pet_info(packet,human_equipment=human)
        pet.fields.update({'0x8c446f':1 if human else 3,'0x8c4489':b'RankProbe',
                           '0x8c4aef':20,'0x8c4a07':100,'0x8c4ab1':100})
        packet=encode_pet_info(pet)
        for points,debt,cap in ((-20,0,29),(0,0,29),(19,0,29),(20,0,29),
                                (50,0,29),(4950,50,29),(35000,0,29),(120,0,2)):
            wire=project(packet,human,points,debt=debt,commander_rank=cap)
            f=decode_pet_info(wire,human_equipment=human).fields
            expected={'index':min(rank_id(points),cap)-1,'points':points&0xffffffff,
                      'recovery':debt,'remaining':f['0x8c4bf6']}
            city=trace(body=wire[1:],human=human,new_slot=True)
            assert city['consumed']==len(wire)-1
            assert city['native_rank']==expected,(city['native_rank'],expected)
            combat=actor_packet(wire,1,encode_item_list(1,()),human=human,actor_id=1,x=2,y=2)
            battle=battle_trace(body=combat[1:],human=human,new_slot=True)
            assert battle['consumed']==len(combat)-1
            assert battle['native_rank']==expected,(battle['native_rank'],expected)
            cases.append({'human':human,'signed_points':points,'commander_rank':cap,
                          'city_bytes':len(wire),'battle_bytes':len(combat),'native':expected})
    (ROOT/'evidence/ranks_native.json').write_text(json.dumps({
        'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print(f'Original 66/3B rank readers: {len(cases)*2} cases PASS')


if __name__=='__main__':main()
