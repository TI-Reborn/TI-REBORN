"""Bounded client extension after the exact phase2 equipment release.

Adds scoped full-HP use guard, binocular selection via existing33/49, and
F7/v1 authoritative area cell overlays using original renderer callbacks.
patch() only returns a candidate; it does not modify installed/published files.
"""
import hashlib
import struct
import pefile
from .client_equipment_batch import Code

BASE_SHA = 'ccbb3f9eaca7d92ea36e5ca816ce44af9b86c0f501ffc585adcc61f83d6b1458'
BASE_BYTES = 7737344
RVA = 0x817000
BASE_SIZE = 0x1400
SIZE = 0x5200
HP_ENTRY = 0x400000+RVA+0x1400
SELECT_ENTRY = 0x400000+RVA+0x1500
TARGET_ENTRY = 0x400000+RVA+0x1600
READER_ENTRY = 0x400000+RVA+0x1800
DRAW_ENTRY = 0x400000+RVA+0x1a00
SELECTED = RVA+0x1bf0
ACTOR = RVA+0x1bf4
COUNT = RVA+0x1bf8
CELLS = RVA+0x1c00
MAX_CELLS = 4096
STATE = 11
SIGNATURE = b'TIO-battle-items-F7-v1'


def hp_code():
    # Hook the native conditional branch, not its following absolute MOV:
    # the original relocation table must never relocate a new relative JMP.
    c=Code(HP_ENTRY);c.branch('0f85','non_medkit');c.emit('9c60');c.base()
    c.emit('8b442410 8b4018 83f823');c.branch('0f84','allow')
    c.emit('3d8a130000');c.branch('0f82','stock')
    c.emit('3d93130000');c.branch('0f87','stock')
    c.label('allow');c.emit('619d');c.jump(0xa658fe)  # Native AP comparison remains.
    c.label('stock');c.emit('619d');c.jump(0xa658b7)
    c.label('non_medkit');c.jump(0xa65974)
    return c.finish(0x100)


def select_code():
    c=Code(SELECT_ENTRY);c.call(0x66754c);c.emit('9c60');c.base()
    c.emit('8b93');c.word(0xac64a0-0x400000);c.emit('803a00');c.branch('0f84','done')
    c.emit('83bd78fdffff18');c.branch('0f85','done')  # TSItem.template +8 in copied native frame.
    c.emit('807d08ff');c.branch('0f85','done')
    c.emit('8b856cfdffff 8983');c.word(ACTOR)
    c.emit('c683');c.word(SELECTED);c.emit('01')
    c.emit('8b83');c.word(0xac5a30-0x400000);c.emit('c6000b')
    c.emit('b80e000000');c.call(0xa6a610)  # Original EXE cursor14=ti_binocular.ani.
    c.label('done');c.emit('619d c3')
    return c.finish(0x100)


def target_code():
    c=Code(TARGET_ENTRY);c.emit('9c60 83ec08');c.base()
    c.emit('80bb');c.word(SELECTED);c.emit('00');c.branch('0f84','stock')
    c.emit('8b83');c.word(0xac5a30-0x400000);c.emit('80380b');c.branch('0f85','cancel')
    c.emit('8b83');c.word(0xac64a0-0x400000);c.emit('803800');c.branch('0f84','clear')
    c.call(0xa843d4);c.emit('85c0');c.branch('0f88','clear')
    c.emit('8b93');c.word(0xac618c-0x400000);c.emit('8b3482 85f6');c.branch('0f84','clear')
    c.emit('8b4628 3b83');c.word(ACTOR);c.branch('0f85','clear')
    c.emit('89f0');c.call(0xa843ac);c.emit('84c0');c.branch('0f84','clear')
    c.emit('89e0 8d542404');c.call(0x9db7ac);c.emit('84c0');c.branch('0f84','done')
    c.emit('8b0424 85c0');c.branch('0f88','done')
    c.emit('8b93');c.word(0xac561c-0x400000);c.emit('3b02');c.branch('0f83','done')
    c.emit('8b442404 85c0');c.branch('0f88','done')
    c.emit('8b93');c.word(0xac5494-0x400000);c.emit('3b02');c.branch('0f83','done')
    c.emit('8b83');c.word(ACTOR);c.emit('8b1424 8b4c2404');c.call(0x95dfe8)
    c.label('clear');c.emit('8b83');c.word(0xac5a30-0x400000);c.emit('c60000')
    c.emit('31c0');c.call(0xa6a610)
    c.label('cancel');c.emit('c683');c.word(SELECTED);c.emit('00')
    c.branch('e9','stock')
    c.label('done');c.emit('83c408 619d c3')
    c.label('stock');c.emit('83c408 619d');c.call(0x72e668);c.emit('c3')
    return c.finish(0x200)


