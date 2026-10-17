"""Freeze review provenance and aggregate existing offline asset evidence.

Writes metadata under reports/ui-hd-assets only. It installs no font, atlas,
native adapter, game client, or hosted artifact.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/ui-hd-assets'
B_GRID_REPAIR = (
    'Use case: precise-object-edit. Target: tactical flat ivory and olive 16-icon sprite sheet. '
    'Correct ONLY the layout and alpha cleanliness. Retain all sixteen recognizable icon designs '
    'and the same two-color style. Arrange them EXACTLY in a uniform four-column, four-row square '
    'grid. Reduce and reposition each icon so it fits entirely inside the CENTRAL 60% of its own '
    'equal-sized square cell, centered both horizontally and vertically; leave fully transparent '
    '20% padding along EACH edge of EACH cell. No icon or fragment may touch or cross a cell '
    'boundary. In particular helmet and crates must end well before row2, and row2 '
    'information/rifle/lightning must have perfectly empty transparent space above them. Uniform '
    'optical size rather than overlarge helmets. Remove any detached edge flecks. Crisp ivory '
    '(#E6E4BF) and restrained olive (#88A564) only; no luminous/neon green outlines, no yellow '
    'speckles, no background, no text or labels. Genuine alpha transparency. Keep this exact row '
    'order: map/soldier/crates/money; info/rifle/lightning/squad; handshake/search/refresh/gear; '
    'check/left-chevron/right-chevron/close-X.'
)
FLAGS = {'prepared_for_user_selection': True, 'native_adapter_installed': False,
         'client_installed': False, 'published': False}


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    path = path.resolve()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def exact_record(data: dict, path_key: str = 'path') -> dict:
    actual = record(Path(data[path_key]))
    assert actual['sha256'] == data['sha256'], data[path_key]
    if 'bytes' in data:
        assert actual['bytes'] == data['bytes']
    return actual


def exclusive_json(path: Path, value: dict) -> None:
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main() -> None:
    prompts_path = OUT / 'generation-prompts.json'
    history_path = OUT / 'generation-prompts.initial.json'
    aggregate_path = OUT / 'review-manifest.json'
    assert not history_path.exists() and not aggregate_path.exists(), 'Preserve existing provenance freezes'
    prior = prompts_path.read_bytes()
    with history_path.open('xb') as stream:
        stream.write(prior)
    provenance = json.loads(prior.decode('utf-8'))

    icon_path = OUT / 'icons/candidate-packs-v3/manifest.json'
    icon = read(icon_path)
    icon_proof_path = OUT / 'icons/export-static-proof-v3.json'
    icon_proof = read(icon_proof_path)
    assert sha(icon_path) == icon_proof['candidate_manifest_sha256']
    assert icon_proof['status'] == 'SOURCE_PACK_STATIC_PASS_VISUAL_REVIEW_PASS'
    assert not icon['client_installable'] and not icon['published']

    board_path = OUT / 'previews/final/preview-manifest.json'
    board = read(board_path)
    assert board['result'] == 'PASS' and not board['provisional_sources']
    assert board['concepts_not_game_screenshots']
    assert board['repeat_same_PNG_bytes']
    font_path = OUT / 'fonts/candidates.json'
    fonts = read(font_path)
    assert sha(font_path) == board['font_manifest']['sha256']
    assert fonts['result'] == 'PASS' and len(fonts['candidates']) == 3
    fonts_by_family = {candidate['family']: candidate for candidate in fonts['candidates']}

    final_sources = {}
    variants = []
    for variant in board['variants']:
        key = variant['id'].upper()
        master = exact_record(variant['master'])
        candidate = fonts_by_family[variant['actual_font_family']]
        exact_record(variant['original_TTF'])
        assert variant['original_TTF']['sha256'] == candidate['ttf']['sha256']
        style = {'A': 'a-classic-hd', 'B': 'b-tactical-clean', 'C': 'c-enamel'}[key]
        assert icon['styles'][style]['source']['sha256'] == master['sha256']
        final_sources[key] = {**master, 'dimensions': variant['source_dimensions'],
                              'source_kind': variant['icon_source_kind']}
        variants.append({'id': key, 'title': variant['title'], 'icon_source': final_sources[key],
                         'font_family': candidate['family'], 'font_candidate_id': candidate['id'],
                         'font_source': exact_record(candidate['ttf']),
                         'font_license': candidate['license'],
                         'font_license_file': exact_record(next(item for item in candidate['files']
                                                               if item['filename'] == 'OFL.txt')),
                         'style_and_font_pairing_is_optional': True})
    assert final_sources['B']['source_kind'] == 'original_svg_geometry_rendered_to_RGBA'
    vector_path = OUT / 'icons/vector-b/manifest.json'
    vector = read(vector_path)
    assert vector['generated_from_geometry'] and not vector['traced_from_raster']
    assert vector['masterRecord']['sha256'] == final_sources['B']['sha256']
    svg_sources = [exact_record(item['source'], 'file') for item in vector['symbols']]
    assert len(svg_sources) == 16

    historical_sources = {
        'A_original': record(OUT / 'icons/source/a-classic-hd.png'),
        'B_generated_initial': record(OUT / 'icons/source/b-tactical-clean.png'),
        'B_generated_grid_repair': record(OUT / 'icons/source/b-tactical-clean-grid.png'),
        'C_original': record(OUT / 'icons/source/c-enamel.png'),
    }
    provenance.update({
        'schema': 2, 'mode': 'image_gen A/C masters plus original code-native SVG B',
        'scope': 'Review concepts and offline density source packs; no native adapter, client installation or hosted publication',
        **FLAGS,
        'source_files': {key: str(Path(value['path']).relative_to(OUT)).replace('\\', '/')
                         for key, value in final_sources.items()},
        'final_source_records': final_sources,
        'historical_source_records': historical_sources,
        'source_provenance': {
            'A': {'generator': 'built-in image_gen', 'original_prompt': 'A',
                  'cleanup_prompt': 'A_cleanup', 'original_source': 'A_original',
                  'final_source': final_sources['A']},
            'B': {'generator': 'original SVG geometry authored in code',
                  'image_gen_output': False, 'traced_from_raster': False, 'raster_retouched': False,
                  'geometry_generator': record(ROOT / 'tools/build_tactical_vector_icons.cjs'),
                  'vector_manifest': record(vector_path), 'svg_sources': svg_sources,
                  'final_source': final_sources['B'],
                  'historical_imagegen_attempts': [
                      {'source': historical_sources['B_generated_initial'], 'prompt_key': 'B',
                       'used_in_final': False},
                      {'source': historical_sources['B_generated_grid_repair'],
                       'prompt_key': 'B_grid_repair', 'used_in_final': False}],
                  'selection_reason': 'Generated B sheets retained neighboring-cell fragments; original vector geometry provides isolated tactical pictograms.'},
            'C': {'generator': 'built-in image_gen', 'original_prompt': 'C',
                  'cleanup_prompt': 'C_cleanup', 'original_source': 'C_original',
                  'final_source': final_sources['C']},
        },
        'historical_prompt_text_preserved': True,
        'prior_metadata': record(history_path),
        'style_choice_pending': True,
        'production_native_adapter_installed': False,
        'remaining_art_review': 'Actual density source-over composites have no observed colored fringe. C retains a tiny detached sliver beside the skills lightning symbol; review and refine it before production integration.',
        'art_review': {
            'method': 'RGBA source-over on actual dark/olive GUI backgrounds at 40/50/60/80 px',
            'colored_fringe_observed_on_reviewed_composites': False,
            'production_art_review_pending': True,
            'known_detail': {'variant': 'C', 'symbol': 'skills',
                             'finding': 'Tiny detached sliver beside lightning',
                             'action': 'Later production art review; original pixels preserved'},
            'evidence': record(icon_proof_path),
        },
    })
    provenance['prompts']['B_grid_repair'] = B_GRID_REPAIR
    # This is the single existing metadata file explicitly authorized for finalization.
    prompts_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')

    atlas_path = OUT / 'font-atlases/manifest.json'
    atlas = read(atlas_path)
    atlas_proof_path = OUT / 'font-atlases/offline-atlas-proof.json'
    atlas_proof = read(atlas_proof_path)
    assert atlas_proof['result'] == atlas['result'] == 'PASS'
    assert sha(atlas_path) == atlas_proof['manifest_sha256']
    assert atlas['candidate_manifest_sha256'] == sha(font_path)
    assert not atlas['native_drop_in_compatible'] and not atlas['native_adapter_implemented']
    assert not atlas_proof['native_client_tested']
    atlas_file_checks = 0
    for item in atlas['sets']:
        assert sha(Path(item['atlas'])) == item['atlas_sha256']
        assert sha(Path(item['contract'])) == item['contract_sha256']
        contract = read(Path(item['contract']))
        xml_path = Path(item['contract']).with_name(item['font_stem'] + '.logical.xml')
        assert sha(xml_path) == contract['logical_xml_sha256']
        atlas_file_checks += 3

    boards = []
    text_draws = 0
    for output in board['outputs']:
        actual = exact_record(output)
        assert output['all_icons_fit'] and output['all_text_fits']
        proof_rows = output['fresh_TTF_text_proof']
        assert all(row['drawn_from_ttf'] and row['fits'] for row in proof_rows)
        text_draws += len(proof_rows)
        boards.append({**actual, 'dimensions': output['dimensions'],
                       'all_icons_fit': True, 'all_text_fits': True,
                       'fresh_ttf_text_draws': len(proof_rows)})
    font_records = []
    for candidate in fonts['candidates']:
        retained_files = [exact_record(item) for item in candidate['files']]
        assert not candidate['coverage']['Russian_missing']
        assert not candidate['coverage']['cp1251_printable_missing']
        font_records.append({
            'id': candidate['id'], 'family': candidate['family'], 'license': candidate['license'],
            'source_repository': candidate['source_repository'],
            'distribution_repository': candidate['distribution_repository'],
            'pinned_distribution_commit': candidate['pinned_distribution_commit'],
            'source_files': retained_files, 'unicode_coverage': candidate['coverage'],
            'preview': candidate['preview'],
        })
    aggregate = {
        'schema': 1, 'status': 'REVIEW_READY_OFFLINE_PROTOTYPES', **FLAGS,
        'native_graphical_validation': False, 'style_choice_pending': True,
        'production_ready': False, 'client_and_hosting_modified': False,
        'densities_percent': [100, 125, 150, 200],
        'variant_count': 3, 'symbols_per_variant': 16,
        'provenance': record(prompts_path), 'variants': variants,
        'font_candidates': font_records,
        'font_preview_contract': {
            'actual_licensed_TTF': True, 'fresh_rasterization_at_each_size': True,
            'legacy_metric_box_fitting_applied': False,
            'description': 'Review boards use the actual typeface outlines and natural bearings; they are not text re-painted onto old font bitmaps.',
        },
        'compatibility_atlas_contract': {
            'prototype': True, 'native_drop_in_compatible': False,
            'old_logical_glyph_boxes_and_line_metrics_retained': True,
            'fresh_TTF_rasterization_at_each_density': True,
            'glyph_fit_can_change_new_face_proportions_and_bearings': True,
            'description': 'Offline compatibility atlases fit new outlines into existing logical boxes. Their appearance can differ from the unrestricted TTF preview and requires a native texture/source-rectangle adapter.',
            'manifest': record(atlas_path), 'offline_proof': record(atlas_proof_path),
            'atlas_sets': atlas_proof['atlas_sets'], 'glyph_instances': atlas_proof['glyph_instances'],
            'independently_hashed_atlas_contract_and_xml_files': atlas_file_checks,
        },
        'icon_source_pack_contract': {
            'prototype': True, 'manifest': record(icon_path), 'static_proof': record(icon_proof_path),
            'counts': icon_proof['counts'], 'logical_glyph_reference': [40, 40],
            'physical_glyph_sizes': [40, 50, 60, 80],
            'wide_native_toolbar_bounds_retained': [88, 31],
            'native_source_and_destination_adapter_required': True,
            'not_generated_native_symbols': icon['not_generated_native_symbols'],
            'unmapped_concepts': icon['unmapped_concepts'],
            'known_production_art_review': provenance['art_review']['known_detail'],
        },
        'review_boards': {'manifest': record(board_path), 'concepts_not_game_screenshots': True,
                         'outputs': boards, 'checked_fresh_ttf_text_draws': text_draws,
                         'deterministic_png_repeat_pass': True},
        'checks': {
            'PASS': True, 'source_and_proof_hashes_bound': True,
            'all_final_sources_match_boards_and_icon_pack': True,
            'all_font_TTF_license_and_metadata_bytes_match_retained_hashes': True,
            'all_120_atlas_sets_360_files_hash_checked': atlas_file_checks == 360,
            'no_client_or_hosting_installation': True,
        },
        'integration_pending': [
            'User selection of icon style and font, which may be combined independently.',
            'Review the C skills detached sliver before shipping selected artwork.',
            'Guarded native font/icon source rectangles, actual texture sizes, tint and four-state behavior.',
            'Native client checks at each allowed UI scale, reload/reset and hosted two-account gameplay validation.',
        ],
        'historical_attempts_retained': historical_sources,
        'separate_interactive_specimens': {
            'path': str(OUT / 'previews/specimens/proof.json'),
            'owned_by_parent_task': True,
            'note': 'Interactive browser proof is finalized separately; this aggregate does not claim native game validation or edit its files.',
        },
    }
    exclusive_json(aggregate_path, aggregate)
    print(json.dumps({'PASS': True, 'aggregate': record(aggregate_path),
                      'provenance': record(prompts_path), 'boards': len(boards),
                      'atlas_files_hash_checked': atlas_file_checks, **FLAGS}))


if __name__ == '__main__':
    main()
