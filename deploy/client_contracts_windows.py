"""Native TGUIWindow/TGUIButton layout using the same classes as Wall search.

Builds a relocation plan for an owned in-process extension. No client files,
player data or network state are modified by this compiler.
"""
import json
import struct
from pathlib import Path

IMAGE_SHA='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
HEADER=0x8000
RECORDS=0x8100
STRIDE=544
COUNT=57
SIZE=0x20000
ENTRY=dict(construct=0,layout=0x400,tick=0x800,initialize=0x1000,update=0x5000)


class Code:
    def __init__(self,offset):self.offset=offset;self.raw=bytearray();self.relocations=[];self.labels={};self.fixups=[]
    def emit(self,value):self.raw.extend(bytes.fromhex(value))
    def word(self,n):self.raw.extend(struct.pack('<I',n&0xffffffff))
    def pointer(self,kind,offset,relative=False):
        self.relocations.append(dict(at=self.offset+len(self.raw),kind=kind,offset=offset,relative=relative));self.word(0)
    def alloc(self,offset):self.pointer('allocation',offset)
    def module(self,va):self.pointer('silver',va-0x400000)
    def call(self,va):self.emit('e8');self.pointer('silver',va-0x400000,True)
    def local(self,offset):self.emit('e8');self.pointer('allocation',offset,True)
    def jump(self,va):self.emit('e9');self.pointer('silver',va-0x400000,True)
    def branch(self,opcode,label):self.emit(opcode);self.fixups.append((len(self.raw),label));self.word(0)
    def label(self,name):self.labels[name]=len(self.raw)
    def finish(self):
        for at,label in self.fixups:struct.pack_into('<i',self.raw,at,self.labels[label]-at-4)
        return dict(offset=self.offset,hex=self.raw.hex(),relocations=self.relocations)


def record(index):return RECORDS+index*STRIDE
def pointer(c,opcode,index):c.emit(opcode);c.alloc(record(index))
def mov(c,offset,value):c.emit('c705');c.alloc(offset);c.word(value)
def absolute_load(c,va):c.emit('a1');c.module(va)
def geometry(c,x,y,w,h):
    for field,value in ((0x30,x),(0x34,y),(0x38,w),(0x3c,h)):
        c.emit('c780');c.word(field);c.word(value)


