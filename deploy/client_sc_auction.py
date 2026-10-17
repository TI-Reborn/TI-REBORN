"""Checked F8/v1 SC GUI receiver after the exact phase3 item release.

Only chains the existing PacketHandler gate to preserve F7, the other four item
hooks, all earlier F6/equipment hooks and every stock BD request builder. This
module returns candidate bytes; it never installs, publishes or restarts.
"""
import hashlib
import struct
import pefile
from .client_equipment_batch import Code
from .client_battle_items import READER_ENTRY as F7_ENTRY, sites as item_sites

BASE_SHA = '2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f'
BASE_BYTES = 7753216
RVA = 0x817000
BASE_SIZE = 0x5200
SIZE = 0x7200
READER_ENTRY = 0x400000 + RVA + 0x5200
CHECK_ENTRY = 0x400000 + RVA + 0x6a00
TEXT_ENTRY = 0x400000 + RVA + 0x6a80
REFRESH_ENTRY = 0x400000 + RVA + 0x6b80
INPUT_ENTRY = 0x400000 + RVA + 0x6c80
SIGNATURE = b'TIO-SC-auction-F8-v1'
HOOK = 0x9f5563


def _global(c, opcode, address): c.emit(opcode); c.word(address - 0x400000)
def _constant(c, address): _global(c, '8d83', address)


def _bound(c, n):
    c.emit('b8'); c.word(n); c.call(CHECK_ENTRY); c.emit('85c0'); c.branch('0f84','done')


def _zero(c, offset):
    c.emit('837a'); c.emit(f'{offset:02x}00'); c.branch('0f85','done')


def _number(c, offset, positive=False):
    c.emit('8b42'); c.emit(f'{offset:02x}'); c.emit('85c0'); c.branch('0f88','done')
    if positive: c.branch('0f84','done')


def _date(c, offset):
    # Positive finite calendar interval 30000..100000 days; little-endian high
    # word checks keep all NaN/infinity/negative dates outside native formatters.
    c.emit('8b42'); c.emit(f'{offset+4:02x}'); c.emit('3d004cdd40'); c.branch('0f82','done')
    c.emit('3d006af840'); c.branch('0f87','done')


def _array(c, var, type_address, count_var):
    c.emit('ff75'); c.emit(f'{count_var & 255:02x}')
    c.emit('8d45'); c.emit(f'{var & 255:02x}')
    _global(c,'8b93',type_address); c.emit('b901000000'); c.call(0x40d5a4); c.emit('83c404')


def _clear_array(c, address, type_address):
    _constant(c,address); _global(c,'8b93',type_address); c.call(0x40d6c8)


def _show(c, name):
    _constant(c,name); c.emit('b201'); c.call(0xa69cd0)


