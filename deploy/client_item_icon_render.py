"""Native HD item drawing within the A2 warehouse and equipment controls.

The original item renderer retains counts, upgrades, hints and condition
overlays. Only its base illustration receives a high-resolution resource.
Texture metadata is restored before returning to any other native control.
"""
from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE=0x400000
SIZE=0xa000


def _square_side(c: Code, state: int, register: str, label: str) -> None:
    """Use 72 for the warehouse; keep pictures inside compact native slots."""
    immediate, load, subtract, compare = {
        'esi': ('be', '8bb3', '83ee04', '83fe48'),
        'edx': ('ba', '8b93', '83ea04', '83fa48'),
    }[register]
    c.emit(immediate);c.word(72)
    c.emit('83bb');c.word(state);c.emit('01');c.branch('0f84',label)
    c.emit(load);c.word(state+8);c.emit(subtract+' '+compare)
    c.branch('0f8e',label)
    c.emit(immediate);c.word(72);c.label(label)


def validate_ids(values: tuple[int,...]) -> tuple[int,...]:
    if (not values or len(values)>160 or len(set(values))!=len(values)
            or any(type(value) is not int or not 1<=value<=65535 for value in values)):
        raise ValueError('Expected unique inventory item IDs')
    return tuple(sorted(values))


def image_path(identity: int) -> str:
    validate_ids((identity,))
    return f'items\\hd\\tio_ih_{identity}_512.png'


def _scope(origin: int, offset: int, layout_state: int, state: int, paper: bool, bag: bool=False) -> bytes:
    from .client_equipment_batch import Code
    c=Code(BASE+origin+offset)
    c.emit('55 89e5 83ec30 9c60');c.base()
    c.emit('83bb');c.word(layout_state);c.emit('01');c.branch('0f85','stock')
    c.emit('8b44241c 8945f8')
    if paper:
        c.emit('8b504c 3b93');c.word(0xad10a0-BASE);c.branch('0f85','stock')
    else:
        c.emit('3b83');c.word((0xac4bd4 if bag else 0xac4bd8)-BASE);c.branch('0f85','stock')
    for position,field in ((-4,0),(-12,4),(-16,8)):
        c.emit('8b93');c.word(state+field);c.emit('8955'+f'{position&255:02x}')
    c.emit('c783');c.word(state);c.word(3 if bag else (2 if paper else 1))
    if bag:
        # Both native background images use the actual cell bounds. Their
        # metadata and the shared illustration scope are restored on return.
        c.emit('8b90ec020000 8955e8 8b90f8020000 8955e4')
        c.emit('8b90d4020000 8955ec c780d402000000000000')
        c.emit('0fb69088020000 8955e0 c6808802000000')
        c.emit('8b908c020000 3b503c');c.branch('0f8f','bag_scroll')
        c.emit('c6808802000001');c.label('bag_scroll')
        c.emit('8b5038 83ea26 c1fa02 8993');c.word(state+4)
        c.emit('c783');c.word(state+8);c.word(56)
        c.emit('83fa50');c.branch('0f83','bag_tall')
        c.emit('c783');c.word(state+8);c.word(42)
        c.emit('81ca00002a00');c.branch('e9','bag_dimensions')
        c.label('bag_tall');c.emit('81ca00003800')
        c.label('bag_dimensions');c.emit('8990ec020000 8990f8020000')
    if paper:
        c.emit('8b5038 8993');c.word(state+4)
        c.emit('8b503c 8993');c.word(state+8)
        c.emit('89c6 0fb6901b050000 8955ec 8b5030 8955e8 8b5034 8955e4')
        c.call(0xa4211c);c.emit('89c7 89f0');c.call(0xa42140);c.emit('8945e0')
        # Draw a full native slot frame; the original paper renderer keeps
        # its item overlays and empty-slot hint in the same control.
        for inset,color in ((0,0xff3a6b2f),(1,0xff1a3012)):
            c.emit('8b463c')
            if inset:c.emit('83e802')
            c.emit('50 6a00 68');c.word(color);c.emit('6802010000 8b4e38')
            if inset:c.emit('83e902')
            c.emit('8b55e0 89f8')
            if inset:c.emit('40 42')
            c.call(0x4f2888)
        c.emit('83be9002000000');c.branch('0f84','empty_slot')
        c.emit('c6861b05000000');c.branch('e9','paper_ready')
        c.label('empty_slot')
        c.emit('8b4638 83e840 d1f8 014630 8b463c 83e820 d1f8 014634')
        c.label('paper_ready')
    original = 0x9bc394 if bag else (0xa4e38c if paper else 0x99ddcc)
    if not paper and not bag:
        c.emit('8b45f8');c.call(BASE+origin+0x9800)
    c.emit('619d');c.call(original)
    c.emit('9c60');c.base()
    for position,field in ((-4,0),(-12,4),(-16,8)):
        c.emit('8b55'+f'{position&255:02x}'+' 8993');c.word(state+field)
    if paper:
        c.emit('8b45f8 8b55ec 88901b050000 8b55e8 895030 8b55e4 895034')
        c.call(BASE+origin+0x10000+0xc000)
    if bag:
        c.emit('8b45f8 8b55e8 8990ec020000 8b55e4 8990f8020000')
        c.emit('8b55ec 8990d4020000 8b55e0 889088020000')
    c.emit('619d 89ec5dc3')
    c.label('stock');c.emit('619d 89ec5d');c.jump(original)
    return c.finish(0x500)


