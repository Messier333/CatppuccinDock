"""GIF validation/resizing worker; invoked only by gif_optimizer."""
import json
import math
import mmap
import os
from pathlib import Path
import resource
import subprocess
import sys

from PIL import Image

from app.services.media.backgrounds import MAX_BYTES, MAX_EDGE, MAX_FRAMES, MAX_FRAME_PIXELS, inspect_gif

MAX_INPUT_FRAMES = 2400
MAX_INPUT_PIXELS = 4_000_000_000
FRAME_PIXEL_BUDGET = 60_000_000


def scan_gif(data):
    """Read GIF blocks without decompressing pixels or trusting frame metadata."""
    if len(data) < 14 or data[:6] not in (b'GIF87a', b'GIF89a'):
        raise ValueError('올바른 GIF 파일을 선택해 주세요.')
    width, height = int.from_bytes(data[6:8], 'little'), int.from_bytes(data[8:10], 'little')
    if not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > 16_777_216:
        raise ValueError('원본 GIF 해상도가 처리 가능한 범위를 넘었습니다.')
    position = 13 + (3 * 2 ** ((data[10] & 7) + 1) if data[10] & 128 else 0)
    durations, delay = [], 100

    def subblocks(position):
        while position < len(data):
            length = data[position]; position += 1
            if not length:
                return position
            position += length
            if position > len(data):
                break
        raise ValueError('GIF 파일이 잘렸거나 손상되었습니다.')

    while position < len(data):
        block = data[position]; position += 1
        if block == 0x3B:
            if not durations or any(byte not in b'\x00 \t\r\n' for byte in data[position:]):
                break
            return width, height, durations
        if block == 0x21:
            if position >= len(data):
                break
            extension = data[position]; position += 1
            if extension == 0xF9:
                if position + 6 > len(data) or data[position] != 4 or data[position+5] != 0:
                    break
                delay = int.from_bytes(data[position+2:position+4], 'little') * 10 or 100
            position = subblocks(position)
        elif block == 0x2C:
            if position + 9 > len(data):
                break
            left = int.from_bytes(data[position:position+2], 'little')
            top = int.from_bytes(data[position+2:position+4], 'little')
            w = int.from_bytes(data[position+4:position+6], 'little')
            h = int.from_bytes(data[position+6:position+8], 'little')
            if not w or not h or left + w > width or top + h > height:
                break
            packed = data[position+8]; position += 9
            position += 3 * 2 ** ((packed & 7) + 1) if packed & 128 else 0
            if position >= len(data) or not 1 <= data[position] <= 8:
                break
            position = subblocks(position+1)
            durations.append(delay); delay = 100
            if len(durations) > MAX_INPUT_FRAMES or width * height * len(durations) > MAX_INPUT_PIXELS:
                raise ValueError('원본 GIF의 재생 길이·프레임 수가 처리 가능한 범위를 넘었습니다.')
        else:
            break
    raise ValueError('GIF 파일이 잘렸거나 손상되었습니다.')


def groups(durations, limit, fps):
    # Keep every group's first frame and sum its delays, preserving playback time.
    count = min(len(durations), max(2, min(limit, math.ceil(sum(durations) * fps / 1000))))
    # Distribute samples instead of using a fixed stride, which can freeze
    # alternating animations by repeatedly selecting the same visual frame.
    indices = [round(index * (len(durations)-1) / (count-1)) for index in range(count)] if count > 1 else [0]
    return [(index, sum(durations[index:end])) for index, end in zip(indices, indices[1:] + [len(durations)])]


