"""Relocatable, finite F7/v2 flame adapter for the exact published Silver.

Only memory is patched by the launcher. The existing terrain effect reader,
draw callback, recon adapter and immutable DLL remain intact. Server points
are recipient filtered; the client never computes damage or obstacle rules.
"""
import json,struct
from pathlib import Path
from .client_equipment_batch import Code
from . import client_battle_items as old,client_throwable_effects as fx

SHA='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
BASE=0x20000000
READER,DRAW,ATTACK,AREA=0,0x500,0xc00,0xe00
SILVER,NEXT,ROWS=0x7000,0x7004,0x8000
SIZE=0xc000
TEXTURE,PATH,LOAD=0x7020,0xf20,0xe80
ASSET='gfx\\tio-effects\\tio-flame-jet.png'
RELOCATIONS=[]


class NativeCode(Code):
    def __init__(self,offset):super().__init__(BASE+offset)
    def base(self):
        self.emit('e800000000 5b 81eb');self.word(self.address+len(self.data)-3-BASE)
    def native(self,target,jump=False):
        self.emit('e9' if jump else 'e8');RELOCATIONS.append(dict(offset=self.address-BASE+len(self.data),target=target-0x400000));self.word(0)
    def global_value(self,rva,register='eax'):
        self.emit('8b83');self.word(SILVER)
        self.emit('8b80' if register=='eax' else '8b90');self.word(rva)
    def clock(self):
        self.emit('8b83');self.word(SILVER);self.emit('ff90');self.word(0xb79b10-0x400000)


def reader():
    c=NativeCode(READER);c.emit('3cf7');c.branch('0f85','stock')
    c.emit('83f902');c.branch('0f82','stock');c.emit('803a02');c.branch('0f85','stock')
    c.emit('9c60');c.base()
    c.emit('83f911');c.branch('0f82','done')
    c.emit('837a0100');c.branch('0f84','done')
    c.emit('0fb67209 85f6');c.branch('0f84','done')
    c.emit('83fe48');c.branch('0f87','done')
    c.emit('6bc606 83c00b 39c8');c.branch('0f85','done')
    c.emit('8d7a0a 89f1')
    c.label('validate')
    for off in (0,2):
        c.emit('0fb747'+format(off,'02x')+' 3de01f0000');c.branch('0f83','done')
    c.emit('807f0404');c.branch('0f82','done');c.emit('807f0420');c.branch('0f87','done')
    c.emit('807f0501');c.branch('0f82','done');c.emit('807f0518');c.branch('0f87','done')
    c.emit('83c706 49');c.branch('0f85','validate')
    # Identity/token deduplication includes expired slots until reused.
    c.emit('8dbb');c.word(ROWS);c.emit('b910000000')
    c.label('dedup');c.emit('8b4201 394708');c.branch('0f85','scan')
    c.emit('8b4205 39470c');c.branch('0f84','done')
    c.label('scan');c.emit('81c700020000 49');c.branch('0f85','dedup')
    c.emit('8b83');c.word(NEXT);c.emit('83e00f c1e009 8dbc03');c.word(ROWS)
    c.emit('ff83');c.word(NEXT)
    c.emit('8b4201 894708 8b4205 89470c 897710 c70701000000')
    c.emit('89f1 6bc906 8d720a 83c714 fc f3a4 81ef');c.word(20)
    # EDI was advanced by the copy. Recover the chosen row from NEXT.
    c.emit('8b83');c.word(NEXT);c.emit('48 83e00f c1e009 8dbc03');c.word(ROWS)
    # Quantize the world-space vector to eight banks of the Blender atlas.
    # Direction is derived only from server points; combat never runs here.
    c.emit('8b4f10 49 6bc906 8d540f14 0fb702 0fb74f14 29c8 0fb74a02 0fb75716 29d1')
    c.emit('89c2 c1fa1f 31d0 29d0 89ca c1fa1f 31d1 29d1')
    # EAX/ECX absolute delta, signs recovered from first/last below.
    c.emit('8d1409 39d0');c.branch('0f8f','horizontal')
    c.emit('8d1400 39d1');c.branch('0f8f','vertical')
    c.emit('8b5710 4a 6bd206 8d541714 0fb702 663b4714');c.branch('0f82','leftdiag')
    c.emit('0fb74202 663b4716');c.branch('0f82','bank7');c.emit('b808000000');c.branch('e9','bankdone')
    c.label('bank7');c.emit('b838000000');c.branch('e9','bankdone')
    c.label('leftdiag');c.emit('0fb74202 663b4716');c.branch('0f82','bank5');c.emit('b818000000');c.branch('e9','bankdone')
    c.label('bank5');c.emit('b828000000');c.branch('e9','bankdone')
    c.label('horizontal');c.emit('8b5710 4a 6bd206 8d541714 0fb702 663b4714 b800000000');c.branch('0f83','bankdone');c.emit('b820000000');c.branch('e9','bankdone')
    c.label('vertical');c.emit('8b5710 4a 6bd206 8d541714 0fb74202 663b4716 b810000000');c.branch('0f83','bankdone');c.emit('b830000000')
    c.label('bankdone');c.emit('8987f0010000')
    c.clock();c.emit('894704')
    c.label('done');c.emit('c744241c01000000 619d c3')
    c.label('stock');c.native(fx.READER,jump=True)
    return c.finish(0x500)


