"""Reproducible original-ti.exe probes for decorative surrounding resources.

The native TILE record reader, SET loader, RenderGround, rectangle construction,
and UV calculation execute under Unicorn. File/managed-string/allocation and
graphics endpoints are explicit stubs. The current foreground proof also runs
the original cell dispatcher, attachment builder, alpha updater and UV batch.
This is not a real-client GPU/UI test. Cached-ground tests are historical only:
the original post-ground mask erases such sprites outside the playable map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

from arena_surroundings_native import (encode_scene, encode_tile, TILE_DONOR,
    TILE_DONOR_SHA256, SCENE_DONOR, SCENE_DONOR_SHA256)
from verify_auth_native import (DATA, STACK, STOP, ROOT, put32, get32,
    return_from_stub, UC_HOOK_CODE, UC_X86_REG_EAX, UC_X86_REG_ECX,
    UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EIP)
from verify_battle_loaded_native import exe_emulator, EXE_SHA
from unicorn.x86_const import UC_X86_REG_EFLAGS


def consume_tile(raw: bytes, expected_model_type: int = 0):
    u = exe_emulator()
    stream, vt, read, obj = DATA, DATA + 0x100, DATA + 0x200, DATA + 0x1000
    put32(u, stream, vt)
    put32(u, vt + 12, read)
    put32(u, 0x76e3d8, DATA + 0x300)
    put32(u, DATA + 0x300, stream)
    position = 24
    reads = []

    def hook(uc, address, size, user):
        nonlocal position
        if address == read:
            n, target = uc.reg_read(UC_X86_REG_ECX), uc.reg_read(UC_X86_REG_EDX)
            assert position + n <= len(raw), "Truncated native TILE read"
            reads.append([position, n])
            uc.mem_write(target, raw[position:position + n])
            position += n
            uc.reg_write(UC_X86_REG_EAX, n)
        elif address == 0x40cc78:
            uc.mem_write(obj, bytes(0x720))
            uc.reg_write(UC_X86_REG_EAX, obj)
        elif address == 0x67e534:
            pointer, source = DATA + 0x9000, uc.reg_read(UC_X86_REG_EAX)
            n = uc.mem_read(source, 1)[0]
            put32(uc, pointer - 4, n)
            put32(uc, pointer - 8, 2)
            uc.mem_write(pointer, bytes(uc.mem_read(source + 1, n)) + b"\0")
            put32(uc, uc.reg_read(UC_X86_REG_ECX), pointer)
        elif address == 0x40beac:
            source = uc.reg_read(UC_X86_REG_EDX)
            n = min(get32(uc, source - 4), uc.reg_read(UC_X86_REG_ECX))
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX), bytes((n,)) + bytes(uc.mem_read(source, n)))
        elif address in (0x40afb4, 0x6d7e20):
            pass
        elif address == 0x6d7eb0:
            uc.reg_write(UC_X86_REG_EAX, 1)
        else:
            return
        return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, stream)
    u.reg_write(UC_X86_REG_EDX, 0)
    u.emu_start(0x74a4b4, STOP, count=30000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP and position == len(raw)
    model = bytes(u.mem_read(obj, 0x720))
    assert model[0x2c:0x2e] == bytes((expected_model_type, 0))
    assert model[0x340:0x350] == bytes(16)
    result = {
        "file_sha256": hashlib.sha256(raw).hexdigest(), "file_bytes": len(raw),
        "native_reader": "0x74a4b4", "consumed_bytes": position,
        "record_stream_start": 24, "reads": reads,
        "world_coordinates": list(struct.unpack_from("<ii", model, 4)),
        "screen_offsets": list(struct.unpack_from("<hh", model, 0x18)),
        "frame_dimensions": list(struct.unpack_from("<HH", model, 0x24)),
        "cached_dimensions": list(struct.unpack_from("<HH", model, 0x334)),
        "static_flag": model[0x2c], "render_as_tile": model[0x2d],
        "interaction_bytes_hex": model[0x340:0x350].hex(),
    }
    return model, result


def consume_scene(raw: bytes, expected_coordinates):
    u = exe_emulator()
    resource, stream, vt, read = DATA + 0x1000, DATA + 0x2000, DATA + 0x2100, DATA + 0x2200
    scene, lst, gridroot, cols, grid = DATA + 0x3000, DATA + 0x4000, DATA + 0x5000, DATA + 0x5100, DATA + 0x5200
    pointer = DATA + 0x7000
    u.mem_write(pointer, b"test\0")
    put32(u, pointer - 4, 4)
    put32(u, pointer - 8, 0xffffffff)
    for global_address, indirect, value in (
        (0x76e0bc, DATA + 0x100, resource), (0x76e000, DATA + 0x104, scene),
        (0x76e5f4, DATA + 0x108, gridroot), (0x76e0f0, DATA + 0x10c, pointer),
        (0x76dc8c, DATA + 0x110, DATA + 0x6000)):
        put32(u, global_address, indirect)
        put32(u, indirect, value)
    put32(u, resource + 0x14, stream)
    put32(u, stream, vt)
    put32(u, vt + 12, read)
    put32(u, scene + 0xd4, lst)
    put32(u, scene + 0xd0, lst)
    put32(u, lst + 8, 0)
    put32(u, gridroot + 0xc, cols)
    put32(u, cols, grid)
    grid_before = bytes(u.mem_read(grid, 0x40))
    position, seen = 0, []

    def end(uc, pop=0):
        sp = uc.reg_read(UC_X86_REG_ESP)
        return_from_stub(uc)
        uc.reg_write(UC_X86_REG_ESP, sp + 4 + pop)

    def hook(uc, address, size, user):
        nonlocal position
        if address == read:
            n, target = uc.reg_read(UC_X86_REG_ECX), uc.reg_read(UC_X86_REG_EDX)
            assert position + n <= len(raw), "Truncated native SET read"
            uc.mem_write(target, raw[position:position + n])
            position += n
            uc.reg_write(UC_X86_REG_EAX, n)
        elif address == 0x6cd428:
            uc.reg_write(UC_X86_REG_EAX, 1)
        elif address == 0x40c134:
            uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) | 0x40)
        elif address == 0x749478:
            put32(uc, uc.reg_read(UC_X86_REG_EDX), pointer)
        elif address in (0x67e4a0, 0x67e534, 0x6b0f7c):
            put32(uc, uc.reg_read(UC_X86_REG_ECX), pointer)
        elif address == 0x40bffc:
            put32(uc, uc.reg_read(UC_X86_REG_EAX), pointer)
        elif address in (0x40b038, 0x40af54, 0x40afb4, 0x6d6e9c, 0x6cd678):
            pass
        elif address == 0x6693c4:
            end(uc, 4)
            return
        elif address == 0x6d7b3c:
            seen.append(list(struct.unpack("<ii", uc.mem_read(scene + 0xe4, 8))))
            end(uc, 4)
            return
        else:
            return
        return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, pointer)
    u.reg_write(UC_X86_REG_EDX, 0)
    u.reg_write(UC_X86_REG_ECX, 0)
    u.emu_start(0x6d24d0, STOP, count=30000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP and position == len(raw)
    assert seen == [list(p) for p in expected_coordinates]
    assert bytes(u.mem_read(grid, 0x40)) == grid_before
    return {"native_loader": "0x6d24d0", "file_bytes": len(raw), "consumed_bytes": position,
            "file_sha256": hashlib.sha256(raw).hexdigest(), "scene_origin": [0, 0],
            "cell_dimensions": [1, 1], "cell_payload_hex": raw[32:34].hex(),
            "model_signed_coordinates": seen, "grid_bytes_unchanged": True,
            "model_file_load_stub": "0x6d7b3c; only signed placement dispatch is tested"}


def initialise_texture(model: bytes):
    """Execute original post-TILE initialization and capture resource requests."""
    u = exe_emulator()
    obj, scene, texture = DATA + 0x1000, DATA + 0x3000, DATA + 0x5000
    u.mem_write(obj, model)
    put32(u, 0x76e000, DATA + 0x100)
    put32(u, DATA + 0x100, scene)
    put32(u, 0x76dc48, DATA + 0x104)
    put32(u, 0x76e168, DATA + 0x108)
    put32(u, DATA + 0x108, DATA + 0x6000)
    put32(u, texture + 0x14, 1024)
    put32(u, texture + 0x18, 1024)
    pointer_next = DATA + 0x7000
    requests = []

    def managed(value):
        nonlocal pointer_next
        pointer = pointer_next
        pointer_next += 0x400
        put32(u, pointer - 4, len(value))
        put32(u, pointer - 8, 2)
        u.mem_write(pointer, value.encode("utf-16le") + b"\0\0")
        return pointer

    def value(uc, pointer):
        return bytes(uc.mem_read(pointer, get32(uc, pointer - 4) * 2)).decode("utf-16le")

    put32(u, scene + 0xec, managed("base\\setting\\"))

    def hook(uc, address, size, user):
        if address == 0x40bf18:
            source = uc.reg_read(UC_X86_REG_EDX)
            n = uc.mem_read(source, 1)[0]
            put32(uc, uc.reg_read(UC_X86_REG_EAX), managed(bytes(uc.mem_read(source + 1, n)).decode("ascii")))
        elif address == 0x60fba8:
            requests.append({"texture_lookup": value(uc, uc.reg_read(UC_X86_REG_EDX))})
            uc.reg_write(UC_X86_REG_EAX, 0)
        elif address == 0x6b0f7c:
            root, filename = value(uc, uc.reg_read(UC_X86_REG_EAX)), value(uc, uc.reg_read(UC_X86_REG_EDX))
            requests.append({"file_lookup_root": root, "texture_basename": filename})
            put32(uc, uc.reg_read(UC_X86_REG_ECX), managed(root + "arena_surroundings\\" + filename))
        elif address == 0x4246b8:
            uc.reg_write(UC_X86_REG_EAX, 1)
        elif address == 0x6b11f4:
            requests.append({"resolved_filename": value(uc, uc.reg_read(UC_X86_REG_EAX)),
                             "registered_texture_name": value(uc, uc.reg_read(UC_X86_REG_EDX))})
            uc.reg_write(UC_X86_REG_EAX, texture)
        elif address in (0x40beac, 0x40afe4, 0x40afb4):
            pass
        else:
            return
        return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x6d7eb0, STOP, count=30000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    current = bytes(u.mem_read(obj, 0x720))
    expected_dimensions = struct.unpack_from("<HH", model, 0x24)
    assert struct.unpack_from("<HH", current, 0x334) == expected_dimensions
    assert current[0x2c:0x2e] == model[0x2c:0x2e]
    assert requests[1]["texture_basename"] == model[0x233:0x233 + model[0x232]].decode("ascii")
    return {"native_initializer": "0x6d7eb0", "requests": requests,
        "cached_dimensions_after_native_initialization": list(expected_dimensions),
        "model_type_after_native_initialization": current[0x2c],
        "fade_trigger_after_native_initialization": current[0x3a0],
        "native_word_2e_after_initialization": struct.unpack_from("<H", current, 0x2e)[0],
        "native_opacity_values": [struct.unpack_from("<I", current, off)[0] for off in (0x20, 0x394, 0x398, 0x39c)],
        "scope": "Native initialization executes; supplied SettingPath and filesystem/texture allocation are stubs."}


def render_ground(model: bytes, anchor, desired_screen_origin, expect_draw=True):
    """Run original static renderer through original XY/UV vertex construction."""
    u = exe_emulator()
    scene, lst, obj, texture = DATA + 0x1000, DATA + 0x2000, DATA + 0x3000, DATA + 0x5000
    context, backend, device, owner, vertices = DATA + 0x6000, DATA + 0x7000, DATA + 0x8000, DATA + 0x9000, DATA + 0xa000
    u.mem_write(obj, model)
    u.mem_write(obj + 4, struct.pack("<ii", *anchor))
    put32(u, scene + 0xd4, lst)
    put32(u, lst + 8, 1)
    put32(u, texture + 8, context)
    put32(u, context + 0x1d0, backend)
    put32(u, backend + 4, device)
    put32(u, backend + 8, owner)
    put32(u, owner + 0x30, vertices)
    width, height = struct.unpack_from("<HH", model, 0x334)
    for offset, value in ((0x14, width), (0x18, height), (0x1c, height), (0x20, width)):
        put32(u, texture + offset, value)
    put32(u, texture + 4, DATA + 0xb000)
    put32(u, 0x76e4e0, DATA + 0xc000)
    put32(u, 0x76e168, DATA + 0xc100)
    put32(u, DATA + 0xc100, DATA + 0xc200)
    shiftx, shifty = struct.unpack_from("<hh", model, 0x18)
    sx, sy = desired_screen_origin
    camerax = sx - 32 * (anchor[1] - anchor[0]) - shiftx
    cameray = sy - 16 * (anchor[0] + anchor[1]) - shifty
    u.mem_write(STACK + 0x8004, struct.pack("<ii", cameray, camerax))
    endpoints, calls = [], []

    def hook(uc, address, size, user):
        if address in (0x6d578c, 0x6119fc, 0x661058, 0x60afe4):
            calls.append(hex(address))
            return
        if address == 0x4b1dec:
            uc.reg_write(UC_X86_REG_EAX, obj)
        elif address == 0x40bf18:
            put32(uc, uc.reg_read(UC_X86_REG_EAX), DATA + 0xb000)
        elif address == 0x60fba8:
            uc.reg_write(UC_X86_REG_EAX, texture)
        elif address == 0x40c134:
            uc.reg_write(UC_X86_REG_EFLAGS, uc.reg_read(UC_X86_REG_EFLAGS) & ~0x40)
        elif address in (0x40af54, 0x611da4, 0x650d98):
            pass
        elif address == 0x65085c:
            quad = []
            for i in range(4):
                v = bytes(uc.mem_read(vertices + i * 28, 28))
                quad.append({"xy": list(struct.unpack_from("<ff", v, 0)),
                             "uv": list(struct.unpack_from("<ff", v, 20)),
                             "color": hex(struct.unpack_from("<I", v, 16)[0])})
            endpoints.append(quad)
        else:
            return
        return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, scene)
    u.reg_write(UC_X86_REG_EDX, 0)
    u.reg_write(UC_X86_REG_ECX, 0)
    u.emu_start(0x6d578c, STOP, count=30000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert len(endpoints) == int(expect_draw), (anchor, desired_screen_origin, calls, endpoints)
    if expect_draw:
        assert [v["xy"] for v in endpoints[0]] == [[sx, sy], [sx + width, sy], [sx + width, sy + height], [sx, sy + height]]
        assert [v["uv"] for v in endpoints[0]] == [[0, 0], [1, 0], [1, 1], [0, 1]]
        assert all(v["color"] == "0xffffffff" for v in endpoints[0])
    return {"anchor": list(anchor), "camera_offset": [camerax, cameray],
            "sprite_screen_origin": list(desired_screen_origin), "sprite_dimensions": [width, height],
            "native_calls": calls, "draw_count": len(endpoints), "quad_vertices": endpoints}


def verify_cached_ground():
    manifest_path = ROOT / "reports/arena-surroundings-concepts/source/current-client-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    donor_paths = {"base/setting/forest/ground_forest_1.t": TILE_DONOR_SHA256,
                   "base/maps/forest_tree_v01.s": SCENE_DONOR_SHA256}
    published_donors = [f for f in manifest["files"] if f["path"] in donor_paths]
    assert len(published_donors) == 2
    assert all(f["sha256"] == donor_paths[f["path"]] for f in published_donors)
    raw = encode_tile("arena_native_probe.png", 1024, 512, -1100, -900)
    model, tile = consume_tile(raw)
    texture_initialization = initialise_texture(model)
    assert tile["screen_offsets"] == [-1100, -900]
    assert tile["frame_dimensions"] == tile["cached_dimensions"] == [1024, 512]
    positions = [(-8, 0), (0, -8), (38, 0), (0, 38), (-16, -16), (57, 57)]
    scene_raw = encode_scene(("arena_native_probe.t", x, y) for x, y in positions)
    scene = consume_scene(scene_raw, positions)
    renders = [render_ground(model, p, (-200, -100)) for p in positions]
    # Sprite straddles the screen although its anchor is outside the gameplay grid.
    culling = [render_ground(model, (-8, 0), p, expected) for p, expected in (
        ((-1023, -511), True), ((-1025, 0), False), ((0, -513), False),
        ((513, 0), False), ((0, 513), False))]
    square_model, square_tile = consume_tile(encode_tile("arena_square_probe.png", 1024, 1024, 700, 1300))
    square_render = render_ground(square_model, (-12, 69), (-512, -512))
    return {
        "status": "PASS", "reproduce": "python tools/verify_arena_surroundings_native.py",
        "method": __doc__.strip(), "exe_sha256": EXE_SHA,
        "published_manifest_reference": {"path": str(manifest_path),
            "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "version": manifest["version"], "matching_donors": published_donors,
            "scope": "Saved previously inspected published manifest; this probe makes no network calls."},
        "donors": [{"path": str(TILE_DONOR), "sha256": TILE_DONOR_SHA256},
                   {"path": str(SCENE_DONOR), "sha256": SCENE_DONOR_SHA256}],
        "tile": tile, "texture_initialization": texture_initialization,
        "scene": scene, "four_sides_and_corners": renders,
        "screen_culling": culling, "square_tile": square_tile, "square_render": square_render,
        "field_offsets": {"v2_record_start": 24, "world_xy_i32": [28, 32],
            "screen_offsets_i16": [48, 50], "frame_dimensions_u16": [60, 62],
            "pattern_u8": 64, "static_flag_u8": 68, "render_as_tile_u8": 69,
            "texture_name_shortstring65": 74, "model_name_shortstring64": 139,
            "texture_filename_shortstring129": 203, "cached_dimensions_u16": [334, 336],
            "interactive_fields": [340, 356]},
        "uv_evidence": "Native 0x60afe4 computes UV; raw356..427 are BPoint records, not UV. Full image frame plus pattern0 gives UV0..1 when texture allocation matches canvas dimensions.",
        "render_bounds_evidence": "Native RenderGround0x6d578c walks scene+d4 static sprites. It projects signed world coordinates, applies signed pixel offsets, and culls only their cached screen rectangle against512px; no mapwidth/grid clamp on this path.",
        "texture_location_evidence": {"scene_field": "scene+0xec is SettingPath in RTTI0x6d330b; native0x6d8030 passes it to0x6b0f7c with model+0x232 texture_filename",
            "recursive_directory_enumeration": "Native0x6b0d34 recursively calls itself at0x6b0ea1;0x6b0f7c appends requested basename to each discovered subdirectory and checks file existence",
            "export_location": "base/setting/arena_surroundings; PNGs reside beside .t and under the same original setting tree",
            "original_standard_png_examples": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "png_magic": p.read_bytes()[:8].hex(), "ihdr_dimensions": list(struct.unpack(">II", p.read_bytes()[16:24])),
                "ihdr_bitdepth_color_type": list(p.read_bytes()[24:26])}
                for p in (TILE_DONOR.parents[1] / "environment/flare_v01.png", TILE_DONOR.parents[1] / "military/tent_big_01.png")]},
        "limitations": ["No real game client, GPU, PNG decoding, remote server or UI validation.",
            "Texture lookup/allocation/file/string endpoints are stubbed; native numeric parsing, scene coordinate addition, XY quad construction and UV arithmetic execute.",
            "Scene model-file dispatch is stubbed; TILE parsing is verified independently. All inserted models must retain native+2c=0 to avoid interactive grid attachment.",
            "Exact UV0..1 requires texture allocation dimensions to match source canvas; use1024 or other power-of-two padded patches.",
            "Render backend half-texel correction flag is0 in this probe; a real backend may apply its usual half-texel UV shift."]}


def _foreground_proof(script_name, report_name):
    folder = ROOT / "reports/arena-surroundings-implementation"
    script, report = folder / script_name, folder / report_name
    process = subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True)
    if process.returncode:
        raise AssertionError(process.stdout + process.stderr)
    content = json.loads(report.read_text(encoding="utf-8"))
    assert content.get("exe_sha256", content.get("ti_exe_sha256")) == EXE_SHA
    return content, {"path": str(report.relative_to(ROOT)),
                     "sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
                     "script": str(script.relative_to(ROOT)),
                     "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                     "passed": True}


def verify():
    legacy = verify_cached_ground()
    model, tile = consume_tile(encode_tile("arena_native_probe.png", 1024, 1024, -700, 600, render_type=1), expected_model_type=1)
    initialization = initialise_texture(model)
    assert initialization["model_type_after_native_initialization"] == 1
    assert initialization["fade_trigger_after_native_initialization"] == 0
    assert initialization["native_opacity_values"] == [255] * 4
    inside = [(0, 19), (19, 0), (37, 19), (19, 37), (0, 28), (28, 0), (56, 28), (28, 56)]
    scene = consume_scene(encode_scene(("arena_native_probe.t", x, y) for x, y in inside), inside)
    attachment, attachment_reference = _foreground_proof("native-foreground-attachment-probe.py", "native-foreground-attachment-probe.json")
    renderer, renderer_reference = _foreground_proof("native-renderer-cache-probe.py", "native-renderer-cache-proof.json")
    assert attachment["passed"] and [case["map_size"] for case in attachment["cases"]] == [38, 57]
    assert all(case["anchors_inside_map"] and case["fade_graph_edges"] == 0 and case["door_container_marker_assault_flags_zero"] for case in attachment["cases"])
    rows = renderer["foreground_execution"]
    assert len(rows) == 8 and len(renderer["foreground_viewport_culling"]) == 6
    assert all(len(row["vertices"]) == 6 and row["interaction_fields_zero"] and row["game_dimensions_unchanged"] for row in rows)
    assert all(len(case["quads"]) == 4 for case in renderer["mask_execution"])
    return {
        "schema": "arena-surroundings-native/v2-foreground", "status": "PASS",
        "render_mode": "noninteractive_foreground_type1",
        "reproduce": "python tools/verify_arena_surroundings_native.py",
        "method": __doc__.strip(), "exe_sha256": EXE_SHA,
        "published_manifest_reference": legacy["published_manifest_reference"],
        "donors": legacy["donors"], "field_offsets": legacy["field_offsets"],
        "tile": tile, "scene": scene, "texture_initialization": initialization,
        "texture_location_evidence": legacy["texture_location_evidence"],
        "foreground": {"model_type": 1, "render_as_tile": 0, "interactive_fields_zero": True,
            "anchors_inside_game_grid": True, "scene_footprint": [1, 1], "scene_cells_zero": True,
            "texture_full_uv": True, "post_ground_mask": True,
            "max_models_per_anchor": max(case["max_models_per_anchor"] for case in attachment["cases"]),
            "attachment_limit": 255,
            "renderer": "0x6d626c -> 0x6d5c98 -> 0x749808 -> 0x663be0 -> 0x60afe4",
            "map_sizes": [38, 57], "sides_verified": ["x_negative", "y_negative", "x_positive", "y_positive"],
            "placement_x": "cameraX+32*(anchorY-anchorX)-32+signed_offsetX",
            "placement_y": "cameraY+16*(anchorX+anchorY)+signed_offsetY",
            "fade_trigger": 0, "fade_graph_edges": 0, "opaque_alpha_after_update": 255,
            "visible_from_ground_entry_loader": True, "visible_value": 1, "fog_cell_filter": False},
        "ground_scene_visibility": renderer["ground_scene_visibility"],
        "native_original_prop_uv_cases": renderer["native_prop_uv_cases"],
        "foreground_attachment_proof": attachment_reference,
        "foreground_renderer_proof": renderer_reference,
        "legacy_static_ground": {"superseded": True, "outside_strips_erased": True,
            "reason": "The original 0x72bb00 opaque mask runs after RenderGround at cache construction. Direct RenderGround quads alone do not establish visible surroundings.",
            "historical_parser_renderer_diagnostics": legacy},
        "limitations": ["Original numeric parsing, attachment/alpha phases, final sprite culling, XY/UV arithmetic execute in isolated Unicorn; no real client, GPU, PNG decoding, hosted service or UI validation.",
            "Managed allocation/list/file endpoints, actor/query state and GPU endpoints are explicit fixtures. Attachment and alpha probes stop before unrelated actor/particle and UI phases.",
            "Safe foreground anchors must remain inside the existing logical field; native attachment builder checks upper bounds only, making negative anchors unsafe.",
            "One cell can hold at most255 attached models. Actual caller prefilters anchor screen centers with a1024px margin; use closest inside border anchors for split sprites.",
            "Exact UV0..1 requires allocated dimensions matching padded power-of-two PNGs. The real backend may apply its ordinary half-texel correction."],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "reports/arena-surroundings-implementation/native.json")
    args = parser.parse_args()
    result = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PASS: native foreground TILE/SET, inside cell attachments, alpha, four-side XY/UV, post-ground-mask placement and screen culling")
    print(args.output)