def _item(origin: int, rows: int, state: int, count: int) -> bytes:
    from .client_equipment_batch import Code
    c=Code(BASE+origin+0xa00)
    c.emit('55 89e5 81ecb0000000 53 56 57')
    c.emit('8945fc 8955f8 894df4');c.base()
    c.emit('83bb');c.word(state);c.emit('00');c.branch('0f84','stock')
    c.emit('83bb');c.word(state);c.emit('01');c.branch('0f85','frame_done')
    c.emit('9c60')
    from .client_barracks_skin import native_colour
    for inset, colour in ((0,0xff2f6b3a),(1,0xff12301a)):
        c.emit('68');c.word(72-2*inset)
        c.emit('6a00 68');c.word(native_colour(colour));c.emit('6802010000')
        c.emit('b9');c.word(72-2*inset)
        c.emit('8b45fc 83e8'+f'{32-inset:02x}'+' 8b55f8 83ea'+f'{16-inset:02x}')
        c.call(0x4f2888)
    c.emit('619d');c.label('frame_done')
    c.emit('8b7108 8d93');c.word(rows);c.emit('b9');c.word(count)
    c.label('find');c.emit('3b32');c.branch('0f84','found')
    c.emit('83c220 49');c.branch('0f85','find');c.branch('e9','stock')
    c.label('found');c.emit('89d6');c.call(BASE+origin+0x1d00)
    c.emit('837e0401');c.branch('0f85','stock')
    c.emit('8b45f4');c.call(0xa7b030);c.emit('85c0');c.branch('0f88','stock')
    c.emit('69c04f070000 8b93');c.word(0xac637c-BASE)
    c.emit('8b12 8b44c210 85c0');c.branch('0f84','stock')
    c.emit('8b78fc 83ff01');c.branch('0f82','stock')
    c.emit('83ff20');c.branch('0f87','stock')
    c.emit('8945f0 897dec 8b93');c.word(state+12);c.emit('8955e8 89b3');c.word(state+12)
    c.emit('31c9 89c2')
    c.label('save_tile');c.emit('8b7208 89b48d50ffffff')
    _square_side(c,state,'esi','tile_size')
    c.emit('66897208 6689720a')
    c.emit('83c20c 41 39f9');c.branch('0f82','save_tile')
    c.emit('8b45fc 8b55f8 8b4df4 83bb');c.word(state);c.emit('01');c.branch('0f85','paper')
    c.emit('83c004 83c214');c.branch('e9','draw')
    c.label('paper')
    c.emit('8bb3');c.word(state+4);c.emit('d1fe 83ee20 01f0')
    c.emit('8bb3');c.word(state+8);c.emit('d1fe 83ee10 01f2')
    c.label('draw')
    for offset in (0x20,0x1c,0x18,0x14,0x10,0xc,8):c.emit('ff75'+f'{offset:02x}')
    c.call(BASE+origin+0x1c00);c.emit('8945e4 8b55f0 31c9')
    c.label('restore_tile');c.emit('8bb48d50ffffff 897208 83c20c 41 3b4dec');c.branch('0f82','restore_tile')
    c.emit('8b55e8 8993');c.word(state+12)
    c.call(BASE+origin+0x2700)
    c.emit('8b45e4 5f5e5b 89ec5d c21c00')
    c.label('stock');c.emit('8b45fc 8b55f8 8b4df4')
    for offset in (0x20,0x1c,0x18,0x14,0x10,0xc,8):c.emit('ff75'+f'{offset:02x}')
    c.call(BASE+origin+0x1c00);c.emit('8945e4')
    c.call(BASE+origin+0x2700)
    c.emit('8b45e4 5f5e5b 89ec5d c21c00')
    return c.finish(0xe00)