def reader_code():
    c=Code(READER_ENTRY); c.emit('3cf8'); c.branch('0f85','stock')
    c.emit('9c60 89e5 83ec40'); c.base()
    # Original incoming EDX points after opcode; ECX includes the opcode.
    c.emit('8955fc 83f903'); c.branch('0f82','done')
    c.emit('81f9fdff0000'); c.branch('0f87','done')
    c.emit('8d7c0aff 39d7'); c.branch('0f82','done')
    c.emit('89d6 c745ec00000000 c745e000000000')
    _bound(c,2); c.emit('807efe01'); c.branch('0f85','done')
    c.emit('0fb646ff 8945f4 83f800'); c.branch('0f84','clear_check')
    c.emit('83f801'); c.branch('0f84','catalog_check')
    c.emit('83f802'); c.branch('0f84','history_check')
    c.emit('83f803'); c.branch('0f84','bot_check')
    c.emit('83f804'); c.branch('0f84','claim_check'); c.branch('e9','done')
    c.label('clear_check'); c.emit('39fe'); c.branch('0f85','done'); c.branch('e9','clear')

    c.label('catalog_check'); _bound(c,2)
    c.emit('0fb746fe 3dc8000000'); c.branch('0f87','done')
    c.emit('8945f0 8945e8 85c0'); c.branch('0f84','validated')
    c.label('check_lot'); _bound(c,88); c.emit('8d56a8')
    _number(c,0,True); c.emit('807a0801'); c.branch('0f82','done')
    c.emit('807a0802'); c.branch('0f87','done')
    c.emit('807a0901'); c.branch('0f87','done')
    _number(c,4)
    for offset in (12,16,20,24,28,40,44,48,76): _number(c,offset)
    for offset in (52,56,64,80,84): _zero(c,offset)
    for offset in (10,62,74):
        c.emit('66837a'); c.emit(f'{offset:02x}00'); c.branch('0f85','done')
    for offset in (60,61,72,73):
        c.emit('807a'); c.emit(f'{offset:02x}01'); c.branch('0f87','done')
    _date(c,32)
    c.emit('8b4244 3d0050c347'); c.branch('0f87','done')  # finite, nonnegative weight <=100000.
    for _ in range(3):
        c.call(TEXT_ENTRY); c.emit('85c0'); c.branch('0f84','done')
    _bound(c,2); c.emit('0fb746fe 85c0'); c.branch('0f84','done')
    c.emit('83f820'); c.branch('0f87','done'); c.emit('8945dc')
    c.label('check_prize'); _bound(c,12); c.emit('8d56f4')
    _number(c,0,True); _number(c,4,True)
    c.emit('807a081b'); c.branch('0f87','done')
    c.emit('807a0900'); c.branch('0f85','done')
    c.emit('66837a0a00'); c.branch('0f85','done')
    c.emit('ff4ddc'); c.branch('0f85','check_prize')
    c.emit('ff4de8'); c.branch('0f85','check_lot'); c.branch('e9','validated')

    c.label('history_check'); _bound(c,14); c.emit('8d56f2'); _number(c,0,True)
    c.emit('66837a0400'); c.branch('0f84','done')
    c.emit('0fb74204 663b4206'); c.branch('0f87','done')
    _number(c,8); c.emit('0fb7420c 3dc8000000'); c.branch('0f87','done')
    c.emit('8945f0 8945e8 85c0'); c.branch('0f84','validated')
    c.label('check_history'); _bound(c,24); c.emit('8d56e8'); _zero(c,12); _date(c,0)
    c.emit('807a0809'); c.branch('0f87','done')
    c.emit('807a0900'); c.branch('0f85','done')
    c.emit('66837a0a00'); c.branch('0f85','done')
    c.emit('66837a1600'); c.branch('0f85','done')
    _number(c,16)
    c.emit('807a1401'); c.branch('0f87','done')
    c.emit('807a1501'); c.branch('0f87','done')
    c.call(TEXT_ENTRY); c.emit('85c0'); c.branch('0f84','done')
    c.emit('ff4de8'); c.branch('0f85','check_history'); c.branch('e9','validated')

    c.label('bot_check'); _bound(c,20); c.emit('8d56ec')
    _number(c,0,True)
    for offset in (4,8,12,16): _number(c,offset)
    c.branch('e9','validated')
    c.label('claim_check'); _bound(c,18); c.emit('8d56ee'); _number(c,0,True); _date(c,4)
    _number(c,12)
    c.emit('807a1001'); c.branch('0f87','done')
    c.emit('807a1101'); c.branch('0f87','done')
    c.label('validated'); c.emit('39fe'); c.branch('0f85','done')
    c.emit('8b75fc 83c602 8b45f4 83f801'); c.branch('0f84','catalog')
    c.emit('83f802'); c.branch('0f84','history')
    c.emit('83f803'); c.branch('0f84','bot'); c.branch('e9','claim')

    c.label('clear')
    for address,kind in ((0xacf418,0x88c7a8),(0xacf41c,0x88c7a8),(0xacf420,0x88c7d4)):
        _clear_array(c,address,kind)
    for address in (0xac4918,0xac491c,0xac4920,0xac4924,0xac4928,0xac492c,0xac493c,0xac4940,0xacf444):
        _global(c,'c783',address); c.word(0)
    _global(c,'c683',0xac490e); c.emit('00')
    _global(c,'c683',0xac490d); c.emit('00')
    for name in (0x8917c4,0x891f10,0x894b5c): _constant(c,name); c.call(0xa6a114)
    c.call(REFRESH_ENTRY); c.branch('e9','done')

    c.label('catalog'); c.emit('83c602 8975fc')
    _global(c,'c683',0xac490d); c.emit('00')
    _global(c,'83bb',0xac5fe4); c.emit('00'); c.branch('0f84','catalog_clock_done')
    _global(c,'c683',0xac490d); c.emit('01')
    c.label('catalog_clock_done')
    _array(c,-20,0x88c7a8,-16); c.emit('c745e800000000')
    c.emit('837df000'); c.branch('0f84','catalog_swap')
    c.label('load_lot'); c.emit('6b45e858 0345ec 8945e4 89c7 8b75fc b916000000 fc f3a5 8975fc')
    _global(c,'8b93',0xac5fe4); c.emit('85d2'); c.branch('0f84','lot_clock_done')
    c.emit('8b45e4 8b4828 030a 89482c')
    c.label('lot_clock_done')
    for offset in (52,56,64):
        c.emit('8d45fc 8b55e4 83c2'); c.emit(f'{offset:02x}'); c.call(0x605df4)
    c.emit('8b75fc 0fb706 8945dc 83c602 8975fc ff75dc 8b45e4 83c050')
    _global(c,'8b93',0x88c474); c.emit('b901000000'); c.call(0x40d5a4); c.emit('83c404')
    c.emit('8b7de4 8b7f50 8b75fc 6b4ddc03 fc f3a5 8975fc ff45e8 8b45e8 3b45f0')
    c.branch('0f82','load_lot')
    c.label('catalog_swap'); _clear_array(c,0xacf418,0x88c7a8)
    c.emit('8b45ec'); _global(c,'8983',0xacf418); _global(c,'c683',0xac490e); c.emit('01')
    c.call(REFRESH_ENTRY); c.branch('e9','done')

    c.label('history'); c.emit('8b06'); _global(c,'8983',0xac491c)
    c.emit('0fb74604'); _global(c,'8983',0xac4928)
    c.emit('0fb74606'); _global(c,'8983',0xac492c)
    c.emit('8b4608'); _global(c,'8983',0xac4920)
    _global(c,'8b93',0xac5fe4); c.emit('85d2'); c.branch('0f84','history_no_clock')
    c.emit('0302'); _global(c,'8983',0xac4924); _global(c,'c683',0xac490d); c.emit('01')
    c.branch('e9','history_clock_done')
    c.label('history_no_clock'); _global(c,'c683',0xac490d); c.emit('00')
    c.label('history_clock_done'); c.emit('83c60e 8975fc')
    _array(c,-20,0x88c7d4,-16); c.emit('c745e800000000 837df000'); c.branch('0f84','history_swap')
    c.label('load_history'); c.emit('6b45e818 0345ec 8945e4 89c7 8b75fc b906000000 fc f3a5 8975fc')
    c.emit('8d45fc 8b55e4 83c20c'); c.call(0x605df4)
    c.emit('ff45e8 8b45e8 3b45f0'); c.branch('0f82','load_history')
    c.label('history_swap'); _clear_array(c,0xacf420,0x88c7d4)
    c.emit('8b45ec'); _global(c,'8983',0xacf420)
    _global(c,'8b83',0xac4914); c.emit('85c0'); c.branch('0f84','done')
    c.call(0x89b2d8); _show(c,0x891f10); c.branch('e9','done')

    c.label('bot'); c.emit('8b06'); _global(c,'8983',0xac493c)
    c.emit('8b4604'); _global(c,'8983',0xac4940)
    # Store valid scalars even before a window exists, but never call a missing UI.
    for address in (0xacf740,0xacf744,0xacf748):
        _global(c,'83bb',address); c.emit('00'); c.branch('0f84','done')
    for offset,address in ((8,0xacf740),(12,0xacf748),(16,0xacf744)):
        c.emit('8b46'); c.emit(f'{offset:02x}'); _global(c,'8b93',address); c.call(INPUT_ENTRY)
    _show(c,0x894b5c); c.branch('e9','done')

    c.label('claim'); c.emit('8b06'); _global(c,'8983',0xacf444)
    c.emit('8b4604'); _global(c,'8983',0xacf438)
    c.emit('8b4608'); _global(c,'8983',0xacf43c)
    _global(c,'c783',0xacf440); c.word(0)  # No historical below-reserve deficit in configured offers.
    c.emit('8b460c'); _global(c,'8983',0xacf44c)
    c.emit('8a4610'); _global(c,'8883',0xacf449)
    c.emit('8a4611'); _global(c,'8883',0xacf448)
    _show(c,0x8917c4)
    c.label('done'); c.emit('89ec c7451c01000000 619d c3')
    c.label('stock'); c.call(F7_ENTRY); c.emit('c3')
    return c.finish(0x1800)


