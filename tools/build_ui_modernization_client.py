"""Build only the reviewed .11 -> UI scale -> controls -> portrait chain.

Writes report artifacts, never an installed client, player configuration or
publication. Records byte preservation for the previous live Screen patch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_ui_scale as scale
from deploy import client_ui_scale_controls as controls
from deploy import client_portrait_quality as portrait


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build(source, ti_source, output):
    source, ti_source, output = (Path(p).absolute() for p in (source, ti_source, output))
    require(output.is_relative_to(ROOT/'reports/ui-modernization'), 'Output must remain in the report directory')
    base, ti_base = source.read_bytes(), ti_source.read_bytes()
    core = scale.patch(base)
    panel = controls.patch(core, expected_sha=sha(core))
    final = portrait.patch(panel, expected_sha=sha(panel))
    # GameStarter pins the original TI image. Portrait quality composes through
    # Silver's startup and the existing native target rebuild lifecycle.
    require(sha(ti_base) == portrait.TI_SHA, 'Original launcher-compatible TI is required')
    ti_final = ti_base
    before, after = pefile.PE(data=base), pefile.PE(data=final)
    # This payload owns hot Apply, VSync, render target Reset, rollback and chat
    # reflow. New functionality composes around it without changing a byte.
    old_screen = before.get_data(0x823000, 0x2000)
    require(after.get_data(0x823000, 0x2000) == old_screen, 'Previous Screen runtime was modified')
    require(before.FILE_HEADER.NumberOfSections == after.FILE_HEADER.NumberOfSections, 'Unexpected PE header addition')
    require(after.OPTIONAL_HEADER.SizeOfImage == portrait.SECTION_RVA+portrait.SIZE, 'Combined image layout differs')
    for section in after.sections:
        require(section.PointerToRawData+section.SizeOfRawData <= len(final), 'PE section exceeds the candidate')
    require(ti_base == ti_final, 'Launcher-pinned executable must remain byte-identical')
    require(portrait.patch(panel, expected_sha=sha(panel)) == final and scale.patch(base) == core,
            'Native transformer is not deterministic')
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (('silver.dll', final), ('ti.exe', ti_final), ('scale-core.dll', core), ('scale-panel.dll', panel)):
        (output/name).write_bytes(data)
    report = dict(result='PASS', base_sha256=sha(base), ti_base_sha256=sha(ti_base),
                  core_sha256=sha(core), controls_sha256=sha(panel),
                  candidate_sha256=sha(final), candidate_bytes=len(final),
                  ti_candidate_sha256=sha(ti_final), ti_candidate_bytes=len(ti_final),
                  prior_screen_runtime_sha256=sha(old_screen), prior_screen_runtime_byte_identical=True,
                  sections=after.FILE_HEADER.NumberOfSections, size_of_image=hex(after.OPTIONAL_HEADER.SizeOfImage),
                  changed_ti_bytes=0, launcher_pinned_ti_byte_identical=True,
                  portrait_runtime_target=[512,512], portrait_uses_native_resource_rebuild=True,
                  deterministic=True, graphical_validation=False, published=False)
    (output/'build-proof.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'reports/screen-settings/client/silver.dll')
    parser.add_argument('--ti-source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'reports/ui-modernization/client')
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.ti_source, args.output), indent=2))


if __name__ == '__main__':
    main()