def _quantity(origin: int, state: int) -> bytes:
    """The stock warehouse used a separate quantity column, now a cell badge."""
    from .client_equipment_batch import Code
    from .client_barracks_skin import native_colour

    c = Code(BASE+origin+0x2700)
    c.base()
    c.emit('83bb'); c.word(state); c.emit('01')
    c.branch('0f85', 'done')
    c.emit('8b45f4 8b401c 83f802'); c.branch('0f82', 'done')
    c.emit('8d9560ffffff'); c.call(BASE+origin+0x23000)
    c.emit('8b50fc d1ea 6bd207 8b4dfc 83c124 29d1')
    c.emit('68'); c.word(native_colour(0xffece5b8)); c.emit('6a00 6a00')
    c.emit('89ca 8b4df8 83c124'); c.call(0x67571c)
    c.label('done'); c.emit('c3')
    return c.finish(0x800)


def _load(origin: int) -> bytes:
    from .client_equipment_batch import Code
    c=Code(BASE+origin+0x1d00);c.emit('9c60 837e0400');c.branch('0f85','done')
    c.emit('c74604ffffffff 6a00 6a00 6a02 8d4608 50 8b4614 01f0 ba00020000 b900020000')
    c.call(0x4f2cb4);c.emit('837e0800');c.branch('0f84','done')
    c.emit('c7460401000000')
    c.label('done');c.emit('619dc3');return c.finish(0x200)


def _art(origin: int, state: int) -> bytes:
    from .client_equipment_batch import Code
    c=Code(BASE+origin+0x1800);c.emit('55 89e5 83ec10 53 56 57 8945fc 8955f8 894df4');c.base()
    c.emit('8bb3');c.word(state+12);c.emit('85f6');c.branch('0f84','stock')
    _square_side(c,state,'edx','art_size')
    c.emit('6800020000 6800020000 ff75f8 ff75f4 5252 ff7510 6a00')
    c.emit('8b4608 31d2 31c9 bf10067400 ffd7')
    c.emit('b801000000 5f5e5b 89ec5d c20c00')
    c.label('stock');c.emit('8b45fc 8b55f8 8b4df4 5f5e5b 89ec5d');c.jump(0x674e78)
    return c.finish(0x400)


def _base_picture(origin: int, state: int) -> bytes:
    """An HD master replaces the composite illustration as one whole image."""
    from .client_equipment_batch import Code

    c = Code(BASE+origin+0x2f00)
    c.emit('9c53'); c.base()
    c.emit('83bb'); c.word(state+12); c.emit('00')
    c.branch('0f84', 'stock')
    c.emit('5b9d'); c.jump(0xa77a3f)
    c.label('stock'); c.emit('5b9d 84c0')
    c.branch('0f84', 'plain')
    c.jump(0xa778dc)
    c.label('plain'); c.jump(0xa77a3f)
    return c.finish(0x100)


def _warehouse_cells(origin: int) -> bytes:
    """Empty visible cells use the same pitch as native item hit regions."""
    from .client_barracks_skin import native_colour
    from .client_equipment_batch import Code

    c=Code(BASE+origin+0x9800)
    c.emit('55 89e5 83ec20 9c60 89c6')
    c.emit('89f0');c.call(0xa4211c);c.emit('8945fc 89f0')
    c.call(0xa42140);c.emit('8945f8')
    # Same wrap as the native item layout: 72 px tiles every 76 px from x=3,
    # beside the 16 px scrollbar; every row that fits completely is framed.
    c.emit('8b4638 2d');c.word(16+72+3);c.branch('0f8c','done')
    c.emit('31d2 b94c000000 f7f1 40 8945e4')
    c.emit('8b463c 31d2 f7f1')
    c.emit('0faf45e4 8945e0 85c0');c.branch('0f84','done')
    c.emit('31ff')
    c.label('cell')
    c.emit('89f8 31d2 f775e4 6bc04c 6bd24c 83c003 83c203 8945f0 8955f4')
    for inset, colour in ((0,0xff30383c),(1,0xff14191d)):
        c.emit('68');c.word(72-2*inset)
        c.emit('6a00 68');c.word(native_colour(colour));c.emit('6802010000 b9');c.word(72-2*inset)
        c.emit('8b45fc 0345f4 8b55f8 0355f0')
        if inset:c.emit('40 42')
        c.call(0x4f2888)
    c.emit('47 3b7de0');c.branch('0f82','cell')
    c.label('done')
    c.emit('619d 89ec5dc3')
    return c.finish(0x700)


