"""Guarded native barracks presentation, composed over the published client.

Native controls retain their owners, callbacks and item data. The transformer
only appends presentation code and redirects exact constructor/resize/draw
calls. It does not install files, attach to processes or contact a server.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_equipment_batch import Code

BASE_SHA = '28f33ff6a920182eeb7a81b9d3c30853081f3f52c7d505da15b54de97c01b2ad'
BASE_FILE_SIZE = 8184320
BASE = 0x400000
ORIGINAL_SIZE = 0x886000
# Align the extension to a Windows reservation boundary. The same reviewed
# code can then be exercised in an isolated QA process before publication.
REGION = 0x890000
SIZE = 0x40000
LAYOUT = BASE + REGION
CONSTRUCT = LAYOUT + 0xc000
RESIZE = LAYOUT + 0xc100
DRAW = LAYOUT + 0xc200
SHOW = LAYOUT + 0xe000
SHOW_TRAMPOLINE = LAYOUT + 0xe100
MAIL = LAYOUT + 0xe200
STRINGS = REGION + 0xd000
STATE = REGION + 0xff00
# The launcher writes 1 before the barracks exists when the player chooses
# the original interface. Zero keeps the A2 layout as the default.
MODE = REGION + 0xff04
SIGNATURE_OFFSET = 0xff40
SIGNATURE = b'TIO-barracks-A2-layout-v2'
HEADER = 0xac4bdc
LEFT = 0xad10a0
TABLE = 0xad10a4
TABS = 0xad1094
INFO = 0xad109c
Expr = int | tuple[str, int, int]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


def equipment_slots(width: int) -> tuple[Rect, ...]:
    """The reference has armour vertically, beside two weapons and a device."""
    armour = 110 if width >= 430 else 84
    weapon_x = 18 + armour + 14
    height = 76 if width >= 430 else 56
    rows = (50, 136, 222) if width >= 430 else (42, 106, 170)
    return tuple(Rect(x, y, w, height)
                 for x, w in ((18, armour), (weapon_x, width-18-weapon_x))
                 for y in rows)


def bag_cells(width: int) -> tuple[Rect, ...]:
    """Twelve visible backpack cells, with independent native item callbacks."""
    cell_width = (width - 36 - 18) // 4
    top, height = (348, 56) if width >= 430 else (250, 42)
    return tuple(Rect(18 + column*(cell_width+6), top+row*(height+6), cell_width, height)
                 for row in range(3) for column in range(4))


def bag_viewport(width: int) -> Rect:
    """Reserve a separate scrollbar without clipping the fourth item column."""
    top, height = (345, 186) if width >= 430 else (247, 144)
    return Rect(15, top, width-16, height)


def _spec(left: int, right: int, portrait: int) -> dict[str, tuple[Expr, ...]]:
    return {
        'equipment': (12,112,left,('h',1,-124)),
        'model': (('w',2,(left-right-portrait)//2),112,portrait,('h',1,-234)),
        'right': (('w',1,-right-12),186,right,('h',1,-198)),
        'tabs': (('w',1,-right-12),112,right,64),
    }


def _value(value: Expr, width: int, height: int) -> int:
    if isinstance(value,int):
        return value
    axis, divisor, offset = value
    return (width if axis=='w' else height)//divisor+offset


def layout(width: int, height: int) -> dict[str, Rect] | None:
    """Return bounded A2 columns, or retain stock layout on small canvases."""
    if width < 1200 or height < 544:
        return None
    left,right = (430,554) if width >= 1600 else (330,430)
    portrait = 600 if height >= 640 else 384
    inset_x, inset_y = (38, 6) if width >= 1600 else (0, 0)
    inner_width = width-52 if width >= 1600 else width
    inner_height = min(height, 682) if width >= 1600 else height
    result = {}
    for name, values in _spec(left,right,portrait).items():
        x, y, w, h = (_value(v, inner_width, inner_height) for v in values)
        result[name] = Rect(x+inset_x, y+inset_y, w, h)
    return result


def _relative(value: Expr, offset: int) -> Expr:
    if isinstance(value,int):
        return value+offset
    return value[0],value[1],value[2]+offset


def _calculate(c: Code, value: Expr) -> None:
    if isinstance(value,int):
        c.emit('ba');c.word(value)
        return
    axis,divisor,offset=value
    c.emit('8b56'+('38' if axis=='w' else '3c'))
    done = f'canvas_{len(c.data)}'
    c.emit('817e3840060000');c.branch('0f8c',done)
    if axis == 'w':
        c.emit('83ea34')
    else:
        c.emit('81faaa020000');c.branch('0f8e',done)
        c.emit('baaa020000')
    c.label(done)
    if divisor==2:
        c.emit('d1fa')
    if offset:
        c.emit('81c2');c.word(offset)


def _fields(c: Code, rect: tuple[Expr, ...], *, cached: bool=False) -> None:
    for offset,value in zip((0x30,0x34,0x38,0x3c),rect,strict=True):
        _calculate(c,value);c.emit('8950'+f'{offset:02x}')
    if cached:
        c.emit('8b5038 895044 8b503c 895040')


def _global(c: Code, address: int, skip: str) -> None:
    c.emit('8b83');c.word(address-BASE);c.emit('85c0');c.branch('0f84',skip)


def _child(c: Code, address: int, index: int, skip: str) -> None:
    _global(c,address,skip)
    c.emit('8b502c 85d2');c.branch('0f84',skip)
    c.emit('817a08');c.word(index);c.branch('0f8e',skip)
    c.emit('8b5204 8b82');c.word(4*index)
    c.emit('85c0');c.branch('0f84',skip)


def _caption(c: Code, index: int) -> None:
    c.emit('8d93');c.word(STRINGS+index*0x80+4);c.call(0xa42b04)


def _arrange(c: Code, left: int, right: int, portrait: int, prefix: str) -> None:
    spec=_spec(left,right,portrait);counter=0
    def place(address: int, index: int | None, rect: tuple[Expr,...], *, cached: bool=False, caption: int | None=None) -> None:
        nonlocal counter
        skip=f'{prefix}_{counter}';counter+=1
        (_global(c,address,skip) if index is None else _child(c,address,index,skip))
        if index is None and address in (HEADER, LEFT, TABLE, TABS, INFO, 0xad1098) and left == 430:
            rect=(_relative(rect[0],38),_relative(rect[1],6),*rect[2:])
        _fields(c,rect,cached=cached)
        if caption is not None:
            _caption(c,caption)
        c.label(skip)
    place(HEADER,None,(70,8,('w',1,-100),92))
    skip=f'{prefix}_card_pitch';_global(c,HEADER,skip)
    c.emit('c7808c02000004010000');c.label(skip)
    place(LEFT,None,(12,112,('w',1,-right-38),('h',1,-124)))
    place(INFO,None,spec['right'])
    place(TABLE,None,spec['right'])
    place(TABS,None,spec['tabs'])
    # The native side selectors remain accessible beside the warehouse.
    place(0xad1098,None,(('w',1,-right-34),183,20,('h',1,-198)))
    model=spec['model']
    place(LEFT,2,(_relative(model[0],-12),_relative(model[1],-112),*model[2:]))
    skip=f'{prefix}_portrait_fields';_child(c,LEFT,2,skip)
    _calculate(c,('h',2,-55));c.emit('8990f0020000')
    _calculate(c,model[3]);c.emit('8990f4020000');c.label(skip)
    for index in (0,1):
        skip=f'{prefix}_old_rotate_{index}';_child(c,LEFT,index,skip)
        c.emit('c6404900');c.label(skip)
    skip=f'{prefix}_template_caption';_child(c,LEFT,5,skip)
    c.emit('c6404900');c.label(skip)
    # Original rotate buttons move under the enlarged native portrait.
    place(LEFT,0,(_relative(model[0],-12),('h',1,-168),100,25))
    place(LEFT,1,(_relative(model[0],portrait-112),('h',1,-168),100,25))
    slots = equipment_slots(left)
    for indices, rect in zip(((8,9),(10,11),(12,13),(14,15,17,18),
                              (16,19,20),(21,22,23,24)), slots, strict=True):
        for index in indices:
            place(LEFT,index,tuple(vars(rect).values()))
    # Templates keep their native controls, below the reference backpack title.
    place(LEFT,5,(35,325,left-70,16))
    heading=310 if left==430 else 228
    place(LEFT,6,(left-54,heading,16,16));place(LEFT,7,(left-32,heading,16,16))
    special_x=equipment_slots(left)[5].x
    device=equipment_slots(left)[5]
    device_size=48 if left==430 else 32
    place(LEFT,25,(special_x+18,device.y+18,device_size,device_size))
    viewport = bag_viewport(left)
    place(0xac4bd4,None,tuple(vars(viewport).values()),cached=True)
    # The bag uses its existing scrollbar; cached row size is refreshed below.
    place(0xac4bd4,0,(viewport.width-16,0,16,viewport.height))
    # The weight bar is the final concrete child in the stock panel.
    place(LEFT,26,(18,('h',1,-146),left-36,18))
    tab_width=right//5
    for index,column,caption in ((0,0,0),(1,1,1),(3,2,2),(5,3,3),(6,4,4)):
        place(TABS,index,(column*tab_width,0,tab_width-4,64),caption=caption)
        skip=f'{prefix}_caption_{index}';_child(c,TABS,index,skip)
        c.emit('c680cc02000001 c780d0020000');c.word((tab_width-4)//2)
        c.emit('c780d402000022000000');c.label(skip)
    place(TABS,2,(2*tab_width-22,32,20,20))
    # Reuse the existing inventory grid, filters, search and counter footer.
    grid_top=54 if left==430 else 60
    place(0xac4bd8,None,(150,grid_top,right-150,('h',1,-312-grid_top)),cached=True)
    place(0xac4bd8,0,(right-166,0,16,('h',1,-312-grid_top)))
    place(TABLE,6,(0,14,144,('h',1,-212)),cached=True)
    skip=f'{prefix}_category_rows';_child(c,TABLE,6,skip)
    c.emit('c78080020000');c.word(26 if left==430 else 16);c.label(skip)
    for index in (2,3,4,5,7):
        skip=f'{prefix}_column_{index}';_child(c,TABLE,index,skip)
        c.emit('c6404900');c.label(skip)
    for index,rect in ((2,(150,3,77,18)),(3,(right-200,3,80,18)),(4,(right-120,3,120,18)),(5,(227,3,right-427,18)),
                       (7,(right-32,('h',1,-288),32,32)),(8,(0,('h',1,-254),right,56)),
                       (9,(5,('h',1,-227),22,22)),(10,((81 if left==430 else 61),('h',1,-226),22,22)),
                       (11,(120,('h',1,-282),24,24)),
                       (12,((270 if left==430 else 286),(14 if left==430 else 8),90,15)),
                       (13,((right-140 if left==430 else 220),(10 if left==430 else 26),(126 if left==430 else 196),(30 if left==430 else 24))),
                       (14,((right-190 if left==430 else 160),(18 if left==430 else 30),(50 if left==430 else 60),15)),
                       (15,(right-52,('h',1,-244),0,0)),(16,(120,14,16,16))):
        place(TABLE,index,rect)
    # Use the stock viewport functions to refresh scroll geometry from real data.
    skip=f'{prefix}_warehouse_scroll';_global(c,0xac4bd8,skip)
    c.emit('8b5038 8b483c');c.call(0xc28600);c.label(skip)
    c.emit('c783');c.word(STATE);c.word(1)


def payload(item_ids: tuple[int,...]) -> bytes:
    from .client_equipment_batch import Code
    from .client_item_icon_render import payload as item_payload
    c=Code(LAYOUT);c.emit('9c60');c.base()
    c.emit('c783');c.word(STATE);c.word(0)
    _global(c,HEADER,'done');c.emit('8b704c 85f6');c.branch('0f84','done')
    c.emit('8d93');c.word(0xa31a40-BASE);c.emit('3916');c.branch('0f85','done')
    for index in (0,1,5):
        skip=f'restore_visible_{index}';_child(c,LEFT,index,skip)
        c.emit('c6404901');c.label(skip)
    for index in (2,3,4,5,7):
        skip=f'restore_column_{index}';_child(c,TABLE,index,skip)
        c.emit('c6404901');c.label(skip)
    # STATE stays 0, so every A2 renderer and the HD item art keep stock paths.
    c.emit('83bb');c.word(MODE);c.emit('00');c.branch('0f85','done')
    c.emit('817e38b0040000');c.branch('0f8c','done')
    c.emit('817e3c20020000');c.branch('0f8c','done')
    c.emit('817e3840060000');c.branch('0f8c','compact')
    c.emit('817e3c80020000');c.branch('0f8c','full_short')
    _arrange(c,430,554,600,'full');c.branch('e9','done')
    c.label('full_short');_arrange(c,430,554,384,'full_short');c.branch('e9','done')
    c.label('compact');c.emit('817e3c80020000');c.branch('0f8c','compact_short')
    _arrange(c,330,430,600,'compact');c.branch('e9','done')
    c.label('compact_short');_arrange(c,330,430,384,'compact_short')
    c.label('done');c.emit('619dc3')
    result=bytearray(SIZE);result[:0xc000]=c.finish(0xc000)
    for address,stock in ((CONSTRUCT,0x40ec90),(RESIZE,0xc27d00)):
        wrapper=Code(address);wrapper.call(stock);wrapper.emit('9c60');wrapper.call(LAYOUT);wrapper.emit('619dc3')
        at=address-LAYOUT;result[at:at+0x100]=wrapper.finish(0x100)
    draw=Code(DRAW);draw.emit('60');draw.base()
    draw.emit('83bb');draw.word(STATE);draw.emit('01');draw.branch('0f85','stock')
    draw.emit('8b4f0c 85c9');draw.branch('0f84','stock')
    draw.emit('8b414c 3b83');draw.word(LEFT-BASE);draw.branch('0f85','stock')
    draw.emit('8b4938 894c2418 61');draw.jump(0xc2ba00)
    draw.label('stock');draw.emit('61');draw.jump(0xc2b800)
    at=DRAW-LAYOUT;result[at:at+0x200]=draw.finish(0x200)
    for index,text in enumerate(('Информация','Инвентарь','Почта','Клан','Альянс')):
        encoded=text.encode('utf-16le');at=STRINGS-REGION+index*0x80
        raw=struct.pack('<I',len(encoded))+encoded+b'\0\0';result[at:at+len(raw)]=raw
    result[SIGNATURE_OFFSET:SIGNATURE_OFFSET+len(SIGNATURE)]=SIGNATURE
    show = Code(SHOW)
    show.emit('55 89e5 50')
    show.call(SHOW_TRAMPOLINE)
    show.emit('9c60 8b45fc')
    show.call(MAIL)
    show.emit('8b45fc')
    show.call(LAYOUT+0x3e800)
    show.emit('619d 89ec5dc3')
    result[0xe000:0xe100] = show.finish(0x100)
    trampoline = Code(SHOW_TRAMPOLINE)
    trampoline.emit('558bec51535657')
    trampoline.jump(0xa43a5b)
    result[0xe100:0xe200] = trampoline.finish(0x100)
    result[0xe200:0xfe00] = _mail_payload().ljust(0x1c00, b'\0')
    name = 'window_mail_packages'.encode('utf-16le') + b'\0\0'
    result[0xd300:0xd300+len(name)] = name
    item_art=item_payload(REGION+0x10000,STATE,item_ids)
    result[0x10000:0x10000+len(item_art)]=item_art
    from .client_barracks_skin import payload as skin_payload
    skin = skin_payload(REGION+0x20000,STATE)
    result[0x20000:0x20000+len(skin)] = skin
    from .client_barracks_cards import payload as cards_payload
    cards = cards_payload(REGION+0x30000,STATE)
    result[0x30000:0x30000+len(cards)] = cards
    from .client_barracks_bag import payload as bag_payload
    bag = bag_payload(REGION+0x34000, STATE)
    result[0x34000:0x34000+len(bag)] = bag
    from .client_barracks_navigation import payload as navigation_payload
    navigation = navigation_payload(REGION+0x38000, STATE)
    result[0x38000:0x38000+len(navigation)] = navigation
    from .client_barracks_social import payload as social_payload
    result[0x3e800:0x40000] = social_payload(REGION+0x3e800, STATE)
    return bytes(result)


def _mail_payload() -> bytes:
    """Fit the existing inbox and outgoing form beside the barracks actor."""
    from .client_equipment_batch import Code

    c = Code(MAIL)
    c.emit('9c60 89c7')
    c.base()
    c.emit('83bb'); c.word(STATE); c.emit('01')
    c.branch('0f85', 'done')
    _global(c, HEADER, 'done')
    c.emit('8b704c 807e4900'); c.branch('0f84', 'done')
    c.emit('8b4768 8d93'); c.word(REGION+0xd300)
    c.emit('b914000000'); c.call(0xc2be00)
    c.emit('85c0'); c.branch('0f84', 'done')
    c.emit('817e3840060000'); c.branch('0f8c', 'compact')
    widths = (554, 430)
    for column, width in enumerate(widths):
        if column: c.label('compact')
        prefix = f'mail_{width}'
        c.emit('89f8')
        inset_x, inset_y = (38, 6) if width == 554 else (0, 0)
        _fields(c, (('w',1,-width-12+inset_x),186+inset_y,
                    width,('h',1,-198)))
        c.emit('8b5630 015030 8b5634 015034')
        rectangles = {
            (1,): (width-190,0,180,25),
            (3,): (8,5,350,16),
            (4,): (8,5,350,32),
            (5,): (8,38,width-16,('h',1,-238)),
            (5,0): (0,0,width-16,('h',1,-278)),
            (5,0,0): (width-32,0,16,('h',1,-278)),
            (5,1): (0,('h',1,-270),32,32),
            (5,2): (width-50,('h',1,-270),32,32),
            (5,3): ((width-16)//2,('h',1,-256),0,0),
            (5,4): ((width-16)//2-92,('h',1,-270),32,32),
            (5,5): ((width-16)//2+60,('h',1,-270),32,32),
            (6,): (8,38,width-16,('h',1,-238)),
            (6,0): (width-240,145,220,94),
            (6,1): (20,('h',1,-360),64,64),
            (6,2): (0,0,width-16,40),
            (6,7): (100,('h',1,-370),width-120,93),
            (6,7,0): (width-136,0,16,87),
            (6,9): (0,('h',1,-266),180,25),
            (6,10): (190,('h',1,-266),12,16),
        }
        for number, (path, rect) in enumerate(rectangles.items()):
            skip = f'{prefix}_{number}'
            c.emit('89f8')
            for index in path:
                c.emit('8b502c 85d2'); c.branch('0f84',skip)
                c.emit('817a08'); c.word(index); c.branch('0f8e',skip)
                c.emit('8b5204 8b82'); c.word(index*4)
                c.emit('85c0'); c.branch('0f84',skip)
            _fields(c, rect)
            c.label(skip)
        c.branch('e9','done')
    c.label('done'); c.emit('619dc3')
    return c.finish(0x1c00)


def _presentation_edits() -> tuple[tuple[int,bytes,bytes], ...]:
    from .client_item_icon_render import edits as item_edits
    from .client_barracks_skin import edits as skin_edits
    from .client_barracks_cards import edits as cards_edits
    from .client_barracks_bag import edits as bag_edits
    from .client_barracks_navigation import edits as navigation_edits
    from .client_portrait_quality import INSTALL_ENTRY, install_code

    return (item_edits(REGION+0x10000)+skin_edits(REGION+0x20000)
            +cards_edits(REGION+0x30000)+bag_edits(REGION+0x34000)
            +navigation_edits(REGION+0x38000)
            +((INSTALL_ENTRY,install_code(),install_code(1024)),))


def patch(source: bytes, *, item_ids: tuple[int,...]) -> bytes:
    """Append the exact reviewed layout to the pinned current Silver image."""
    import pefile
    if hashlib.sha256(source).hexdigest()!=BASE_SHA:
        if _is_complete(source, item_ids):
            return source
        raise ValueError('Unknown published Silver build')
    pe=pefile.PE(data=source);last=pe.sections[-1]
    if (pe.OPTIONAL_HEADER.SizeOfImage!=ORIGINAL_SIZE or last.VirtualAddress+last.Misc_VirtualSize!=ORIGINAL_SIZE
            or last.Misc_VirtualSize!=last.SizeOfRawData or last.PointerToRawData+last.SizeOfRawData!=len(source)):
        raise ValueError('Native runtime is not safely appendable')
    result=bytearray(source)
    def redirect(site: int, before: int, after: int) -> None:
        at=pe.get_offset_from_rva(site-BASE)
        expected=b'\xe8'+struct.pack('<i',before-site-5)
        if source[at:at+5]!=expected:
            raise ValueError(f'Presentation call changed: {site:#x}')
        result[at:at+5]=b'\xe8'+struct.pack('<i',after-site-5)
    redirect(0x9af06a,0x40ec90,CONSTRUCT)
    redirect(0x8aa21f,0xc2b800,DRAW)
    # Locate the unique existing resize call by its decoded relative target.
    matches=[]
    raw=pe.get_data(0x825000,0x400)
    for offset in range(len(raw)-4):
        if raw[offset]==0xe8 and 0xc25000+offset+5+struct.unpack_from('<i',raw,offset+1)[0]==0xc27d00:
            matches.append(0xc25000+offset)
    if len(matches)!=1:
        raise ValueError('Native barracks resize chain differs')
    redirect(matches[0],0xc27d00,RESIZE)
    at = pe.get_offset_from_rva(0xa43a54-BASE)
    if source[at:at+7] != bytes.fromhex('558bec51535657'):
        raise ValueError('Native window visibility entry changed')
    result[at:at+7] = b'\xe9' + struct.pack('<i', SHOW-0xa43a54-5) + b'\x90\x90'
    for site,before,after in _presentation_edits():
        at=pe.get_offset_from_rva(site-BASE)
        if source[at:at+len(before)]!=before:
            raise ValueError(f'Native item presentation changed: {site:#x}')
        result[at:at+len(before)]=after
    for name in ('Misc_VirtualSize','SizeOfRawData'):
        struct.pack_into('<I',result,last.get_field_absolute_offset(name),getattr(last,name)+REGION-ORIGINAL_SIZE+SIZE)
    struct.pack_into('<I',result,pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),REGION+SIZE)
    result.extend(bytes(REGION-ORIGINAL_SIZE))
    result.extend(payload(item_ids))
    return bytes(result)


def _is_complete(source: bytes, item_ids: tuple[int, ...]) -> bool:
    """Recognize our exact output by recovering and hashing the pinned input."""
    import pefile

    if len(source) != BASE_FILE_SIZE + REGION - ORIGINAL_SIZE + SIZE:
        return False
    try:
        pe = pefile.PE(data=source)
    except pefile.PEFormatError:
        return False
    last = pe.sections[-1]
    original = bytearray(source[:BASE_FILE_SIZE])
    changes = list(_presentation_edits())
    changes.append((0xa43a54, bytes.fromhex('558bec51535657'),
                    b'\xe9' + struct.pack('<i', SHOW-0xa43a54-5) + b'\x90\x90'))
    calls = [(0x9af06a, 0x40ec90, CONSTRUCT), (0x8aa21f, 0xc2b800, DRAW)]
    raw = pe.get_data(0x825000, 0x400)
    matches = [0xc25000 + i for i in range(len(raw) - 4)
               if raw[i] == 0xe8 and 0xc25000 + i + 5
               + struct.unpack_from('<i', raw, i + 1)[0] == RESIZE]
    if len(matches) != 1:
        return False
    calls.append((matches[0], 0xc27d00, RESIZE))
    for site, before, after in calls:
        changes.append((site, b'\xe8' + struct.pack('<i', before - site - 5),
                        b'\xe8' + struct.pack('<i', after - site - 5)))
    for site, before, after in changes:
        at = pe.get_offset_from_rva(site - BASE)
        if source[at:at + len(after)] != after:
            return False
        original[at:at + len(before)] = before
    for name in ('Misc_VirtualSize', 'SizeOfRawData'):
        size = getattr(last, name) - (REGION - ORIGINAL_SIZE + SIZE)
        if size < 0:
            return False
        struct.pack_into('<I', original, last.get_field_absolute_offset(name), size)
    struct.pack_into('<I', original,
                     pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),
                     ORIGINAL_SIZE)
    if hashlib.sha256(original).hexdigest() != BASE_SHA:
        return False
    return patch(bytes(original), item_ids=item_ids) == source
