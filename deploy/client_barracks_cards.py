"""A2 soldier cards reuse native roster data and the original input callbacks."""
from __future__ import annotations

import struct

BASE = 0x400000
SIZE = 0x4000


def _input(origin: int, layout_state: int, *, release: bool) -> bytes:
    """Select on a completed native click; preserve drag and other list input."""
    from .client_equipment_batch import Code

    offset=0xc00 if release else 0x900
    c=Code(BASE+origin+offset)
    c.emit('55 89e5 83ec20 9c60');c.base()
    c.emit('8b44241c 8945fc 8b542414 8955f8 8b542418 8955f4')
    c.emit('c745f000000000 83bb');c.word(layout_state);c.emit('01')
    c.branch('0f85','native')
    c.emit('3b83');c.word(0xac4bdc-BASE);c.branch('0f85','native')
    c.emit('837df800');c.branch('0f85','native')
    pending=origin+0x3f00
    if release:
        c.emit('3b83');c.word(pending);c.branch('0f85','native')
        c.emit('c783');c.word(pending);c.word(0)
        for field,source in ((4,'8b45f4'),(8,'8b4508')):
            c.emit(source+' 2b83');c.word(pending+field)
            c.emit('83c003 83f806');c.branch('0f87','native')
        c.emit('8b45fc 8b55f4 2b5030 83ea05 83fa00')
        c.branch('0f8c','native')
        c.emit('8955ec 8b5508 2b5034 83ea05 83fa54')
        c.branch('0f83','native')
        c.emit('8b45fc 8b8084020000 85c0')
        c.branch('0f84', 'scroll_done')
        c.emit('d980a4020000'); c.call(0x407438)
        c.emit('0145ec')
        c.label('scroll_done')
        c.emit('8b45ec 31d2 b904010000 f7f1 81fafa000000')
        c.branch('0f83','native')
        c.emit('8b55fc 8b9280020000 85d2')
        c.branch('0f84','native')
        c.emit('3b42fc');c.branch('0f83','native')
        c.emit('8b0482 85c0');c.branch('0f84','native')
        c.emit('8b4028 8945f0')
    else:
        c.emit('8983');c.word(pending)
        c.emit('8b55f4 8993');c.word(pending+4)
        c.emit('8b5508 8993');c.word(pending+8)
    c.label('native');c.emit('619d ff7508')
    c.call(0x8d1f80 if release else 0x8d1ec0)
    if release:
        c.emit('9c60');c.base()
        c.emit('837df000');c.branch('0f84','done')
        c.emit('8b83');c.word(0xac64b4-BASE)
        c.emit('85c0');c.branch('0f84','select')
        c.emit('8b00 83f820');c.branch('0f83','select')
        c.emit('8b93');c.word(0xac618c-BASE)
        c.emit('85d2');c.branch('0f84','select')
        c.emit('8b0482 85c0');c.branch('0f84','select')
        c.emit('8b4028 3b45f0');c.branch('0f84','done')
        c.label('select');c.emit('8b45fc 8b55f0');c.call(0x8d2b7c)
        c.label('done');c.emit('619d')
    c.emit('89ec5d c20400')
    return c.finish(0x400 if release else 0x300)


def number_code(address: int) -> bytes:
    """Unsigned decimal into a caller-owned immutable UTF16/font string."""
    from .client_equipment_batch import Code

    c=Code(address)
    c.emit('535657 89d6 c706b0040200 c74604ffffffff 8d7e0c 31db b90a000000')
    c.label('digit'); c.emit('31d2 f7f1 6683c230 668917 83c702 43 85c0')
    c.branch('0f85','digit')
    c.emit('66c7070000 8d045d00000000 894608 8d560c 83ef02')
    c.label('reverse'); c.emit('39fa'); c.branch('0f83','done')
    c.emit('668b02 668b0f 66890a 668907 83c202 83ef02')
    c.branch('e9','reverse')
    c.label('done'); c.emit('8d460c 5f5e5bc3')
    return c.finish(0x100)


def _draw_text(c, x: int, y: int, *, font: int=0,
               colour: int=0xffece5b8) -> None:
    from .client_barracks_skin import native_colour

    c.emit('68'); c.word(native_colour(colour))
    c.emit('6a'+f'{font:02x}'+' 6a00 8b55fc 81c2'); c.word(x)
    c.emit('8b4df8 81c1'); c.word(y)
    c.call(0x67571c)


