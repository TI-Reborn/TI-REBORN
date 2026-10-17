"""Project supported local owned actors into room soldierInfo.

Level/NPC/rank/points come from recovered66 fields. Equip=1, injury=0,
avatar=0 remain compatibility values. Soldier rank on the wire is one based.
"""
from .protocol.pet_info import decode_pet_info
from .protocol.battle_members import MemberGroup1


def room_soldiers(rows, limit, *, path=None, account=None):
    from .avatars import selections
    avatars=selections(path,account) if path is not None and account is not None else {}
    if not 1 <= limit <= 3:
        raise ValueError('Unsupported room soldier capacity')
    result=[]
    for owner, packet, inventory in rows:
        resource=int.from_bytes(packet[5:9], 'little')
        if resource not in (1,2,3,4,5,6):
            raise ValueError('Unrecovered arena actor resource')
        pet=decode_pet_info(packet,human_equipment=resource in (1,2,6))
        fields=pet.fields
        if fields['0x8c43eb']!=owner:
            raise ValueError('Actor key mismatch')
        if fields['0x8c44a6'] not in (1,2,3):
            continue
        result.append(MemberGroup1.soldier(level=fields['0x8c4aef'],
                      npc_id=fields['0x8c446f'],equip_status=1,injure_status=0,
                      avatar_id=avatars.get(owner,0),rank=max(1,fields['0x8c4bbc']),
                      military_rank=fields['0x8c4bd0'],points_to_next_rank=fields['0x8c4bf6']))
        if len(result)==limit:break
    return tuple(result)
