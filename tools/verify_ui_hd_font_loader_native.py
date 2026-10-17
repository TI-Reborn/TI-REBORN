"""Verify real TI font filename Unicode ABI and unique native cache keys.

The actual TI7404fc→7492cc→424d7c loader path and delimiter/extension scans
execute at two ASLR bases. Unicode allocation and resource decoding/GPU
allocation are fixtures; no client is launched and no text/render QA is claimed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_ui_hd_fonts as font
from tools.verify_ui_hd_icons_native import NativeLoaderFixture, get, DATA


def terminated_text(u,address):
    for length in range(512):
        if bytes(u.mem_read(address+length*2,2))==b'\0\0':
            return bytes(u.mem_read(address,length*2)).decode('utf-16le')
    raise ValueError('Font resource filename lacks bounded terminator')


def verify(source):
    manifest=font.assets_manifest()
    ti=(ROOT/'reports/ui-modernization/baseline/ti.exe').read_bytes()
    assert font.sha(ti)==font.TI_SHA
    results=[];failures=[];executed=set()
    for base,ti_base in ((0x10000000,0x400000),(0x17000000,0x600000)):
        fixture=NativeLoaderFixture(source,ti,base,ti_base)
        for native in manifest['fonts']:
            for asset in native['density_sets']:
                fixture.asset_dimensions[asset['path'].replace('/','\\')]=(asset['width'],asset['height'])
        all_textures=[];all_keys=[]
        for role,native in enumerate(manifest['fonts']):
            for density,atlas in enumerate(native['density_sets']):
                pointer=base+get(fixture.u,base+font.TABLE+role*0x80+0x38+density*4)+12
                raw_length=get(fixture.u,pointer-4)
                text=terminated_text(fixture.u,pointer)
                expected=atlas['path'].replace('/','\\')
                row={'silver_base':hex(base),'ti_base':hex(ti_base),'font':native['font'],
                     'density':font.PERCENTS[density],'path':text,
                     'unicode_character_length':raw_length,'expected_character_length':len(expected)}
                if text!=expected or raw_length!=len(expected):
                    row['error']='Native TI7404fc filename requires UnicodeString character count; doubled WideString length is invalid.'
                    failures.append(row)
                    continue
                # Fixture.run maps Silver preferred addresses. Translate this
                # entry so execution starts in the genuinely mapped native TI.
                value=fixture.run(0x7404fc+ti_base-base,pointer,0,0,args=(DATA+0x1600,0,0))
                source_texture=fixture.cache_inputs[-1]
                key=source_texture['native_key']
                expected_key=expected.rsplit('\\',1)[-1].rsplit('.',1)[0]
                assert source_texture['source']==expected and key==expected_key
                assert value!=0 and get(fixture.u,value+12)!=0
                assert get(fixture.u,value+0x14)==atlas['width']
                assert get(fixture.u,value+0x18)==atlas['height']
                assert fixture.u.mem_read(value+0x60,1)==b'\0'
                all_textures.append(value);all_keys.append(key)
                row.update({'native_cache_key':key,'native_texture':hex(value),
                            'actual_size':[get(fixture.u,value+0x14),get(fixture.u,value+0x18)],
                            'managed_render_target_flag':0,'gpu_present':True})
                results.append(row)
        if not failures:
            assert len(set(all_textures))==len(set(all_keys))==36
            assert {'0x7404fc','0x7492cc','0x424d7c','0x42f698','0x42f7e4'}<=fixture.loader_executed
        executed.update(fixture.loader_executed)
    return {'result':'FAIL' if failures else 'PASS','case_count':len(results),'failure_count':len(failures),
            'source_sha256':font.sha(source),'assets_manifest_sha256':font.ASSET_MANIFEST_SHA,
            'immutable_ti_sha256':font.sha(ti),'native_executed':sorted(executed),
            'explicit_stubs':['Unicode substring allocation','resource decoding/allocation/cache'],
            'native_cache_key_contract':'directory and extension removed; basename retained',
            'filename_contract':'UnicodeString header -4 contains UTF16 character count; text WideString ABI is separate',
            'unique_native_cache_keys_per_aslr':36 if not failures else None,
            'unique_native_texture_objects_per_aslr':36 if not failures else None,
            'cases':results,'failures':failures,'graphical_validation':False,'published':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    result=verify(args.source.read_bytes())
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items()if k not in ('cases','failures')}))
    raise SystemExit(0 if result['result']=='PASS' else 1)