def fit_size(width, height, max_width, max_height):
    scale = min(1, max_width / width, max_height / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def palette_frame(image, size, colors):
    frame = image.convert('RGBA')
    if frame.size != size:
        frame = frame.resize(size, Image.Resampling.LANCZOS)
    # Reserve one transparent index; full composited frames + disposal=2 also
    # preserve moving transparency and source restore/overlay disposal modes.
    result = frame.convert('RGB').quantize(colors=colors-1)
    palette = (result.getpalette() or [])[:765]
    result.putpalette(palette + [0] * (768-len(palette)))
    result.paste(255, mask=frame.getchannel('A').point(lambda alpha: 255 if alpha < 128 else 0))
    result.info = {'transparency': 255}
    return result


def optimize(root):
    source = root / 'input.gif'
    with source.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        width, height, durations = scan_gif(data)
    if source.stat().st_size <= MAX_BYTES and max(width, height) <= MAX_EDGE and len(durations) <= MAX_FRAMES and width * height * len(durations) <= MAX_FRAME_PIXELS:
        inspect_gif(source.read_bytes())
        return {'optimized': False}

    size = fit_size(width, height, 960, 540)
    selected = groups(durations, min(300, FRAME_PIXEL_BUDGET // (size[0] * size[1])), 12)
    wanted = {index for index, _ in selected}
    frames = []
    with Image.open(source, formats=['GIF']) as image:
        loop = image.info.get('loop')
        for index in range(len(durations)):
            image.seek(index)
            image.load()  # Decode skipped frames too: compositing and validation.
            if index in wanted:
                frames.append(palette_frame(image, size, 128))
    delays = [delay for _, delay in selected]
    output = root / 'output.gif'
    for max_width, max_height, colors, limit, fps in (
        (960, 540, 128, 300, 12), (640, 360, 64, 120, 10),
        (480, 270, 32, 96, 8), (320, 180, 32, 60, 6),
    ):
        smaller = fit_size(*frames[0].size, max_width, max_height)
        if smaller != frames[0].size or colors < 128:
            selected = groups(delays, limit, fps)
            old_frames = frames
            frames = [palette_frame(old_frames[index], smaller, colors) for index, _ in selected]
            delays = [delay for _, delay in selected]
            for frame in old_frames:
                frame.close()
        kwargs = {'loop': loop} if loop is not None else {}
        frames[0].save(output, format='GIF', save_all=True, append_images=frames[1:],
                       duration=delays, disposal=2, transparency=255, background=255,
                       optimize=False, **kwargs)
        if output.stat().st_size <= MAX_BYTES:
            inspect_gif(output.read_bytes())
            return {'optimized': True}
    raise ValueError('GIF 크기를 충분히 줄이지 못했습니다. 다른 GIF를 선택해 주세요.')


def convert_video(root):
    source=root/'input.gif'
    converted=root/'converted.gif'
    palette=root/'palette.png'
    # glibc's per-thread arenas can exhaust the inherited address-space limit
    # even for tiny videos. Bound decoder heap reservations, not just threads.
    decoder_env={**os.environ,'MALLOC_ARENA_MAX':'1'}
    common=['ffmpeg','-cpucount','1','-nostdin','-v','error','-y','-max_alloc','67108864',
            '-threads','1','-filter_threads','1','-filter_complex_threads','1',
            '-protocol_whitelist','file,pipe','-f','mov','-enable_drefs','0','-use_absolute_path','0','-i',str(source)]
    scale="fps=10,scale=w='min(640,iw)':h='min(360,ih)':force_original_aspect_ratio=decrease"
    subprocess.run(common+['-t','20','-an','-vf',scale+',palettegen=max_colors=96','-frames:v','1','-threads','1',str(palette)],
                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=25,env=decoder_env)
    subprocess.run(common+['-threads','1','-i',str(palette),'-t','20','-an','-lavfi','[0:v]'+scale+'[x];[x][1:v]paletteuse=dither=bayer',
                          '-loop','0','-threads','1',str(converted)],
                   stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=25,env=decoder_env)
    converted.replace(source)
    result=optimize(root)
    if not result['optimized']:
        source.replace(root/'output.gif')
    return {'optimized':True}


def main():
    # These limits apply only to this child, never to the API server.
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (50, 51))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128 * 1024 * 1024, 128 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    root = Path(sys.argv[1])
    try:
        result = convert_video(root) if len(sys.argv)>2 and sys.argv[2]=='video' else optimize(root)
    except Exception:
        result = {'error': 'GIF가 손상되었거나 처리 가능한 해상도·프레임 범위를 넘었습니다.'}
    (root / 'result.json').write_text(json.dumps(result))


if __name__ == '__main__':
    main()
