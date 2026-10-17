"""Original skill XML catalogue loader and default skill28 atlas selection.

The full original loader 9d61c0 executes against a descriptor parsed by Python
ElementTree into explicit XML-node/attribute stubs. File/DOM access, Delphi
allocation/string ownership and logging are isolated; the original catalogue
control flow, ID/integer conversion, enum comparisons and record writes run.
The installed client and server assets are never modified. This does not
claim an on-screen button or a complete native XML tokenizer/renderer test.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EFLAGS
from collections import deque
import xml.etree.ElementTree as ET

BASE = BINARY.parent / 'base'
DESCRIPTOR = '''<skills><skill id="28" name="Radio Help">
  <table>1</table>
  <value key="effectText" val="skill_help_desc" />
  <value key="operateType" val="OP_ACTIVE" />
  <value key="target" val="target_self" />
  <value key="apConsume" val="0" />
  <value key="castRange" val="0" />
  <value key="reuseTurns" val="0" />
</skill></skills>'''


def wide(u, address):
    if not address:
        return ''
    result = bytearray()
    for i in range(2048):
        value = bytes(u.mem_read(address + 2 * i, 2))
        if value == b'\0\0':
            return result.decode('utf-16-le')
        result.extend(value)
    raise ValueError('Unterminated original WideString')


def return_pop(u, size=0):
    return_from_stub(u)
    u.reg_write(UC_X86_REG_ESP, u.reg_read(UC_X86_REG_ESP) + size)


def catalogue(xml=DESCRIPTOR):
    root_xml = ET.fromstring(xml)
    assert root_xml.tag == 'skills' and len(root_xml) == 1
    skill = root_xml[0]
    assert skill.tag == 'skill'
    values = {v.attrib['key']: v.attrib['val'] for v in skill.findall('value')}
    table = [int(v) for v in skill.findtext('table').split()]
    assert len(table) == 1
    u = emulator(); cursor = DATA + 0x100; lists = {}; attributes = {}; looked_up = []; isolated = set()

    def allocate(size):
        nonlocal cursor
        result = cursor; cursor += (size + 15) & ~15
        if cursor >= DATA + 0xe000:
            raise ValueError('Bounded native probe allocation exceeded')
        return result

    def string(text):
        if not text:
            return 0
        raw = text.encode('utf-16-le'); base = allocate(len(raw) + 14)
        u.mem_write(base, struct.pack('<HHii', 1200, 2, -1, len(text)) + raw + b'\0\0')
        return base + 12

    def node(tag, text='', children=(), attrs=None, properties=None):
        obj = allocate(0x30); collection = allocate(0x10)
        put32(u, obj + 0x18, string(tag)); put32(u, obj + 0x1c, string(text))
        put32(u, obj + 0x20, collection); put32(u, collection + 8, len(children))
        lists[collection] = tuple(children); attributes[obj] = (attrs or {}, properties or {})
        return obj

    children = [node('table', skill.findtext('table'))]
    children += [node('value', attrs=v.attrib) for v in skill.findall('value')]
    skill_node = node('skill', children=children, attrs=skill.attrib, properties=values)
    root_node = node('skills', children=(skill_node,))
    path_pointer = allocate(4); put32(u, path_pointer, string(str(BASE))); put32(u, 0xac5c80, path_pointer)
    table_pointer = 0
    errors = []; trace = deque(maxlen=32)

    def hook(uc, address, size, user):
        nonlocal table_pointer
        trace.append(hex(address))
        eax = uc.reg_read(UC_X86_REG_EAX); edx = uc.reg_read(UC_X86_REG_EDX)
        ecx = uc.reg_read(UC_X86_REG_ECX); sp = uc.reg_read(UC_X86_REG_ESP)
        if address == 0x40c244:  # concatenated filenames; no file writes
            put32(uc, eax, string('probe/skills.xml')); return_pop(uc)
            uc.reg_write(UC_X86_REG_ESP, uc.reg_read(UC_X86_REG_ESP) + edx * 4)
        elif address == 0x424f2c:  # existence; input is the bounded descriptor
            uc.reg_write(UC_X86_REG_EAX, 1); return_pop(uc)
        elif address == 0x68049c:  # XML-document allocation
            uc.reg_write(UC_X86_REG_EAX, root_node); return_pop(uc, 4)
        elif address == 0x67f7d4:  # XML tokenizer/DOM already supplied above
            return_pop(uc)
        elif address == 0x68266c:
            uc.reg_write(UC_X86_REG_EAX, lists[eax][edx]); return_pop(uc)
        elif address == 0x680a48:
            uc.reg_write(UC_X86_REG_EAX, 1); return_pop(uc)
        elif address in (0x680770, 0x6807d0, 0x680974, 0x680860):
            key = wide(uc, edx); attr, properties = attributes[eax]
            source = attr if address == 0x680770 else properties
            looked_up.append(dict(helper=hex(address), key=key, configured=key in source))
            if address == 0x680770:
                put32(uc, ecx, string(source.get(key, ''))); return_pop(uc)
            elif address == 0x6807d0:
                put32(uc, get32(uc, sp + 4), string(source.get(key, wide(uc, ecx)))); return_pop(uc, 4)
            else:
                value = int(source.get(key, ecx))
                uc.reg_write(UC_X86_REG_EAX, value); return_pop(uc)
        elif address == 0x40d5a4:  # bounded dynamic array allocation
            count = get32(uc, sp + 4); type_info = edx
            unit = 0x348 if type_info == get32(uc, 0x9d4f98) else 4
            old = get32(uc, eax); base = allocate(8 + unit * count); target = base + 8
            put32(uc, base, 1); put32(uc, base + 4, count)
            if old:
                old_count = get32(uc, old - 4)
                uc.mem_write(target, bytes(uc.mem_read(old, unit * min(count, old_count))))
            put32(uc, eax, target)
            if unit == 0x348:
                table_pointer = target
            return_pop(uc)
        elif address == 0x9d565c:  # original whitespace/float table tokenizer isolated
            parent = get32(uc, sp + 4); values_array = allocate(8 + 4 * len(table))
            put32(uc, values_array, 1); put32(uc, values_array + 4, len(table))
            uc.mem_write(values_array + 8, struct.pack('<' + 'i' * len(table), *table))
            put32(uc, parent - 4, values_array + 8); return_pop(uc)
        elif address == 0x40c06c:  # Unicode to ShortString
            raw = wide(uc, edx).encode('cp1251')[:ecx]
            uc.mem_write(eax, bytes((len(raw),)) + raw); return_pop(uc)
        elif address == 0x4237d0:  # lowercase copied string
            put32(uc, edx, string(wide(uc, eax).lower())); return_pop(uc)
        elif address in (0x40b47c, 0x40b4c4):  # assign owned string reference
            put32(uc, eax, edx); return_pop(uc)
        elif address == 0x40c1bc:  # invalid-target diagnostic string
            put32(uc, eax, string(wide(uc, edx) + wide(uc, ecx))); return_pop(uc)
        elif address == 0x40c354:  # WideString compare preserves x86 condition flags
            flags = uc.reg_read(UC_X86_REG_EFLAGS)
            equal = wide(uc, eax) == wide(uc, edx)
            uc.reg_write(UC_X86_REG_EFLAGS, (flags | 0x40) if equal else (flags & ~0x40))
            return_pop(uc)
        elif address in (0x40d6c8, 0x40b0fc, 0x40b12c, 0x40b09c, 0x40b180, 0x4092dc, 0xa88908):
            if address == 0x40d6c8 and eax == 0xad1694:
                put32(uc, eax, 0)
            return_pop(uc)
        elif address in (0x40b88c, 0x40b934, 0x40c028):  # success-log construction
            put32(uc, eax, 0); return_pop(uc)
        elif address == 0x4f2158:
            severity = get32(uc, sp + 4)
            if severity:
                errors.append(severity)
            return_pop(uc, 12)
        else:
            return
        isolated.add(hex(address))

    u.hook_add(UC_HOOK_CODE, hook)
    try:
        u.emu_start(0x9d61c0, STOP, count=50000)
    except Exception as exc:
        raise RuntimeError('Native loader trace ' + ','.join(trace)) from exc
    assert u.reg_read(UC_X86_REG_EIP) == STOP, hex(u.reg_read(UC_X86_REG_EIP))
    assert table_pointer and not errors, errors
    raw = bytes(u.mem_read(table_pointer, 0x348))
    result = dict(loader='0x9d61c0', id=struct.unpack_from('<I', raw, 8)[0],
        name=raw[0xd:0xd + raw[0xc]].decode('cp1251'),
        effect_text=raw[0x10d:0x10d + raw[0x10c]].decode('cp1251'),
        level=raw[0x31e], levels=raw[0x31f], value=struct.unpack_from('<i', raw, 0x320)[0],
        active=raw[0x326], ap=raw[0x327], cooldown=struct.unpack_from('<I', raw, 0x32c)[0],
        range=raw[0x332], target=raw[0x337], hidden=raw[5],
        lookups=looked_up, isolated=sorted(isolated), xml_sha256=hashlib.sha256(xml.encode()).hexdigest())
    return result


def icon_path():
    """Original skill renderer forwards the catalogue ID as atlas tile index."""
    from PIL import Image
    from unicorn.x86_const import UC_X86_REG_EBX
    u = emulator(); frame = STACK + 0x7000; skill = DATA + 0x2000; atlas = DATA + 0x3000
    u.reg_write(UC_X86_REG_EBP, frame); u.reg_write(UC_X86_REG_EBX, skill)
    put32(u, skill + 8, 28); put32(u, 0xac62b4, atlas)
    u.mem_write(atlas, struct.pack('<IHHHH', 1, 0, 0, 32, 32))
    put32(u, frame - 8, 0xffffffff); u.mem_write(frame - 2, struct.pack('<H', 32))
    draws = []
    def hook(uc, address, size, user):
        if address == 0x674f94:
            sp = uc.reg_read(UC_X86_REG_ESP)
            draws.append(dict(renderer='0x674f94', atlas_pointer=get32(uc, sp + 16),
                              tile=get32(uc, sp + 8)))
            return_pop(uc, 20)
    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(0x8ba4a0, 0x8ba4f9, count=1000)
    assert draws == [dict(renderer='0x674f94', atlas_pointer=atlas, tile=28)], draws
    asset = BASE / 'pda/skills.png'; image = Image.open(asset).convert('RGBA')
    assert image.size == (256, 256)
    tile = image.crop((4 * 32, 3 * 32, 5 * 32, 4 * 32))
    assert tile.getextrema()[3][1] > 0
    return dict(path=str(asset), sha256=hashlib.sha256(asset.read_bytes()).hexdigest(),
        dimensions=list(image.size), native_tile_size=[32, 32], tile_index=28,
        crop=[128, 96, 160, 128], visible_pixels=sum(a != 0 for a in tile.getchannel('A').tobytes()),
        draws=draws, loader_atlas_setup='0xa6b6b6..0xa6b6ef', explicit_icon_xml_required=False)


def main():
    accepted = catalogue()
    assert (accepted['id'], accepted['level'], accepted['levels'], accepted['value'], accepted['active'],
            accepted['target'], accepted['ap'], accepted['range'], accepted['cooldown']) == (28, 1, 1, 1, 1, 0, 0, 0, 0)
    assert accepted['effect_text'] == 'skill_help_desc'
    rejected = catalogue(DESCRIPTOR.replace('target_self', 'unknown_target'))
    assert rejected['active'] == 0
    passive = catalogue(DESCRIPTOR.replace('OP_ACTIVE', 'OP_PASSIVE'))
    assert passive['active'] == 0
    installed = ET.parse(BASE / 'shared config/skills.xml').getroot()
    assert not any(int(s.attrib['id']) == 28 for s in installed)
    report = dict(status='PASS', binary_sha256=EXPECTED_SHA, method=__doc__,
        descriptor=DESCRIPTOR, explicit_policy='Radio help is anytime, zero AP/range/reuse; level/value 1 is server metadata policy, not recovered original server data.',
        accepted=accepted, rejected_target=rejected, passive_control=passive, icon=icon_path(),
        installed_catalogue_has_28=False,
        limitations='Native control flow/metadata writes/default icon forwarding verified with XML DOM and RTL stubs; no native XML tokenizer, GUI rendering, hosted request or installed-file change.')
    (ROOT / 'evidence/mine_help_catalog_native.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Original skill loader: skill28 active/self/zero-AP accepted; invalid-target and passive controls PASS; native atlas tile28 PASS')


if __name__ == '__main__': main()
