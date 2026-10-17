"""Creation-only free editor presentation, layered over the verified v1 transition."""
import hashlib
import struct
import pefile
from . import client_character_onboarding_v1 as v1
from .client_character_onboarding_v1 import RVA, FLAG

STATE=RVA+0x500
BUTTON=RVA+0x504
CAPTION=RVA+0x508
ACCEPT=RVA+0x514
SIGNATURE=b'TIO-appearance-free-v2'


def code():
    out=bytearray(v1.code());labels={};fixups=[]
    def emit(raw):out.extend(bytes.fromhex(raw))
    def word(n):out.extend(struct.pack('<I',n&0xffffffff))
    def relative(op,target):
        emit(op);word(target-(0x400000+RVA+len(out)+4))
    def branch(op,label):
        emit(op);fixups.append((len(out),label));word(0)
    def base():
        emit('e8 00000000 5b 81eb');word(RVA+len(out)-3)
    def pad(offset):
        if len(out)>offset:raise ValueError('Hook overflow')
        out.extend(bytes(offset-len(out)))
    # v1 calls this only for the server's pending-creation marker.
    pad(0x200);emit('9c60');base()
    emit('c683');word(STATE);emit('01 619d');relative('e9',0x6d0318)
    # Capture the actual native buy button and retain its localized BSTR caption.
    pad(0x240);emit('9c60');base()
    emit('8983');word(BUTTON)
    emit('8d83');word(CAPTION);relative('e8',0x40b4f0)
    emit('619d');relative('e8',0xa42b04);relative('e9',0x6d2224)
    # Called each time a selector refreshes its labels and price.
    pad(0x2c0);emit('9c60');base()
    emit('80bb');word(STATE);emit('00');branch('0f84','keep_price')
    # ECX is the price label text; substitute the empty string at creation.
    emit('c744241800000000')
    labels['keep_price']=len(out);emit('619d');relative('e8',0x6d0788)
    emit('9c60');base()
    emit('8b83');word(BUTTON);emit('85c0');branch('0f84','caption_done')
    emit('8b93');word(CAPTION)
    emit('80bb');word(STATE);emit('00');branch('0f84','set_caption')
    emit('8d93');word(ACCEPT)
    labels['set_caption']=len(out);relative('e8',0xa42b04)
    labels['caption_done']=len(out);emit('619d');relative('e9',0x6d106e)
    # Apply/cancel both close the editor. Later in-game edits use normal pricing.
    pad(0x380);emit('9c60');base()
    emit('c683');word(STATE);emit('00 619d');relative('e9',0x9e5908)
    for at,label in fixups:struct.pack_into('<i',out,at,labels[label]-(at+4))
    pad(0x510)
    text='Принять'.encode('utf-16le');word(len(text));out.extend(text+b'\0\0')
    pad(0x5d0);out.extend(SIGNATURE);pad(0x600)
    # Redirect v1's native-editor call through the mode-setting wrapper.
    old=v1.code()
    for at in range(0x60,0x1d0-4):
        if old[at]==0xe8 and 0x400000+RVA+at+5+struct.unpack_from('<i',old,at+1)[0]==0x6d0318:
            struct.pack_into('<i',out,at+1,0x200-at-5);break
    else:raise ValueError('Missing v1 editor call')
    return bytes(out)


def patch(data):
    if SIGNATURE in data:
        pe=pefile.PE(data=data);s=pe.sections[-1]
        if s.Name.rstrip(b'\0')!=b'.tiochar' or s.VirtualAddress!=RVA or data[s.PointerToRawData:s.PointerToRawData+0x600]!=code():
            raise ValueError('Unexpected free-creation patch')
        return data
    data=v1.patch(data);pe=pefile.PE(data=data);result=bytearray(data)
    s=pe.sections[-1]
    if s.PointerToRawData+s.SizeOfRawData!=len(result):raise ValueError('Unexpected PE overlay')
    result[s.PointerToRawData:]=code()
    struct.pack_into('<I',result,s.get_file_offset()+8,0x600)
    struct.pack_into('<I',result,s.get_file_offset()+16,0x600)
    for va,target,original in [(0x6d221f,0x240,0xa42b04),(0x6d1069,0x2c0,0x6d0788),(0x6d06dd,0x380,0x9e5908)]:
        offset=pe.get_offset_from_rva(va-0x400000)
        expected=b'\xe8'+struct.pack('<i',original-va-5)
        if result[offset:offset+5]!=expected:raise ValueError('Unexpected presentation hook')
        # Close is a CALL wrapper (tail-calls native); other hooks jump back explicitly.
        op=b'\xe8' if va==0x6d06dd else b'\xe9'
        result[offset:offset+5]=op+struct.pack('<i',0x400000+RVA+target-va-5)
    return bytes(result)
