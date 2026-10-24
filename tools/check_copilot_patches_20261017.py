"""Isolated counterexamples extracted from proposed patches; no server writes."""
from pathlib import Path
import json
import pickle
import threading

ROOT=Path(__file__).resolve().parents[1]
PATCHES=Path('C:/Users/jundu/OneDrive/Desktop/patches')

def added(path):
    return '\n'.join(line[1:] for line in path.read_text(encoding='utf-8-sig').splitlines()
        if line.startswith('+') and not line.startswith('+++'))

def main():
    results={}
    namespace={}
    exec(compile(added(PATCHES/'project_action_apply_effects_optimization_patch.diff'),'<proposed-project-action>','exec'),namespace)
    calls=[]
    namespace['_project_action_fast']=lambda units,action:calls.append(units[0]['hp']) or {'observed_hp':units[0]['hp']}
    def state(hp):return dict(owner_id=1,action={'id':1},turn=1,units=[{'hp':hp}])
    first=namespace['project_action'](state(100));second=namespace['project_action'](state(10))
    assert second=={'observed_hp':100} and calls==[100]
    results['projection_cache_reuses_changed_state']=dict(first=first,second=second,computations=len(calls))
    first_file=(PATCHES/'unit_data_structure_optimization_patch.diff').read_text(encoding='utf-8-sig').split('diff --git a/server/battle_logic.py')[0]
    code='\n'.join(line[1:] for line in first_file.splitlines() if line.startswith('+') and not line.startswith('+++'))
    compact={};exec(compile(code,'<proposed-unit-structs>','exec'),compact)
    unit=dict(id=1,hp=100,pos={'x':2,'y':3},team='ally',action_points=15,ammo=20,armor=7,owner_id=9)
    converted=compact['to_dict_unit'](compact['from_dict_unit'](unit))
    lost=sorted(set(unit)-set(converted));assert lost==['action_points','ammo','armor','owner_id']
    results['compact_conversion_loses_fields']=lost
    # Actual checkpoint encoder rejects a lock placed inside a battle dict.
    from tio.battle_snapshot import dumps
    try:dumps({'lock':threading.Lock()})
    except ValueError as error:results['checkpoint_lock_rejected']=str(error)
    else:raise AssertionError('Lock unexpectedly serializable')
    from server.team_arena import TeamArena
    hub=TeamArena()
    try:pickle.dumps(hub.tick_battle)
    except (TypeError,pickle.PicklingError) as error:results['bound_hub_method_not_picklable']=str(error)
    else:raise AssertionError('Hub unexpectedly picklable')
    lock=threading.Lock()
    with lock:
        reacquired=lock.acquire(blocking=False)
        assert not reacquired
    results['nested_nonreentrant_lock_acquire']=reacquired
    # Proposed snapshot holds the same mutable arrays; clearing queues also
    # deletes arrivals that happened after the snapshot was taken.
    battle=dict(units=[{'hp':100}],pending_actions=[])
    snapshot=dict(units=battle['units'],pending_actions=battle['pending_actions'])
    battle['units'][0]['hp']=90;battle['pending_actions'].append('new-player-action')
    assert snapshot['units'][0]['hp']==90
    battle['pending_actions']=[]
    results['snapshot_is_not_isolated']=True
    results['new_pending_action_discarded']=not battle['pending_actions']
    out=ROOT/'reports/copilot-patches-20261017/counterexamples.json'
    out.write_text(json.dumps(dict(passed=True,results=results,hosted_changes=False),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
