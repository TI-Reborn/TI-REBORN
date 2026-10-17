"""Inventory original SHA-matching city sprites for composition without stretching.

Reads installed original SET/TILE resources and a live published manifest.
Native numeric TILE v2/v4/v5 readers execute in Unicorn with file/graphics
endpoints stubbed. Outputs evidence JSON only; no runtime resource export.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
BASE = Path(r'C:/Program Files (x86)/TIOnline/base')
OUT = ROOT/'reports/arena-surroundings-implementation/assets-original-inventory.json'

THEMES = {
 'R1': dict(city='reservation', theme='fence, pipes and storage', scenes=['fenced_storage_v1.s', 'refinery_v1.s'],
            primary=['steel_fence_01.t', 'steel_fence_01b.t', 'metal_pipe_01.t', 'metal_pipe_02.t', 'oil_tank_01.t']),
 'R2': dict(city='reservation', theme='hangar and shed roofs', scenes=['hangar_v1.s', 'shed_v1.s'], primary=['hangar.t', 'shed.t']),
 'R3': dict(city='reservation', theme='concrete drainage canal', scenes=['concrete_wall_v1.s'],
            primary=['concrete_wall_01.t', 'concrete_wall_01b.t', 'metal_pipe_01.t'],
            limitation='No original canal/water-surface/drain-channel asset exists. Concrete walls and pipes alone do not reproduce the approved canal.',
            fallback='Keep approved R3 master as uniformly scaled sprite with native 1:2 projection; do not invent a canal or warp UVs.'),
 'D1': dict(city='denver', theme='forest trees and fallen wood', scenes=['forest_tree_v01.s', 'forest_tree_v02.s', 'forest_tree_v03.s'],
            primary=['forest_tree_v1.t', 'forest_tree_v2.t', 'forest_tree_v3.t', 'forest_tree_v4.t', 'forest_tree_v5.t',
                     'forest_stub_v1.t', 'forest_indoor_logs_v1.t', 'log_single_01.t', 'log_single_01b.t'],
            note='Original fallen log sprites are from village/log_single_01; forest_indoor_logs is a cut-log pile, not a whole fallen tree.'),
 'D2': dict(city='denver', theme='ravine and rough rooted earth edge', scenes=['forest_pack_01/ravine_big_01.s', 'forest_pack_01/ravine_big_02.s', 'forest_pack_01/ravine_big_03.s'],
            primary=['ground_forest_ravine_v1.t', 'ground_forest_ravine_v1p.t', 'forest_bush_v1.t', 'forest_tree_v1.t'],
            note='Original ravine_v1.png contains the earth/grass edge; no separately named root sprite was found.'),
 'D3': dict(city='denver', theme='forest cabin', scenes=['forest_house01_v1.s', 'forest_house01_v2.s', 'forest_house01_v3.s'],
            primary=['forest_house.t', 'forest_bush_v1.t']),
 'N1': dict(city='new_york', theme='clinic annex and walls', scenes=['ny_clinic_v01.s', 'concrete_wall_v1.s', 'concrete_wall_v2.s'],
            primary=['ny_clinic.t', 'NY_wall_DL_v01.t', 'NY_wall_UR_v01.t']),
 'N2': dict(city='new_york', theme='road and parked ruined cars', scenes=['ny_parking_v01.s', 'ny_streetjunk_v01.s'],
            primary=['NY_road_v01.t', 'NY_road_v02.t', 'NY_car_v01.t', 'NY_car_v01b.t', 'NY_carjunk_v01.t', 'NY_car_truck_v01.t']),
 'N3': dict(city='new_york', theme='residential roofs with water tank', scenes=['ny_residential_area_v01.s'],
            primary=['ny_livhouse_v01.t', 'NY_wall_DL_v01.t', 'NY_wall_UR_v01.t', 'NY_wall_UL_v01.t', 'NY_wall_DR_v01.t'], note='Original ny_roof_v01.png already includes the roof room and cylindrical water tank.'),
 'M1': dict(city='military_zone', theme='barracks hangar row', scenes=['military_barrack.s'],
            primary=['hangar.t', 'concrete_wall_01.t', 'concrete_wall_01b.t', 'wire_fence_01.t'],
            note='military_barrack.s actually contains two hangar.t models; barracks appearance is corrugated arched hangars.'),
 'M2': dict(city='military_zone', theme='sheds and barrel storage', scenes=['shed_v1.s', 'shed_v2.s', 'shed_v3.s', 'mappack2/barrel_set_01.s'],
            primary=['shed.t', 'barrel_01.t', 'barrel_02.t', 'barrel_03.t', 'wood_box_pile_01.t']),
 'M3': dict(city='military_zone', theme='original tarp tent camp', scenes=['tent_v1.s', 'tent_v2.s'],
            primary=['tent.t', 'wood_support_02.t', 'planks_01d.t'], note='Original tent.t is sagging khaki canvas over a plank platform.'),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def union(rectangles):
    return [min(r[0] for r in rectangles), min(r[1] for r in rectangles),
            max(r[2] for r in rectangles), max(r[3] for r in rectangles)] if rectangles else None


class NativeReader:
    def __init__(self):
        from tools.verify_auth_native import (DATA, STACK, STOP, put32, get32, return_from_stub,
            UC_HOOK_CODE, UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EIP)
        from tools.verify_battle_loaded_native import exe_emulator, EXE_SHA
        self.u = exe_emulator()
        self.exe_sha = EXE_SHA
        self.raw = b''
        self.position = 0
        self.reads = []
        self.stack, self.stop, self.obj = STACK+0x8000, STOP, DATA+0x1000
        self.put32, self.eax, self.edx, self.esp, self.eip = put32, UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EIP
        self.stream, vt, read = DATA, DATA+0x100, DATA+0x200
        put32(self.u, self.stream, vt); put32(self.u, vt+12, read)
        put32(self.u, 0x76e3d8, DATA+0x300); put32(self.u, DATA+0x300, self.stream)
        def hook(uc, address, size, user):
            if address == read:
                count, target = uc.reg_read(UC_X86_REG_ECX), uc.reg_read(UC_X86_REG_EDX)
                if self.position+count > len(self.raw):
                    raise ValueError('Truncated original TILE record')
                self.reads.append(dict(file_offset=self.position, bytes=count, native_target=hex(target-self.obj)))
                uc.mem_write(target, self.raw[self.position:self.position+count])
                self.position += count
                uc.reg_write(UC_X86_REG_EAX, count)
            elif address == 0x40cc78:
                uc.mem_write(self.obj, bytes(0x720)); uc.reg_write(UC_X86_REG_EAX, self.obj)
            elif address == 0x67e534:
                pointer, source = DATA+0x9000, uc.reg_read(UC_X86_REG_EAX)
                length = uc.mem_read(source, 1)[0]
                put32(uc, pointer-4, length); put32(uc, pointer-8, 2)
                uc.mem_write(pointer, bytes(uc.mem_read(source+1, length))+b'\0')
                put32(uc, uc.reg_read(UC_X86_REG_ECX), pointer)
            elif address == 0x40beac:
                source = uc.reg_read(UC_X86_REG_EDX)
                length = min(get32(uc, source-4), uc.reg_read(UC_X86_REG_ECX))
                uc.mem_write(uc.reg_read(UC_X86_REG_EAX), bytes((length,))+bytes(uc.mem_read(source, length)))
            elif address in (0x40afb4, 0x6d7e20):
                pass
            elif address == 0x6d7eb0:
                uc.reg_write(UC_X86_REG_EAX, 1)
            else:
                return
            return_from_stub(uc)
        self.u.hook_add(UC_HOOK_CODE, hook)

    def model(self, raw):
        if raw[:8] != b'TI TILE\0':
            raise ValueError('Not an original TILE')
        count, version = struct.unpack_from('<H', raw, 8)[0], raw[10]
        result = dict(version=version, records_count=count, header_hex=raw[:24].hex())
        if version not in (2, 4, 5):
            return dict(result, native_parsed=False, limitation='Original numeric reader for this legacy version is not covered; no fields guessed')
        extra_words = struct.unpack_from('<I', raw, 12)[0]
        self.position = 24 if version == 2 else 228+4*extra_words
        self.raw, self.reads = raw, []
        start = self.position
        records = []
        reader = {2:0x74a4b4, 4:0x749b30, 5:0x74a9d8}[version]
        for index in range(count):
            begin, read_begin = self.position, len(self.reads)
            self.put32(self.u, self.stack, self.stop)
            self.u.reg_write(self.esp, self.stack); self.u.reg_write(self.eax, self.stream); self.u.reg_write(self.edx, 0)
            self.u.emu_start(reader, self.stop, count=30000)
            if self.u.reg_read(self.eip) != self.stop:
                raise ValueError('Native reader did not return')
            obj = bytes(self.u.mem_read(self.obj, 0x720))
            x,y = struct.unpack_from('<ii', obj, 4)
            sx,sy = struct.unpack_from('<hh', obj, 0x18)
            fw,fh = struct.unpack_from('<HH', obj, 0x24)
            cw,ch = struct.unpack_from('<HH', obj, 0x334)
            filename_refs = sorted(set(m.decode('ascii') for m in re.findall(rb'[A-Za-z0-9_ .()\-]+\.(?:png|tga|bmp|jpg|dds)', raw[begin:self.position], re.I)))
            logical_texture = obj[0x33:0x33+obj[0x32]].decode('ascii')
            native_filename = obj[0x233:0x233+obj[0x232]].decode('ascii')
            px,py = 32*(y-x)+sx, 16*(x+y)+sy
            records.append(dict(index=index, original_file_span=[begin,self.position], record_bytes=self.position-begin,
                world_xy=[x,y], screen_shift_xy=[sx,sy], rgb_hex=f'{struct.unpack_from("<I",obj,0x1c)[0]:08x}',
                transparency=struct.unpack_from('<I',obj,0x20)[0], frame_width=fw,frame_height=fh,
                cached_width=cw,cached_height=ch, pattern_index=obj[0x28], static_flag=obj[0x2c],render_as_tile=obj[0x2d],
                interaction_bytes_hex=obj[0x340:0x350].hex(), texture_filename_refs=filename_refs,
                native_texture_id=logical_texture, native_texture_filename=native_filename,
                cached_zero_extent=cw==0 or ch==0,
                screen_bbox_native_cached=[px,py,px+cw,py+ch], screen_bbox_native_frame=[px,py,px+fw,py+fh],
                native_read_trace=self.reads[read_begin:]))
        if self.position != len(raw):
            raise ValueError('Original TILE has unconsumed bytes')
        return dict(result, native_parsed=True, native_reader=hex(reader), record_stream_start=start,
                    consumed_bytes=self.position, records=records,
                    screen_bbox_native_cached=union([r['screen_bbox_native_cached'] for r in records]),
                    static_flags=dict(Counter(str(r['static_flag']) for r in records)),
                    render_as_tile_flags=dict(Counter(str(r['render_as_tile']) for r in records)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, help='Use a saved manifest; default fetches read-only current HTTPS manifest')
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    if args.manifest:
        manifest_raw = args.manifest.read_bytes(); source = str(args.manifest)
    else:
        source = 'https://185.184.42.88/updates/manifest.json'
        with urllib.request.urlopen(source, timeout=30) as response:
            manifest_raw = response.read(8*1024*1024)
    manifest = json.loads(manifest_raw)
    published = {record['path']:record for record in manifest['files']}
    all_models = defaultdict(list)
    all_textures = defaultdict(list)
    for path in (BASE/'setting').rglob('*'):
        if path.suffix.lower() == '.t':
            all_models[path.name.lower()].append(path)
        elif path.suffix.lower() in ('.png','.tga','.bmp','.jpg','.dds'):
            all_textures[path.name.lower()].append(path)
    def provenance(path):
        raw = path.read_bytes(); name = 'base/'+path.relative_to(BASE).as_posix()
        record = published.get(name)
        if record is None or record['sha256'] != sha(raw) or record['size'] != len(raw):
            raise ValueError('Original asset differs from published manifest: '+name)
        return dict(path=name,sha256=sha(raw),bytes=len(raw),published_match=True)
    scenes = {}
    needed = set(name.lower() for theme in THEMES.values() for name in theme['primary'])
    for name in sorted({name for theme in THEMES.values() for name in theme['scenes']}):
        path = BASE/'maps'/name; original=path.read_bytes()
        raw = zlib.decompress(original[16:]) if original[:4]==b'\x03ZIP' else original
        if raw[:8] != b'TI SET\0\x02':
            raise ValueError('Unsupported original scene')
        width,height,count = struct.unpack_from('<3H',raw,12); start=32+2*width*height
        if start+72*count > len(raw):
            raise ValueError('Truncated original scene')
        props=[]
        for index in range(count):
            record=raw[start+72*index:start+72*(index+1)]
            model=record[1:record[0]+1].decode('ascii');x,y=struct.unpack_from('<ii',record,64)
            needed.add(model.lower())
            props.append(dict(index=index,model_basename=model,world_xy=[x,y],record_file_span=[start+72*index,start+72*(index+1)]))
        scenes[name]=dict(provenance(path),version=2,width=width,height=height,prop_count=count,
            prop_record_stride=72,footprint_cell_classes=dict(Counter(str(n) for n in raw[32:start:2])),
            header_hex=raw[:32].hex(),trailing_bytes=len(raw)-(start+72*count),props=props)
    reader = NativeReader()
    models, textures, unsupported, unresolved, ambiguous = {}, {}, [], [], []
    from tools.build_visual_asset_catalog import decode
    for name in sorted(needed):
        matches=all_models[name]
        if not matches:
            raise ValueError('Absent original model: '+name)
        if len({sha(p.read_bytes()) for p in matches}) != 1:
            candidates=[dict(provenance(p), **reader.model(p.read_bytes())) for p in sorted(matches)]
            ambiguous.append(dict(model_basename=name, candidates=candidates,
                note='Different original resources share this basename; native recursive lookup order is not assumed. Use a uniquely renamed proven exact candidate for any wrapper.'))
            models[name]=dict(path=None, version=None, native_parsed=False,
                complete_original_texture_dependencies=False, basename_ambiguous=True,
                candidate_paths=[candidate['path'] for candidate in candidates])
            continue
        # Some original setting subfolders contain byte-identical aliases.
        # Record every published alias; numeric fields are identical by SHA.
        matches=sorted(matches, key=lambda p:p.as_posix())
        path=matches[0]; raw=path.read_bytes(); info=reader.model(raw)
        asset=provenance(path); asset['identical_published_aliases']=[provenance(p) for p in matches]
        asset.update(info); models[name]=asset
        if not info['native_parsed']:
            unsupported.append(asset['path'])
        refs = sorted(set(m.decode('ascii').strip() for m in re.findall(rb'[A-Za-z0-9_ .()\-]+\.(?:png|tga|bmp|jpg|dds)',raw,re.I)))
        asset['texture_dependencies'] = []
        asset['unresolved_texture_refs'] = []
        for reference in refs:
            candidates = all_textures[reference.lower()]
            if not candidates:
                asset['unresolved_texture_refs'].append(reference)
                unresolved.append(dict(model=asset['path'], texture_basename=reference,
                    matching_records=[record['index'] for record in info.get('records',[]) if
                                      record['native_texture_filename'].lower()==reference.lower()],
                    note='Missing original texture filename in historical TILE records; do not guess a replacement or blindly clone these records'))
                continue
            for texture in candidates:
                key='base/'+texture.relative_to(BASE).as_posix()
                asset['texture_dependencies'].append(key)
                if key not in textures:
                    proof=provenance(texture); image,kind=decode(texture.read_bytes())
                    proof.update(width=image.width,height=image.height,format=kind,
                                 rgba_pixels_sha256=sha(image.tobytes()),alpha_bbox=image.getchannel('A').getbbox())
                    textures[key]=proof
        asset['texture_dependencies'] = sorted(set(asset['texture_dependencies']))
        asset['complete_original_texture_dependencies'] = not asset['unresolved_texture_refs']
        if args.verbose:
            print(f"PASS {path.name}: original TILE v{info['version']}, {info['records_count']} records", flush=True)
    for scene in scenes.values():
        rectangles=[]
        for prop in scene['props']:
            model=models[prop['model_basename'].lower()]
            prop['model_path']=model['path'];prop['model_native_version']=model['version']
            if model.get('basename_ambiguous'):
                prop['model_candidate_paths']=model['candidate_paths']
            box=model.get('screen_bbox_native_cached')
            if box:
                x,y=prop['world_xy'];dx,dy=32*(y-x),16*(x+y)
                prop['screen_bbox_at_scene_anchor']=[box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy]
                rectangles.append(prop['screen_bbox_at_scene_anchor'])
        scene['screen_bbox_known_models_at_scene_origin']=union(rectangles)
    themes={}
    for identity,theme in THEMES.items():
        themes[identity]=dict(theme,primary_model_paths=[models[n.lower()]['path'] for n in theme['primary']],
            native_only_feasible=identity!='R3' and all(models[n.lower()]['complete_original_texture_dependencies'] for n in theme['primary']),
            original_scene_paths=[scenes[n]['path'] for n in theme['scenes']])
    report=dict(schema=1,passed=True,manifest=dict(source=source,version=manifest['version'],sha256=sha(manifest_raw)),
        original_root=str(BASE),native_reader_exe_sha256=reader.exe_sha,
        projection=dict(x='32*(worldY-worldX)+screenShiftX',y='16*(worldX+worldY)+screenShiftY',diamond_slope='1/2'),
        themes=themes,scenes=scenes,models=models,textures=textures,
        totals=dict(themes=len(themes),scenes=len(scenes),models=len(models),textures=len(textures),unsupported_native_models=len(unsupported)),
        unsupported_native_models=unsupported,
        unresolved_original_texture_references=unresolved,
        ambiguous_original_model_basenames=ambiguous,
        policy='Keep original texture bytes, frame/pattern/color/UV and sprite scale; change only scene placement/interaction bits in a separately proven wrapper.',
        limitations=['No runtime export, server/UI change, account creation or graphical GPU render.',
            'Screen boxes use native cached/frame fields before camera; texture lookup and render setup are stubbed.',
            'Selected .s props are72-byte records; scene trailing sections are recorded, not guessed.',
            'TILE legacy versions outside2/4/5 retain provenance but no decoded numeric fields.',
            'R3 original canal geometry unavailable; approved-master fallback remains a separate composition choice.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,version=manifest['version'],totals=report['totals'],report=str(args.output))))


if __name__=='__main__':
    main()