def reader_code():
    c=Code(READER_ENTRY);c.emit('3cf7');c.branch('0f85','stock')
    c.emit('9c60');c.base();c.emit('c783');c.word(COUNT);c.word(0)
    c.emit('83f904');c.branch('0f82','done')
    c.emit('803a01');c.branch('0f85','done')
    c.emit('0fb77201 81fe00100000');c.branch('0f87','done')
    c.emit('8d0476 83c004 39c8');c.branch('0f85','done')
    c.emit('89f1 8d7a03 85c9');c.branch('0f84','copy')
    c.label('validate');c.emit('803fff');c.branch('0f84','done')
    c.emit('807f01ff');c.branch('0f84','done')
    c.emit('0fb64702 83f801');c.branch('0f82','done')
    c.emit('83f803');c.branch('0f87','done')
    c.emit('83c703 49');c.branch('0f85','validate')
    c.label('copy');c.emit('89b3');c.word(COUNT)
    c.emit('8d83');c.word(CELLS);c.emit('89c7 8d0c76 8d7203 fc f3a4')
    c.label('done');c.emit('c744241c01000000 619d c3')  # New packet consumed; malformed clears overlays.
    c.label('stock');c.call(0x87daa4);c.emit('c3')
    return c.finish(0x200)


def draw_code():
    c=Code(DRAW_ENTRY);c.call(0x814608);c.emit('9c60 83ec08');c.base()
    c.emit('8b83');c.word(0xac64a0-0x400000);c.emit('803800');c.branch('0f84','done')
    # An active binocular choice keeps its established cursor while hovering.
    c.emit('8b83');c.word(0xac5a30-0x400000);c.emit('80380b');c.branch('0f85','cells')
    c.emit('b80e000000');c.call(0xa6a610)
    c.label('cells');c.emit('8db3');c.word(CELLS);c.emit('8bbb');c.word(COUNT)
    c.emit('85ff');c.branch('0f84','done')
    c.label('loop');c.emit('0fb606 c1e005 83c010 890424 0fb64601 c1e005 83c010 89442404')
    c.emit('89e0 8d542404');c.call(0xa896f0)
    c.emit('8b83');c.word(0xac61b0-0x400000);c.emit('8b00 030424 83e808')
    c.emit('8b93');c.word(0xac6068-0x400000);c.emit('8b12 03542404 83ea05')
    c.emit('b969696960 807e0201');c.branch('0f84','color')
    c.emit('b96be3ff50 807e0202');c.branch('0f84','color')
    c.emit('b9ffa85230')
    c.label('color');c.emit('6a0a 51 6a00 b910000000');c.call(0x4f2864)
    c.emit('83c603 4f');c.branch('0f85','loop')
    c.label('done');c.emit('83c408 619d c3')
    return c.finish(0x1c0)


def extension():
    return (hp_code()+select_code()+target_code()+reader_code()+draw_code()+SIGNATURE).ljust(SIZE-BASE_SIZE, b'\0')


def sites():
    def call(address, target): return b'\xe8'+struct.pack('<i',target-address-5)
    return ((0xa658b1,b'\x0f\x85'+struct.pack('<i',0xa65974-0xa658b1-6),b'\xe9'+struct.pack('<i',HP_ENTRY-0xa658b1-5)+b'\x90'),
        (0x99052e,call(0x99052e,0x66754c),call(0x99052e,SELECT_ENTRY)),
        (0x95db15,call(0x95db15,0x72e668),call(0x95db15,TARGET_ENTRY)),
        (0x9f5563,call(0x9f5563,0x87daa4),call(0x9f5563,READER_ENTRY)),
        (0x9f40ae,call(0x9f40ae,0x814608),call(0x9f40ae,DRAW_ENTRY)))


