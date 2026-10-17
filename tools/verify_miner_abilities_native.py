"""Original81/4B/AA and PetInfo readers for all four miner ranks.

Numeric protocol routines execute unchanged. Tree metadata enrichment and
PetInfo model/UI/allocation are isolated by the existing diagnostic stubs.
"""
from verify_auth_native import *
from verify_skill_tree_native import tree_case
from verify_ability_cast_native import run as cast_case
from verify_attack_native import response
from trace_pet_info_native import trace
from tio.protocol.ability_cast import AbilityCast
from tio.protocol.battle_attack import AttackResult,AttackHit
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.abilities import AbilityEntry
from tio.ability_learning import AbilityLearning
from tio.passive_stats import project_passives
from tio.abilities import AbilityCatalog,AbilityLevel


def main():
    source=json.loads((ROOT/'config/abilities.json').read_text())
    catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
    p=decode_pet_info(bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
    p.fields.update({'0x8c446f':6,'0x8c4a07':98,'0x8c4ab1':98,'0x8c4b57':1000,'0x8c4ac5':0})
    cases=[]
    for rank in range(1,5):
        entries=[AbilityEntry(i,rank,0,int(i==22)) for i in (20,21,22,24)]
        wire=project_passives(encode_pet_info(p),True,entries,catalog)
        read=trace(body=wire[1:],human=True)
        assert read['native_health']['maximum']==98+(20,28,36,44)[rank-1]
        assert read['native_max_weight']==1000+(60,110,160,210)[rank-1]
        assert read['native_armor']==(52,67,83,99)[rank-1]
        cases.append({k:read[k] for k in ('native_health','native_max_weight','native_armor')})
    # No historical price is claimed: this numeric-only probe uses sentinels.
    tree=tree_case([(i,r,0,AbilityLearning.required_level(i,r),0x12345678,0) for i in (20,21,22,24) for r in range(1,5)])
    cast=cast_case(AbilityCast(22,1,0,5,4))
    hit=response(AttackResult(1,(4,4),(5,4),335,(AttackHit(2,100,20),AttackHit(3,80,0)),skill_id=22))
    (ROOT/'evidence/miner_abilities_native.json').write_text(json.dumps({'method':__doc__,'sha256':EXPECTED_SHA,'passives':cases,'tree':tree,'cast':cast,'attack':hit},indent=2)+'\n')
    print('Miner ranks/PetInfo, AA tree, 81 cast, 4B slash PASS')


if __name__=='__main__':main()
