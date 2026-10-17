"""Invalidate native path caches at the actual completed-scene boundary.

Pinned .3 Silver only. SILVER_Game_BattleBegin is called by TI726844 after
717de0 accepts the loaded game state. The wrapper invalidates the map's wave
matrix and resets the original preview/target cache, then resumes the exact
original prologue. It neither recalculates routes nor changes UI/input, TI,
authentication, packets, assets, player state or a hosting manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile
from .client_equipment_batch import Code

ROOT=Path(__file__).resolve().parents[1]
BASE_SHA='a35961b73363d759d6229e793f6265d3efb337dd826509e8efb6104e8b7aa42b'
BASE_SIZE=8004096
IMAGE_BASE=0x400000
HOOK=0x9f580c
PROLOGUE=bytes.fromhex('558becb919000000')
RESUME=HOOK+len(PROLOGUE)
APPEND_RVA=0x85a000
APPEND_SIZE=0x200
WRAPPER=IMAGE_BASE+APPEND_RVA
HOST_MAP_POINTER=0x76e5f4
HOST_RESET=0x70d704
SIGNATURE=b'TIO-mine-scene-path-reset-v3'
ACTIVE_ROUTE=0x7850f8
FULL_ROUTE=0x785288
ROUTE_COUNT=0x76d9e0


def sha(raw):return hashlib.sha256(raw).hexdigest()


def payload():
    c=Code(WRAPPER)
    c.emit('9c60 a1');c.word(HOST_MAP_POINTER)
    c.emit('85c0');c.branch('0f84','reset')
    c.emit('8b00 85c0');c.branch('0f84','reset')
    c.emit('c6401400')
    c.label('reset')
    # TI is the exact pinned fixed-base executable; a DLL-relative CALL would
    # incorrectly relocate this host address along with Silver.
    c.emit('b8');c.word(HOST_RESET);c.emit('ffd0')
    # Repeat TI70d42c's own plain-array clear. Otherwise click706d2c can
    # consume old active records before the next periodic preview rebuild.
    # These fixed arrays hold plain native records. Bounded integer stores
    # avoid native FillChar's x87 scratch state; POPFD restores the caller DF.
    c.emit('fc 31c0') # CLD; XOR EAX,EAX
    for address,size in ((ACTIVE_ROUTE,0x190),(FULL_ROUTE,0x4c4)):
        c.emit('bf');c.word(address);c.emit('b9');c.word(size//4);c.emit('f3ab')
    c.emit('a3');c.word(ROUTE_COUNT);c.emit('619d')
    c.data.extend(PROLOGUE);c.jump(RESUME)
    code=c.finish(0x100)
    return code+(SIGNATURE+b'\0').ljust(0x100,b'\0')


def patch(raw):
    if (sha(raw),len(raw))!=(BASE_SHA,BASE_SIZE):
        raise ValueError('Mine entry patch requires the exact inspected .3 Silver')
    p=pefile.PE(data=raw)
    try:
        if (p.FILE_HEADER.Machine!=0x14c or p.OPTIONAL_HEADER.ImageBase!=IMAGE_BASE
                or len(p.sections)!=13 or p.OPTIONAL_HEADER.SizeOfImage!=APPEND_RVA
                or p.OPTIONAL_HEADER.FileAlignment!=0x200
                or p.OPTIONAL_HEADER.SectionAlignment!=0x1000):
            raise ValueError('Unexpected pinned native PE geometry')
        last=p.sections[-1]
        if (last.Name!=b'.tioscr\0' or last.VirtualAddress!=0x823000
                or last.Misc_VirtualSize!=0x37000 or last.SizeOfRawData!=0x37000
                or last.PointerToRawData!=0x76b200
                or last.VirtualAddress+last.Misc_VirtualSize!=APPEND_RVA
                or last.PointerToRawData+last.SizeOfRawData!=len(raw)
                or not last.Characteristics&0x20000000):
            raise ValueError('Existing final section is not exactly appendable')
        if p.get_data(HOOK-IMAGE_BASE,len(PROLOGUE))!=PROLOGUE:
            raise ValueError('Battle begin instruction boundary changed')
        target=next((e for e in p.DIRECTORY_ENTRY_EXPORT.symbols
                     if e.name==b'SILVER_Game_BattleBegin'),None)
        if target is None or target.address+IMAGE_BASE!=HOOK:
            raise ValueError('Scene completion export changed')
        for block in p.DIRECTORY_ENTRY_BASERELOC:
            for entry in block.entries:
                if entry.type==3 and HOOK-IMAGE_BASE<=entry.rva<RESUME-IMAGE_BASE:
                    raise ValueError('Prologue replacement overlaps a relocation')
        out=bytearray(raw)
        at=p.get_offset_from_rva(HOOK-IMAGE_BASE)
        out[at:at+len(PROLOGUE)]=b'\xe9'+struct.pack('<i',WRAPPER-HOOK-5)+b'\x90'*3
        for field in ('Misc_VirtualSize','SizeOfRawData'):
            struct.pack_into('<I',out,last.get_field_absolute_offset(field),getattr(last,field)+APPEND_SIZE)
        image_end=(APPEND_RVA+APPEND_SIZE+0xfff)&~0xfff
        struct.pack_into('<I',out,p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),image_end)
        # CheckSum is already zero in the pinned baseline; preserve it exactly.
        out.extend(payload())
        return bytes(out)
    finally:p.close()


def review(source,candidate):
    if patch(source)!=candidate:raise ValueError('Candidate differs from exact transformer')
    p=pefile.PE(data=source)
    try:
        fields=[(p.sections[-1].get_field_absolute_offset(f),4,'Map the bounded scene-entry runtime in the existing final section')
                for f in ('Misc_VirtualSize','SizeOfRawData')]
        fields.extend([(p.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'),4,'Align the mapped image after the 512-byte append'),
                       (p.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'),4,'Use the existing loader-compatible zero checksum'),
                       (p.get_offset_from_rva(HOOK-IMAGE_BASE),len(PROLOGUE),'Reset native path caches at SILVER_Game_BattleBegin then replay its exact prologue')])
        return {'changes':[{'offset':a,'size':n,'source_sha256':sha(source[a:a+n]),
                            'candidate_sha256':sha(candidate[a:a+n]),'purpose':purpose}
                           for a,n,purpose in sorted(fields)],
                'appended_size':APPEND_SIZE,'appended_sha256':sha(candidate[len(source):])}
    finally:p.close()


def metadata():
    return {'scope':'Completed mine/battle scene native path caches','source_sha256':BASE_SHA,
            'hook_va':hex(HOOK),'hook_size':len(PROLOGUE),'resume_va':hex(RESUME),
            'wrapper_rva':hex(APPEND_RVA),'appended_size':APPEND_SIZE,
            'map_pointer':'TI[[0x76e5f4]]','matrix_valid_offset':20,
            'native_reset_va':hex(HOST_RESET),'registers_and_eflags_preserved':True,
            'x87_environment_and_registers_preserved':True,
            'route_clear':'CLD; zero fixed native arrays with bounded REP STOSD',
            'active_route_bytes':400,
            'full_route_bytes':1220,'route_count_reset':hex(ROUTE_COUNT),
            'physical_mouse_and_camera_preserved':True,'existing_ui_and_auth_preserved':True,
            'ti_file_modified':False,'published':False,'real_client_validated':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'reports/mine-path-scale-20261010/baseline/silver.dll')
    parser.add_argument('--out',type=Path,default=ROOT/'reports/mine-path-entry-20261010/client')
    args=parser.parse_args()
    source=args.source.read_bytes();candidate=patch(source)
    args.out.mkdir(parents=True,exist_ok=True)
    for path,raw in ((args.out/'silver.dll',candidate),):
        if path.exists() and path.read_bytes()!=raw:raise ValueError('Preserve differing prior candidate for review')
        path.write_bytes(raw)
    report={'metadata':metadata(),'native_review':review(source,candidate),
            'candidate_sha256':sha(candidate),'candidate_size':len(candidate),
            'source_path':str(args.source),'candidate_path':str(args.out/'silver.dll')}
    (args.out/'native-review.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
