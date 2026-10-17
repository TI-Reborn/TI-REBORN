"""Original x86 dog packet reader; UI, allocation and renderer are stubbed."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_world_encounters import EncounterTests
from trace_battle_soldier_native import trace

def main():
    case=EncounterTests();case.setUp()
    try:
        room,scene=case.encounter();results=[]
        for identity in scene.field.actor_ids(scene.bot_owner):
            packet=scene.visibility.snapshot(identity)
            result=trace(human=False,body=packet[1:])
            assert result['body_hex']==packet[1:].hex()
            assert result['model']['soldier_id']==identity
            results.append(dict(actor=identity,native_model=result['model'],packet_hex=packet.hex()))
        report=dict(passed=True,kind=__doc__,cases=results,real_graphical_client=False)
        (ROOT/'reports/dog-encounters/native-parser.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Infected dogs: original x86 packet consumption and IDs PASS (renderer/UI stubbed)')
    finally:case.doCleanups()

if __name__=='__main__':main()
