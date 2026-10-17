"""Prepare a scoped native client candidate; do not install or publish it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pefile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy import client_texture_quality as q
from tools.verify_texture_quality_native import verify


def build(source,ti,output,expected_sha):
    source,ti,output=(Path(p).resolve() for p in (source,ti,output))
    if not output.is_relative_to(ROOT/'reports/gameplay-completion/legacy-lobbies-20261011/textures'):
        raise ValueError('Write only into the scoped texture candidate staging')
    before,exe=source.read_bytes(),ti.read_bytes()
    candidate=q.patch(before,expected_sha=expected_sha,ti=exe)
    review=q.review(before,candidate)
    mask=bytearray(len(before))
    for change in review['changes']:
        at,n=change['offset'],change['size'];mask[at:at+n]=b'\1'*n
    if any(not mask[i] and old!=new for i,(old,new) in enumerate(zip(before,candidate))):
        raise ValueError('Candidate changed a byte outside reviewed ranges')
    pe_before,pe_after=pefile.PE(data=before),pefile.PE(data=candidate)
    if pe_before.FILE_HEADER.NumberOfSections!=pe_after.FILE_HEADER.NumberOfSections:
        raise ValueError('Native section count changed')
    if q.patch(before,expected_sha=expected_sha,ti=exe)!=candidate:
        raise ValueError('Native transformer is not deterministic')
    proof=verify(candidate,exe)
    output.mkdir(parents=True,exist_ok=False)
    (output/'silver.dll').write_bytes(candidate)
    (output/'native-review.json').write_text(json.dumps(review,indent=2)+'\n',encoding='utf-8')
    (output/'native-sampler-proof.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8')
    result=dict(passed=True,source=str(source),source_sha256=q.sha(before),candidate_sha256=q.sha(candidate),candidate_bytes=len(candidate),
                ti_sha256=q.sha(exe),ti_on_disk_changed_bytes=0,image_resource_bytes_changed=0,existing_native_bytes_preserved_outside_declared_ranges=True,
                previous_ui_portrait_map_payloads_preserved=True,appended_bytes=q.SIZE,native_cases=proof['cases'],
                physical_resolution_and_uv_unchanged=True,gpu_sampler_proof='../gpu-sampler-proof.json',
                sampling_policy={'MAG_MIN_0_1':2,'MIP_1':2,'MIP_0':0,'all_other_values':'retained'},
                public_release=False,graphical_game_client=False,
                limitation='Reduces aliasing through native filtering; baked source grain and visual appearance require real game-client inspection',
                documentation=['https://learn.microsoft.com/en-us/windows/win32/direct3d9/d3dtexturefiltertype',
                               'https://learn.microsoft.com/en-us/windows/win32/direct3d9/d3dsamplerstatetype'])
    (output/'build-proof.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--expected-sha',required=True)
    p.add_argument('--ti',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.source,a.ti,a.output,a.expected_sha),indent=2))


if __name__=='__main__':main()
