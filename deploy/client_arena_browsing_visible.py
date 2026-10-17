"""Keep actual Team/Wall browse window visible with zero selected fighters.

Original873E40 OnShow hid the list after successful browse for an empty squad.
Only categories1/4 bypass that presentation-only empty-selected branch. Original
roster scan, other modes, jailed check, create/join/admission stay unchanged.
"""
import struct,pefile
from . import client_arena_empty_roster_navigation as prior
from . import client_arena_lobby_navigation as navigation
from .client_equipment_batch import Code
from .client_server_list_status import sha,call_bytes
BASE_SHA=prior.BASE_SHA;GREEN=prior.GREEN;GRAY=prior.GRAY
GUARD=navigation.OPEN_HELPER+0x700;TEAM=navigation.OPEN_HELPER+0x800;WALL=navigation.OPEN_HELPER+0x880
SIGNATURE=b'TIO-actual-Arena-Team-Wall-empty-selected-list-visible-v5'

def guard():
    c=Code(GUARD);c.emit('84c9');c.branch('0f85','allowed')
    c.emit('9c 53');c.base()
    c.emit('83bb');c.word(0xac48a0-0x400000);c.emit('01');c.branch('0f84','restore_allow')
    c.emit('83bb');c.word(0xac48a0-0x400000);c.emit('04');c.branch('0f84','restore_allow')
    c.emit('8d83');c.word(0x873f0c-0x400000);c.emit('5b 9d');c.jump(0x873e84)
    c.label('restore_allow');c.emit('5b 9d')
    c.label('allowed');c.jump(0x873ea7)
    return c.finish(0x100)

def before_show(address,mode):
    c=Code(address);c.emit('9c60');c.base()
    c.emit('c783');c.word(0xac48a0-0x400000);c.word(mode)
    c.emit('619d');c.call(0x873ad0);c.emit('c3');return c.finish(0x80)

def payload():
    previous=prior.payload()
    return (previous[:0x600]+SIGNATURE+b'\0').ljust(0x700,b'\0')+guard()+before_show(TEAM,1)+before_show(WALL,4)+previous[0x900:]

def specifications():
    return (
        (0x873e7b,bytes.fromhex('84c97528b80c3f8700'),b'\xe9'+struct.pack('<i',GUARD-0x873e7b-5)+b'\x90'*4,'Only Team/Wall browsing bypasses original OnShow empty-selected hide; preserve others and jail gate'),
        (0x9443dd,call_bytes(0x9443dd,0x873ad0),call_bytes(0x9443dd,TEAM),'Set actual Team category before native Show so the first mode0 entry keeps its lobby visible'),
        (0x944441,call_bytes(0x944441,0x873ad0),call_bytes(0x944441,WALL),'Set actual Wall category before native Show; original browse callback/request order retained'),
    )

def relocation(p):
    found=[entry for block in p.DIRECTORY_ENTRY_BASERELOC for entry in block.entries if entry.rva==0x873e80-0x400000]
    if len(found)!=1 or found[0].type!=3:raise ValueError('Original OnShow absolute operand relocation differs')
    return found[0].struct.get_file_offset(),(found[0].type<<12)|(found[0].rva&0xfff)

def patch(source):
    previous=prior.patch(source);result=bytearray(previous[:len(source)]+payload());p=pefile.PE(data=source)
    try:
        for va,old,new,_ in specifications():
            at=p.get_offset_from_rva(va-0x400000)
            if source[at:at+len(old)]!=old:raise ValueError('Original browse path differs at '+hex(va))
            result[at:at+len(new)]=new
        offset,expected=relocation(p)
        if struct.unpack_from('<H',source,offset)[0]!=expected:raise ValueError('OnShow relocation bytes differ')
        struct.pack_into('<H',result,offset,expected&0xfff)
        assert len(result)==len(previous)
        return bytes(result)
    finally:p.close()

def review(source,candidate):
    if patch(source)!=candidate:raise ValueError('Browse visibility differs from exact source composition')
    report=prior.review(source,prior.patch(source));p=pefile.PE(data=source)
    try:
        for va,old,new,purpose in specifications():
            at=p.get_offset_from_rva(va-0x400000);report['changes'].append(dict(offset=at,size=len(old),purpose=purpose,source_sha256=sha(source[at:at+len(old)]),candidate_sha256=sha(candidate[at:at+len(old)])))
        at,_=relocation(p);report['changes'].append(dict(offset=at,size=2,purpose='Neutralize replaced original absolute OnShow-name operand relocation; keep block geometry',source_sha256=sha(source[at:at+2]),candidate_sha256=sha(candidate[at:at+2])))
        report['changes'].sort(key=lambda r:r['offset']);report['appended_sha256']=sha(candidate[len(source):]);return report
    finally:p.close()

def metadata():
    value=prior.metadata();value.update(native_revision='actual-Arena-Team-Wall-keep-visible-v5',original_OnShow='873e40',scoped_categories=[1,4],original_selected31_scan_preserved=True,other_modes_and_jail_gate_unchanged=True,Team_Wall_set_category_before_original_Show=True,original_browse_requests_unchanged=True,published=False);return value
