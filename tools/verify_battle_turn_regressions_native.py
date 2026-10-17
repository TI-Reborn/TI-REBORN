"""Original 3B reader on human/canine fog snapshots; rendering is stubbed.

Uses the real server projector and original x86 reader. Verifies model position
and HP, not visual rendering or live game-client interaction.
"""
from verify_auth_native import *
sys.path.insert(0,str(ROOT/'tests'))
from trace_battle_soldier_native import trace
from test_battle_turn_regressions import TurnRegressionTests
from tio.visibility import VisibilityView,visible_actors
from tio.protocol.battle_soldier import decode_battle_soldier,encode_battle_soldier
from server.battle_events import project_action
from dataclasses import replace


def main():
    case=TurnRegressionTests();case.setUp();checks=[]
    try:
        owners,b=case.dog_battle();field=b['field'];viewer=owners[0]
        hostile=next(o for o in b['bots'] if not field.allied(o,viewer))
        for j,(i,a) in enumerate(field._actors.items()):
            field._actors[i]=replace(a,x=5+j if field.allied(a.owner_id,viewer) else 40+j,y=5,sight_radius=2)
        view=b['views'][viewer];view.refresh()
        foreign=VisibilityView(field,hostile,dict(view.templates))
        foreign.visible=visible_actors(field,hostile)
        source=foreign.refresh()
        result=project_action(view,hostile,dict(field._actors),view.visible,source)
        for identity in field.actor_ids(viewer):
            human=field.combat.human[identity]
            def native(packet):
                a=decode_battle_soldier(packet,human_equipment=human)
                a=replace(a,fields={**a.fields,'0x8c50ea':1})
                return trace(body=encode_battle_soldier(a)[1:],human=human)['model']
            initial=native(view.snapshot(identity))
            bad=next(p for p in source if p[0]==0x3b and int.from_bytes(p[1:5],'little')==identity)
            corrupted=native(bad)
            assert corrupted['position']==[255,255] and corrupted['health']==1
            own_updates=[p for p in result if p[0] in (0x3b,0x43) and int.from_bytes(p[1:5],'little')==identity]
            assert not own_updates,'Foreign fog still updates own original-client model'
            actor=field.actor(identity)
            assert initial['position']==[actor.x,actor.y] and initial['health']==actor.health
            checks.append(dict(actor=identity,human=human,initial=initial,
                old_foreign_packet_model=corrupted,fixed_own_updates=0))
    finally:case.doCleanups()
    report=dict(passed=True,binary_sha256=EXPECTED_SHA,method=__doc__,checks=checks)
    (ROOT/'reports/battle-turn-regressions/native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Original human/dog readers reproduce foreign-fog corruption; corrected projector preserves both: PASS')


if __name__=='__main__':main()
