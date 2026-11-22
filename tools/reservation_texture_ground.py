"""Register the two ground brush images and preserve their native masks."""
from PIL import Image, ImageChops


def align_ground_base(art: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new('RGBA', size)
    for half in (0, 1):
        crop = art.crop((0, half * art.height // 2, art.width, (half + 1) * art.height // 2))
        bounds = crop.getchannel('A').point(lambda a: 255 if a >= 128 else 0).getbbox()
        if bounds is None:
            raise ValueError('Empty ground island')
        sprite = crop.crop(bounds).resize((size[0], size[1] // 2), Image.Resampling.LANCZOS)
        canvas.paste(sprite, (0, half * size[1] // 2))
    return canvas


def ground_double_density(original: Image.Image, master: Image.Image) -> Image.Image:
    size = (original.width * 2, original.height * 2)
    registered = align_ground_base(master, size).convert('RGB')
    coarse = registered.resize(original.size, Image.Resampling.BOX).resize(size, Image.Resampling.BICUBIC)
    # Retain the published ground colours and take only the extra detail from the master.
    detail = ImageChops.subtract(registered, coarse, offset=128)
    base = original.convert('RGB').resize(size, Image.Resampling.BICUBIC)
    image = ImageChops.add(base, detail, offset=-128)
    image.putalpha(original.getchannel('A').resize(size, Image.Resampling.BILINEAR))
    return image
