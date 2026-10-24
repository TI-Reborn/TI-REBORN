"""Read-only original-client animation research; no GPU or game-client claim.

The original x86 animation matcher executes against records transcribed from
the unmodified animation.xml. The original attack-animation callback executes
against a typed 4B object and a minimal metadata table. Only item lookup,
actor lookup, managed string conversion/cleanup, and angle calculation are
isolated. Control cases stop at the real projectile constructor boundary.
"""
import hashlib
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_auth_native import (BINARY, EXPECTED_SHA, DATA, STACK, STOP,
    emulator, put32, get32)
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESP)
from dog_native_animation import animation

OUT = ROOT / 'reports/flamethrower-animation-20261021'
BASE = BINARY.parent / 'base'
CLASS = {'Any': 1, 'Melee': 2, 'Light': 3, 'Auto': 4, 'Dist': 5,
         'Heavy': 6, 'Throw': 7, 'Skill': 8}


def match_animation(race, weapon):
    """Execute original attack row priority matcher 8b327c, without stubs."""
    xml = ET.parse(BASE / 'animation.xml').getroot()
    rows = list(xml.find(race).find('Attack'))
    u = emulator()
    closure, manager, races, actions, records = (
        DATA + 0x100, DATA + 0x200, DATA + 0x300, DATA + 0x400, DATA + 0x1000)
    put32(u, closure - 8, manager)
    put32(u, closure - 0xc, 0)
    u.mem_write(closure - 0xd, b'\x02')
    u.mem_write(closure - 0x10, struct.pack('<H', 1))  # wildcard enemy weapon class
    put32(u, closure - 0x14, 0xffffffff)  # no specific enemy race
    u.mem_write(closure - 0x16, b'\0\0')
    put32(u, manager + 0x10, races)
    put32(u, races, actions)
    put32(u, actions + 2 * 4, records)
    put32(u, records - 4, len(rows))
    for index, row in enumerate(rows):
        at = records + index * 0x11c
        key = row.get('WeaponType', 'Any')
        parsed = re.fullmatch(r'([A-Za-z]+)(\d*)', key)
        u.mem_write(at, bytes((CLASS[parsed[1]],)))
        u.mem_write(at + 2, struct.pack('<H', int(parsed[2] or 0)))
        # All Heavy matching candidates use default enemy/state qualifiers.
        # Exclude nonmatching EnemyType-specific melee rows faithfully.
        enemy = row.get('EnemyType')
        put32(u, at + 0x104, 0xfffffffe if enemy else 0xffffffff)
        u.mem_write(at + 0x108, b'\x01')
        u.mem_write(at + 0x10c, bytes((1 if row.get('State') == 'Sit' else 0,)))
    sp = STACK + 0x8000
    put32(u, sp + 4, closure)
    u.reg_write(UC_X86_REG_EAX, CLASS['Heavy'])
    u.reg_write(UC_X86_REG_EDX, weapon)
    u.emu_start(0x8b327c, STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    selected = get32(u, closure - 4)
    assert selected < len(rows)
    result = dict(race=race, weapon=weapon, selected_index=selected,
                  attributes=dict(rows[selected].attrib), native_matcher='0x8b327c',
                  instruction_stubs=[])
    if weapon == 324:
        assert result['attributes']['Name'] == 'human_heavy_fire_'
        assert result['attributes']['WeaponType'] == 'Heavy'
    else:
        assert result['attributes']['Name'] == 'human_shotgun_fire_'
    return result


def attack_callback(weapon, attack_type):
    u = emulator()
    obj, table, actor, owners = DATA, DATA + 0x1000, DATA + 0x6000, DATA + 0xe000
    metadata = table + 0x3a78  # one metadata record is 0x74f * 8 bytes
    put32(u, 0xac637c, DATA + 0xf000)
    put32(u, DATA + 0xf000, table)
    u.mem_write(metadata + 0x12c, bytes((attack_type,)))
    put32(u, 0xac618c, owners)
    put32(u, owners, actor)
    put32(u, actor + 0x28, 17)
    put32(u, actor + 0xdf8, weapon)
    put32(u, obj, 17)
    u.mem_write(obj + 4, b'\x01')
    for off, (x, y) in ((8, (2, 2)), (0x1c, (6, 2)), (0x3c, (6, 2))):
        put32(u, obj + off, x)
        put32(u, obj + off + 8, y)
        for flag in (4, 12, 16):
            u.mem_write(obj + off + flag, b'\x01')
    u.mem_write(obj + 0x2e, struct.pack('<H', weapon))
    u.mem_write(obj + 0x30, b'\x01')
    put32(u, obj + 0x34, 0)
    u.mem_write(obj + 0x38, b'\x01')
    events = []
    stubs = []
    branches = []

    def ret(result=None, extra=0):
        sp = u.reg_read(UC_X86_REG_ESP)
        target = get32(u, sp)
        u.reg_write(UC_X86_REG_ESP, sp + 4 + extra)
        u.reg_write(UC_X86_REG_EIP, target)
        if result is not None:
            u.reg_write(UC_X86_REG_EAX, result)

    def hook(uc, address, size, _):
        if address in (0x95fa40, 0x95fd64, 0x95fdd8, 0x95fddf, 0x9600b9):
            branches.append(hex(address))
        if address == 0xa78afc:
            assert uc.reg_read(UC_X86_REG_EAX) == weapon
            stubs.append('item metadata index lookup')
            ret(1)
        elif address == 0xa93f70:
            assert uc.reg_read(UC_X86_REG_EAX) == 17
            stubs.append('actor ID lookup')
            ret(0)
        elif address == 0xa8907c:
            stubs.append('angle calculation')
            ret(90, 16)
        elif address == 0x40c0d8:
            stubs.append('managed string conversion (empty source)')
            put32(u, uc.reg_read(UC_X86_REG_EAX), 0)
            ret()
        elif address in (0x40c9f4, 0x40b0fc):
            stubs.append('managed cleanup')
            ret()
        elif address == 0x949084:
            events.append('native projectile/effect constructor 0x949084')
            uc.emu_stop()
        elif address == 0x68a890:
            stubs.append('positional sound output (empty fixture sound)')
            ret()

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x95f960, STOP, count=30000)
    completed = u.reg_read(UC_X86_REG_EIP) == STOP
    if attack_type == 2:
        assert completed and not events
        assert '0x95fddf' in branches and '0x9600b9' in branches
    else:
        assert events == ['native projectile/effect constructor 0x949084'], (weapon, events, hex(u.reg_read(UC_X86_REG_EIP)), stubs, branches)
    return dict(weapon=weapon, attack_type=attack_type, completed=completed,
                boundary_events=events, branches=branches,
                isolated_functions=sorted(set(stubs)),
                entry='0x95f960', projectile_predicate='0xa75e54')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    assert hashlib.sha256(BINARY.read_bytes()).hexdigest() == EXPECTED_SHA
    archived = ROOT / 'reports/client-version-research/archive-20231004/base/animation.xml'
    assert archived.read_bytes() == (BASE / 'animation.xml').read_bytes()
    clips = []
    for name in ('human_heavy_fire', 'human_heavy_fire_01',
                 'human_heavy_fire_02', 'human_heavy_fire_03'):
        p = BASE / 'models/anim' / (name + '.adjx')
        clip = animation(p)
        clips.append(dict(name=name, frames=clip['frames'], fps=clip['fps'],
                          duration_seconds=clip['frames'] / clip['fps'],
                          bones=len(clip['names']), sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    report = dict(original_binary=str(BINARY), binary_sha256=EXPECTED_SHA,
        animation_xml_sha256=hashlib.sha256((BASE / 'animation.xml').read_bytes()).hexdigest(),
        animation_xml_matches_archived_20231004=True,
        native_row_selection=[match_animation(r, w) for r in ('Man', 'Woman') for w in (324, 302)],
        native_attack_callback=[attack_callback(w, t) for w, t in ((324, 2), (302, 2), (316, 3), (317, 4))],
        clip_resources=clips,
        graphical_clients_used=False, hosted_state_modified=False,
        limitations=['Original x86 branch/row selection and existing clip structure verified.',
                    'No GPU rendering, audible output, full metadata XML parsing, or live game-client verification.'])
    (OUT / 'native-animation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
