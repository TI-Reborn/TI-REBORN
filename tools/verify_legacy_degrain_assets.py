"""Read-only independent contract/native proof review for imagegen asset export."""
from __future__ import annotations
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.native_texture_contract import validate_replacement
from tools.build_visual_asset_catalog import decode
from tools.build_legacy_degrain_assets import OUT, UI_WINDOWS


def activity(image, box):
    """Read-only adjacent luminance change; no image pixels are edited."""
    gray = image.convert('L')
    left, top, right, bottom = box
    values = [abs(gray.getpixel((x, y)) - gray.getpixel((x + 1, y)))
              for y in range(top, bottom) for x in range(left, right - 1)]
    values += [abs(gray.getpixel((x, y)) - gray.getpixel((x, y + 1)))
               for y in range(top, bottom - 1) for x in range(left, right)]
    return sum(values) / len(values)


def main():
    report = json.loads((OUT / 'changed-files.json').read_bytes())
    baseline_raw = (OUT / 'baseline-manifest.json').read_bytes()
    baseline = json.loads(baseline_raw)
    native = json.loads((OUT / 'native-d3dx-proof.json').read_text(encoding='utf-8-sig'))
    expected = {'base/pda/' + n for n in UI_WINDOWS}
    expected |= {'base/pda/menuframe.png', 'base/pda/charbevel.png',
                 'base/pda/gui_button.png', 'base/pda/menubutton.png',
                 'base/setting/military/ground_military_base_a.tga',
                 'base/setting/military/ground_military_base_b.tga',
                 'base/setting/reservation_v2/rv_bunker.png'}
    assert report['changed_count'] == native['pair_count'] == len(expected) == 13
    assert native['passed']
    assert {item['path'] for item in report['files']} == expected
    assert {p.relative_to(OUT / 'candidate').as_posix() for p in (OUT / 'candidate').rglob('*') if p.is_file()} == expected
    records = {r['path']: r for r in baseline['files']}
    metrics, verified, cards = [], [], []
    for item in report['files']:
        relative = item['path']
        before = (OUT / 'source' / relative).read_bytes()
        after = (OUT / 'candidate' / relative).read_bytes()
        assert hashlib.sha256(before).hexdigest() == records[relative]['sha256'] == item['original_sha256']
        assert hashlib.sha256(after).hexdigest() == item['sha256'] and len(after) == item['size']
        contract = validate_replacement(before, after)
        old_image, _ = decode(before)
        new_image, _ = decode(after)
        assert old_image.size == new_image.size == (item['width'], item['height'])
        assert old_image.getchannel('A').tobytes() == new_image.getchannel('A').tobytes()
        for key, value in contract.items():
            if key != 'codec': assert item[key] == value
        paired = next(p for p in native['pairs'] if p['after']['Path'] == str((OUT / 'candidate' / relative).resolve()))
        assert paired['invariants_equal'] and paired['before']['Device'] == paired['after']['Device'] == 'HAL'
        assert paired['before']['Width'] == paired['after']['Width'] == item['width']
        assert paired['before']['Height'] == paired['after']['Height'] == item['height']
        verified.append(relative)
        if relative.endswith('d_window.png'):
            box = (34, 34, 62, 62)
        elif relative.endswith(('ground_military_base_a.tga', 'ground_military_base_b.tga')):
            box = (188, 80, 324, 152)
        else:
            box = None
        if box:
            old, new = activity(old_image, box), activity(new_image, box)
            metrics.append(dict(path=relative, sample_box=list(box),
                                before_adjacent_luminance_change=round(old, 4),
                                after_adjacent_luminance_change=round(new, 4),
                                reduction_percent=round((1-new/old)*100, 1)))
        filename = Path(relative).name + '.png'
        cards.append('<article><h2>' + html.escape(relative) + '</h2><div class="pair"><figure><img src="decoded/' + filename + '"><figcaption>До</figcaption></figure><figure><img src="review-decoded/' + filename + '"><figcaption>После</figcaption></figure></div><p>' + item['native_codec'] + ' · ' + str(item['width']) + ' × ' + str(item['height']) + ' · исходная прозрачность сохранена</p></article>')
    counts = Counter(Path(r['path']).suffix.lower() for r in baseline['files'])
    summary = dict(passed=True, verified_count=len(verified), baseline_version=baseline['version'],
                   baseline_records=len(baseline['files']),
                   changed_files_sha256=hashlib.sha256((OUT / 'changed-files.json').read_bytes()).hexdigest(),
                   png_jpeg_tga_records=sum(counts[e] for e in ('.png', '.jpg', '.tga')),
                   dimensions_codec_alpha_header_verified=True, native_d3dx_pair_proof=True,
                   native_gpu_device='HAL', original_npot_allocation_behavior_preserved=True,
                   visual_review='Original decoded inputs and native-sized outputs inspected; first irregular ground generation rejected.',
                   read_only_sample_metrics=metrics,
                   metric_limit='Adjacent luminance change measures local high frequency, not universal image quality or zero noise.',
                   unchanged_scope='Other bitmap files, native executables, fonts, glyphs, icon atlases, models, UVs, XML and combat effects unchanged.',
                   remaining_scope='This bounded package cleans UI framing/button panels and representative Military ground/Reservation material atlases. It does not claim grain removal from every remaining image.')
    (OUT / 'verification-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (OUT / 'review.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Очистка текстур старого клиента</title><style>body{background:#172026;color:#e9ebed;font:16px system-ui;margin:20px}article{padding:16px;border:1px solid #596675;margin:16px 0}h2{font:16px monospace}.pair{display:flex;gap:24px}figure{margin:0;flex:1}img{max-width:100%;min-width:256px;max-height:600px;object-fit:contain;background:#34373b}p{max-width:1100px}</style><h1>13 текстур: исходник и кандидат</h1><p>Реальная очистка bitmap через imagegen. Родные размеры, кодеки, прозрачность и раскладка атласов сохранены. Это подготовленный пакет; проверка в настоящих игровых окнах выполняется отдельно.</p>' + ''.join(cards) + '</html>', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
