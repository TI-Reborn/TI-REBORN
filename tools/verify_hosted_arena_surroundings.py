"""Verify shared hosted arena art over public encrypted TCP after deployment.

Only randomly named accounts created by this tool may be provisioned or
adjusted. A consistent SQLite backup precedes account creation. Existing
accounts/saves and runtime configuration are never written. QA accounts remain
for audit and optional graphical validation; this script does not launch a
graphical client. Importing the module and --self-test perform no network work.
"""
from collections import Counter, deque
from dataclasses import dataclass, replace
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import struct
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]

from test_multi_account import MultiAccountTests
from tio.protocol.arena import decode_room_list
from tio.protocol.battle_ground import (BattleGround, GroundEntry,
                                        decode_battle_ground, encode_battle_ground)
from tio.protocol.battle_move import BattleMove, decode_battle_move, encode_move_request
from tio.protocol.battle_turn import encode_end_turn


PROFILES = {
    'denver': dict(town=2, level=4, brushes={3}, code='de'),
    'new_york': dict(town=5, level=4, brushes={2}, code='ny'),
    'military_zone': dict(town=8, level=4, brushes={1}, code='mz'),
    'reservation': dict(town=3, level=1, brushes={10, 11}, code='rv'),
}
PARTICIPANTS = {0: 2, 1: 4, 4: 8}
PRIVATE = ROOT/'reports/arena-surroundings/private'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def scene_names(policy, profile, size):
    require(policy['version'] == 1, 'Unsupported surroundings policy')
    variants = policy['profiles'][profile]['variants']
    names = {variant['scene_by_size'][str(size)] for variant in variants}
    pattern = r'as_' + PROFILES[profile]['code'] + r'_[1-3]_' + str(size)
    require(bool(names) and all(re.fullmatch(pattern, n) for n in names),
            'Unexpected scene names in the surroundings policy')
    return names


def validate_shared_ground(packets, profile, mode, policy):
    """Assert actual wire bytes, rather than ground_id layout metadata."""
    require(len(packets) >= 2 and len(set(packets)) == 1,
            'Real accounts received different encoded BattleGround bytes')
    ground = decode_battle_ground(packets[0])
    size = 57 if mode in (1, 4) else 38
    require((ground.width, ground.height) == (size, size), 'Playable field dimensions changed')
    brushes = set(ground.first_layer)
    require(len(brushes) == 1 and brushes <= PROFILES[profile]['brushes'],
            'Actual native ground brush does not match the city')
    require(ground.unknown_u8 == 0, 'Terrain altered the fog flag')
    markers = [entry for entry in ground.entries if entry.name.startswith(b'as_')]
    require(len(markers) == 1, 'A match must have exactly one surroundings scene')
    marker = markers[0]
    name = marker.name.decode('ascii')
    require(name in scene_names(policy, profile, size), 'Another city/size scene was substituted')
    require((marker.unknown_u8_01, marker.unknown_u8_02) == (0, 0),
            'Surroundings scene must be anchored at 0,0')
    return ground, name


def native_resource(blob):
    """Decode the published native ZIP envelope without installing resources."""
    require(len(blob) >= 16, 'Truncated published native resource')
    raw = zlib.decompress(blob[16:]) if blob[:4] == b'\x03ZIP' else blob
    if blob[:4] == b'\x03ZIP':
        require(len(raw) == struct.unpack_from('<I', blob, 8)[0], 'Compressed scene length mismatch')
    return raw


def validate_scene_blob(blob, size):
    """Parse visual-only SET cells and safe internal foreground attachment anchors."""
    require(size in (38, 57), 'Unexpected playable map size')
    raw = native_resource(blob)
    require(len(raw) >= 32 and raw[:8] == b'TI SET\0\2', 'Expected native TI SET v2')
    width, height, count = struct.unpack_from('<3H', raw, 12)
    offset = 32 + 2*width*height
    require((width, height) == (1, 1) and count > 0 and offset + 72*count == len(raw),
            'Decorative native scene must have exact1x1 cells and complete model records')
    require(struct.unpack_from('<H', raw, 18)[0] == 2 and
            struct.unpack_from('<I', raw, 20)[0] == 0 and raw[32:34] == bytes(2),
            'Decorative scene contains cell payload or extra collision data')
    models, attachment_counts = [], Counter()
    for index in range(count):
        record = raw[offset + 72*index:offset + 72*(index+1)]
        length = record[0]
        require(0 < length <= 63, 'Invalid static model name')
        name = record[1:1+length].decode('ascii')
        require(re.fullmatch(r'[A-Za-z0-9_.-]+\.t', name) is not None, 'Unsafe native model basename')
        x, y = struct.unpack_from('<ii', record, 64)
        require(0 <= x < size and 0 <= y < size, 'Foreground anchor is outside native attachment bounds')
        attachment_counts[x, y] += 1
        require(attachment_counts[x, y] <= 255, 'Foreground attachment byte count would overflow')
        models.append(dict(name=name, x=x, y=y))
    return dict(width=width, height=height, model_count=count, cell_payload_hex='0000',
                anchors_inside_playable_bounds=True, max_models_per_anchor=max(attachment_counts.values()), models=models)