def _number(c, origin: int, field: int, x: int, y: int, *, word=False) -> None:
    c.emit('8b7df4 '+('0fb787' if word else '8b87')); c.word(field)
    c.emit('8d95a0ffffff'); c.call(BASE+origin+0x3000)
    _draw_text(c,x,y)


def payload(origin: int, layout_state: int) -> bytes:
    from .client_equipment_batch import Code
    from .client_barracks_skin import _rectangle

    entry=Code(BASE+origin)
    entry.emit('9c60'); entry.base()
    entry.emit('83bb'); entry.word(layout_state); entry.emit('01')
    entry.branch('0f85','stock')
    entry.emit('8b442410 8b400c 3b83'); entry.word(0xac4bdc-BASE)
    entry.branch('0f85','stock')
    entry.emit('619d 8b45d0 8945e8');entry.call(BASE+origin+0x1000)
    entry.jump(0x8d19e0)
    entry.label('stock'); entry.emit('619d 8b45d0 8945e8');entry.jump(0x8d19e0)
    result=bytearray(SIZE);result[:0x100]=entry.finish(0x100)
    tail=Code(BASE+origin+0x100)
    tail.emit('9c60'); tail.base()
    tail.emit('83bb'); tail.word(layout_state); tail.emit('01')
    tail.branch('0f85','stock')
    tail.emit('8b442410 8b400c 3b83'); tail.word(0xac4bdc-BASE)
    tail.branch('0f85','stock')
    tail.emit('619d'); tail.jump(0x8d19da)
    tail.label('stock'); tail.emit('619d 8d45f4 8bd3');tail.jump(0x8d0da0)
    result[0x100:0x200]=tail.finish(0x100)
    c=Code(BASE+origin+0x1000)
    c.emit('55 89e5 81ec00010000 9c60');c.base()
    c.emit('8b442410 8b400c 89c6 8b8080020000 8b4c2404 8b3c88 897df4')
    c.emit('8b5500 8b42e4 03442400 83c005 8945fc 8b42e8 83c005 8945f8')
    _rectangle(c,(0,0,250,84),0xff3a4148)
    c.emit('8b93');c.word(0xac64b4-BASE);c.emit('85d2');c.branch('0f84','unselected')
    c.emit('8b12 83fa00');c.branch('0f8c','unselected')
    c.emit('83fa20');c.branch('0f83','unselected')
    c.emit('8b8b');c.word(0xac618c-BASE);c.emit('85c9');c.branch('0f84','unselected')
    c.emit('8b0c91 85c9');c.branch('0f84','unselected')
    c.emit('8b4928 8b7df4 3b4f28');c.branch('0f85','unselected')
    _rectangle(c,(0,0,250,84),0xffe8891f)
    c.label('unselected');_rectangle(c,(2,2,246,80),0xff20262c)
    _rectangle(c,(10,10,56,64),0xff101417)
    # Reuse the native actor silhouette (including the human/dog selector).
    c.emit('8b7df4 8b87f85f0000 85c0');c.branch('0f84','no_portrait')
    c.emit('8b4030 50 6a00 8b55fc 83c216 8b4df8 83c10a 8b83');c.word(0xac5bfc-BASE)
    c.call(0x674e38);c.branch('e9','portrait_done')
    c.label('no_portrait')
    c.label('portrait_done')
    # Compose a bounded display name locally; the authoritative actor name is
    # never truncated or written back. The stack string has immutable lifetime.
    c.emit('8b7df4 8bb7f45f0000 8dbd0cffffff c78500ffffffb0040200 c78504ffffffffffffff 31c9 85f6')
    c.branch('0f84','name_copy')
    c.emit('8b4efc 83f914');c.branch('0f86','name_copy')
    c.emit('b914000000')
    c.label('name_copy');c.emit('f366a5 c70720005b00 83c704 897dec')
    c.emit('8b7df4 8b87fc5f0000 8d95a0ffffff');c.call(BASE+origin+0x3000)
    c.emit('89c6 8b48fc d1e9 8b7dec f366a5 66c7075d00 83c702 66c7070000 8d850cffffff 29c7 89bd08ffffff')
    _draw_text(c,78,10,font=3)
    # The current native font lacks a star glyph. Draw the small rank symbol
    # from GUI primitives so it is visible with every published font atlas.
    for y,x,width in ((0,4,1),(1,4,1),(2,3,3),(3,0,9),(4,1,7),
                      (5,2,5),(6,2,5),(7,1,3),(7,5,3),(8,1,2),(8,6,2)):
        _rectangle(c,(78+x,36+y,width,1),0xffc9b77a)
    _number(c,origin,0x600c,89,36)
    _rectangle(c,(78,58,160,18),0xff14181b)
    # HP values remain native fields, never percentages inferred from pixels.
    c.emit('8b7df4 0fb78708600000 85c0');c.branch('0f84','hp_done')
    c.emit('89c1 0fb78706600000 3bc1');c.branch('0f86','hp_bounded')
    c.emit('89c8');c.label('hp_bounded');c.emit('69c0a0000000 31d2 f7f1 8945f0')
    c.emit('6a12 6a00 6852665cff 6802010000 8b4df0 8b45fc 83c04e 8b55f8 83c23a')
    c.call(0x4f2888)
    c.label('hp_done');_number(c,origin,0x6006,110,60,word=True)
    c.emit('8d83');c.word(origin-0x2000+9*0x100+12)
    _draw_text(c,153,60)
    _number(c,origin,0x6008,170,60,word=True)
    c.emit('619d 89ec5dc3')
    result[0x1000:0x3000]=c.finish(0x2000)
    result[0x3000:0x3100]=number_code(BASE+origin+0x3000)
    # Native responsive updates can replace +28C after constructor/resize.
    # Set the pitch at the point shared by drawing and callback rectangles.
    pitch=Code(BASE+origin+0x800)
    pitch.emit('9c53');pitch.base()
    pitch.emit('83bb');pitch.word(layout_state);pitch.emit('01')
    pitch.branch('0f85','stock')
    pitch.emit('3b83');pitch.word(0xac4bdc-BASE);pitch.branch('0f85','stock')
    pitch.emit('c7808c02000004010000')
    pitch.label('stock');pitch.emit('5b9d 8b808c020000');pitch.jump(0x8d0889)
    result[0x800:0x900]=pitch.finish(0x100)
    result[0x900:0xc00]=_input(origin,layout_state,release=False)
    result[0xc00:0x1000]=_input(origin,layout_state,release=True)
    # Each hit region still comes from the native collection's stock closure.
    for index,(site,before,after) in enumerate(HITS):
        code=Code(BASE+origin+0x400+index*0x80)
        code.emit('9c5053');code.base()
        code.emit('83bb');code.word(layout_state);code.emit('01');code.branch('0f85','stock')
        code.emit('8b0424 8b400c 3b83');code.word(0xac4bdc-BASE);code.branch('0f85','stock')
        code.emit('5b589d');code.emit(after);code.jump(site+len(bytes.fromhex(before)))
        code.label('stock');code.emit('5b589d');code.emit(before);code.jump(site+len(bytes.fromhex(before)))
        result[0x400+index*0x80:0x480+index*0x80]=code.finish(0x80)
    return bytes(result)


HITS = (
    (0x8d0b95,'6a4d8d85c4feffff','6a548d85c4feffff'),
    (0x8d0c1b,'6a4d8d859cfeffff','6a548d859cfeffff'),
    (0x8d0c87,'6a4d8d8554feffff','6a548d8554feffff'),
)


def edits(origin: int) -> tuple[tuple[int,bytes,bytes], ...]:
    result=[]
    for site,before,target in ((0x8d19da,'8b45d08945e8',BASE+origin),
                               (0x8d0883,'8b808c020000',BASE+origin+0x800)):
        old=bytes.fromhex(before);new=b'\xe9'+struct.pack('<i',target-site-5)
        result.append((site,old,new.ljust(len(old),b'\x90')))
    for index,(site,before,_) in enumerate(HITS):
        old=bytes.fromhex(before);new=b'\xe9'+struct.pack('<i',BASE+origin+0x400+index*0x80-site-5)
        result.append((site,old,new.ljust(len(old),b'\x90')))
    for site,before,offset in ((0x8c98d8,0x8d1ec0,0x900),(0x8c98ec,0x8d1f80,0xc00)):
        result.append((site,struct.pack('<I',before),struct.pack('<I',BASE+origin+offset)))
    return tuple(result)
