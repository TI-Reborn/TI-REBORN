"""Stage and observe selected HD assets only in the existing owned QA pair.

Uses the unchanged hosted TLS/native authentication bridge and read-only
display observer. Actual window actions are performed through Computer Use.
No startup occurs on import, help, check-only, preparation or staging.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import verify_ui_scale_graphical as qa
from tools import build_ui_hd_client as builder

OUT = ROOT / 'reports/ui-hd-assets/graphical'
PACKAGE = ROOT / 'reports/ui-hd-assets/client/package.json'
BASE_SHA = builder.BASE_SHA
MANIFEST_SHA = '77c984e9346f1208c84ee739ca18ebebdd45fcdc970cd4de50f618627191738d'
CREATOR = 'tools/verify_ui_hd_assets_graphical.py'


def require(value, message):
    if not value:
        raise ValueError(message)


def candidate_bytes(candidate, expected):
    path = Path(candidate).absolute()
    require(path.is_relative_to((ROOT / 'reports/ui-hd-assets/client').absolute())
            and path.name == 'silver.dll' and not path.is_symlink(),
            'Expected selected reviewed HD candidate')
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, 'Exact HD native SHA differs')
    reconstructed, _ = builder.reconstruct()
    require(reconstructed == data, 'HD native transform changes unrelated bytes')
    builder.preserve(builder.BASE.read_bytes(), data)
    return data


def configure():
    qa.OUT = OUT
    qa.BASE_SHA = BASE_SHA
    qa.MANIFEST_SHA = MANIFEST_SHA
    qa.candidate_bytes = candidate_bytes
    # Reuse the same owned launcher/auth/cleanup. Its display observer is a
    # separate generated file containing the pinned original plus HD observation.
    qa.__file__ = str(Path(__file__).resolve())


def prepare(copies, check_only):
    roots = [qa.adapter.own_copy(qa.preparation.QA_BASE / ('game-' + c)) for c in copies]
    for root in roots:
        qa.adapter.no_running_copy(root)
    raw = qa.adapter.https(qa.preparation.ORIGIN + 'manifest.json', 8 * 1024 * 1024)
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, 'Public12 manifest moved')
    value = json.loads(raw)
    require(value['version'] == '2026.10.09.12' and len(value['files']) == 6330,
            'Expected reviewed public12 resource set')
    qa.preparation.accepted_native_hashes = lambda name: {
        BASE_SHA if name == 'silver.dll' else qa.auth.HASHES[name]}
    records = qa.preparation.validate_manifest(value)
    if check_only:
        return {'check_only': True, 'manifest_sha256': MANIFEST_SHA,
                'manifest_version': value['version'], 'started': 0, 'changed': 0}
    OUT.mkdir(parents=True, exist_ok=True)
    source = OUT / 'source'
    source.mkdir(exist_ok=True)
    qa.preparation.replace_private(source / 'manifest.json', data=raw)
    qa.preparation.static_guards = lambda root: qa.native_guards(root, BASE_SHA)
    verified = {}
    proofs = [qa.preparation.prepare_copy(root, value, records, MANIFEST_SHA, verified)
              for root in roots]
    qa.preparation.replace_private(source / 'silver.dll', source=roots[0] / 'silver.dll')
    require((source / 'silver.dll').read_bytes() == builder.BASE.read_bytes(),
            'Actual public12 Silver source differs from frozen baseline')
    report = {'creator': CREATOR, 'manifest_sha256': MANIFEST_SHA,
              'manifest_version': value['version'], 'owned_copies': [r.name for r in roots],
              'resource_count': len(records), 'proofs': proofs,
              'started': 0, 'remote_mutations': 0, 'personal_data_imported': False}
    (OUT / 'prepared.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {k: v for k, v in report.items() if k != 'proofs'}


def package_records(package):
    """Use the same strict selected package validator as the publisher."""
    from tools import publish_ui_hd_assets_remote as publisher
    return publisher.load_package(package, expected_sha='2a98b1a14ee4f294a0d6efad45dd0ef36e93e8cde89b78309b461f0fd32f1bf6')


def run_resource_guard(copy, package, candidate, expected):
    data = candidate_bytes(candidate, expected)
    _, payloads = package_records(package)
    require(payloads['silver.dll'] == data, 'Launch package and native candidate disagree')
    root = qa.adapter.own_copy(qa.preparation.QA_BASE / ('game-' + copy))
    for relative, content in payloads.items():
        require(qa.preparation.checked_target(root, relative).read_bytes() == content,
                'Owned launch resource differs: ' + relative)
    observer = Path(__file__).with_suffix('.js')
    require(qa.digest(observer) == '5c34a9aea7ab91b9534103de9406f4e462a4db46cb7c8f070517a837f51a21a9',
            'Frozen HD observer differs')
    return {'event': 'hd_launch_resources_verified', 'copy': copy,
            'candidate_sha256': expected, 'package_sha256': qa.digest(package),
            'selected_resource_count': len(payloads), 'observer_sha256': qa.digest(observer)}


def stage(copies, candidate, expected, check_only, package=PACKAGE):
    data = candidate_bytes(candidate, expected)
    # Publisher validation returns the normalized manifest and bytes bound to
    # exact selected paths. The staging API is finalized with that module.
    selected = package_records(package)
    manifest, payloads = selected
    require('silver.dll' in payloads and payloads['silver.dll'] == data,
            'Package and exact reconstructed Silver disagree')
    previous = None
    receipt_path = OUT / 'staged-candidate.json'
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        require(receipt.get('creator') == CREATOR and receipt.get('manifest_sha256') == MANIFEST_SHA,
                'Foreign HD staging receipt')
        saved = Path(receipt['verified_candidate']).absolute()
        require(saved.is_relative_to((OUT / 'source').absolute()) and saved.name == 'silver.dll'
                and not saved.is_symlink() and qa.digest(saved) == receipt['candidate_sha256'],
                'Prior owned HD native candidate is unavailable')
        previous = receipt['candidate_sha256']
    for copy in copies:
        root = qa.adapter.own_copy(qa.preparation.QA_BASE / ('game-' + copy))
        qa.adapter.no_running_copy(root)
        require(qa.digest(root / 'silver.dll') in (BASE_SHA, expected, previous),
                'Owned copy is not the reviewed public12 or staged HD candidate')
        require(qa.digest(root / 'ti.exe') == builder.TI_SHA, 'Immutable TI identity differs')
        if not check_only:
            for relative, content in payloads.items():
                target = qa.preparation.checked_target(root, relative)
                qa.preparation.replace_private(target, data=content)
            qa.native_guards(root, expected)
            for relative, content in payloads.items():
                require(qa.preparation.checked_target(root, relative).read_bytes() == content,
                        'Final staged selected resource differs: ' + relative)
    if not check_only:
        source = OUT / 'source' / expected / 'silver.dll'
        qa.preparation.replace_private(source, data=data)
        receipt = {'creator': CREATOR, 'manifest_sha256': MANIFEST_SHA,
                   'candidate_sha256': expected, 'verified_candidate': str(source),
                   'ti_candidate_sha256': builder.TI_SHA,
                   'package': str(Path(package).absolute()),
                   'package_sha256': qa.digest(package), 'managed_selected_paths': sorted(payloads),
                   'pure_transform_reconstruction': True}
        receipt_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return {'check_only': check_only, 'candidate_sha256': expected,
            'copies': list(copies), 'selected_resource_count': len(payloads),
            'staged': 0 if check_only else len(copies), 'started': 0, 'remote_mutations': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'seed', 'stage', 'run'))
    parser.add_argument('--copies', choices=('a', 'b'), nargs='+', default=['a', 'b'])
    parser.add_argument('--candidate', type=Path, default=builder.OUT / 'silver.dll')
    parser.add_argument('--candidate-sha')
    parser.add_argument('--package', type=Path, default=PACKAGE)
    parser.add_argument('--fixture', type=Path, default=qa.FIXTURE)
    parser.add_argument('--seconds', type=int, default=1200)
    parser.add_argument('--qhd-a', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(len(args.copies) == len(set(args.copies)), 'Duplicate owned copy')
    require(1 <= args.seconds <= 1800, 'Observation time exceeds1800 seconds')
    configure()
    if args.mode == 'prepare':
        qa.emit(prepare(args.copies, args.check_only))
    elif args.mode == 'seed':
        qa.emit(qa.seed(args.copies, args.qhd_a, args.check_only))
    else:
        require(args.candidate_sha, 'Exact reviewed candidate SHA required')
        if args.mode == 'stage':
            qa.emit(stage(args.copies, args.candidate, args.candidate_sha, args.check_only, args.package))
        else:
            require(len(args.copies) == 1, 'Run one owned copy at a time')
            qa.emit(run_resource_guard(args.copies[0], args.package, args.candidate, args.candidate_sha))
            if args.check_only:
                candidate_bytes(args.candidate, args.candidate_sha)
                qa.native_guards(qa.preparation.QA_BASE / ('game-' + args.copies[0]), args.candidate_sha)
                qa.FreshSurroundingsQA.load_private(args.fixture)
                qa.adapter.launcher_guard()
                qa.emit({'check_only': True, 'started': 0, 'credentials_printed': False})
            else:
                qa.launch(args.copies[0], args.candidate, args.candidate_sha, args.fixture, args.seconds)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        qa.emit({'event': 'hd_qa_failed', 'error_type': type(error).__name__, 'detail': str(error)})
        raise SystemExit(1)