def validate_tile_blob(blob):
    raw = native_resource(blob)
    require(len(raw) == 544 and raw[:8] == b'TI TILE\0' and
            struct.unpack_from('<HH', raw, 8) == (1, 2) and
            raw[12:24] == bytes(12), 'Expected exact native one-record TILE v2')
    require(raw[68:70] == b'\1\0', 'Decorative tile must use foreground flag1 and rectangular full-frame UVs')
    require(raw[28:36] == bytes(8), 'Tile-local coordinates would shift its safe scene anchor')
    require(raw[340:356] == bytes(16) and raw[440:539] == bytes(99),
            'Decorative tile contains native interaction or chained action fields')
    require(raw[539:544] == b'\1\0\0\0\0', 'Decorative tile visibility/behavior differs')
    require(struct.unpack_from('<II', raw, 52) == (0x00ffffff, 255) and raw[64:66] == bytes(2),
            'Decorative tile must be opaque white with one stationary full frame')
    dimensions = struct.unpack_from('<HH', raw, 60)
    require(dimensions == struct.unpack_from('<HH', raw, 334) == (1024, 1024),
            'Decorative texture/frame dimensions must be1024x1024')
    length = raw[203]
    require(0 < length <= 128, 'Invalid native texture basename')
    texture = raw[204:204+length].decode('ascii')
    require(re.fullmatch(r'[A-Za-z0-9_.-]+\.png', texture) is not None, 'Unsafe native PNG basename')
    return dict(texture=texture, dimensions=list(dimensions),
                screen_offset=list(struct.unpack_from('<hh', raw, 48)),
                static_flag=1, render_as_tile=0, interaction_bytes_hex='00'*16)