def check_code():
    c=Code(CHECK_ENTRY); c.emit('89f2 01c2'); c.branch('0f82','bad')
    c.emit('39fa'); c.branch('0f87','bad'); c.emit('89d6 b801000000 c3')
    c.label('bad'); c.emit('31c0 c3'); return c.finish(0x80)


def text_code():
    c=Code(TEXT_ENTRY); c.emit('51 b901010000')
    c.label('loop'); c.emit('b802000000'); c.call(CHECK_ENTRY); c.emit('85c0'); c.branch('0f84','bad')
    c.emit('0fb746fe 85c0'); c.branch('0f84','good')
    c.emit('3d00d80000'); c.branch('0f82','next')
    c.emit('3dffdf0000'); c.branch('0f86','bad')
    c.label('next'); c.emit('49'); c.branch('0f85','loop')
    c.label('bad'); c.emit('31c0 59 c3')
    c.label('good'); c.emit('b801000000 59 c3'); return c.finish(0x100)


def refresh_code():
    c=Code(REFRESH_ENTRY)
    for address in (0xac4910,0xacf424,0xacf428,0xacf42c,0xacf430,0xacf434):
        _global(c,'83bb',address); c.emit('00'); c.branch('0f84','done')
    _global(c,'8b83',0xac4910); c.call(0x89a514)
    c.label('done'); c.emit('c3'); return c.finish(0x100)


