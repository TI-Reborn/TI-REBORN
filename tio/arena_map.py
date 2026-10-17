"""Validated battlefield layouts assembled from original client fragments."""
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import json
from .protocol.battle_ground import BattleGround, GroundEntry, encode_battle_ground


@dataclass(frozen=True)
class ArenaMap:
    ground: BattleGround
    blocked: frozenset
    player_spawns: tuple
    bot_spawns: tuple
    containers: tuple=()
    doors: tuple=()
    transparent_obstacles: frozenset | None=None


def load_arena_map(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    fragments=json.loads((Path(path).parent/'arena_fragments.json').read_text(encoding='utf-8')) if data['objects'] else {}
    return build_arena_map(data, fragments)


def build_arena_map(data, fragments, *, max_deployment=6):
    if type(max_deployment) is not int or not 1 <= max_deployment <= 8:
        raise ValueError('Invalid deployment capacity')
    """Validate a fixed or generated layout before emitting client resources."""
    width, height, terrain = (data[k] for k in ('width','height','ground_id'))
    if any(type(v) is not int for v in (width,height,terrain)) or not 8<=width<=128 or not 8<=height<=128 or terrain not in range(5):
        raise ValueError('Unsupported training map dimensions or ground')
    # Native7173cc selects ground.xml brushes from each first-layer cell.
    # Keep this explicit opt-in separate from legacy ground_id metadata so
    # fixed training layouts and other existing callers retain their terrain.
    ground_brush = data.get('ground_brush_id', 0)
    if type(ground_brush) is not int or not 0 <= ground_brush <= 255:
        raise ValueError('Invalid native ground brush')
    blocked, entries, containers, doors = set(), [], [], []
    transparent=set()
    reserved=set()
    for obj in data['objects']:
        name = obj['file']
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name or relative.suffix != '.s':
            raise ValueError('Invalid client map fragment path')
        fragment=fragments.get(name)
        if fragment is None:raise ValueError('Fragment has no verified footprint')
        x,y=obj['x'],obj['y']
        w,h=fragment['width'],fragment['height']
        if any(type(v) is not int for v in (x,y,w,h)) or not (w>0 and h>0 and 0<=x<x+w<=width and 0<=y<y+h<=height):
            raise ValueError('Object outside map')
        cells = {(i,j) for i in range(x,x+w) for j in range(y,y+h)}
        if reserved & cells: raise ValueError('Overlapping object reservations')
        reserved.update(cells)
        tiles=fragment['tiles']
        if len(tiles)!=w*h or any(type(t) is not int or not 0<=t<=255 for t in tiles):raise ValueError('Invalid fragment grid')
        # Source fragments use0 for unset,1 for open margins,2/3 for
        # occupied cells. Both obstacle classes remain impassable.
        # Type4 occurs in newer fragments (including standalone steel boxes).
        # Conservatively reserve it too; its exact collision class is unrecovered.
        if any(t not in (0,1,2,3,4) for t in tiles):raise ValueError('Unmapped fragment cell type')
        blocked.update((x+i,y+j) for j in range(h) for i in range(w) if tiles[j*w+i] in (2,3,4))
        # Original CanTrace tests only class3; 2/4 still block movement.
        transparent.update((x+i,y+j) for j in range(h) for i in range(w) if tiles[j*w+i] in (2,4))
        for i,j,opened in fragment.get('doors',()):
            if not (0<=i<w and 0<=j<h) or type(opened) is not bool:
                raise ValueError('Invalid door position or state')
            doors.append((x+i,y+j,opened))
            # Door collision is dynamic; connectivity considers openable doors.
            blocked.discard((x+i,y+j))
            transparent.discard((x+i,y+j))
        for i,j in fragment.get('containers',()):
            if not (0<=i<w and 0<=j<h):raise ValueError('Invalid container position')
            containers.append((x+i,y+j))
            blocked.add((x+i,y+j))
            if tiles[j*w+i]!=3:transparent.add((x+i,y+j))
        # Native6cd428 indexes resources by basename. Its ExtractFileName
        # helper424d7c only strips backslash/colon, not POSIX '/', so sending
        # mappack1/foo silently misses the indexed foo.s (invisible walls).
        entries.append(GroundEntry(relative.stem.encode('ascii'),x,y))
    spawns=[]
    for key in ('player_spawns','bot_spawns'):
        points=tuple(tuple(p) for p in data[key])
        if not 1<=len(points)<=max_deployment: raise ValueError('Too many spawns for deployment capacity')
        for point in points:
            if len(point)!=2 or any(type(v) is not int for v in point) or not (0<=point[0]<width and 0<=point[1]<height) or point in blocked or point in spawns:
                raise ValueError('Invalid or occupied spawn')
            spawns.append(point)
    # Second-layer obstacle codes have not been mapped: server reservations
    # enforce collisions without inventing client tile meanings.
    # ti.exe717eea interprets the first byte as persistent exploration (==1),
    # NOT a terrain ID. UpdateFog6e40a4 skips clearing old visibility in that
    # mode. Arena maps must recalculate fog after every movement; keep the
    # legacy ground_id layout metadata out of this protocol flag.
    ground=BattleGround(0,width,height,bytes([ground_brush])*(width*height),tuple(entries),bytes(width*height))
    encode_battle_ground(ground)
    if len({(x,y) for x,y,_ in doors})!=len(doors):raise ValueError('Duplicate door')
    if {(x,y) for x,y,_ in doors} & (set(containers)|set(spawns)):
        raise ValueError('Door overlaps actor or container')
    split=len(data['player_spawns'])
    if split!=len(data['bot_spawns']):raise ValueError('Balanced deployment sides required')
    return ArenaMap(ground,frozenset(blocked),tuple(spawns[:split]),tuple(spawns[split:]),tuple(containers),tuple(doors),frozenset(transparent))
