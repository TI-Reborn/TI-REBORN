"""Version-bound validation for B1 native foreground; v1 evidence stays intact."""
import struct
import types
from tools import verify_hosted_arena_surroundings as legacy

VERSION = '2026.10.07.2'
TINT = 0x00b1b1b1


def validate_fog_tile(blob):
    raw = legacy.native_resource(blob)
    legacy.require(len(raw) == 544 and struct.unpack_from('<II', raw, 52) == (TINT, 255),
                   'Fog release requires fixed B1 RGB tint and full native opacity')
    # Delegate all unchanged structural guards to the frozen white-T validator.
    # Only this temporary validation copy is normalized; published bytes remain B1.
    copy = bytearray(raw)
    struct.pack_into('<I', copy, 52, 0x00ffffff)
    result = legacy.validate_tile_blob(bytes(copy))
    result.update(native_tcolor_hex='00b1b1b1', native_vertex_argb='ffb1b1b1', native_alpha=255)
    return result


def published_fog_scene(host, manifest, scene, size, *, fetch=None):
    legacy.require(manifest['version'] == VERSION, 'Unexpected published fog client version')
    # Reuse the unchanged SHA/SET/PNG/alpha projection implementation with a
    # private namespace, avoiding process-global changes to the v1 validator.
    namespace = dict(legacy.published_scene.__globals__)
    namespace['validate_tile_blob'] = validate_fog_tile
    probe = types.FunctionType(legacy.published_scene.__code__, namespace,
                               'published_fog_scene_probe', legacy.published_scene.__defaults__)
    probe.__kwdefaults__ = legacy.published_scene.__kwdefaults__.copy()
    return probe(host, manifest, scene, size, fetch=fetch)