def input_code():
    # EAX integer, EDX original input object. Native numeric conversion returns
    # a managed UTF16 string; input setter+RTL own its normal refcount lifecycle.
    c=Code(INPUT_ENTRY); c.emit('55 89e5 56 52 6a00 8d55f4'); c.call(0x4244b4)
    c.emit('8b45f8 8b55f4'); c.call(0xa46b10)
    c.emit('8d45f4'); c.call(0x40b09c); c.emit('83c408 5e 5d c3')
    return c.finish(0x100)


def extension():
    return (reader_code()+check_code()+text_code()+refresh_code()+input_code()+SIGNATURE).ljust(SIZE-BASE_SIZE,b'\0')


def _call(target): return b'\xe8'+struct.pack('<i',target-HOOK-5)


def patch(data):
    try: pe=pefile.PE(data=data)
    except pefile.PEFormatError as error: raise ValueError('Unsupported SC client PE') from error
    section=pe.sections[-1]; offset=pe.get_offset_from_rva(HOOK-0x400000)
    if SIGNATURE in data:
        if (section.VirtualAddress!=RVA or section.SizeOfRawData!=SIZE or section.Misc_VirtualSize!=SIZE
            or pe.OPTIONAL_HEADER.SizeOfImage!=RVA+0x8000 or section.PointerToRawData+SIZE!=len(data)
            or data[section.PointerToRawData+BASE_SIZE:]!=extension() or data[offset:offset+5]!=_call(READER_ENTRY)):
            raise ValueError('Unknown SC extension')
        restored=bytearray(data[:section.PointerToRawData+BASE_SIZE]); restored[offset:offset+5]=_call(F7_ENTRY)
        for field in (8,16): struct.pack_into('<I',restored,section.get_file_offset()+field,BASE_SIZE)
        struct.pack_into('<I',restored,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x6000)
        if len(restored)!=BASE_BYTES or hashlib.sha256(restored).hexdigest()!=BASE_SHA:
            raise ValueError('Unknown SC base release')
        return data
    if len(data)!=BASE_BYTES or hashlib.sha256(data).hexdigest()!=BASE_SHA:
        raise ValueError('Expected exact phase3 items client release')
    if (section.VirtualAddress!=RVA or section.SizeOfRawData!=BASE_SIZE or section.Misc_VirtualSize!=BASE_SIZE
        or section.PointerToRawData+BASE_SIZE!=len(data) or pe.OPTIONAL_HEADER.SizeOfImage!=RVA+0x6000):
        raise ValueError('Unexpected SC extension base layout')
    for address,before,after in item_sites():
        at=pe.get_offset_from_rva(address-0x400000)
        if data[at:at+len(after)]!=after: raise ValueError('Required existing item hook differs')
    relocations={e.rva for b in getattr(pe,'DIRECTORY_ENTRY_BASERELOC',()) for e in b.entries if e.type}
    if any(HOOK-0x400000 <= rva < HOOK-0x400000+5 for rva in relocations):
        raise ValueError('SC relative hook overlaps a relocation')
    result=bytearray(data); result[offset:offset+5]=_call(READER_ENTRY); result.extend(extension())
    for field in (8,16): struct.pack_into('<I',result,section.get_file_offset()+field,SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),RVA+0x8000)
    return bytes(result)


def patch_plan(previous, updated):
    if patch(previous)!=updated: raise ValueError('SC candidate differs from checked patch')
    pe=pefile.PE(data=previous); section=pe.sections[-1]
    offsets=(pe.get_offset_from_rva(HOOK-0x400000),section.get_file_offset()+8,
             section.get_file_offset()+16,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'))
    changes=[dict(offset=o,before_hex=previous[o:o+n].hex(),after_hex=updated[o:o+n].hex())
             for o,n in zip(offsets,(5,4,4,4))]
    allowed={at for row in changes for at in range(row['offset'],row['offset']+len(bytes.fromhex(row['before_hex'])))}
    if any(a!=b and at not in allowed for at,(a,b) in enumerate(zip(previous,updated))):
        raise ValueError('Unexpected SC edit outside receiver hook and PE sizes')
    if updated[len(previous):]!=extension(): raise ValueError('Unexpected SC appended code')
    return dict(previous_sha256=hashlib.sha256(previous).hexdigest(),updated_sha256=hashlib.sha256(updated).hexdigest(),
        previous_bytes=len(previous),updated_bytes=len(updated),changes=changes,appended_bytes=len(extension()),
        existing_f6_f7_and_four_other_item_hooks_preserved=True,all_stock_bd_builders_preserved=True,
        namespace='Explicit emulator F8/v1 SC model snapshots; original BD GUI requests')
