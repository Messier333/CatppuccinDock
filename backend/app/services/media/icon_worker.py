"""Decode untrusted icon files in a bounded process. Only a PNG leaves it."""
from io import BytesIO
from pathlib import Path
import os
import resource
import sys
import warnings

from PIL import Image, ImageOps

SIDE = 128


def deny_resource(*args, **kwargs):
    raise ValueError('External SVG resources are disabled')


def normalize(raw):
    Image.MAX_IMAGE_PIXELS = 16_777_216
    warnings.simplefilter('error', Image.DecompressionBombWarning)
    try:
        image = Image.open(BytesIO(raw))
        if image.format not in ('PNG', 'JPEG', 'WEBP', 'GIF', 'ICO'):
            raise ValueError('Unsupported icon format')
    except Image.UnidentifiedImageError:
        from defusedxml import ElementTree
        from cairosvg.surface import PNGSurface
        root = ElementTree.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
        if root.tag not in ('svg', '{http://www.w3.org/2000/svg}svg'):
            raise ValueError('Not an SVG image')
        # Custom fetcher rejects HTTP, file, data, CSS imports and external <use>.
        # Inline shapes/gradients and references within this document still work.
        raster = PNGSurface.convert(bytestring=raw, unsafe=False, url_fetcher=deny_resource,
                                    output_width=SIDE, output_height=SIDE)
        image = Image.open(BytesIO(raster))
    if image.width > 8192 or image.height > 8192 or image.width * image.height > 16_777_216:
        raise ValueError('Image dimensions too large')
    image.seek(0)
    image = ImageOps.exif_transpose(image).convert('RGBA')
    image.thumbnail((SIDE, SIDE), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (SIDE, SIDE))
    canvas.alpha_composite(image, ((SIDE-image.width)//2, (SIDE-image.height)//2))
    output = BytesIO()
    canvas.save(output, format='PNG', optimize=True)
    return output.getvalue()


def main():
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128*1024, 128*1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    root = Path(sys.argv[1])
    try:
        raw = (root/'input').read_bytes()
        (root/'output.png').write_bytes(normalize(raw))
    except Exception:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
