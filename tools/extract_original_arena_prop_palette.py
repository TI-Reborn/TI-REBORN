"""Decode original native prop pixels at1:1; never resize or export runtime assets."""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from inspect_original_arena_decor import BASE, THEMES, union
from build_visual_asset_catalog import decode
from verify_battle_loaded_native import exe_emulator, EXE_SHA
from verify_auth_native import DATA,STACK,STOP,put32,return_from_stub,UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX,UC_X86_REG_ESP,UC_X86_REG_EIP,UC_X86_REG_EFLAGS
from PIL import Image

OUT=ROOT/'reports/arena-surroundings-implementation/native-prop-palette'
BUILDINGS={'hangar.t','shed.t','tent.t','forest_house.t','ny_clinic.t','ny_livhouse_v01.t'}
NY_STREET=['ny_hydrant.t','ny_lamppost_dl.t','ny_lamppost_dr.t','ny_lamppost_ul.t',
    'ny_hatch.t','ny_mailbox_dl.t','ny_mailbox_ur.t','ny_canister_v01.t','ny_canister_v02.t','ny_canister_v03.t',
    'ny_trash_container_v01.t','ny_trash_container_v04.t','ny_trash_v01.t','ny_trash_v02.t',
    'ny_trashbag_pile_v01.t','ny_trashbag_v02.t','ny_trashbag_v04.t','ny_paperbox_v01b.t','ny_paperbox_v02b.t',
    'ny_newspaper_v01.t','ny_newspaper_v02.t','ny_newspaper_v03.t','ny_carjunk_v01.t','ny_carjunk_v02.t',
    'ny_carjunk_v03.t','ny_carjunk_v04.t','ny_carjunk_v05.t','ny_carjunk_v06.t','ny_whell.t',
    'ny_tree_lw_v02.t','ny_tree_rw_v03.t','ny_fence_01.t','ny_fence_03.t','ny_fence_09.t',
    'ny_fence_12.t','ny_fence_15.t','ny_fence_18.t']
INDUSTRIAL=['barrel_01.t','barrel_02.t','barrel_03.t','wood_box_01.t','wood_box_02.t','wood_box_02b.t',
    'wood_box_03.t','wood_box_column_01.t','wood_box_column_02.t','wood_box_column_03.t',
    'wood_box_pile_01.t','wood_box_pile_02.t','wood_box_pile_04.t','wood_box_pile_05.t','wood_box_pile_06.t','wood_box_pile_07.t',
    'cord_roll_01.t','cord_roll_02.t','tire_02.t','tire_05.t','tire_pile_01.t','metal_pipe_01b.t','oil_tank_01b.t',
    'cargo_army_01b.t','item_steel_box_01.t','item_steel_box_01b.t','paper_box_01b.t','paper_box_02.t',
    'paper_box_02b.t','paper_box_03.t','paper_box_03b.t','shelves_01.t','shelves_01b.t',
    'fence_sign_01a.t','fence_sign_01b.t','fence_sign_01c.t','fence_sign_02b.t']
FOREST_SMALL=['forest_bush_v1.t','forest_bush_v2.t','forest_bush_v3.t','forest_stub_v1.t',
    'forest_indoor_logs_v1.t','log_single_01.t','log_single_01b.t','village_bench_01.t','village_bench_01b.t']
FOREST_CABIN=['forest_indoor_axe_v1.t','forest_indoor_crowbar.t','forest_indoor_waterbarrel_v1.t',
    'forest_indoor_heater.t','forest_indoor_pot_v1.t','forest_indoor_shelves_p.t']
EXTRA_BY_MASTER={
    'R1':INDUSTRIAL+['foliage_bush_01.t'], 'R2':INDUSTRIAL+['planks_01d.t','wood_support_02.t'],
    'D1':FOREST_SMALL, 'D2':FOREST_SMALL, 'D3':FOREST_SMALL+FOREST_CABIN,
    'N1':NY_STREET+['ny_boxcart_v02.t','ny_bottlepack_v03.t','village_bench_01.t'],
    'N2':NY_STREET+['ny_car_v02b.t','ny_traficlight_l.t','ny_traficlight_u.t'], 'N3':NY_STREET+['village_bench_01.t'],
    'M1':INDUSTRIAL+['water_tower.t','wire_fence_01b.t','wire_fence_02a.t'],
    'M2':INDUSTRIAL+['wood_support_02b.t'], 'M3':INDUSTRIAL+['wood_support_02b.t'],
}

def sha(raw):return hashlib.sha256(raw).hexdigest()
def power2(n):return 1<<(n-1).bit_length()