def widgets():
    # Native list rows and footer buttons use the same skin as Team/Wall.
    rows=[(3,'button',20,38,140,25),(4,'button',166,38,140,25)]
    rows += [(i,'button',20,80+(i-5)*34,225,27) for i in range(5,8)]
    rows += [(i,'label',265,80+(i-8)*23,495,20) for i in range(8,22)]
    rows += [(i,'button',20+(i-22)*190,470,180,27) for i in range(22,26)]
    rows += [(26,'label',20,77,740,20)]
    rows += [(i,'button',20,105+(i-27)*30,740,25) for i in range(27,31)]
    rows += [(31,'edit',20,235,215,25),(32,'button',245,235,145,25),
             (33,'button',400,235,185,25),(34,'button',595,235,165,25)]
    rows += [(i,'button',20+((i-35)%2)*370,295+((i-35)//2)*30,360,25) for i in range(35,41)]
    rows += [(41,'button',20,390,80,25),(42,'button',110,390,80,25),
             (43,'button',200,390,190,25),(44,'button',400,390,170,25),(45,'button',580,390,180,25)]
    rows += [(46,'button',20,425,170,25),(47,'button',200,425,170,25),(48,'button',380,425,170,25)]
    rows += [(49,'label',20,461,450,20),(50,'button',480,455,130,25),(51,'button',620,455,140,25),
             (52,'button',280,455,180,25),(53,'label',20,528,575,20),(54,'label',20,505,740,20),
             (55,'label',20,271,740,20),(56,'button',610,530,150,25)]
    return rows


def build_plan():
    blocks=[]
    # The existing city decoration call has five callee-cleaned arguments.
    c=Code(ENTRY['construct']);c.emit('ff742414 '*5);c.call(0x8d3604);c.emit('9c60')
    c.emit('891d');c.alloc(HEADER+24)
    for index in (0,1):
        c.emit('53 8b0d');c.module(0xac5798);c.emit('b201');absolute_load(c,0xa2ecdc);c.call(0xa4517c)
        pointer(c,'a3',index);c.emit('89c7');geometry(c,8,32,150,25)
        c.emit('8d87a0020000 ba');c.alloc(0x6000+index*32);c.call(0xa55038)
    c.local(ENTRY['layout']);c.emit('619dc21400');blocks.append(c.finish())
    # Append the two new controls to the ordinary native city service list.
    c=Code(ENTRY['layout']);c.emit('9c60 8b35');c.alloc(HEADER+24);c.emit('85f6');c.branch('0f84','done')
    c.emit('31ff');absolute_load(c,0xac5d58);c.emit('85c0');c.branch('0f84','visibility');c.emit('8b00')
    for city in (2,3,5,8):c.emit('83f8'+f'{city:02x}');c.branch('0f84','allowed')
    c.branch('e9','visibility');c.label('allowed');c.emit('bf01000000');c.label('visibility')
    for index in (0,1):pointer(c,'a1',index);c.emit('85c0');c.branch('0f84',f'skip{index}');c.emit('89fa88504988504a');c.label(f'skip{index}')
    c.emit('89f0');c.call(0xa424d4);c.emit('5031ffbd20000000');c.label('loop')
    c.emit('3b3c24');c.branch('0f8d','fitted');c.emit('89f089fa');c.call(0xa424c4);c.emit('508b15');c.module(0xa2ecdc);c.call(0x4095ac)
    c.emit('84c058');c.branch('0f84','next');c.emit('80784900');c.branch('0f84','next')
    c.emit('89683483c520');c.label('next');c.emit('47');c.branch('e9','loop')
    c.label('fitted');c.emit('83c40483c510896e3c');c.label('done');c.emit('619dc3');blocks.append(c.finish())
    # Refresh calls retain the original service refresh before our reflow.
    c=Code(0x700);c.call(0x9e3c88);c.local(ENTRY['layout']);c.emit('c3');blocks.append(c.finish())
    c=Code(ENTRY['tick']);c.emit('9c60')
    c.emit('833d');c.alloc(HEADER+24);c.emit('00');c.branch('0f84','done')
    pointer(c,'a1',2);c.emit('85c0');c.branch('0f85','existing');c.local(ENTRY['initialize'])
    c.label('existing');c.emit('833d');c.alloc(HEADER);c.emit('01');c.branch('0f85','open');c.local(ENTRY['update'])
    c.label('open');c.emit('a1');c.alloc(HEADER+8);c.emit('85c0');c.branch('0f84','done')
    c.emit('50');mov(c,HEADER+8,0);pointer(c,'a1',2);c.emit('5a83fa010f94c28b08ff11')
    # TGUIInterface.DoStep is shared by city, map and battle. Using a battle
    # tick here would leave city updates waiting indefinitely.
    c.label('done');c.emit('619d558bec5356');c.jump(0xa3f301);blocks.append(c.finish())
    # Create an independent native window on the same GUI manager as the city.
    c=Code(ENTRY['initialize']);c.emit('8b0d');c.alloc(HEADER+24);c.emit('8b8988020000b201');absolute_load(c,0xa319e8);c.call(0xa4341c)
    pointer(c,'a3',2);c.emit('89c6ba20030000');c.call(0xa43630)
    c.emit('c7463c40020000c6868c02000001c6868d02000000c686ac02000001c686a002000001')
    c.emit('89f0');c.call(0xa43748)
    for index,kind,x,y,w,h in widgets():
        if kind=='button':c.emit('56 8b0d');c.module(0xac5798);c.emit('b201');absolute_load(c,0xa2ecdc);c.call(0xa4517c)
        else:
            c.emit('89f1b201');absolute_load(c,0xa30e38 if kind=='label' else 0xa2fb7c);c.call(0xa47d78 if kind=='label' else 0xa45ab4)
        pointer(c,'a3',index);geometry(c,x,y,w,h)
        if kind=='button':
            c.emit('89c7 8d87a0020000 ba');c.alloc(0x6000+index*32);c.call(0xa55038)
    mov(c,HEADER+28,1);c.emit('c3');block=c.finish();assert len(c.raw)<0x4000;blocks.append(block)
    c=Code(ENTRY['update']);mov(c,HEADER,0)
    for index in range(COUNT):
        pointer(c,'a1',index);c.emit('85c0');c.branch('0f84',f'skip{index}')
        if index!=2:
            c.emit('8b15');c.alloc(record(index)+4);c.emit('8850498b15');c.alloc(record(index)+8);c.emit('88504a')
        if index!=31:
            c.emit('ba');c.alloc(record(index)+16);c.call(0xa42b04)
        c.label(f'skip{index}')
    c.emit('c3');blocks.append(c.finish())
    for index in range(COUNT):
        c=Code(0x6000+index*32);c.emit('9c50 a1');c.alloc(HEADER+4);c.emit('85c0');c.branch('0f85','done')
        mov(c,HEADER+4,index+1);c.label('done');c.emit('589dc3');assert len(c.raw)<=32;blocks.append(c.finish())
    hooks=[dict(rva=0x85c9ef-0x400000,before='e8106c0700',target=ENTRY['construct'],opcode=0xe8),
           dict(rva=0xa3f2fc-0x400000,before='558bec5356',target=ENTRY['tick'],opcode=0xe9)]
    for site in (0x7d2af3,0x7d307b,0x7d30b7,0x7d30df,0x8596ea,0x873e89,0x873ebb,0x9e5130):
        raw=b'\xe8'+struct.pack('<i',0x9e3c88-site-5)
        hooks.append(dict(rva=site-0x400000,before=raw.hex(),target=0x700,opcode=0xe8))
    # The original decoration call is separately guarded against the live image.
    hooks[0]['before']=(b'\xe8'+struct.pack('<i',0x8d3604-0x85c9ef-5)).hex()
    return dict(schema=1,silver_sha256=IMAGE_SHA,size=SIZE,header=HEADER,records=RECORDS,stride=STRIDE,count=COUNT,blocks=blocks,hooks=hooks)


def relocate(plan,allocation,silver):
    output=bytearray(plan['size'])
    for block in plan['blocks']:
        raw=bytes.fromhex(block['hex']);output[block['offset']:block['offset']+len(raw)]=raw
        for fix in block['relocations']:
            value=(allocation if fix['kind']=='allocation' else silver)+fix['offset']
            if fix['relative']:value-=allocation+fix['at']+4
            struct.pack_into('<I',output,fix['at'],value&0xffffffff)
    return bytes(output)


if __name__=='__main__':
    path=Path(__file__).resolve().parents[1]/'launcher/Assets/native-contracts-windows.json'
    path.write_text(json.dumps(build_plan(),indent=2)+'\n',encoding='utf-8')
