"""Guarded native Screen Apply extension; no process or publication side effects.

Runs on the native UI thread after all five original cvar commands, retaining
the existing Direct3D lost/reset resource lifecycle and Silver resize callback.
The supported TI host is the unchanged SHA-pinned launcher executable.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import pefile
from .client_equipment_batch import Code

IMAGE_BASE = 0x400000
SECTION_RVA = 0x823000
ENTRY = IMAGE_BASE + SECTION_RVA
SNAPSHOT_ENTRY = ENTRY
APPLY_ENTRY = ENTRY + 0x180
STATE = SECTION_RVA + 0xc00
STRINGS = SECTION_RVA + 0xd00
SIZE = 0x2000
CHAT_ENTRY = ENTRY+0x1000
HUD_ENTRY = ENTRY+0x1300
SIGNATURE = b'TIO-native-screen-apply-v1'
SIGNATURE_RVA = SECTION_RVA+0xf00
TITLE = SECTION_RVA + 0xf40
ERROR = SECTION_RVA + 0xf60
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
CVARS = ('r_monitor', 'r_fullscreen', 'r_width', 'r_height', 'r_vsync')
OLD_OFFSETS = (0,4,8,12,0x28)
NEW_OFFSETS = (0x10,0x14,0x18,0x1c,0x2c)
VSYNC_NAME = SECTION_RVA+0xf20
VSYNC_PREFIX = STATE+0x40
TARGETS = ((0x76dfd4,0x70),(0x76e40c,0x80))


def host_call(c, address):
    # TI is a fixed-base executable. Silver itself is relocated/PIC.
    c.emit('bf'); c.word(address); c.emit('ffd7')


def cvar_read(c, index):
    c.emit('8d83'); c.word((STRINGS + index*0x40 if index<4 else VSYNC_NAME) + 12)
    c.call(0x688328)


def state_get(c, register, offset):
    c.emit({'eax':'8b83','edx':'8b93','ecx':'8b8b'}[register]); c.word(STATE+offset)


def state_put(c, offset):
    c.emit('8983'); c.word(STATE+offset)


def snapshot_code():
    c = Code(SNAPSHOT_ENTRY); c.emit('9c60'); c.base()
    for index in range(5):
        cvar_read(c,index); state_put(c,OLD_OFFSETS[index])
    c.emit('619d 8d55e0 8b45f8'); c.jump(0x88384a)
    return c.finish(0x180)


def restore_cvars(c):
    # The outer Apply has its own SEH/string cleanup. Use independent local
    # managed strings, releasing each exactly like the original native setter.
    c.emit('83ec08 31c0 890424 89442404')
    for index in range(5):
        state_get(c,'eax',OLD_OFFSETS[index]); c.emit('8d1424'); c.call(0x4244b4)
        c.emit('8b0c24 8d442404 8d93')
        c.word((STRINGS+0x100+index*0x40 if index<4 else VSYNC_PREFIX)+12)
        c.call(0x40c1bc)
        c.emit('8b442404'); c.call(0x6882a4)
        c.emit('8d0424'); c.call(0x40b09c)
        c.emit('8d442404'); c.call(0x40b09c)
    c.emit('83c408')


def snapshot_targets(c):
    # City composition and optional bloom use persistent screen-sized targets.
    # Their logical sizes survive OnLostDevice, and OnResetDevice rebuilds them.
    for absolute, offset in TARGETS:
        c.emit('a1'); c.word(absolute)
        c.emit('85c0'); c.branch('0f84','target_absent_'+str(offset))
        c.emit('8b00')
        c.label('target_absent_'+str(offset)); state_put(c,offset)
        c.emit('85c0'); c.branch('0f84','target_saved_'+str(offset))
        c.emit('89c2 8b4220'); state_put(c,offset+4)
        c.emit('8b421c'); state_put(c,offset+8)
        c.emit('0fb64260'); state_put(c,offset+12)
        c.label('target_saved_'+str(offset))
    c.emit('8b93'); c.word(STATE+0x24)
    for native, saved in ((0x2dc,0x98),(0x2e0,0x9c)):
        c.emit('8b82'); c.word(native); state_put(c,saved)


def size_targets(c, restore):
    if not restore:
        # Match the original square power-of-two composition target, using
        # actual client dimensions (LCD fullscreen can differ from r_width).
        c.emit('a170727800 3b0574727800')
        c.branch('0f8d','actual_max'); c.emit('a174727800')
        c.label('actual_max'); c.emit('ba00020000')
        c.label('target_power'); c.emit('39c2')
        c.branch('0f8d','target_power_done'); c.emit('d1e2')
        c.branch('e9','target_power')
        c.label('target_power_done'); c.emit('8993'); c.word(STATE+0x90)
    for _, offset in TARGETS:
        c.emit('8bb3'); c.word(STATE+offset)
        c.emit('85f6'); c.branch('0f84','target_sized_'+str(restore)+str(offset))
        c.emit('83bb'); c.word(STATE+offset+12); c.emit('00')
        c.branch('0f84','target_sized_'+str(restore)+str(offset))
        state_get(c,'eax',offset+4 if restore else 0x90); c.emit('894620')
        state_get(c,'eax',offset+8 if restore else 0x90); c.emit('89461c c6466001')
        c.label('target_sized_'+str(restore)+str(offset))
    # The shared depth surface must cover the square composition texture too.
    for native, saved in ((0x2dc,0x98),(0x2e0,0x9c)):
        c.emit('8bb3'); c.word(STATE+0x24)
        state_get(c,'eax',saved if restore else 0x90)
        if not restore:
            c.emit('3b86'); c.word(native)
            c.branch('0f8e','depth_sized_'+str(native))
        c.emit('8986'); c.word(native)
        if not restore:c.label('depth_sized_'+str(native))


def check_targets(c, restore=False):
    # Resource recreation has its own allocation failures after device Reset.
    # Treat these as a failed Apply and run the complete old-mode lifecycle.
    failed = 'rollback_failed' if restore else 'resource_failed'
    c.emit('8b83'); c.word(STATE+0x24)
    c.emit('83b8c001000000'); c.branch('0f84',failed)
    for _, offset in TARGETS:
        c.emit('8bb3'); c.word(STATE+offset)
        label = 'target_checked_'+str(restore)+str(offset)
        c.emit('85f6'); c.branch('0f84',label)
        c.emit('83bb'); c.word(STATE+offset+12); c.emit('00')
        c.branch('0f84',label)
        c.emit('807e6001'); c.branch('0f85',failed)
        c.emit('837e0c00'); c.branch('0f84',failed)
        for dimension, saved in ((0x14,offset+4),(0x18,offset+8)):
            state_get(c,'eax',saved if restore else 0x90)
            c.emit('3946'+format(dimension,'02x')); c.branch('0f8c',failed)
        c.label(label)


def resize_host(c, restore=False):
    values = 0 if restore else 0x10
    # The exact startup properties are ClientWidth/ClientHeight, not the
    # decorated outer window dimensions. Restoring the border is required when
    # leaving the original desktop/fullscreen borderless modes.
    c.emit('8b83'); c.word(STATE+0x20); c.emit('b202'); host_call(c,0x5b1250)
    for index, offset in ((1,0x3d0),(0,0x3d1)):
        state_get(c,'eax',values+index*4)
        c.emit('8b93'); c.word(STATE+0x20); c.emit('8882'); c.word(offset)
    for index, address in ((2,0x5b0208),(3,0x5b0234)):
        state_get(c,'edx',values+index*4)
        c.emit('8b83'); c.word(STATE+0x20); host_call(c,address)
    c.emit('8b83'); c.word(STATE+0x20); host_call(c,0x746470)
    # SetFullscreen would reset a second time. Assign its exact field first,
    # then perform one ResizeBackBuffer covering size and presentation mode.
    c.emit('31d2')
    state_get(c,'eax',values+4); c.emit('83f801'); c.branch('0f85','windowed_'+str(restore))
    state_get(c,'eax',values); c.emit('85c0'); c.branch('0f85','windowed_'+str(restore))
    c.emit('b201')
    c.label('windowed_'+str(restore))
    c.emit('8b83'); c.word(STATE+0x24); c.emit('8890d7020000')
    # A VCL border-style change can recreate HWND. Refresh the device window
    # property through the same native Handle getter used at startup.
    c.emit('8b83'); c.word(STATE+0x20); host_call(c,0x5eb048)
    c.emit('8b93'); c.word(STATE+0x24); c.emit('8982fc010000')
    state_get(c,'eax',0x28 if restore else 0x2c)
    c.emit('8b93');c.word(STATE+0x24);c.emit('8882d3020000')
    # ResizeBackBuffer discards Reset's HRESULT. Its two setters update the
    # maximum depth dimensions too; the native Reset recreates that surface.
    for dimension, address in ((0x787270,0x64b290),(0x787274,0x64b2d4)):
        c.emit('8b15'); c.word(dimension)
        c.emit('8b83'); c.word(STATE+0x24); host_call(c,address)
    size_targets(c,restore)
    c.emit('8b83'); c.word(STATE+0x24); host_call(c,0x64ade8)


def failure_dialog(c):
    c.emit('8d83'); c.word(ERROR+12)
    c.emit('8d93'); c.word(TITLE+12)
    c.call(0x6d4190)
    c.emit('31c0'); c.call(0x6d4090)


def resize_ui(c):
    # TI721a24 deliberately suppresses callbacks during a Silver input event.
    # We are already inside Silver and must call its own stdcall resize entry;
    # it updates the root controls and the city/battle viewport rectangle.
    c.emit('ff3574727800 ff3570727800'); c.call(0x9f47f8)
    # Native chat refresh retains messages, tabs and the user's chat height.
    # It moves the chat to the new bottom edge and resizes its existing children.
    c.call(0xa029dc)
    c.call(CHAT_ENTRY)
    c.call(HUD_ENTRY)


def chat_code():
    # Current chat has native tabbed pages below the legacy window. Refresh
    # these existing controls through their own resize routine, without
    # recreating tabs or messages, dispatching scripts, or changing selection.
    c=Code(CHAT_ENTRY); c.emit('60'); c.base()
    c.emit('8b83'); c.word(0x6c622c)
    c.emit('85c0'); c.branch('0f84','done'); c.emit('8b00 85c0')
    c.branch('0f84','done')
    c.emit('8d93'); c.word(0x602a80); c.call(0xa3fca8)
    c.emit('83f8ff'); c.branch('0f84','done')
    c.emit('89c2 8b83'); c.word(0x6c622c); c.emit('8b00'); c.call(0xa3f2a0)
    c.emit('89c7')
    # Height150 is the native folded low-resolution chat mode. The original
    # root refresh skips its Y coordinate; retain its intentional37px fold
    # below the bottom edge while moving it to the new screen height.
    c.emit('817f3c96000000'); c.branch('0f85','chat_positioned')
    c.emit('8b83'); c.word(0x6c5e60); c.emit('8b00 2d96000000 83c025 894734')
    c.label('chat_positioned'); c.emit('31f6')
    c.label('root_next'); c.emit('89f8'); c.call(0xa424d4)
    c.emit('39f0'); c.branch('0f8e','done')
    c.emit('89f8 89f2'); c.call(0xa424c4)
    c.emit('8d93'); c.word(0x62c208); c.emit('3910')
    c.branch('0f84','render_area')
    c.emit('8d93'); c.word(0x634c48); c.emit('3910')
    c.branch('0f85','root_advance')
    c.emit('8b5738 895038 8b573c 89503c 56 57 89c7 31f6')
    c.label('page_next'); c.emit('89f8'); c.call(0xa424d4)
    c.emit('39f0'); c.branch('0f8e','page_done')
    c.emit('89f8 89f2'); c.call(0xa424c4)
    c.emit('8d93'); c.word(0x633fa0); c.emit('3910')
    c.branch('0f85','page_advance')
    c.emit('8b5738 895038 8b573c 89503c'); c.call(0xa4f608)
    c.label('page_advance'); c.emit('46'); c.branch('e9','page_next')
    c.label('page_done'); c.emit('5f 5e'); c.branch('e9','root_advance')
    c.label('render_area')
    # Retain intentionally empty overlay render areas at zero dimensions.
    for offset in (0x38,0x3c):
        c.emit('8378'+format(offset,'02x')+'00'); c.branch('0f8e','root_advance')
    c.emit('8b5738 895038 8b573c 89503c')
    c.label('root_advance'); c.emit('46'); c.branch('e9','root_next')
    c.label('done'); c.emit('61 c3')
    return c.finish(0x300)


def hud_code():
    # Re-anchor existing fixed HUD windows using their exact native placement
    # formulas. Preserve visibility, child controls and current game state.
    c=Code(HUD_ENTRY); c.emit('60'); c.base()
    c.emit('8b83'); c.word(0x6c622c)
    c.emit('85c0'); c.branch('0f84','done'); c.emit('8b38 85ff')
    c.branch('0f84','done')
    for name, label in ((0x3dad98,'jackpot'),(0x45cc10,'pda'),(0x5c27a0,'topmenu')):
        c.emit('89f8 8d93'); c.word(name); c.call(0xa3fca8)
        c.emit('83f8ff'); c.branch('0f84',label+'_done')
        c.emit('89c2 89f8'); c.call(0xa3f2a0); c.emit('89c6')
        c.emit('8b83'); c.word(0x6c56e0); c.emit('8b00 8b5638')
        if label=='jackpot':c.emit('83e869 d1fa')
        if label=='topmenu':
            # Native constructor centers its requested300px extent before
            # the skinned window rounds its actual width to frame tiles.
            c.emit('2d2c010000 d1f8')
        else:c.emit('29d0')
        c.emit('894630')
        if label=='jackpot':
            c.emit('8b83'); c.word(0x6c5e60)
            c.emit('8b00 2d3b010000 8b563c d1fa 29d0 894634')
        c.label(label+'_done')
    # HUD2 draws and hit-tests these nine existing battle-slot rectangles.
    # Only coordinates change; item/selection/callback state stays intact.
    for index in range(9):
        for saved, global_rva, adjustment in (
                (4,0x6c56e0,(86,139,192)[index%3]-256),
                (8,0x6c5e60,(206,153,100)[index//3]-256)):
            c.emit('8b83'); c.word(global_rva); c.emit('8b00 05'); c.word(adjustment)
            c.emit('8983'); c.word(0x6d11e0+index*0x48+saved)
    c.label('done'); c.emit('61 c3')
    return c.finish(0xd00)


def apply_code():
    c = Code(APPLY_ENTRY)
    c.call(0x6882a4)  # displaced final r_height command
    c.emit('9c60'); c.base()
    # Guard the fixed-base host entry and initialized form/renderer references.
    c.emit('813d70647400558bec83'); c.branch('0f85','unavailable')
    for absolute, offset in ((0x76e568,0x20),(0x76de0c,0x24)):
        c.emit('a1'); c.word(absolute); c.emit('85c0'); c.branch('0f84','unavailable')
        c.emit('8b00 85c0'); c.branch('0f84','unavailable'); state_put(c,offset)
    for index in range(5):
        cvar_read(c,index); state_put(c,NEW_OFFSETS[index])
    # Reject implausible values before any window/device operation.
    for offset, lower, upper in ((0x10,0,3),(0x14,0,2),(0x18,800,7680),(0x1c,600,4320),(0x2c,0,1)):
        state_get(c,'eax',offset); c.emit('3d');c.word(lower);c.branch('0f8c','unavailable')
        c.emit('3d');c.word(upper);c.branch('0f8f','unavailable')
    for index in range(5):
        state_get(c,'eax',OLD_OFFSETS[index])
        c.emit('3b83'); c.word(STATE+NEW_OFFSETS[index])
        c.branch('0f85','changed')
    c.branch('e9','accepted')
    c.label('changed')
    snapshot_targets(c)
    resize_host(c)
    state_put(c,0x34); c.emit('85c0'); c.branch('0f88','failed')
    check_targets(c)
    resize_ui(c)
    c.label('accepted')
    c.emit('c783');c.word(STATE+0x30);c.word(1)
    c.emit('619d');c.jump(0x883930)
    c.label('failed')
    # Default-pool resources have already received OnLostDevice. A rollback
    # must not notify their destruction again before a successful restore.
    c.emit('8b83');c.word(STATE+0x24);c.emit('c680a902000001')
    c.branch('e9','restore_mode')
    # Reset succeeded and resources received OnResetDevice. Notify OnLostDevice
    # again on rollback so its newly allocated default-pool resources release.
    c.label('resource_failed')
    c.emit('8b83');c.word(STATE+0x24);c.emit('c680a902000000')
    c.label('restore_mode'); restore_cvars(c)
    resize_host(c,True); state_put(c,0x38)
    c.emit('85c0');c.branch('0f88','rollback_failed')
    check_targets(c,True)
    resize_ui(c)
    c.emit('c783');c.word(STATE+0x30);c.word(2)
    c.branch('e9','error_dialog')
    c.label('rollback_failed')
    c.emit('c783');c.word(STATE+0x30);c.word(4)
    c.branch('e9','error_dialog')
    c.label('unavailable');restore_cvars(c)
    c.emit('c783');c.word(STATE+0x30);c.word(3)
    c.label('error_dialog');failure_dialog(c)
    c.emit('619d');c.jump(0x883930)
    return c.finish(0xa80)


def extension():
    result=bytearray(snapshot_code()+apply_code())
    assert len(result)==0xc00
    result.extend(b'\0'*0x100)
    prefix='r_vsync '
    raw=struct.pack('<HHiI',1200,2,-1,len(prefix))+prefix.encode('utf-16le')+b'\0\0'
    result[0xc40:0xc40+len(raw)]=raw
    for value in CVARS[:4] + tuple(name+' ' for name in CVARS[:4]):
        raw=struct.pack('<HHiI',1200,2,-1,len(value))+value.encode('utf-16le')+b'\0\0'
        assert len(raw)<=0x40
        result.extend(raw.ljust(0x40,b'\0'))
    result.extend(SIGNATURE)
    result.extend(bytes(VSYNC_NAME-SECTION_RVA-len(result)))
    value='r_vsync'
    raw=struct.pack('<HHiI',1200,2,-1,len(value))+value.encode('utf-16le')+b'\0\0'
    result.extend(raw.ljust(0x20,b'\0'))
    result.extend(bytes(TITLE-SECTION_RVA-len(result)))
    for value, limit in (('Экран',0x20),('Не удалось изменить экран. Сохранены прежние настройки.',0xa0)):
        raw=struct.pack('<HHiI',1200,2,-1,len(value))+value.encode('utf-16le')+b'\0\0'
        assert len(raw)<=limit
        result.extend(raw.ljust(limit,b'\0'))
    assert len(result)==0x1000
    result.extend(chat_code())
    result.extend(hud_code())
    assert len(result)==SIZE
    return bytes(result)


def sites():
    return (
        (0x883816,bytes.fromhex('8d55ecb8b03a8800'), b'\xe9'+struct.pack('<i',0x883844-0x883816-5)+b'\x90'*3),
        (0x883844,bytes.fromhex('8d55e08b45f8'),b'\xe9'+struct.pack('<i',SNAPSHOT_ENTRY-0x883844-5)+b'\x90'),
        (0x883924,bytes.fromhex('e87b49e0ffeb05'),b'\xe9'+struct.pack('<i',APPLY_ENTRY-0x883924-5)+b'\x90'*2),
    )


def patch(data, *, expected_sha):
    if hashlib.sha256(data).hexdigest()!=expected_sha:
        raise ValueError('Screen Apply requires the exact reviewed resolution-UI candidate')
    pe=pefile.PE(data=data)
    if pe.FILE_HEADER.Machine!=0x14c or pe.OPTIONAL_HEADER.ImageBase!=IMAGE_BASE:
        raise ValueError('Unknown Silver PE')
    if pe.OPTIONAL_HEADER.SizeOfImage!=SECTION_RVA:
        raise ValueError('Unexpected UI extension layout')
    header=pe.sections[-1].get_file_offset()+40
    if header+40>pe.sections[0].PointerToRawData or any(data[header:header+40]):
        raise ValueError('No unused PE section header for Screen Apply')
    if len(data)%0x200:
        raise ValueError('Unknown Silver file alignment')
    result=bytearray(data)
    for address,before,after in sites():
        offset=pe.get_offset_from_rva(address-IMAGE_BASE)
        if data[offset:offset+len(before)]!=before:raise ValueError('Screen Apply hook changed')
        result[offset:offset+len(after)]=after
    # The removed message contains a relocated absolute string operand. Mark
    # only that existing entry ABSOLUTE; otherwise ASLR corrupts the new jump.
    overlapping=[entry for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
                 if entry.type==3 and 0x483816<=entry.rva<0x48381e]
    if len(overlapping)!=1 or overlapping[0].rva!=0x48381a:
        raise ValueError('Unexpected restart-message relocation')
    relocation=overlapping[0]
    struct.pack_into('<H',result,relocation.struct.get_file_offset(),relocation.rva & 0xfff)
    result[header:header+40]=struct.pack('<8sIIIIIIHHI',b'.tioscr\0',SIZE,SECTION_RVA,SIZE,len(data),0,0,0,0,0xe0000060)
    struct.pack_into('<H',result,pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'),len(pe.sections)+1)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),SECTION_RVA+SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),0)
    result.extend(extension())
    return bytes(result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    original=args.source.read_bytes()
    updated=patch(original,expected_sha=args.expected_sha)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_bytes(updated)
    report=dict(source_sha256=hashlib.sha256(original).hexdigest(),
                candidate_sha256=hashlib.sha256(updated).hexdigest(),
                source_bytes=len(original),candidate_bytes=len(updated),
                fixed_host_sha256=TI_SHA,section_rva=hex(SECTION_RVA),
                native_device_lifecycle=True,native_ui_resize=True,
                hresult_rollback=True,unchanged_settings_skip_reset=True,
                removed_restart_popup=True,neutralized_relocation='0x48381a',
                graphical_validation=False,published=False)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
