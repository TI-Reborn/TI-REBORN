"""Replay encoded BattleSoldier3B through original read phase with marker values.

Shares explicit allocation/resource/UI isolation with structural tracer.
The original reader verifies actual model writes and conditional consumption.
"""
from trace_battle_soldier_native import trace, ROOT, EXPECTED_SHA
from tio.protocol.battle_soldier import (
    BattleSoldier, decode_battle_soldier, encode_battle_soldier, CONDITIONS,
)
import json


if __name__ == '__main__':
    fixtures=json.loads((ROOT/'evidence/battle_soldier_native_variants.json').read_text())
    cases=[]
    for human in (True,False):
        full=next(c for c in fixtures if c['profile']['human']==human and
                  c['profile']['appearance'] and c['profile'].get('all_optional'))
        base=decode_battle_soldier(b'\x3b'+bytes.fromhex(full['body_hex']),human_equipment=human)
        for flag in (0,1,2):
            fields=dict(base.fields)
            for key in ('0x6d0203','0x8c5898','0x8c5918','0x8c5998','0x8c59e8','0x8c5831'):
                fields[key]=flag
            for key,(control,expected) in CONDITIONS.items():
                if not (bool(fields[control]) if expected is None else fields[control]==expected):
                    fields.pop(key,None)
            fields.update({'0x8c5134':5,'0x8c519b':31,'0x8c51af':47,'0x8c50ea':1 if flag==1 else 2})
            packet=encode_battle_soldier(BattleSoldier(human,fields))
            result=trace(human=human,body=packet[1:])
            assert result['body_hex']==packet[1:].hex()
            assert result['model']=={'soldier_id':1,'owner_id':fields['0x8c50ea'],
                                     'level':5,'position':[31,47],'own':int(flag==1)}
            result['packet_hex']=packet.hex()
            result['branch_flag']=flag
            cases.append(result)
    (ROOT/'evidence/battle_soldier_replay.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('BattleSoldier original read phase:6 marker/branch cases PASS')