def patch(data):
    try: pe=pefile.PE(data=data)
    except pefile.PEFormatError as error: raise ValueError('Unsupported item client PE') from error
    section=pe.sections[-1]
    if SIGNATURE in data:
        restored=bytearray(data)
        if (section.VirtualAddress!=RVA or section.SizeOfRawData!=SIZE or section.Misc_VirtualSize!=SIZE
            or pe.OPTIONAL_HEADER.SizeOfImage!=RVA+0x6000 or section.PointerToRawData+SIZE!=len(data)
            or data[section.PointerToRawData+BASE_SIZE:]!=extension()): raise ValueError('Unknown item extension section')
        for address,before,after in sites():
            offset=pe.get_offset_from_rva(address-0x400000)
            if data[offset:offset+len(after)]!=after: raise ValueError('Unknown item hook')
            restored[offset:offset+len(before)]=before
        del restored[section.PointerToRawData+BASE_SIZE:]
        for field in (8,16):struct.pack_into('<I',restored,section.get_file_offset()+field,BASE_SIZE)
        struct.pack_into('<I',restored,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x2000)
        if hashlib.sha256(restored).hexdigest()!=BASE_SHA: raise ValueError('Unknown item base release')
        return data
    if len(data)!=BASE_BYTES or hashlib.sha256(data).hexdigest()!=BASE_SHA:
        raise ValueError('Expected exact phase2 equipment client release')
    if section.VirtualAddress!=RVA or section.SizeOfRawData!=BASE_SIZE or section.PointerToRawData+BASE_SIZE!=len(data):
        raise ValueError('Unexpected item extension layout')
    result=bytearray(data)
    relocations={entry.rva for block in getattr(pe,'DIRECTORY_ENTRY_BASERELOC',()) for entry in block.entries if entry.type}
    for address,before,after in sites():
        offset=pe.get_offset_from_rva(address-0x400000)
        if any(address-0x400000<=rva<address-0x400000+len(after) for rva in relocations):
            raise ValueError('Relative item hook overlaps an original relocation')
        if data[offset:offset+len(before)]!=before: raise ValueError('Unknown original item hook')
        result[offset:offset+len(after)]=after
    result.extend(extension())
    for field in (8,16):struct.pack_into('<I',result,section.get_file_offset()+field,SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x6000)
    return bytes(result)


