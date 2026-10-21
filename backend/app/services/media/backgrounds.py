"""Storage limits and validation for locally served GIF backgrounds."""
from io import BytesIO
from urllib.parse import unquote

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
MAX_INPUT_BYTES = 100 * 1024 * 1024
MAX_FILES = 20
MAX_EDGE = 4096
MAX_FRAMES = 500
MAX_FRAME_PIXELS = 200_000_000


def image_name(encoded_name):
    name = unquote(encoded_name or '', errors='replace').replace('\\', '/').rsplit('/', 1)[-1]
    return ''.join(character for character in name if character.isprintable()).strip()[:120] or 'GIF 배경'


def inspect_gif(data):
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, 'GIF는 최대 10MB까지 업로드할 수 있습니다.')
    # Some valid GIF encoders append NUL padding after the GIF trailer.
    if data[:6] not in (b'GIF87a', b'GIF89a') or data.rstrip(b'\x00 \t\r\n')[-1:] != b';':
        raise HTTPException(422, '올바른 GIF 파일을 선택해 주세요.')
    try:
        with Image.open(BytesIO(data), formats=['GIF']) as image:
            width, height = image.size
            frames, pixels = 0, 0
            while True:
                w, h = image.size
                frames += 1
                pixels += w*h
                if not 0 < w <= MAX_EDGE or not 0 < h <= MAX_EDGE or frames > MAX_FRAMES or pixels > MAX_FRAME_PIXELS:
                    raise HTTPException(422, 'GIF 해상도 또는 프레임 수가 너무 큽니다. 크기나 재생 길이를 줄여 주세요.')
                image.load()
                try:
                    image.seek(frames)
                except EOFError:
                    break
            return width, height, frames
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        raise HTTPException(422, 'GIF 파일을 읽을 수 없습니다. 손상되지 않은 GIF를 선택해 주세요.') from error