class NativeUV:
    def __init__(self):
        self.u=exe_emulator();self.vertices=[DATA+0x1000+i*0x100 for i in range(4)]
        self.texture=DATA+0x2000
        put32(self.u,self.texture+4,DATA+0x3000)
        def hook(uc,address,size,user):
            if address==0x40c134:
                uc.reg_write(UC_X86_REG_EFLAGS,uc.reg_read(UC_X86_REG_EFLAGS)&~0x40)
                return_from_stub(uc)
            elif address==0x40af54:return_from_stub(uc)
        self.u.hook_add(UC_HOOK_CODE,hook)
    def crop(self,source_size,frame_size,pattern):
        w,h=source_size;fw,fh=frame_size;aw,ah=power2(w),power2(h)
        for offset,value in ((0x14,aw),(0x18,ah),(0x20,w),(0x1c,h)):put32(self.u,self.texture+offset,value)
        sp=STACK+0x8000
        self.u.mem_write(sp,struct.pack('<9I',STOP,0,fh,fw,pattern,0,0,self.texture,self.vertices[3]))
        for reg,address in zip((UC_X86_REG_EAX,UC_X86_REG_EDX,UC_X86_REG_ECX),self.vertices):self.u.reg_write(reg,address)
        self.u.reg_write(UC_X86_REG_ESP,sp)
        self.u.emu_start(0x60afe4,STOP,count=10000)
        assert self.u.reg_read(UC_X86_REG_EIP)==STOP
        uv=[list(struct.unpack('<ff',self.u.mem_read(p+0x14,8))) for p in self.vertices]
        crop=[round(uv[0][0]*aw),round(uv[0][1]*ah),round(uv[2][0]*aw),round(uv[2][1]*ah)]
        expected_fw,expected_fh=fw or w,fh or h
        # Native0x407444 rounds the x87 quotient, rather than integer truncation.
        columns=round(w/expected_fw)
        assert columns>0
        expected=[pattern%columns*expected_fw,pattern//columns*expected_fh]
        expected.extend((expected[0]+expected_fw,expected[1]+expected_fh))
        assert crop==expected,(crop,expected,source_size,frame_size,pattern)
        return dict(crop=crop,uv_vertices=uv,logical_dimensions=[w,h],allocation_dimensions=[aw,ah],grid_columns=columns,
            native_reader='0x60afe4',native_uv_numeric_executed=True,half_texel=False,
            allocation_scope='Power-of-two allocation assumption for source decoding; actual GPU loader not exercised')

def category(name):
    if any(word in name for word in ('fence','wall','pipe')):return 'barrier'
    if any(word in name for word in ('barrel','box','logs','log_single','support','planks','carjunk','stub','bush',
        'cord_roll','tire','shelves','hydrant','hatch','lamppost','mailbox','canister','trash','paper','newspaper',
        'whell','axe','crowbar','heater','pot_v','bottlepack','traficlight','bench')):return 'detail'
    return 'primary'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skeleton-only',action='store_true')
    parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    inventory_path=ROOT/'reports/arena-surroundings-implementation/assets-original-inventory.json'
    inventory=json.loads(inventory_path.read_bytes());models=inventory['models'];textures=inventory['textures']
    by_basename=defaultdict(list)
    for name in textures:by_basename[Path(name).name.lower()].append(name)
    masters_names={master:list(dict.fromkeys(n.lower() for n in theme['primary']+EXTRA_BY_MASTER.get(master,[])))
                   for master,theme in THEMES.items()}
    selected=sorted({name for names in masters_names.values() for name in names})
    original_primaries={name.lower() for theme in THEMES.values() for name in theme['primary']}
    palette={};images={};native=NativeUV();warnings=[]
    for name in selected:
        model=models[name]
        if not model.get('native_parsed') or not model.get('complete_original_texture_dependencies'):
            warnings.append(dict(model=name,reason='Unsupported native record or unresolved source texture'))
            continue
        source=BASE/Path(model['path']).relative_to('base')
        assert sha(source.read_bytes())==model['sha256']
        records=[];parts=[]
        for record in model['records']:
            assert record['render_as_tile']==0,'Diamond renderer needs a separate native probe'
            paths=by_basename[record['native_texture_filename'].lower()]
            assert paths and len({textures[p]['sha256'] for p in paths})==1,'Ambiguous original texture'
            texture_path=sorted(paths)[0];texture=textures[texture_path]
            if texture_path not in images:
                raw=(BASE/Path(texture_path).relative_to('base')).read_bytes()
                assert sha(raw)==texture['sha256'];images[texture_path]=decode(raw)[0]
                assert images[texture_path].size==(texture['width'],texture['height'])
            image=images[texture_path]
            fw,fh=record['frame_width'],record['frame_height']
            proof=native.crop(image.size,(fw,fh),record['pattern_index'])
            crop=proof['crop'];cw,ch=crop[2]-crop[0],crop[3]-crop[1]
            aw,ah=proof['allocation_dimensions']
            # Decode the original pattern against a padded GPU canvas. UVs above
            # one are recorded as unresolved; do not assume its sampler mode.
            wrapped=crop[0]<0 or crop[1]<0 or crop[2]>aw or crop[3]>ah
            gpu_geometry=[fw or aw,fh or ah]
            logical_geometry=[cw,ch]
            x,y=record['world_xy'];sx,sy=record['screen_shift_xy']
            px=32*(y-x)+sx-(32 if record['static_flag'] else 0);py=16*(x+y)+sy
            entry={k:record[k] for k in ('index','world_xy','screen_shift_xy','rgb_hex','transparency','pattern_index','static_flag')}
            entry.update(texture_path=texture_path,texture_source_sha256=texture['sha256'],native_uv=proof,
                pixel_dimensions=logical_geometry,native_geometry_dimensions=gpu_geometry,
                native_geometry_matches_1to1=gpu_geometry==logical_geometry,
                screen_box=[px,py,px+cw,py+ch],requires_sampler_wrap=wrapped)
            records.append(entry)
            if wrapped:
                warnings.append(dict(model=name,record=record['index'],reason='UV outside allocated texture; sampler wrapping is not guessed'))
                continue
            padded=Image.new('RGBA',(aw,ah));padded.paste(image,(0,0));part=padded.crop(tuple(crop))
            assert record['rgb_hex']=='00ffffff' and record['transparency']==255,'Native tint/opacity needs independent verification'
            parts.append((entry,part))
        boxes=[entry['screen_box'] for entry,part in parts]
        if name not in original_primaries and any(r['requires_sampler_wrap'] for r in records):
            warnings.append(dict(model=name,reason='Additional detail omitted entirely because sampler wrapping is unresolved'))
            continue
        bbox=union(boxes);assert bbox
        x0,y0,x1,y1=bbox;combined=Image.new('RGBA',(x1-x0,y1-y0))
        # Original ground layer, then foreground wall strips, then opaque roofs.
        # Keep source order within each layer; this is a static closed-roof view.
        for entry,part in sorted(parts,key=lambda p:(p[0]['static_flag'],p[0]['index'])):
            px,py=entry['screen_box'][:2];combined.alpha_composite(part,(px-x0,py-y0))
        primary_scene=next((s for s in inventory['scenes'].values() if s['prop_count']==1 and
                           s['props'][0]['model_basename'].lower()==name),None)
        if primary_scene:
            footprint=[primary_scene['width'],primary_scene['height']]
            footprint_source=primary_scene['path']
        else:
            footprint=[max(r['world_xy'][axis] for r in model['records'])-
                       min(r['world_xy'][axis] for r in model['records'])+1 for axis in (0,1)]
            footprint_source='Original TILE anchor extrema; visual placement footprint, not collision cells'
        raster=out/'png'/(Path(name).stem+'.png')
        if not args.skeleton_only:
            raster.parent.mkdir(parents=True,exist_ok=True);combined.save(raster)
        palette[name]=dict(id=Path(name).stem,raster=raster.relative_to(ROOT).as_posix(),path_rel_root=raster.relative_to(ROOT).as_posix(),
            dimensions=list(combined.size),screen_bbox=bbox,world_footprint=footprint,world_footprint_source=footprint_source,
            source_path=model['path'],source_sha256=model['sha256'],native_version=model['version'],category=category(name),
            original_scene_references=[s['path'] for s in inventory['scenes'].values() if
                any(p['model_basename'].lower()==name for p in s['props'])],
            pixel_scale=[1,1],rescaling=False,records=records,closed_roof_view=True,
            assembly_scope='Exact decoded crop pixels at1:1; ground->foreground->roof source order. Does not reproduce dynamic roof fade or GPU sampling.',
            all_native_geometry_matches_1to1=all(r['native_geometry_matches_1to1'] for r in records),
            omitted_sampler_records=[r['index'] for r in records if r['requires_sampler_wrap']],
            exported=not args.skeleton_only,usable=not args.skeleton_only,
            extraction_complete_without_sampler_guess=not any(r['requires_sampler_wrap'] for r in records),
            native_gpu_render_reproduced=False,
            rgba_pixels_sha256=sha(combined.tobytes()),
            raster_sha256=sha(raster.read_bytes()) if not args.skeleton_only else None)
    masters={master:[palette[name] for name in names if name in palette] for master,names in masters_names.items()}
    report=dict(schema='arena-original-prop-palette/v1',passed=not args.skeleton_only,masters=masters,models=palette,
        inventory_sha256=sha(inventory_path.read_bytes()),native_exe_sha256=EXE_SHA,manifest=inventory['manifest'],
        warnings=warnings,model_count=len(palette),projection='X=32*(worldY-worldX)+shiftX-(32 if foreground/roof else0);Y=16*(worldX+worldY)+shiftY',
        limitations=['No resize, flip, tint, artwork generation, runtime export, deployment, clients or accounts.',
            'AJPG_EX decode follows native averageRGB alpha; native numeric UV executes with texture/file endpoints stubbed.',
            'Zero frame axes may have a larger native allocated screen rectangle than1:1 logical crop; this discrepancy is explicitly recorded.',
            'UVs outside allocation are omitted rather than inventing a wrapping sampler. R3 canal has no original geometry.'])
    path=out/'palette.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],models=len(palette),warnings=len(warnings),report=str(path))))

if __name__=='__main__':main()
