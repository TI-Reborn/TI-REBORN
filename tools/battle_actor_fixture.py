"""Diagnostic actor from saved66 and equipped30 template IDs; combat incomplete."""
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.battle_soldier import BattleSoldier, SCHEMAS, CONDITIONS, encode_battle_soldier,HUMAN_EQUIPMENT_FIELDS
from tio.protocol.item_list import decode_item_list

MAPPING = {
    '0x8c5134': '0x8c4aef', # model+0x5ffc
    '0x8c514b': '0x8c4b05', # model+0x602c
    '0x8c515f': '0x8c4b18', # model+0x6030
    '0x8c54cc': '0x8c4879', # model+0x310
    '0x8c54e1': '0x8c488d', # model+0x358
    '0x8c54f6': '0x8c48a1', # model+0x314
    '0x8c550b': '0x8c48b5', # model+0x35c
    '0x8c5520': '0x8c48c9', # model+0x318
    '0x8c5535': '0x8c48dd', # model+0x360
    '0x8c554a': '0x8c48f1', # model+0x31c
    '0x8c555f': '0x8c4905', # model+0x364
    '0x8c5574': '0x8c4919', # model+0x320
    '0x8c5589': '0x8c492d', # model+0x368
    '0x8c559e': '0x8c4941', # model+0x324
    '0x8c55b3': '0x8c4955', # model+0x36c
    '0x8c55c8': '0x8c4969', # model+0x328
    '0x8c55dd': '0x8c497d', # model+0x370
    '0x8c55f2': '0x8c4991', # model+0x32c
    '0x8c5607': '0x8c49a5', # model+0x374
    '0x8c561c': '0x8c49b9', # model+0x378
    '0x8c5631': '0x8c49cd', # model+0x37a
    '0x8c5646': '0x8c49e1', # model+0x37c
    '0x8c566a': '0x8c4a07', # model+0x6008
    '0x8c567f': '0x8c4a1b', # original setSight(a86df8), encrypted actor sight
    '0x8c56a8': '0x8c4a42', # model+0x45
    '0x8c56b9': '0x8c4a52', # model+0x60c4
    '0x8c56cd': '0x8c4a65', # model+0x60c8
    '0x8c56e1': '0x8c4a78', # model+0x60cc
    '0x8c56f5': '0x8c4a8b', # model+0x60d0
    '0x8c5709': '0x8c4a9e', # model+0x60d4
    '0x8c571d': '0x8c4a2f', # model+0x6004
    '0x8c5731': '0x8c4ac5', # model+0x6010
    '0x8c5748': '0x8c4adb', # model+0x6014
    '0x8c57bb': '0x8c4ab1', # model+0x6006
    '0x8c57d0': '0x8c4b57', # model+0x6024
    '0x8c57e7': '0x8c4b6d', # model+0x6020
    '0x8c57fe': '0x8c4b83', # model+0x602b
    '0x8c581d': '0x8c4ba9', # model+0x60dc
    '0x8c5831': '0x8c4565', # model+0x43
    '0x8c5847': '0x8c4bbc', # model+0x604c
    '0x8c585c': '0x8c4bd0', # model+0x6050
    '0x8c5870': '0x8c4be3', # model+0x6054
    '0x8c5884': '0x8c4bf6', # model+0x6058
    '0x8c5898': '0x8c4c34', # model+0x605c
    '0x8c5918': '0x8c4cb6', # model+0x6060
    '0x8c5998': '0x8c4d38', # model+0x48
    '0x8c59e8': '0x8c4d88', # model+0x54
}


def actor_packet(pet_packet,character_id,inventory_packet=None,*,human=True,actor_id=None,name=None,x=2,y=2,team=0,color=0):
    pet=decode_pet_info(pet_packet,human_equipment=human).fields
    if pet['0x8c446f'] not in ((1,2,6) if human else (3,4,5)):
        raise ValueError('Resource differs from equipment profile')
    fields={key:(b'' if reader=='CString' else 0) for key,size,reader in SCHEMAS[human]}
    for target,source in MAPPING.items():fields[target]=pet[source]
    for key in fields:
        if key.startswith('0x6d') and key in pet:fields[key]=pet[key]
    fields.update({'0x8c5088':pet['0x8c43eb'] if actor_id is None else actor_id,'0x8c50ea':character_id,
                   '0x8c50fb':pet['0x8c446f'],'0x8c5116':pet['0x8c4489'] if name is None else name,
                   '0x8c519b':x,'0x8c51af':y,'0x8c5187':team,'0x8c5173':color})
    equipment_fields=HUMAN_EQUIPMENT_FIELDS if human else {16:'0x8c543f',4:'0x8c546e',1024:'0x8c549d'}
    if not human:
        for target,source in (('0x8c543f','0x8c47f5'),('0x8c546e','0x8c4821'),('0x8c549d','0x8c484d')):
            fields[target]=pet[source]
    if inventory_packet is not None:
        owner,items,_=decode_item_list(inventory_packet)
        if owner!=pet['0x8c43eb']:raise ValueError('Inventory actor mismatch')
        occupied=set()
        for item in items:
            if item.equipped not in (0,1):raise ValueError('Noncanonical equipped flag')
            if not item.equipped:continue
            slot=item.client_slot
            if slot not in equipment_fields:raise ValueError('Unsupported equipped slot')
            if slot in occupied:raise ValueError('Multiple items in equipment slot')
            occupied.add(slot)
            fields[equipment_fields[slot]]=item.template_id
    for key,(control,expected) in CONDITIONS.items():
        if not (bool(fields[control]) if expected is None else fields[control]==expected):fields.pop(key,None)
    return encode_battle_soldier(BattleSoldier(human,fields))
