"""Read-only, checksum-verified audit of the local cooperative battle journal."""
import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.battle_snapshot import loads


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value,dict):
        return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,set,frozenset)):
        return [plain(v) for v in value]
    if isinstance(value,bytes):
        return value.decode('cp1251')
    if isinstance(value,Path):
        return str(value)
    if value is None or type(value) in (int,float,str,bool):
        return value
    return str(value)


def audit():
    path=ROOT/'data/contracts-local/reservation.sqlite3'
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        # One read transaction preserves consistency while the real battle runs.
        db.execute('BEGIN')
        result=dict(at=datetime.now(timezone.utc).isoformat(),read_only=True,
                    parties=[dict(r) for r in db.execute('SELECT * FROM travel_party_groups')],
                    party_members=[dict(r) for r in db.execute('SELECT * FROM travel_party_members')],
                    routes=[dict(r) for r in db.execute('SELECT * FROM travel_party_journeys')],
                    contracts=[dict(r) for r in db.execute('SELECT id,state,template_id,expires_at,match_id FROM pve_contract_instances')],
                    bindings=[dict(r) for r in db.execute('SELECT * FROM battle_checkpoint_members')],
                    checkpoints=[])
        for row in db.execute('SELECT match_id,revision,payload,checksum,status,updated_at FROM battle_checkpoints'):
            if hashlib.sha256(row['payload'].encode()).hexdigest()!=row['checksum']:
                raise ValueError('Battle checkpoint checksum differs')
            decoded,_timing=loads(row['payload'],rebase=False)
            battle=decoded['battle'];arena=battle['arena'];room=battle['room'];field=battle['field']
            result['checkpoints'].append(dict(
                match_id=row['match_id'],revision=row['revision'],checksum_verified=True,status=row['status'],updated_at=row['updated_at'],
                root_kind=decoded['kind'],kind=battle['kind'],contract_id=battle.get('contract_id'),
                humans=sorted(battle['humans']),bots=sorted(battle['bots']),finished=battle['finished'],
                room=plain(room),loaded=sorted(arena._loading[room.room_id]),turn=plain(arena._turns.get(room.room_id)),
                scene=plain(field.scene_metadata),contract_scene=plain(field.contract_metadata),
                actors=[plain(a) for a in field._actors.values()],
                views={str(owner):sorted(view.visible) for owner,view in battle['views'].items()},
                sessions=plain(decoded['sessions'])))
        return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path)
    args=p.parse_args();result=audit()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
