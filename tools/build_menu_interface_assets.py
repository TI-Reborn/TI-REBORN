"""Prepare generated art for the client's existing sliced native UI resources.

Labels, input fields, lists and callbacks remain native. This prepares textures
from imagegen masters; it does not paint interface text into screenshots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import xml.etree.ElementTree as ET

from PIL import Image, ImageEnhance, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets' / 'menu-interface-v1'
SOURCE_NAMES = {
    'background': 'exec-dd4dc20a-3f1b-4f07-9c03-f1ce87b7810c.png',
    'logo': 'exec-f7b12f20-beeb-47f0-a61d-f057f696551d.png',
    'frame': 'exec-ac639c61-0681-429c-a83b-cf7c1b483503.png',
    'button': 'exec-322e8239-bd24-4397-abe3-8b4d41e37b54.png',
}
NATIVE_MASTERS = {
    'base/fonts/nice.png': ('native-nice.png','601e3e743a23742c06df53b3f7798568d68a83cf41db9cca2d906b2c6b7453bb'),
    'base/fonts/nice.xml': ('native-nice.xml','7f581830ce605af9df68d8fca8877d38f10ce85b82032d4e61a83a32ee9f6b96'),
    'base/pda/borders2.tga': ('native-borders2.tga','3ed1b45006e81ac2afb6193b0d11c6ca59ec4d5f3ec3e730e0b551f4b9bb32ed'),
    'base/pda/listselector.png': ('native-listselector.png','08e176f9af5bf87012360adf4344d769b8d6b336d01234497e8e740e2a43ac58'),
    'base/pda/btn-left.png': ('native-btn-left.png','39bec1236c8047ec75c69156c4943c93cb0a15e4b64d354eceeb1e9b89ced379'),
    'base/pda/btn-right.png': ('native-btn-right.png','1abffdda2ef511d84bc0501aa9db5117ff3fa1b76e57d963c29c8542cd17d646'),
}


def native_master(relative: str, source_dir: Path, client: Path) -> Path:
    """Capture the immutable hosted source once; rebuilds use that saved master."""
    filename,expected=NATIVE_MASTERS[relative]
    saved=source_dir/filename
    origin=saved if saved.exists() else client/relative
    data=origin.read_bytes()
    if hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('Native source does not match published baseline: '+relative)
    if not saved.exists():saved.write_bytes(data)
    return saved


def alpha_crop(image: Image.Image) -> Image.Image:
    image = image.convert('RGBA')
    bounds = image.getchannel('A').point(lambda v: 255 if v > 32 else 0).getbbox()
    if bounds is None:
        raise ValueError('Empty generated source')
    image = image.crop(bounds)
    image.putalpha(image.getchannel('A').point(lambda v: 0 if v < 16 else v))
    return image


def frame_atlas(source: Image.Image, cell: int = 32, edge_width: int = 8) -> Image.Image:
    """4x4 atlas; native renderer uses indices 0,1,2 / 4,5,6 / 8,9,10.

    Native title/text margins are small. Outer metal is compressed into eight
    pixels, with 16px corner crystal accents, leaving readable dark interiors.
    """
    source = alpha_crop(source)
    w, h = source.size
    corner = int(min(w, h) * .19)
    body = source.crop((w//2-64, h//2-64, w//2+64, h//2+64)).resize((cell, cell), Image.Resampling.LANCZOS)
    atlas = Image.new('RGBA', (cell*4, cell*4))
    for row in range(3):
        for col in range(3):
            tile = body.copy()
            if row == 0:
                edge = source.crop((w//2-100, 0, w//2+100, corner)).resize((cell, edge_width), Image.Resampling.LANCZOS)
                tile.alpha_composite(edge, (0, 0))
            if row == 2:
                edge = source.crop((w//2-100, h-corner, w//2+100, h)).resize((cell, edge_width), Image.Resampling.LANCZOS)
                tile.alpha_composite(edge, (0, cell-edge_width))
            if col == 0:
                edge = source.crop((0, h//2-100, corner, h//2+100)).resize((edge_width, cell), Image.Resampling.LANCZOS)
                tile.alpha_composite(edge, (0, 0))
            if col == 2:
                edge = source.crop((w-corner, h//2-100, w, h//2+100)).resize((edge_width, cell), Image.Resampling.LANCZOS)
                tile.alpha_composite(edge, (cell-edge_width, 0))
            if row != 1 and col != 1:
                crop = source.crop((0 if col == 0 else w-corner,
                                    0 if row == 0 else h-corner,
                                    corner if col == 0 else w,
                                    corner if row == 0 else h)).resize((min(cell,edge_width*2), min(cell,edge_width*2)), Image.Resampling.LANCZOS)
                tile.alpha_composite(crop, (0 if col == 0 else cell-crop.width,
                                             0 if row == 0 else cell-crop.height))
            atlas.alpha_composite(tile, (col*cell, row*cell))
    return atlas


def button_atlas(source: Image.Image, cell: int) -> Image.Image:
    """Left/repeated-middle/right cells, normal/disabled/pressed/hover rows."""
    source = alpha_crop(source)
    w, h = source.size
    # Endcaps retain the corner crystal/rivet decoration at the native aspect.
    cap = min(h, w//3)
    pieces = [source.crop((0, 0, cap, h)),
              source.crop((w//2-h//2, 0, w//2+h//2, h)),
              source.crop((w-cap, 0, w, h))]
    atlas = Image.new('RGBA', (cell*4, cell*4))
    for state, brightness in enumerate((1., .48, .72, 1.42)):
        for col, piece in enumerate(pieces):
            tile = piece.resize((cell, cell), Image.Resampling.LANCZOS)
            alpha = tile.getchannel('A')
            tile = ImageEnhance.Brightness(tile.convert('RGB')).enhance(brightness).convert('RGBA')
            tile.putalpha(alpha)
            atlas.alpha_composite(tile, (cell*col, cell*state))
    return atlas


def framed_plate(atlas: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Compose a native-sized row/auxiliary plate with eight pixel margins."""
    w, h = size
    source = atlas.crop((0, 0, 96, 96))
    c = min(16, w//3, h//3)
    result = Image.new('RGBA', size)
    for row, ys in enumerate(((0,32),(32,64),(64,96))):
        for col, xs in enumerate(((0,32),(32,64),(64,96))):
            box = (0 if col == 0 else c if col == 1 else w-c,
                   0 if row == 0 else c if row == 1 else h-c,
                   c if col == 0 else w-c if col == 1 else w,
                   c if row == 0 else h-c if row == 1 else h)
            tile = source.crop((xs[0],ys[0],xs[1],ys[1])).resize((box[2]-box[0],box[3]-box[1]), Image.Resampling.LANCZOS)
            result.alpha_composite(tile, box[:2])
    return result


def build(generated: Path, output: Path = ASSETS / 'runtime', native_client: Path | None = None) -> dict[str, str]:
    source_dir = ASSETS / 'source'
    source_dir.mkdir(parents=True, exist_ok=True)
    native_client=native_client or Path.home()/'AppData/Local/TIO-Online'
    for name, filename in SOURCE_NAMES.items():
        shutil.copy2(generated / filename, source_dir / (name + '.png'))
    pda = output / 'base' / 'pda'
    pda.mkdir(parents=True, exist_ok=True)
    bg = Image.open(source_dir / 'background.png').convert('RGB')
    bg.save(pda / 'mainbg.jpg', quality=96, subsampling=0)
    logo = alpha_crop(Image.open(source_dir / 'logo.png'))
    logo.thumbnail((640, 196), Image.Resampling.LANCZOS)
    logo.save(pda / 'gamelogo.png')
    Image.new('RGBA', (128,86)).save(pda / 'gamerlogo.png')
    window = frame_atlas(Image.open(source_dir / 'frame.png'))
    frame_atlas(Image.open(source_dir/'frame.png'),edge_width=24).save(pda/'menuframe.png')
    for filename in ('d_window.png','d_window2.png','d_window3.png','d_window4.png','steel_window.png','c_window.png'):
        window.save(pda / filename)
    button = Image.open(source_dir / 'button.png')
    button_atlas(button,25).save(pda / 'gui_button.png')
    button_atlas(button,50).save(pda / 'menubutton.png')
    # Character-list row atlas retains the original two 64px states.
    bevel = Image.new('RGBA',(256,128))
    plate = framed_plate(window,(216,60))
    bevel.alpha_composite(plate,(0,0))
    bright = ImageEnhance.Brightness(plate.convert('RGB')).enhance(1.3).convert('RGBA')
    bright.putalpha(plate.getchannel('A'))
    bevel.alpha_composite(bright,(0,64))
    bevel.save(pda/'charbevel.png')
    # Native checkbox atlas: empty/checked; the engine owns label and state.
    check=Image.new('RGBA',(32,16))
    draw=ImageDraw.Draw(check)
    for x in (0,16):
        draw.rounded_rectangle((x+1,1,x+14,14),radius=2,fill=(25,25,28,255),outline=(184,129,66,255),width=2)
    draw.line([(19,8),(22,11),(29,4)],fill=(229,185,104,255),width=2)
    check.save(pda/'checkbox.png')
    # Scroll track/thumb retain original dimensions and tile lookup.
    Image.new('RGBA',(16,18),(70,52,40,255)).save(pda/'sb_bar.png')
    arrows=Image.new('RGBA',(64,16))
    draw=ImageDraw.Draw(arrows)
    for i in range(4):
        draw.rectangle((16*i,0,16*i+15,15),fill=(31,29,31,255),outline=(164,117,65,255))
        points=[(16*i+4,10),(16*i+8,5),(16*i+12,10)] if i%2==0 else [(16*i+4,5),(16*i+8,10),(16*i+12,5)]
        draw.polygon(points,fill=(210,164,95,255))
    arrows.save(pda/'sb_updown.png')
    # Entry boxes/dividers use a tiny 3px-cell native border atlas. Retain its
    # geometry and alpha while replacing the olive color with warm brass.
    original=native_master('base/pda/borders2.tga',source_dir,native_client)
    border=Image.open(original).convert('RGBA')
    pixels=[]
    for red,green,blue,alpha in border.getdata():
        value=max(red,green,blue)/255
        pixels.append((int(215*value),int(157*value),int(87*value),alpha))
    border.putdata(pixels)
    border.save(pda/'borders2.tga')
    # The old bitmap masquerades as PNG; Pillow omits its BMP32 alpha. Native
    # alpha occupies the fourth byte, so retain that exact selection geometry.
    original=native_master('base/pda/listselector.png',source_dir,native_client)
    raw=original.read_bytes()
    if raw[:2]!=b'BM' or struct.unpack_from('<H',raw,28)[0]!=32:
        raise ValueError('Unsupported native list-selector source')
    w,h=struct.unpack_from('<ii',raw,18);offset=struct.unpack_from('<I',raw,10)[0]
    selection=Image.frombytes('RGBA',(w,abs(h)),raw[offset:offset+w*abs(h)*4],'raw','BGRA')
    if h>0:selection=selection.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    alpha=selection.getchannel('A')
    selection=Image.new('RGBA',selection.size,(177,123,64,255));selection.putalpha(alpha)
    selection.save(pda/'listselector.png')
    for filename in ('btn-left.png','btn-right.png'):
        rotation=Image.open(native_master('base/pda/'+filename,source_dir,native_client)).convert('RGBA')
        rotation.putdata([(int(229*max(red,green,blue)/255),int(181*max(red,green,blue)/255),
                           int(99*max(red,green,blue)/255),alpha)
                          for red,green,blue,alpha in rotation.getdata()])
        rotation.save(pda/filename)
    # A separate native font preserves Cyrillic localization. Doubling both
    # atlas and metrics leaves every ordinary nice-font consumer unchanged.
    fonts=output/'base/fonts';fonts.mkdir(parents=True,exist_ok=True)
    font=ET.parse(native_master('base/fonts/nice.xml',source_dir,native_client))
    for element in font.iter():
        for attribute in ('width','height','top','x','y','leading','trailing'):
            if attribute in element.attrib:
                element.set(attribute,str(int(element.get(attribute))*2))
    ET.indent(font,space=' ')
    font.write(fonts/'menu.xml',encoding='utf-8',xml_declaration=False)
    glyphs=Image.open(native_master('base/fonts/nice.png',source_dir,native_client)).convert('RGBA')
    glyphs.resize((glyphs.width*2,glyphs.height*2),Image.Resampling.LANCZOS).save(fonts/'menu.png')
    overrides={path.relative_to(output).as_posix():path.relative_to(output).as_posix() for path in sorted(output.rglob('*')) if path.is_file()}
    (ASSETS/'overrides.json').write_text(json.dumps(overrides,indent=2)+'\n',encoding='utf-8')
    records=[]
    for relative in overrides:
        path=output/relative
        record=dict(path=relative,size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if path.suffix.lower() not in ('.dll','.xml'):
            image=Image.open(path)
            record.update(dimensions=image.size,mode=image.mode)
        records.append(record)
    (ASSETS/'asset-manifest.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    return overrides


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ASSETS/'runtime')
    parser.add_argument('--native-client',type=Path,help='Verified hosted baseline source; saved masters take precedence on rebuilds')
    args=parser.parse_args()
    print(json.dumps(build(args.generated,args.output,args.native_client),indent=2))
