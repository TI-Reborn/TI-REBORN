"""Register AI texture output to original UVs and export native-compatible resources."""
from pathlib import Path
import argparse
import io
import json
import struct
import sys
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.equipment_texture_assets import ASSETS, OUT, fetch, sha
from tools.build_visual_asset_catalog import decode


def icon_registration(art, reference):
    """Restore original canvas placement before applying the exact native alpha."""
    art = art.convert('RGBA')
    original_bounds = reference.getchannel('A').point(lambda p: 255 if p >= 128 else 0).getbbox()
    generated_bounds = art.getchannel('A').point(lambda p: 255 if p >= 128 else 0).getbbox()
    if reference.getchannel('A').getextrema()[0] < 255 and original_bounds and generated_bounds:
        left, top, right, bottom = original_bounds
        canvas = Image.new('RGBA', reference.size)
        canvas.paste(art.crop(generated_bounds).resize((right-left, bottom-top), Image.Resampling.LANCZOS), (left, top))
    else:
        canvas = art.resize(reference.size, Image.Resampling.LANCZOS)
    # The old silhouette can extend a few pixels beyond the generated one.
    # Keep original edge colors there instead of promoting transparent black
    # pixels to opaque pixels when restoring the native alpha plane.
    pixels=list(zip(*(canvas.tobytes()[channel::4] for channel in range(4))))
    originals=list(zip(*(reference.tobytes()[channel::4] for channel in range(4))))
    for index,(new,old) in enumerate(zip(pixels,originals)):
        if new[3]<64 and old[3]>=64:
            pixels[index]=old
    canvas.putdata(pixels)
    canvas.putalpha(reference.getchannel('A'))
    return canvas


def native_encode(raw, image, reference):
    """Keep the codec and original alpha; BMP32 alpha is consumed by the native game."""
    image = image.convert('RGBA')
    image.putalpha(reference.getchannel('A'))
    if raw.startswith(bytes.fromhex('07e181')):
        key=100
        plain=bytearray()
        for cipher in raw:
            plain.append(cipher^(key>>8))
            key=((key+cipher)*0xce6d+0x58bf)&65535
        assert plain[:8]==b'\x07AJPG_EX'
        color_size,mask_size=struct.unpack_from('<QQ',plain,39)
        assert 55+color_size+mask_size==len(plain)
        color=io.BytesIO()
        image.convert('RGB').save(color,format='JPEG',quality=98,subsampling=0)
        header=bytearray(plain[:55])
        struct.pack_into('<QQ',header,39,len(color.getvalue()),mask_size)
        payload=header+color.getvalue()+plain[55+color_size:]
        encrypted=bytearray()
        key=100
        for value in payload:
            cipher=value^(key>>8)
            encrypted.append(cipher)
            key=((key+cipher)*0xce6d+0x58bf)&65535
        return bytes(encrypted)
    if raw.startswith(b'BM'):
        offset = struct.unpack_from('<I', raw, 10)[0]
        width, height, planes, bits, compression = struct.unpack_from('<iiHHI', raw, 18)
        if bits == 32 and compression == 0:
            assert planes == 1 and image.size == (width, abs(height))
            payload = bytearray(raw)
            rgb = image.convert('RGB').tobytes()
            assert offset + width * 4 * abs(height) <= len(payload)
            for y in range(abs(height)):
                row = abs(height)-1-y if height > 0 else y
                for x in range(width):
                    start = (y*width+x)*3
                    dest = offset + (row*width+x)*4
                    red, green, blue = rgb[start:start+3]
                    payload[dest:dest+3] = bytes((blue, green, red))
            return bytes(payload)
    output = io.BytesIO()
    if raw.startswith(b'\xff\xd8'):
        image.convert('RGB').save(output, format='JPEG', quality=98, subsampling=0)
    elif raw.startswith(b'BM'):
        image.convert('RGB').save(output, format='BMP')
    elif raw.startswith(b'\x89PNG'):
        image.save(output, format='PNG')
    elif len(raw) >= 18 and raw[2] in (2, 10):
        image.save(output, format='TGA')
    else:
        raise ValueError('Unsupported native equipment texture codec')
    return output.getvalue()


