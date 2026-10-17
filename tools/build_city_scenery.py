"""Import authored city fragments with cached-image native TILE door decoding."""
from pathlib import Path
import sys,json,hashlib,struct
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import read_tile_doors_extended_native as native
import verify_battle_loaded_native as exe
from tools import import_arena_fragments as importer
from functools import lru_cache

ADDITIONS={
 'denver':{'houses':['forest_house01_v1.s','forest_house01_v2.s','forest_house01_v3.s','forest_house02_v1.s'],
 'cover':['forest_tree_v04.s','forest_tree_v05.s'],
 'scenery':['forest_tree_box_v1.s','forest_tree_box_v2.s','forest_tree_box_v3.s']},
 'new_york':{'houses':['ny_parking_v01.s','ny_parking_v02.s','ny_residential_area_v05.s','ny_residential_area_v10.s'],
 'cover':['ny_streetjunk_v01.s','ny_streetjunk_v02.s','ny_streetjunk_v03.s','ny_streetjunk_v04.s']},
 'military_zone':{'posts':['outpost_v1.s','outpost_v2.s','outpost_v3.s','outpost_v4.s','outpost_v5.s','outpost_v6.s','outpost_v7.s'],
 'cover':['mappack2/container_set_01.s']}}


def main():
    raw=exe.BINARY.with_name('ti.exe').read_bytes();assert hashlib.sha256(raw).hexdigest()==exe.EXE_SHA
    mapped=exe.pefile.PE(data=raw).get_memory_mapped_image()
    def emulator():
        u=exe.Uc(exe.UC_ARCH_X86,exe.UC_MODE_32)
        for address,size in ((0,4096),(0x400000,(len(mapped)+4095)&~4095),(exe.DATA,65536),(exe.STACK,65536)):u.mem_map(address,size)
        u.mem_write(0x400000,mapped);exe.put32(u,exe.STACK+0x8000,exe.STOP);u.reg_write(exe.UC_X86_REG_ESP,exe.STACK+0x8000)
        return u
    native.exe_emulator=emulator
    paths={p.name.lower():p for p in (importer.BASE/'setting').rglob('*.t')};proof={}
    @lru_cache(maxsize=None)
    def doors(name):
        p=paths[name.lower()];raw=p.read_bytes();h=hashlib.sha256(raw).hexdigest()
        assert raw[:8]==b'TI TILE\0'
        records=[] if raw[10]==0 else native.read_doors(p)
        proof[name]=dict(sha256=h,version=raw[10],doors=records)
        return records,h
    importer.model_doors=doors
    profiles=json.loads((ROOT/'config/battle_map_profiles.json').read_text())
    fragments=json.loads((ROOT/'config/arena_fragments.json').read_text());before=set(fragments)
    for city,pools in ADDITIONS.items():
        for category,names in pools.items():
            for name in names:
                f=importer.read_fragment(importer.BASE/'maps'/name)
                f['doors']=sorted(map(list,{tuple(d) for d in f['doors']}))
                fragments[name]=f
                pool=profiles['profiles'][city]['pools'].setdefault(category,[])
                if name not in pool:pool.append(name)
    # Bigger authored houses need room for paths. Small tree groups use a
    # separate sparse category rather than replacing every single tree.
    denver=profiles['profiles']['denver']
    denver['variants'][0]['counts']['cover']=[6,9]
    denver['variants'][0]['counts']['scenery']=[1,2]
    (ROOT/'config/arena_fragments.json').write_text(json.dumps(fragments,indent=2)+'\n')
    (ROOT/'config/battle_map_profiles.json').write_text(json.dumps(profiles,indent=2)+'\n')
    folder=ROOT/'reports/city-scenery'
    (folder/'import-proof.json').write_text(json.dumps(dict(additions=ADDITIONS,new_fragments=sorted(set(fragments)-before),model_proof=proof),indent=2))
    print('Imported',len(proof),'native models into',sum(len(v) for p in ADDITIONS.values() for v in p.values()),'city pool entries',flush=True)


if __name__=='__main__':main()