def patch_plan(previous, updated):
    if patch(previous)!=updated: raise ValueError('Item candidate differs from checked patch')
    pe=pefile.PE(data=previous);section=pe.sections[-1]
    changes=[dict(offset=pe.get_offset_from_rva(address-0x400000),before_hex=before.hex(),after_hex=after.hex(),native_va=hex(address))
        for address,before,after in sites()]
    for offset in (section.get_file_offset()+8,section.get_file_offset()+16,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage')):
        changes.append(dict(offset=offset,before_hex=previous[offset:offset+4].hex(),after_hex=updated[offset:offset+4].hex(),reason='PE appended section size'))
    allowed={at for row in changes for at in range(row['offset'],row['offset']+len(bytes.fromhex(row['before_hex'])))}
    if any(a!=b and offset not in allowed for offset,(a,b) in enumerate(zip(previous,updated))):
        raise ValueError('Unexpected edit outside item hooks and PE sizes')
    if updated[len(previous):]!=extension(): raise ValueError('Unexpected appended item code')
    return dict(previous_sha256=hashlib.sha256(previous).hexdigest(),updated_sha256=hashlib.sha256(updated).hexdigest(),
        previous_bytes=len(previous),updated_bytes=len(updated),changes=changes,appended_bytes=len(extension()),
        all_other_published_bytes_preserved=True,namespace='Explicit TIO emulator F7/v1 item visual snapshot; native33/49 for actions')


# Follow-up over the exact published F8 DLL. Keep the original F7 builder and
# its checked release chain intact: this is a separate, reversible candidate.
NVG_BASE_SHA = '7ae830b5e8db3249915a3c10b9f45cf23ecac64984b95d4c02b7da326ad7a43b'
NVG_BASE_BYTES = 7761408
NVG_BASE_SIZE = 0x7200
NVG_SIZE = 0x8200
NVG_READER_ENTRY = 0x400000 + RVA + NVG_BASE_SIZE
NVG_GATE_ENTRY = NVG_READER_ENTRY + 0x200
NVG_COUNT = RVA + NVG_BASE_SIZE + 0x3c0
NVG_ACTORS = RVA + NVG_BASE_SIZE + 0x400
NVG_MAX_ACTORS = 64
NVG_SIGNATURE = b'TIO-NVG-state-F9-v1'
NVG_READER_HOOK = 0x9f5563
NVG_GATE_HOOK = 0xa65906
NVG_PREVIOUS_READER = 0x400000 + RVA + 0x5200
NVG_GATE_ORIGINAL = bytes.fromhex('0fb68004600000')


def nvg_reader_code():
    """F9/v1 is a full owner-only server snapshot, never a toggle command."""
    c=Code(NVG_READER_ENTRY);c.emit('3cf9');c.branch('0f85','stock')
    c.emit('9c60');c.base();c.emit('c783');c.word(NVG_COUNT);c.word(0)
    c.emit('83f904');c.branch('0f82','done')
    c.emit('803a01');c.branch('0f85','done')
    c.emit('0fb77201 83fe40');c.branch('0f87','done')
    c.emit('8d04b504000000 39c8');c.branch('0f85','done')
    # Positive signed32 IDs in strict ascending order prevent duplicates and
    # unbounded/ambiguous cached state. Validate before copying any actor.
    c.emit('31ed 89f1 8d7a03 85c9');c.branch('0f84','copy')
    c.label('validate');c.emit('8b07 85c0');c.branch('0f8e','done')
    c.emit('39e8');c.branch('0f86','done')
    c.emit('89c5 83c704 49');c.branch('0f85','validate')
    c.label('copy');c.emit('89b3');c.word(NVG_COUNT)
    c.emit('8dbb');c.word(NVG_ACTORS);c.emit('89f1 8d7203 fc f3a5')
    c.label('done');c.emit('c744241c01000000 619d c3')
    c.label('stock');c.call(NVG_PREVIOUS_READER);c.emit('c3')
    return c.finish(0x200)


def nvg_gate_code():
    """Bypass AP only for an authoritative active owned NVG at 0..2 AP.

    Native ownership, living/current-turn and item usability gates have already
    run. The native instruction being hooked has EAX=actor. Preserve every
    other register/flag and rejoin the existing item durability/action path.
    """
    c=Code(NVG_GATE_ENTRY);c.emit('9c60');c.base()
    c.emit('8b93');c.word(0xac64a0-0x400000);c.emit('803a00');c.branch('0f84','stock')
    c.emit('8b442410 8178188a130000');c.branch('0f85','stock')
    c.emit('8b44241c 80b80460000003');c.branch('0f83','stock')
    c.emit('8b5028 8b8b');c.word(NVG_COUNT);c.emit('8dbb');c.word(NVG_ACTORS)
    c.emit('85c9');c.branch('0f84','stock')
    c.label('find');c.emit('3917');c.branch('0f84','allow')
    c.emit('83c704 49');c.branch('0f85','find');c.branch('e9','stock')
    # Conservatively consume this shortcut before native33. A rapid second
    # click cannot attempt free activation while the off reply is in flight.
    # Only the next complete authoritative F9 snapshot can restore eligibility.
    c.label('allow');c.emit('c70700000000 619d');c.jump(0xa65949)
    c.label('stock');c.emit('619d');c.emit(NVG_GATE_ORIGINAL.hex());c.jump(NVG_GATE_HOOK+7)
    return c.finish(0x180)


def nvg_extension():
    return (nvg_reader_code()+nvg_gate_code()+NVG_SIGNATURE).ljust(NVG_SIZE-NVG_BASE_SIZE,b'\0')


def nvg_sites():
    def call(target):return b'\xe8'+struct.pack('<i',target-NVG_READER_HOOK-5)
    return ((NVG_READER_HOOK,call(NVG_PREVIOUS_READER),call(NVG_READER_ENTRY)),
            (NVG_GATE_HOOK,NVG_GATE_ORIGINAL,b'\xe9'+struct.pack('<i',NVG_GATE_ENTRY-NVG_GATE_HOOK-5)+b'\x90\x90'))


def patch_nvg(data):
    """Return an NVG candidate; never install/publish or change server state."""
    try:pe=pefile.PE(data=data)
    except pefile.PEFormatError as error:raise ValueError('Unsupported NVG client PE') from error
    section=pe.sections[-1]
    if NVG_SIGNATURE in data:
        if (section.VirtualAddress!=RVA or section.SizeOfRawData!=NVG_SIZE or section.Misc_VirtualSize!=NVG_SIZE
            or pe.OPTIONAL_HEADER.SizeOfImage!=RVA+0x9000 or section.PointerToRawData+NVG_SIZE!=len(data)
            or data[section.PointerToRawData+NVG_BASE_SIZE:]!=nvg_extension()):
            raise ValueError('Unknown NVG extension section')
        restored=bytearray(data[:section.PointerToRawData+NVG_BASE_SIZE])
        for address,before,after in nvg_sites():
            offset=pe.get_offset_from_rva(address-0x400000)
            if data[offset:offset+len(after)]!=after:raise ValueError('Unknown NVG hook')
            restored[offset:offset+len(before)]=before
        for field in (8,16):struct.pack_into('<I',restored,section.get_file_offset()+field,NVG_BASE_SIZE)
        struct.pack_into('<I',restored,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x8000)
        if len(restored)!=NVG_BASE_BYTES or hashlib.sha256(restored).hexdigest()!=NVG_BASE_SHA:
            raise ValueError('Unknown NVG base release')
        return data
    if len(data)!=NVG_BASE_BYTES or hashlib.sha256(data).hexdigest()!=NVG_BASE_SHA:
        raise ValueError('Expected exact published F8 client release')
    if (section.VirtualAddress!=RVA or section.SizeOfRawData!=NVG_BASE_SIZE or section.Misc_VirtualSize!=NVG_BASE_SIZE
        or section.PointerToRawData+NVG_BASE_SIZE!=len(data) or pe.OPTIONAL_HEADER.SizeOfImage!=RVA+0x8000):
        raise ValueError('Unexpected NVG extension layout')
    result=bytearray(data)
    relocations={e.rva for b in getattr(pe,'DIRECTORY_ENTRY_BASERELOC',()) for e in b.entries if e.type}
    for address,before,after in nvg_sites():
        offset=pe.get_offset_from_rva(address-0x400000)
        if any(address-0x400000<=rva<address-0x400000+len(after) for rva in relocations):
            raise ValueError('NVG relative hook overlaps an original relocation')
        if data[offset:offset+len(before)]!=before:raise ValueError('Unknown original NVG hook')
        result[offset:offset+len(after)]=after
    result.extend(nvg_extension())
    for field in (8,16):struct.pack_into('<I',result,section.get_file_offset()+field,NVG_SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x9000)
    return bytes(result)


def nvg_patch_plan(previous,updated):
    if patch_nvg(previous)!=updated:raise ValueError('NVG candidate differs from checked patch')
    pe=pefile.PE(data=previous);section=pe.sections[-1]
    changes=[dict(offset=pe.get_offset_from_rva(address-0x400000),before_hex=before.hex(),after_hex=after.hex(),native_va=hex(address))
             for address,before,after in nvg_sites()]
    for offset in (section.get_file_offset()+8,section.get_file_offset()+16,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage')):
        changes.append(dict(offset=offset,before_hex=previous[offset:offset+4].hex(),after_hex=updated[offset:offset+4].hex(),reason='PE appended section size'))
    allowed={at for row in changes for at in range(row['offset'],row['offset']+len(bytes.fromhex(row['before_hex'])))}
    if any(a!=b and at not in allowed for at,(a,b) in enumerate(zip(previous,updated))):
        raise ValueError('Unexpected NVG edit outside receiver/AP hooks and PE sizes')
    if updated[len(previous):]!=nvg_extension():raise ValueError('Unexpected NVG appended code')
    return dict(previous_sha256=hashlib.sha256(previous).hexdigest(),updated_sha256=hashlib.sha256(updated).hexdigest(),
                previous_bytes=len(previous),updated_bytes=len(updated),changes=changes,appended_bytes=len(nvg_extension()),
                all_other_published_bytes_preserved=True,existing_f6_f7_f8_code_preserved=True,
                namespace='Explicit emulator F9/v1 authoritative owner-only NVG snapshot; original native33 action',
                free_off_ap=(0,1,2),activation_original_ap_gate_preserved=True,unknown_state_original_ap_gate_preserved=True,
                shortcut_consumed_before_free_off=True)
