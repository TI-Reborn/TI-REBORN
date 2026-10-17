"""Original3B equipment reads and98f978 slot dispatch; managed copy isolated.

Markers are template identifiers, not valid equipment resources. No rendering
claim and no inference that ItemList.location_raw uses these slot masks.
"""
from trace_battle_soldier_native import trace, ROOT
from tio.protocol.battle_soldier import HUMAN_EQUIPMENT_FIELDS
import json

if __name__=='__main__':
    values={key:301+n for n,key in enumerate(HUMAN_EQUIPMENT_FIELDS.values())}
    result=trace(equipment=True,overrides=values)
    assert result['equipment_calls']==[{'slot_mask':mask,'template_id':values[key],
                                        'effective_upgrade':0}
                                      for mask,key in HUMAN_EQUIPMENT_FIELDS.items()]
    offsets=(0x3b0,0x640,0xdf0,0x1310,0x8d0,0xb60,0x1ac0,0x2790,0x2a20,0x2cb0,0x2f40)
    for offset,value in zip(offsets,values.values()):
        assert result['equipment_model'][hex(offset)]==value
    assert result['equipment_model']['0x1080']==values['0x8c52cf']
    result['method']=__doc__
    (ROOT/'evidence/battle_equipment_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original3B equipment:11 slot masks and12 destination records PASS')