def published_alpha_proof(alpha, size, *, minimum=.95):
    """Independent native pixel-center projection: clear hole, exterior sides/corners."""
    depth = {38: 24, 57: 36}[size]
    width, height = 64*(size+2*depth), 32*(size+2*depth)
    require(alpha.mode == 'L' and alpha.size == (width, height), 'Unexpected reconstructed native alpha canvas')
    pixels = alpha.tobytes()
    opaque_table = bytes(int(value >= 128) for value in range(256))
    labels = ('x_negative', 'y_negative', 'x_at_or_above_width', 'y_at_or_above_width')
    corners = ('x_negative_y_negative', 'x_negative_y_positive',
               'x_positive_y_negative', 'x_positive_y_positive')
    counts = {key: dict(pixels=0, opaque_pixels=0) for key in labels+corners}
    hole_bad = outside_bad = 0

    def interval(row_bytes, lower, upper):
        begin = max(0, (lower+width)//2)
        end = min(width, (upper+width-1)//2+1)
        return row_bytes[begin:max(begin, end)]

    for row in range(height):
        a = pixels[row*width:(row+1)*width]
        inner_radius = 64*size-2*abs(2*row+1-height)
        if inner_radius >= 0:
            samples = interval(a, -inner_radius, inner_radius)
            hole_bad += len(samples)-samples.count(b'\0')
        outer_radius = width-2*abs(2*row+1-height)
        if outer_radius < 0:
            outside_bad += len(a)-a.count(b'\0')
        else:
            for samples in (interval(a, -width, -outer_radius-1), interval(a, outer_radius+1, width)):
                outside_bad += len(samples)-samples.count(b'\0')
        sy2 = 2*row+1-64*depth
        negative, positive, middle = (-512, -64), (128*size+64, 128*(size+4)), (256, 128*(size-2))
        regions = ((negative, middle), (middle, negative), (positive, middle), (middle, positive),
                   (negative, negative), (negative, positive), (positive, negative), (positive, positive))
        for label, (xb, yb) in zip(labels+corners, regions):
            # wx=2*sy2-x2,wy=2*sy2+x2; intersect exact integer x2 intervals.
            samples = interval(a, max(2*sy2-xb[1], yb[0]-2*sy2),
                                  min(2*sy2-xb[0], yb[1]-2*sy2))
            counts[label]['pixels'] += len(samples)
            counts[label]['opaque_pixels'] += samples.translate(opaque_table).count(b'\1')
    require(hole_bad == 0, 'Published PNG alpha covers playable ground')
    require(outside_bad == 0, 'Published PNG alpha escapes its decorative outer diamond')
    for label, count in counts.items():
        require(count['pixels'] > 0, 'Exterior native alpha band has no samples')
        count['opaque_fraction'] = count['opaque_pixels']/count['pixels']
        require(count['opaque_fraction'] >= minimum, 'Published PNGs leave a gap on '+label)
    return dict(passed=True, hole_nonzero_pixels=hole_bad, outside_nonzero_pixels=outside_bad,
                minimum_opaque_fraction=minimum, four_sides={key:counts[key] for key in labels},
                four_corners={key:counts[key] for key in corners},
                method='Actual published PNG alpha reconstructed from signed native foreground offsets; independent pixel-center diamond inequalities')


def boundary_route(state):
    """Find the shortest route to a positive edge for an adjacent byte-coordinate exit."""
    width, height = state['width'], state['height']
    actors = state['actors']
    candidates = []
    for actor in actors:
        start = actor['x'], actor['y']
        occupied = {(a['x'], a['y']) for a in actors if a['id'] != actor['id'] and a['hp']}
        unavailable = set(map(tuple, state['blocked'])) | occupied
        pending, previous = deque([start]), {start: None}
        edge = None
        while pending:
            x, y = pending.popleft()
            if x == width-1 or y == height-1:
                edge = x, y
                break
            for cell in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
                if (0 <= cell[0] < width and 0 <= cell[1] < height
                        and cell not in unavailable and cell not in previous):
                    previous[cell] = x, y
                    pending.append(cell)
        if edge is None:
            continue
        route, cell = [], edge
        while cell != start:
            route.append(cell)
            cell = previous[cell]
        outside = (width, edge[1]) if edge[0] == width-1 else (edge[0], height)
        candidates.append((len(route), actor['id'], actor['account'], tuple(reversed(route)), outside))
    require(bool(candidates), 'No reachable boundary cell for the outside-movement check')
    return min(candidates)


# These programs are executed only by an explicit verifier/provisioning run.
READINESS = r'''
import json,sqlite3,subprocess
lines=subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).splitlines()
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
 assert integrity=='ok'
print(json.dumps(dict(established_connections=len(lines),integrity=integrity)))
'''

PROVISION = r'''
import json,pathlib,re,sqlite3,subprocess,sys,tempfile
from server.accounts import Accounts
data=json.load(sys.stdin);prefix=data['prefix'];pairs=data['pairs']
assert re.fullmatch(r'qs[0-9a-f]{8}',prefix) and 2<=len(pairs)<=8
names=[n for n,p in pairs]
assert len(set(names))==len(names) and names==[prefix+chr(97+i) for i in range(len(names))]
assert not subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).strip(),'Players connected; provisioning aborted before writes'
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-surroundings-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:
 assert not any(src.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
before=sqlite3.connect(folder/'reservation.sqlite3').execute('SELECT COUNT(*) FROM accounts').fetchone()[0]
for name,password in pairs:Accounts('/var/lib/tio-server/reservation.sqlite3').create(name,password,character=name)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 owned={n:list(db.execute('SELECT hex(salt),hex(digest),iterations FROM accounts WHERE login=?',(n,)).fetchone()) for n in names}
proof=folder/'qa-owned.json';proof.write_text(json.dumps(dict(prefix=prefix,names=names,credentials=owned)));proof.chmod(0o600)
print(json.dumps(dict(backup=str(folder),accounts_before=before,created=len(names))))
'''

OWNERSHIP = r'''
import json,pathlib,re,sqlite3,sys
data=json.load(sys.stdin);folder=pathlib.Path(data['backup']).resolve();names=data['names']
assert folder.parent==pathlib.Path('/root') and folder.name.startswith('tio-before-surroundings-qa-')
proof=json.loads((folder/'qa-owned.json').read_text())
assert names==proof['names'] and all(re.fullmatch(r'qs[0-9a-f]{8}[a-h]',n) for n in names)
with sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True) as old:
 assert not any(old.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 for n in names:
  assert list(db.execute('SELECT hex(salt),hex(digest),iterations FROM accounts WHERE login=?',(n,)).fetchone())==proof['credentials'][n]
'''

FIXTURE = OWNERSHIP + r'''
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.locations import LocationStore,center
town=data['town'];level=data['level'];assert (town,level) in ((2,4),(5,4),(8,4),(3,1))
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE')
 placeholders=','.join('?' for _ in names)
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN ('+placeholders+')',names).fetchone()
 for n in names:
  raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()
  assert raw,'Enter each fresh account once before changing its fixture'
  pet=decode_pet_info(raw[0],human_equipment=True)
  fields={**pet.fields,'0x8c4aef':level,'0x8c4a07':1000,'0x8c4ab1':1000,'0x8c44a6':1}
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(replace(pet,fields=fields)),n))
  LocationStore._save(db,n,town,*center(town))
print(json.dumps(dict(town=town,level=level,own_accounts=len(names))))
'''

SNAPSHOT = r'''
import hashlib,json,sqlite3,sys
from tio.battle_snapshot import loads
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=[db.execute('SELECT c.match_id,c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(n,)).fetchone() for n in names]
 assert all(rows) and len({r[0] for r in rows})==1,'Own QA accounts are not in one checkpoint'
 battle=loads(rows[0][1])[0]['battle'];field=battle['field'];turn=battle['arena']._turns.get(battle['room'].room_id)
 assert set(r[0] for r in battle['reward_roster'].values())==set(names),'An unrelated account joined the QA match'
 print(json.dumps(dict(match=battle['match_id'],town=battle['city_id'],metadata=field.scene_metadata,
  bots=len(battle['bots']),width=field.width,height=field.height,blocked=list(field.blocked),
  ground_sha256=hashlib.sha256(battle['ground']).hexdigest(),turn=turn[0] if turn else None,
  actors=[dict(id=a.actor_id,owner=a.owner_id,account=battle['reward_roster'][a.owner_id][0],
   x=a.x,y=a.y,hp=a.health,ap=a.action_points) for a in field._actors.values()])))
'''

PRESERVATION = OWNERSHIP + r'''
with sqlite3.connect('file:'+str(folder/'reservation.sqlite3')+'?mode=ro',uri=True) as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 checked={}
 for table, in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"):
  quoted='"'+table.replace('"','""')+'"'
  columns=[r[1] for r in old.execute('PRAGMA table_info('+quoted+')')]
  account=next((c for c in ('account','login') if c in columns),None)
  if account is None:continue
  before=set(map(repr,old.execute('SELECT * FROM '+quoted)))
  after=set(map(repr,db.execute('SELECT * FROM '+quoted+' WHERE "'+account+'" NOT IN ('+','.join('?' for _ in names)+')',names)))
  assert before==after,'Pre-existing account data changed in '+table
  checked[table]=len(before)
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN ('+','.join('?' for _ in names)+')',names).fetchone()
 print(json.dumps(dict(integrity='ok',existing_account_rows_preserved=checked)))
'''

INITIALIZATION = OWNERSHIP + r'''
import hashlib
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 initialized=[]
 for n in names:
  character=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(n,)).fetchone()
  pet=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()
  assert character and character[0]==n.encode('ascii') and pet,'Own QA character initialization incomplete'
  initialized.append(dict(account=n,pet_sha256=hashlib.sha256(pet[0]).hexdigest()))
 print(json.dumps(dict(initialized_count=len(initialized),characters=initialized)))
'''


@dataclass
class FreshSurroundingsQA:
    """Reusable ownership-checked QA fixture for a later graphical harness."""
    host: str
    prefix: str
    names: list
    passwords: list
    backup: str
    key: str = str(Path.home()/'.ssh/tio_server')
    credential_path: str | None = None

    def remote(self, code, payload):
        command = 'cd /opt/tio-emulator && .venv/bin/python -c ' + shlex.quote(code)
        result = subprocess.run(['ssh', '-i', self.key, '-o', 'BatchMode=yes',
                                 '-o', 'ConnectTimeout=10', 'root@'+self.host, command],
                                input=json.dumps(payload), capture_output=True,
                                text=True, encoding='utf-8', timeout=45)
        if result.returncode:
            # The provisioning payload contains passwords: never echo it or
            # include captured remote stdout/stderr in public evidence.
            raise RuntimeError('Remote QA operation failed (exit '+str(result.returncode)+')')
        return json.loads(result.stdout)

    def ownership_payload(self):
        return dict(backup=self.backup, names=self.names)

    @classmethod
    def create(cls, host, participants=8, *, key=None, keep_credentials=True):
        require(participants in (2, 4, 8), 'Use two, four or eight fresh QA participants')
        prefix = 'qs' + secrets.token_hex(4)
        fixture = cls(host, prefix, [prefix+chr(97+i) for i in range(participants)],
                      [secrets.token_urlsafe(24) for _ in range(participants)], '',
                      key or str(Path.home()/'.ssh/tio_server'))
        result = fixture.remote(PROVISION, dict(prefix=prefix, pairs=list(zip(fixture.names, fixture.passwords))))
        fixture.backup = result['backup']
        if keep_credentials:
            fixture.save_private()
        return fixture

    def save_private(self):
        PRIVATE.mkdir(parents=True, exist_ok=True)
        # The workspace's main ignore file does not ignore reports. A local
        # ignore-all rule ensures credentials never become review artifacts.
        (PRIVATE/'.gitignore').write_text('*\n', encoding='utf-8')
        path = PRIVATE/(self.prefix+'.json')
        path.write_text(json.dumps(dict(version=1, host=self.host, prefix=self.prefix,
                                       names=self.names, passwords=self.passwords,
                                       backup=self.backup, key=self.key), indent=2)+'\n', encoding='utf-8')
        if os.name != 'nt':
            path.chmod(0o600)
        self.credential_path = str(path)
        return path

    @classmethod
    def load_private(cls, path):
        path = Path(path).resolve()
        require(path.parent == PRIVATE.resolve(), 'Credentials must reside in the ignored private reports folder')
        require((PRIVATE/'.gitignore').read_text().strip() == '*', 'Private reports are not ignored')
        data = json.loads(path.read_text(encoding='utf-8'))
        require(data.pop('version') == 1, 'Unsupported QA fixture')
        fixture = cls(**data, credential_path=str(path))
        require(re.fullmatch(r'qs[0-9a-f]{8}', fixture.prefix), 'Invalid own QA prefix')
        require(fixture.names == [fixture.prefix+chr(97+i) for i in range(len(fixture.names))]
                and len(fixture.names) in (2, 4, 8), 'Invalid own QA account list')
        require(len(fixture.passwords) == len(fixture.names), 'Incomplete private QA fixture')
        # Loading does not contact the server; every subsequent mutation runs
        # OWNERSHIP against the original consistent backup and salted digests.
        return fixture

    def set_city(self, profile):
        policy = PROFILES[profile]
        return self.remote(FIXTURE, {**self.ownership_payload(),
                                    'town': policy['town'], 'level': policy['level']})

    def snapshot(self, names):
        return self.remote(SNAPSHOT, names)

    def preservation(self):
        return self.remote(PRESERVATION, self.ownership_payload())

    def initialization(self):
        return self.remote(INITIALIZATION, self.ownership_payload())

    def readiness(self):
        return self.remote(READINESS, {})


class NetworkQA:
    def __init__(self, fixture):
        self.fixture = fixture
        self.case = MultiAccountTests()
        self.case.config = SimpleNamespace(game_port=28512, session_port=28513)
        self.case.clients = []
        self.peers, self.received = {}, {}
        def connect(port):
            connection = socket.create_connection((fixture.host, port), timeout=15)
            self.case.clients.append(connection)
            return connection
        self.case.connect = connect
        self.case.ping = self.ping

    def ping(self, peer):
        peer.send(b'\x70')
        require(peer.until(b'\x9e', max_packets=4096) == b'\x9e', 'Missing public TCP keepalive')

    def enter(self, index, *, reconnect=False):
        fixture = self.fixture
        transition = self.case.begin(fixture.names[index], fixture.passwords[index])
        expected = len(self.peers) + (0 if reconnect else 1)
        require(self.case.last_server_entry.unknown_u16_02 == expected,
                'Other accounts are online; refuse to enter shared production matchmaking')
        peer = self.case.handoff(transition)
        original = peer.receive
        self.received[index] = []
        def receive():
            packet = original()
            self.received[index].append(packet)
            return packet
        peer.receive = receive
        self.peers[index] = peer
        self.case.enter(peer, fixture.names[index])
        return peer

    def command(self, index, packet):
        start = len(self.received[index])
        self.peers[index].send(packet)
        self.ping(self.peers[index])
        return self.received[index][start:]

    def close(self):
        for connection in self.case.clients:
            connection.close()
        self.case.clients = []
        self.peers = {}

    def start(self, mode):
        count = PARTICIPANTS[mode]
        for index in range(count):
            self.enter(index)
        if mode == 0:
            for index in (0, 1):
                self.command(index, b'\xba\3\0\1')
        else:
            for captain in (0, 1):
                self.command(captain, bytes((0xba, 3, mode, 1)))
            replies = self.command(0, b'\xba\1')
            rooms = decode_room_list(next(p for p in reversed(replies) if p.startswith(b'\xba\2')))
            own_rooms = {room.name.decode('ascii'): room.unknown_u32_00 for room in rooms
                         if room.name.decode('ascii') in self.fixture.names[:2]}
            require(len(own_rooms) == 2, 'Fresh captains did not create two separate teams')
            for index in range(2, count):
                captain = index % 2
                identity = own_rooms[self.fixture.names[captain]]
                self.command(index, b'\xba\4'+identity.to_bytes(4, 'little'))
            # Every roster change clears Ready, so ready only after all joins.
            for index in range(2, count):
                self.command(index, b'\x2c\1')
            for captain in (0, 1):
                self.command(captain, b'\x2e')
        packets = []
        for index in range(count):
            peer = self.peers[index]
            if b'\x41' not in self.received[index]:
                peer.until(b'\x41', max_packets=2048)
            packets.append(next(p for p in reversed(self.received[index]) if p[:1] == b'\x35'))
            self.command(index, b'\x36')
        return packets

    def await_owner(self, names, owner):
        for _ in range(2*len(names)+2):
            state = self.fixture.snapshot(names)
            if state['turn'] == owner:
                return state
            require(state['turn'] is not None, 'The shared match has no active turn')
            account = next(a['account'] for a in state['actors'] if a['owner'] == state['turn'])
            index = self.fixture.names.index(account)
            self.command(index, encode_end_turn())
            time.sleep(.12)
        raise AssertionError('Could not advance own QA turns to the boundary actor')

    def verify_outside_move(self, names, initial):
        _, identity, account, route, outside = boundary_route(initial)
        index = self.fixture.names.index(account)
        actor = next(a for a in initial['actors'] if a['id'] == identity)
        state = self.await_owner(names, actor['owner'])
        while route:
            actor = next(a for a in state['actors'] if a['id'] == identity)
            chunk = route[:actor['ap']]
            require(bool(chunk), 'No action points for the legal boundary approach')
            self.command(index, encode_move_request(BattleMove(identity, chunk)))
            after = self.fixture.snapshot(names)
            moved = next(a for a in after['actors'] if a['id'] == identity)
            require((moved['x'], moved['y']) in chunk, 'A legal boundary approach did not move')
            consumed = chunk.index((moved['x'], moved['y'])) + 1
            route = route[consumed:]
            state = after
            if route:
                self.command(index, encode_end_turn())
                state = self.await_owner(names, actor['owner'])
        before = next(a for a in state['actors'] if a['id'] == identity)
        require(max(abs(outside[0]-before['x']), abs(outside[1]-before['y'])) == 1,
                'Outside target must be adjacent, so rejection really exercises the map boundary')
        replies = self.command(index, encode_move_request(BattleMove(identity, (outside,))))
        correction = [decode_battle_move(p) for p in replies if p[:1] == b'\x3d']
        require(any(m.actor_id == identity and m.path == ((before['x'], before['y']),)*2
                    for m in correction), 'Outside movement did not restore native prediction')
        after = self.fixture.snapshot(names)
        require(next(a for a in after['actors'] if a['id'] == identity) == before,
                'Outside movement changed the actor or spent action points')
        require((after['width'], after['height']) == (initial['width'], initial['height']),
                'Decoration expanded the authoritative game area')
        require(after['ground_sha256'] == initial['ground_sha256'], 'Movement regenerated decorative art')
        return dict(account=account, actor=identity, from_cell=[before['x'], before['y']],
                    rejected_adjacent_cell=outside, ap_preserved=before['ap'])

    def reconnect_ground(self, index):
        self.peers[index].sock.close()
        time.sleep(.65)
        peer = self.enter(index, reconnect=True)
        if b'\x41' not in self.received[index]:
            peer.until(b'\x41', max_packets=2048)
        packet = next(p for p in reversed(self.received[index]) if p[:1] == b'\x35')
        self.command(index, b'\x36')
        return packet

    def leave(self):
        for index in tuple(self.peers):
            self.command(index, b'\x2a\1')
        self.close()
        time.sleep(.75)


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read(24*1024*1024))


def published_scene(host, manifest, scene, size, *, fetch=None):
    """Bind every SET/TILE/PNG byte to the actual manifest and inspect PNG alpha."""
    from PIL import Image
    records = {r['path']:r for r in manifest['files']}
    require(len(records) == len(manifest['files']), 'Duplicate path in the published manifest')
    observed = {}

    def resource(path):
        record = records.get(path)
        require(record is not None, 'Selected decorative resource is absent from the published manifest: '+path)
        require(re.fullmatch(r'[a-f0-9]{64}', record['sha256']) is not None and
                type(record['size']) is int and 0 < record['size'] <= 8*1024*1024,
                'Unexpected published decorative resource size/SHA')
        if fetch is None:
            with urllib.request.urlopen('https://'+host+'/updates/blobs/'+record['sha256'], timeout=20) as response:
                blob = response.read(record['size']+1)
        else:
            blob = fetch(record)
        require(len(blob) == record['size'] and sha(blob) == record['sha256'],
                'Published decorative resource differs from its exact manifest record: '+path)
        observed[path] = {key:record[key] for key in ('path', 'size', 'sha256')}
        return blob

    path = 'base/maps/'+scene+'.s'
    native = validate_scene_blob(resource(path), size)
    depth = {38:24, 57:36}[size]
    full_width, full_height = 64*(size+2*depth), 32*(size+2*depth)
    alpha = Image.new('L', (full_width, full_height))
    dependencies, occupied_origins = {}, set()
    for model in native['models']:
        basename = model['name']
        require(re.fullmatch(re.escape(scene)+r'_p[0-9]{4}\.t', basename) is not None,
                'Another decorative scene model was substituted')
        model_path = 'base/setting/arena_surroundings/'+basename
        tile = validate_tile_blob(resource(model_path))
        require(tile['texture'] == basename[:-2]+'.png', 'Another decorative texture was substituted')
        texture_path = 'base/setting/arena_surroundings/'+tile['texture']
        image_raw = resource(texture_path)
        with Image.open(io.BytesIO(image_raw)) as image:
            require(image.mode == 'RGBA' and image.size == (1024, 1024),
                    'Published decorative bitmap must be full1024x1024 RGBA')
            pixels = image.getchannel('A').copy()
        sx, sy = tile['screen_offset']
        # Executed original native cell caller subtracts32px before shiftX.
        px = 32*(model['y']-model['x'])-32+sx+full_width//2
        py = 16*(model['x']+model['y'])+sy+32*depth
        require(px % 1024 == py % 1024 == 0 and 0 <= px < full_width and 0 <= py < full_height,
                'Actual foreground sprite offset differs from the registered canvas')
        require((px, py) not in occupied_origins, 'Duplicate foreground patch would cover the same alpha region')
        occupied_origins.add((px, py))
        extent_x, extent_y = min(1024, full_width-px), min(1024, full_height-py)
        require(pixels.crop((0, extent_y, 1024, 1024)).getbbox() is None and
                pixels.crop((extent_x, 0, 1024, 1024)).getbbox() is None,
                'Foreground PNG has opaque pixels in its padded canvas region')
        alpha.paste(pixels.crop((0, 0, extent_x, extent_y)), (px, py))
        dependencies[basename] = dict(model=observed[model_path], texture=observed[texture_path],
                                     tile=tile, canvas_origin=[px, py])
    proof = published_alpha_proof(alpha, size)
    return dict(path=path, sha256=observed[path]['sha256'], native=native,
                model_dependencies=dependencies, alpha_proof=proof,
                exact_published_records=[observed[key] for key in sorted(observed)])


def verify_published_assets(host='185.184.42.88', *, manifest=None, fetch=None, progress=False):
    """Read-only public HTTPS audit of all24 city/variant/size scenes; no QA accounts."""
    policy = json.loads((ROOT/'config/arena_surroundings.json').read_text())
    manifest = manifest or fetch_json('https://'+host+'/updates/manifest.json')
    results = {}
    for profile in PROFILES:
        for size in (38, 57):
            for scene in sorted(scene_names(policy, profile, size)):
                results[scene] = published_scene(host, manifest, scene, size, fetch=fetch)
                if progress:
                    print(json.dumps(dict(public_assets_verified=len(results), expected=24)), flush=True)
    require(len(results) == 24, 'Published audit must contain all24 decorative scenes')
    return dict(passed=True, client_version=manifest['version'], scene_count=len(results),
                scenes=results, accounts_created=0, game_connections_created=0)


def run(host='185.184.42.88', *, modes=(0, 1, 4), fixture_path=None, provision_only=False,
        key=None, keep_credentials=True):
    require(bool(modes) and all(mode in PARTICIPANTS for mode in modes), 'Unsupported QA modes')
    count = max(PARTICIPANTS[mode] for mode in modes)
    fixture = (FreshSurroundingsQA.load_private(fixture_path) if fixture_path else
               FreshSurroundingsQA.create(host, count, key=key, keep_credentials=keep_credentials))
    require(fixture.host == host and len(fixture.names) >= count, 'QA fixture cannot cover this run')
    network = NetworkQA(fixture)
    folder = ROOT/'reports/arena-surroundings'
    folder.mkdir(parents=True, exist_ok=True)
    report = dict(kind='public encrypted TCP with fresh real QA accounts; no graphical clients',
                  accounts=fixture.names, backup=fixture.backup, passed=False, matches=[])
    output = folder/('hosted-'+fixture.prefix+'.json')
    try:
        if fixture_path is None:
            report['before_initialization'] = fixture.readiness()
            require(report['before_initialization']['established_connections'] == 0,
                    'Other accounts are connected; refuse QA character initialization')
            # Ownership and old-account preservation precede all public login.
            report['before_preservation'] = fixture.preservation()
            for index in range(len(fixture.names)):
                network.enter(index)
            network.close()
            report['initialization'] = fixture.initialization()
        if provision_only:
            deadline = time.monotonic()+10
            while True:
                report['after_disconnect'] = fixture.readiness()
                if report['after_disconnect']['established_connections'] == 0:
                    break
                require(time.monotonic() < deadline, 'QA sockets did not close before deployment')
                time.sleep(.25)
            report['preservation'] = fixture.preservation()
            report['passed'] = True
            report['provisioned_only'] = True
        else:
            policy = json.loads((ROOT/'config/arena_surroundings.json').read_text())
            manifest = fetch_json('https://'+host+'/updates/manifest.json')
            report['client_version'] = manifest['version']
            report['published_assets'] = verify_published_assets(host, manifest=manifest, progress=True)
            for profile in PROFILES:
                for mode in modes:
                    fixture.set_city(profile)
                    names = fixture.names[:PARTICIPANTS[mode]]
                    packets = network.start(mode)
                    ground, scene = validate_shared_ground(packets, profile, mode, policy)
                    initial = fixture.snapshot(names)
                    require(initial['town'] == PROFILES[profile]['town']
                            and initial['metadata']['profile'] == profile, 'Hosted match chose another city')
                    require(initial['bots'] == 0 and len(initial['actors']) == len(names),
                            'Validation requires independent real accounts without bots')
                    require((initial['width'], initial['height']) == (ground.width, ground.height),
                            'Client dimensions differ from the authoritative server field')
                    require(initial['ground_sha256'] == sha(packets[0]), 'Checkpoint changed the shared scene')
                    require(all(0 <= x < ground.width and 0 <= y < ground.height
                                for x, y in initial['blocked']), 'Blocked cells lie in the decoration')
                    require(not any(o['file'].startswith('as_') for o in initial['metadata']['objects']),
                            'Decoration was added to authoritative gameplay objects')
                    resource = report['published_assets']['scenes'][scene]
                    movement = network.verify_outside_move(names, initial)
                    replay = network.reconnect_ground(0)
                    require(replay == packets[0], 'Reconnection selected a different decorative variant')
                    restored = fixture.snapshot(names)
                    require(restored['match'] == initial['match'] and restored['ground_sha256'] == sha(replay),
                            'Reconnection replaced the authoritative match')
                    report['matches'].append(dict(profile=profile, mode=mode, match=initial['match'],
                                                  participants=len(names), width=ground.width, height=ground.height,
                                                  brushes=sorted(set(ground.first_layer)), scene=scene,
                                                  ground_sha256=sha(packets[0]), resource=resource,
                                                  outside_move=movement, reconnect_stable=True))
                    network.leave()
            report['preservation'] = fixture.preservation()
            report['passed'] = True
    except BaseException as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        # Only authenticated, freshly provisioned own QA peers receive cleanup.
        for index in tuple(network.peers):
            try:
                network.command(index, b'\x2a\1')
            except (OSError, EOFError, AssertionError, ValueError):
                pass
        raise
    finally:
        network.close()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(report=str(output), passed=report['passed'],
                              credential_file=fixture.credential_path)))
    return fixture, report