def export(partial=False):
    tasks = json.loads((ASSETS / 'tasks.json').read_text(encoding='utf-8'))
    manifest = json.loads((OUT / 'previous-client-manifest.json').read_bytes())
    records = {r['path']: r for r in manifest['files']}
    proofs, provenance = [], []
    for task in tasks:
        index = ASSETS / 'generated-index' / (task['id'] + '.json')
        if partial and not index.exists():
            continue
        generation = json.loads(index.read_text())
        master = ROOT / generation['master']
        assert master.is_file(), task['id']
        raw = fetch(records[task['path']]).read_bytes()
        reference, _ = decode(raw)
        art = Image.open(master).convert('RGBA')
        if task['kind'] == 'atlas':
            assert reference.getchannel('A').getextrema() == (255,255)
            size = (1024, 1024 * reference.height // reference.width)
            canvas = art.resize(size, Image.Resampling.LANCZOS)
            output = io.BytesIO()
            canvas.convert('RGB').save(output, format='JPEG', quality=98, subsampling=0)
            data = output.getvalue()
            alpha_exact = None
        else:
            canvas = icon_registration(art, reference)
            data = native_encode(raw, canvas, reference)
            alpha_exact = True
        target = OUT / 'client' / task['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        check, codec = decode(data)
        assert check.size == canvas.size and data != raw, task['id']
        if alpha_exact:
            assert check.getchannel('A').tobytes() == reference.getchannel('A').tobytes(), task['id']
        proofs.append(dict(id=task['id'], path=task['path'], kind=task['kind'],
                           source_size=list(reference.size), output_size=list(check.size),
                           original_alpha_exact=alpha_exact, native_codec=codec,
                           sha256=sha(data), size=len(data), master_sha256=sha(master.read_bytes()),
                           source_sha256=sha(raw)))
        provenance.append({**generation, 'prompt': generation.get('prompt',task['prompt'])})
    (OUT / 'texture-proof.json').write_text(json.dumps(proofs, indent=2) + '\n')
    (ASSETS / 'generated.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(exported=len(proofs), pending=len(tasks)-len(proofs),
                          atlases=sum(p['kind']=='atlas' for p in proofs), icons=sum(p['kind']=='icon' for p in proofs))))


def review():
    tasks = {t['id']: t for t in json.loads((ASSETS / 'tasks.json').read_text(encoding='utf-8'))}
    proofs = json.loads((OUT / 'texture-proof.json').read_text())
    pages = []
    for kind in ('atlas', 'icon'):
        entries = [p for p in proofs if p['kind'] == kind]
        for offset in range(0,len(entries),12):
            sheet = Image.new('RGB',(1200,6*230),(50,55,61))
            draw = ImageDraw.Draw(sheet)
            for index, record in enumerate(entries[offset:offset+12]):
                x,y=(index%2)*600,(index//2)*230
                draw.text((x+8,y+5),record['id'],fill='white')
                for column,path in enumerate((OUT/'source'/record['path'],OUT/'client'/record['path'])):
                    im,_=decode(path.read_bytes())
                    im.thumbnail((285,190),Image.Resampling.LANCZOS)
                    sheet.paste(im,(x+column*300+(290-im.width)//2,y+28+(190-im.height)//2),im)
                    draw.text((x+column*300+8,y+213),'original' if column==0 else 'new',fill='#b8c3cf')
            target=OUT/f'review-{kind}-{offset//12+1:02d}.png'
            sheet.save(target)
            pages.append(str(target))
    print(json.dumps(dict(pages=pages)))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partial',action='store_true')
    parser.add_argument('--review',action='store_true')
    args=parser.parse_args()
    if args.review:
        review()
    else:
        export(args.partial)