GRID = (
    (0x99dfd5,'8345f0478b45fc','8345f04c8b45fc'),
    (0x99efef,'c7839002000027000000','c783900200004c000000'),
    (0x99f028,'83c2478bce','83c24c8bce'),
    (0x99f03a,'83839002000027','8383900200004c'),
    (0x99f030,'83e9403bd1','83e9483bd1'),
    (0x99dfe4,'83e8403b45f07f0a','wrap'),
    (0x99df43,'6a208d8564ffffff','6a488d8564ffffff'),
    (0x99df55,'b940000000','b948000000'),
    (0x99dfae,'6a228b45f8','6a4a8b45f8'),
    (0x99dfc1,'b942000000','b94a000000'),
    # Dynamic click, double-click, drag and hint regions are registered by
    # the stock item closure, separately from the painted cell rectangle.
    (0x99d4b0,'6a406a208d45a4','6a486a488d45a4'),
    (0x99d544,'6a406a208d854cffffff','6a486a488d854cffffff'),
    (0x99d5aa,'6a406a208d8524ffffff','6a486a488d8524ffffff'),
    (0x99d653,'6a406a208d85dcfeffff','6a486a488d85dcfeffff'),
)


def payload(origin: int, layout_state: int, item_ids: tuple[int,...]) -> bytes:
    from .client_equipment_batch import Code
    ids=validate_ids(item_ids);rows=origin+0x3000;names=origin+0x5000;state=origin+0x9000
    result=bytearray(SIZE)
    for offset,raw in ((0,_scope(origin,0,layout_state,state,False)),(0x500,_scope(origin,0x500,layout_state,state,True)),
                       (0xa00,_item(origin,rows,state,len(ids))),(0x1800,_art(origin,state)),(0x1d00,_load(origin))):
        result[offset:offset+len(raw)]=raw
    trampoline=Code(BASE+origin+0x1c00);trampoline.emit('558bec51b96e000000');trampoline.jump(0xa777e9)
    result[0x1c00:0x1c40]=trampoline.finish(0x40)
    result[0x2f00:0x3000] = _base_picture(origin, state)
    result[0x2700:0x2f00] = _quantity(origin, state)
    result[0x9200:0x9700] = _scope(origin,0x9200,layout_state,state,False,True)
    result[0x9800:0x9f00] = _warehouse_cells(origin)
    for index,(site,stock,replacement) in enumerate(GRID):
        c=Code(BASE+origin+0x2000+index*0x80);c.emit('9c53');c.base()
        c.emit('83bb');c.word(layout_state);c.emit('01');c.branch('0f85','stock')
        if replacement=='wrap':
            # The stock JG targets the following INC. Keep that branch entry
            # intact rather than covering it with a longer patch instruction.
            for mode,width,pitch in (('new',72,76),('stock',64,39)):
                if mode=='stock':c.label('stock')
                c.emit('5b9d 83e8'+f'{width:02x}'+' 3b45f0')
                c.branch('0f8f',f'{mode}_advance')
                c.emit('8d4303 8945f0 8345e8'+f'{pitch:02x}')
                c.label(f'{mode}_advance');c.jump(0x99dff6)
        else:
            c.emit('5b9d');c.emit(replacement);c.jump(site+len(bytes.fromhex(stock)))
            c.label('stock');c.emit('5b9d');c.emit(stock);c.jump(site+len(bytes.fromhex(stock)))
        at=0x2000+index*0x80;result[at:at+0x80]=c.finish(0x80)
    for index,identity in enumerate(ids):
        row=0x3000+index*32;name=0x5000+index*96;text=image_path(identity)
        encoded=struct.pack('<HHiI',1200,2,-1,len(text))+text.encode('utf-16le')+b'\0\0'
        if len(encoded)>96:raise ValueError('Native resource path exceeds its slot')
        result[name:name+len(encoded)]=encoded
        struct.pack_into('<I',result,row,identity)
        struct.pack_into('<I',result,row+20,name+12-row)
    result[0x9f00:0x9f20]=b'TIO-A2-HD-item-render-v1'.ljust(32,b'\0')
    return bytes(result)


def edits(origin: int) -> tuple[tuple[int, bytes, bytes],...]:
    changes=[]
    for site,before,target in ((0x995ecc,0x99ddcc,BASE+origin),(0xa2f518,0xa4e38c,BASE+origin+0x500),
                               (0x9b23e8,0x9bc394,BASE+origin+0x9200)):
        changes.append((site,struct.pack('<I',before),struct.pack('<I',target)))
    for site,before,offset,opcode in ((0xa777e0,bytes.fromhex('558bec51b96e000000'),0xa00,0xe9),
                                    (0xa778d4,bytes.fromhex('84c00f8463010000'),0x2f00,0xe9),
                                    (0xa77a9b,b'\xe8'+struct.pack('<i',0x674e78-0xa77a9b-5),0x1800,0xe8)):
        after=bytes((opcode,))+struct.pack('<i',BASE+origin+offset-site-5)
        changes.append((site,before,after.ljust(len(before),b'\x90')))
    for index,(site,stock,_) in enumerate(GRID):
        before=bytes.fromhex(stock);after=b'\xe9'+struct.pack('<i',BASE+origin+0x2000+index*0x80-site-5)
        changes.append((site,before,after.ljust(len(before),b'\x90')))
    return tuple(changes)