def draw():
    # Rain calls the terrain renderer directly, bypassing the obsolete item
    # draw trampoline. Hook the shared terrain entry and execute its displaced
    # native callback plus the remaining terrain body before our stream.
    c=NativeCode(DRAW);c.native(0x814608);c.native(fx.DRAW+5);c.emit('9c60 83ec28');c.base()
    c.global_value(0xac64a0-0x400000);c.emit('803800');c.branch('0f84','clear')
    c.native(fx.LOAD)
    c.emit('e8');c.word((LOAD-(DRAW+len(c.data)+4))&0xffffffff)
    c.clock();c.emit('890424')
    c.emit('8db3');c.word(ROWS);c.emit('bf10000000')
    c.label('slot');c.emit('833e00');c.branch('0f84','nextslot')
    c.emit('8b0424 2b4604 837e0001');c.branch('0f85','active')
    c.emit('3d88130000');c.branch('0f82','nextslot');c.branch('e9','expire')
    c.label('active');c.emit('3d14050000');c.branch('0f83','expire')
    c.emit('89442404 8b4610 89442408 8d6e14')
    c.label('point')
    c.emit('8b442404 b90a000000 31d2 f7f1 0fb65505 39d0');c.branch('0f82','nextpoint')
    c.emit('0fb74500 8944240c 0fb74502 89442410 8d44240c 8d542410');c.native(0xa896f0)
    c.global_value(0xac61b0-0x400000);c.emit('8b00 0144240c')
    c.global_value(0xac6068-0x400000);c.emit('8b00 01442410 836c241010')
    c.emit('8b44240c 89442420 8b442410 89442424')
    # Each server point is a safe motion envelope, not a cell-bound flame.
    # Independent triangular noise produces continuous small eddies. Shrinking
    # the sprite by four pixels reserves two pixels on every edge for motion.
    c.emit('0fb64504 83e0fe 83f80c');c.branch('0f82','small')
    c.emit('83e804 8944241c')
    for axis,shift,scale in (('x',4,3),('y',5,5)):
        c.emit('8b442404 c1e8'+format(shift,'02x')+' 0fb65505 6bd2'+format(scale,'02x')+' 01d0 33460c 83e00f 83f808')
        c.branch('0f82','wave'+axis)
        c.emit('ba0f000000 29c2 89d0')
        c.label('wave'+axis);c.emit('83e804 d1f8 014424'+('0c' if axis=='x' else '10'))
    c.branch('e9','size')
    c.label('small');c.emit('8944241c')
    c.label('size');c.emit('8b44241c d1e8 2944240c 29442410')
    # Finite atlas frames flow down the stream; late frames fade out.
    c.emit('8b442404 31d2 b923000000 f7f1 0fb65505 01d0 034608 33460c 03442408 83e007 0386f0010000 89442414')
    c.emit('b8e0000000 817c2404e8030000');c.branch('0f86','tint')
    c.emit('b814050000 2b442404 69c0e0000000 31d2 b92c010000 f7f1')
    c.label('tint');c.emit('c1e018 0dffffff00 89442418')
    # The wider, softer body fills gaps between the moving tongues. It is
    # centered without drift and occupies exactly the full safe envelope.
    c.emit('8b542418 81e2000000ff d1ea 81caffffff00')
    c.emit('0fb64504 83e0fe 50 50 ff74241c 52 6a00')
    c.emit('0fb64504 83e0fe d1e8 8b542434 29c2 8b4c2438 29c1 8d83');c.word(TEXTURE)
    c.native(0x4f2910)
    c.emit('8b44241c 50 50 ff74241c ff742424 6a00')
    # After five pushes, coordinates have moved by 20 bytes.
    c.emit('8b542420 8b4c2424 8d83');c.word(TEXTURE)
    c.native(0x4f2910)
    c.label('nextpoint');c.emit('83c506 ff4c2408');c.branch('0f85','point')
    c.branch('e9','nextslot')
    c.label('expire');c.emit('c70600000000')
    c.label('nextslot');c.emit('81c600020000 4f');c.branch('0f85','slot')
    c.branch('e9','done')
    c.label('clear');c.emit('8dbb');c.word(ROWS);c.emit('31c0 b900080000 fc f3ab')
    c.emit('c783');c.word(NEXT);c.word(0)
    c.label('done');c.emit('83c428 619d c3')
    return c.finish(0x700)