def self_test():
    """Offline checks of verifier predicates and embedded-program syntax only."""
    for code in (READINESS, PROVISION, OWNERSHIP, FIXTURE, SNAPSHOT, PRESERVATION, INITIALIZATION):
        compile(code, '<remote QA program>', 'exec')
    policy = dict(version=1, profiles={p: dict(variants=[dict(id='test', scene_by_size={
        str(s): 'as_'+rule['code']+'_1_'+str(s) for s in (38, 57)})]) for p, rule in PROFILES.items()})
    checks = 0
    for profile, rule in PROFILES.items():
        for mode in (0, 1, 4):
            size = 38 if mode == 0 else 57
            marker = 'as_'+rule['code']+'_1_'+str(size)
            ground = BattleGround(0, size, size, bytes([min(rule['brushes'])])*(size*size),
                                  (GroundEntry(marker.encode(), 0, 0),), bytes(size*size))
            packet = encode_battle_ground(ground)
            validate_shared_ground([packet, packet], profile, mode, policy)
            for bad in ([], [packet], [packet, b'wrong']):
                try:
                    validate_shared_ground(bad, profile, mode, policy)
                except AssertionError:
                    checks += 1
                else:
                    raise AssertionError('Invalid shared-ground case was accepted')
            substitutions = (
                replace(ground, first_layer=bytes(size*size)),
                replace(ground, unknown_u8=1),
                replace(ground, entries=()),
                replace(ground, entries=ground.entries*2),
                replace(ground, entries=(GroundEntry(marker.encode(), 1, 0),)),
                replace(ground, entries=(GroundEntry(b'as_other_1_38', 0, 0),)),
                replace(ground, width=8, height=8, first_layer=ground.first_layer[:64],
                        second_layer=bytes(64)),
            )
            for substituted in substitutions:
                bad_packet = encode_battle_ground(substituted)
                try:
                    validate_shared_ground([bad_packet, bad_packet], profile, mode, policy)
                except AssertionError:
                    checks += 1
                else:
                    raise AssertionError('An invalid native brush/scene/field substitution was accepted')
            checks += 1
    raw = bytearray(32 + 2 + 72*4)
    raw[:8] = b'TI SET\0\2'
    struct.pack_into('<3H', raw, 12, 1, 1, 4)
    struct.pack_into('<H', raw, 18, 2)
    for index, position in enumerate(((0, 10), (37, 10), (10, 0), (10, 37))):
        offset = 34 + 72*index
        raw[offset] = 6
        raw[offset+1:offset+7] = b'test.t'
        struct.pack_into('<ii', raw, offset+64, *position)
    require(validate_scene_blob(bytes(raw), 38)['anchors_inside_playable_bounds'],
            'Internal foreground attachment scene parser failed')
    for offset, value in ((34+64, -1), (34+64, 38), (34+68, -1), (34+68, 38)):
        bad = bytearray(raw)
        struct.pack_into('<i', bad, offset, value)
        try:
            validate_scene_blob(bytes(bad), 38)
        except AssertionError:
            checks += 1
        else:
            raise AssertionError('An external foreground anchor was accepted')
    for offset, value in ((32, 1), (33, 1), (18, 0), (20, 1)):
        bad = bytearray(raw)
        bad[offset] = value
        try:
            validate_scene_blob(bytes(bad), 38)
        except AssertionError:
            checks += 1
        else:
            raise AssertionError('Decorative gameplay/extra scene cells were accepted')
    overflow = bytearray(raw[:34]+raw[34:106]*256)
    struct.pack_into('<H', overflow, 16, 256)
    try:
        validate_scene_blob(bytes(overflow), 38)
    except AssertionError:
        checks += 1
    else:
        raise AssertionError('Native attachment byte overflow was accepted')
    from tools.arena_surroundings_native import encode_tile
    tile = bytearray(encode_tile('as_de_1_38_p0000.png', 1024, 1024, 32, 0))
    tile[68] = 1
    require(validate_tile_blob(bytes(tile))['static_flag'] == 1, 'Foreground TILE parser failed')
    for offset, value in ((68, 0), (69, 1), (340, 1), (346, 1),
                          (440, 1), (28, 1), (65, 1), (539, 0), (60, 1)):
        bad = bytearray(tile)
        bad[offset] = value
        try:
            validate_tile_blob(bytes(bad))
        except AssertionError:
            checks += 1
        else:
            raise AssertionError('Invalid foreground frame/interaction/visibility data was accepted')
    state = dict(width=8, height=8, blocked=[], actors=[dict(id=1, account='own', x=6, y=2, hp=10)])
    require(boundary_route(state)[3:] == (((7, 2),), (8, 2)), 'Boundary approach fixture failed')
    print(json.dumps(dict(offline_self_test='passed', shared_ground_checks=checks,
                          remote_contacted=False, accounts_created=0)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='185.184.42.88')
    parser.add_argument('--modes', type=int, nargs='+', choices=(0, 1, 4), default=(0, 1, 4))
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--key')
    parser.add_argument('--provision-only', action='store_true')
    parser.add_argument('--no-keep-credentials', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--assets-only', action='store_true', help='Read-only public HTTPS audit; no accounts, game sockets or SSH')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.assets_only:
        result = verify_published_assets(args.host, progress=True)
        destination = ROOT/'reports/arena-surroundings-implementation/hosted-public-assets.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(passed=True, public_scenes_verified=24, proof=str(destination), accounts_created=0)))
    else:
        run(args.host, modes=tuple(args.modes), fixture_path=args.fixture, key=args.key,
            provision_only=args.provision_only, keep_credentials=not args.no_keep_credentials)