def attack():
    c=NativeCode(ATTACK);c.emit('9c60');c.base()
    c.emit('6681782e4401');c.branch('0f85','done')
    c.emit('8b38');c.clock();c.emit('89c2 8b8b');c.word(NEXT)
    c.emit('b810000000')
    c.label('scan');c.emit('51 83e10f c1e109 8db40b');c.word(ROWS);c.emit('59')
    c.emit('833e01');c.branch('0f85','next')
    c.emit('397e08');c.branch('0f85','next')
    c.emit('895604 c70602000000');c.branch('e9','done')
    c.label('next');c.emit('41 48');c.branch('0f85','scan')
    c.label('done');c.emit('619d')
    # Original callback still executes: for 324/Bullet it creates no projectile.
    c.emit('558bec b93a000000');c.native(0x95f968,jump=True)
    return c.finish(0x200)


def load():
    c=NativeCode(LOAD);c.emit('9c60');c.base()
    c.emit('8db3');c.word(TEXTURE);c.emit('833e00');c.branch('0f85','loaded')
    c.emit('6a00 6a00 6a02 56 8d83');c.word(PATH)
    c.emit('ba40000000 b940000000');c.native(0x4f2cb4)
    c.label('loaded');c.emit('619d c3')
    return c.finish(0x80)


def area():
    c=NativeCode(AREA);c.emit('668178084401');c.branch('0f85','stock')
    c.emit('b001 c3');c.label('stock');c.emit('558bec 53 8bd8');c.native(0xa7a94e,jump=True)
    return c.finish(0x80)


def plan():
    RELOCATIONS.clear()
    path=ASSET.encode('utf-16le');names=bytearray(0x100)
    struct.pack_into('<HHiI',names,0x14,1200,2,-1,len(ASSET));names[0x20:0x20+len(path)+2]=path+b'\0\0'
    raw=reader()+draw()+attack()+area()+load()+bytes(names)
    return dict(sha256=SHA,code=raw.hex(),relocations=list(RELOCATIONS),size=SIZE,
                silverPointer=SILVER,reader=READER,draw=DRAW,attack=ATTACK,area=AREA,
                hooks=[dict(rva=site-0x400000,before=(b'\xe9'+struct.pack('<i',target-site-5)).hex(),entry=entry)
                       for site,target,entry in ((old.READER_ENTRY,fx.READER,READER),)]
                +[dict(rva=fx.DRAW-0x400000,before=(b'\xe8'+struct.pack('<i',0x814608-fx.DRAW-5)).hex(),entry=DRAW)]
                +[dict(rva=0x95f960-0x400000,before='558becb93a000000',entry=ATTACK),
                  dict(rva=0xa7a948-0x400000,before='558bec538bd8',entry=AREA)])


def build(allocation,silver):
    value=plan();raw=bytearray.fromhex(value['code'])
    for row in value['relocations']:
        struct.pack_into('<I',raw,row['offset'],(silver+row['target']-allocation-row['offset']-4)&0xffffffff)
    return bytes(raw)


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    value=plan();(root/'launcher/Assets/native-flame-stream.json').write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(dict(code_bytes=len(bytes.fromhex(value['code'])),relocations=len(value['relocations']),hooks=len(value['hooks']))))
