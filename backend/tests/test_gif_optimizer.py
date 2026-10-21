from io import BytesIO
import random
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from PIL import Image

from app.services.media import gif_optimizer
from app.services.media.backgrounds import MAX_BYTES, inspect_gif
from app.services.media.gif_worker import scan_gif
from test_backgrounds import gif


def timings(data):
    with Image.open(BytesIO(data)) as image:
        loop = image.info.get('loop')
        delays = []
        for index in range(image.n_frames):
            image.seek(index)
            delays.append(image.info.get('duration', 100))
        return loop, delays


class GifOptimizerTests(unittest.TestCase):
    def test_timeout_terminates_worker_and_its_video_decoder_process_group(self):
        process=MagicMock(pid=12345)
        process.wait.side_effect=[subprocess.TimeoutExpired('worker',60),0]
        with patch('app.services.media.gif_optimizer.subprocess.Popen',return_value=process) as spawn,patch('app.services.media.gif_optimizer.os.killpg') as terminate:
            with self.assertRaises(subprocess.TimeoutExpired):gif_optimizer.run_worker('/tmp/fixture','video')
        self.assertTrue(spawn.call_args.kwargs['start_new_session'])
        terminate.assert_called_once_with(process.pid,gif_optimizer.signal.SIGKILL)
    def test_small_valid_animation_is_byte_identical(self):
        original = gif()
        self.assertEqual(gif_optimizer.prepare_gif(original), original)
        self.assertEqual(gif_optimizer.prepare_gif(original+b'\x00\r\n'), original+b'\x00\r\n')

    def test_genuine_large_animation_is_compressed_with_duration_and_loop_preserved(self):
        rng = random.Random(42)
        frames = [Image.frombytes('P', (512, 384), rng.randbytes(512*384)) for _ in range(48)]
        for frame in frames:
            frame.putpalette([channel for color in range(256) for channel in (color, 255-color, color//2)])
        stream = BytesIO()
        frames[0].save(stream, format='GIF', save_all=True, append_images=frames[1:], duration=[80, 120]*24, loop=2, optimize=False)
        original = stream.getvalue()
        self.assertGreater(len(original), MAX_BYTES)
        output = gif_optimizer.prepare_gif(original)
        self.assertLessEqual(len(output), MAX_BYTES)
        width, height, count = inspect_gif(output)
        self.assertGreater(count, 1)
        self.assertLessEqual(width, 960); self.assertLessEqual(height, 540)
        before, after = timings(original), timings(output)
        self.assertEqual(before[0], after[0]); self.assertEqual(sum(before[1]), sum(after[1]))
        self.assertLess(len(output), len(original))
        self.assertEqual(gif_optimizer.prepare_gif(original), output)

    def test_oversized_canvas_keeps_aspect_transparency_and_once_only_playback(self):
        frames = []
        for color in ('red', 'blue', 'green'):
            image = Image.new('RGBA', (4200, 210), (0, 0, 0, 0))
            image.paste(color, (1500, 0, 2100, 210))
            frames.append(image)
        stream = BytesIO()
        frames[0].save(stream, format='GIF', save_all=True, append_images=frames[1:], duration=[100,200,300], disposal=2)
        output = gif_optimizer.prepare_gif(stream.getvalue())
        width, height, count = inspect_gif(output)
        self.assertLessEqual(width, 960); self.assertEqual(width/height, 20)
        self.assertEqual(count, 3); self.assertEqual(timings(output), (None,[100,200,300]))
        with Image.open(BytesIO(output)) as image:
            for index, color in enumerate(((255,0,0),(0,0,255),(0,128,0))):
                image.seek(index); rgba = image.convert('RGBA')
                self.assertEqual(rgba.getpixel((0,0))[3], 0)
                pixel = rgba.getpixel((width*2//5,height//2))
                self.assertEqual(pixel[:3], color); self.assertEqual(pixel[3],255)

    def test_too_many_frames_are_sampled_without_shortening_animation(self):
        frames = [Image.new('RGB', (2, 2), 'red' if index%2 else 'blue') for index in range(501)]
        stream=BytesIO();frames[0].save(stream,format='GIF',save_all=True,append_images=frames[1:],duration=100,loop=0)
        output=gif_optimizer.prepare_gif(stream.getvalue())
        self.assertLessEqual(inspect_gif(output)[2],500)
        self.assertGreater(inspect_gif(output)[2],1)
        self.assertEqual(sum(timings(output)[1]),50100)

    def test_bad_blocks_truncation_and_appended_html_are_rejected(self):
        for data in (b'<html>', gif()[:-1], gif()+b'<script/>', b'GIF89a;', gif()[:30]+b';'):
            with self.assertRaises(HTTPException) as error:
                gif_optimizer.prepare_gif(data)
            self.assertEqual(error.exception.status_code,422)
        with self.assertRaises(ValueError):
            scan_gif(b'GIF89a'+b'\xff\xff\xff\xff'+b'\x00'*10)

    def test_input_cap_busy_timeout_and_worker_failure_release_resources(self):
        with patch('app.services.media.gif_optimizer.MAX_INPUT_BYTES',10):
            with self.assertRaises(HTTPException) as error:gif_optimizer.prepare_gif(gif())
            self.assertEqual(error.exception.status_code,413)
        gif_optimizer.processing.acquire()
        try:
            with self.assertRaises(HTTPException) as error:gif_optimizer.prepare_gif(gif())
            self.assertEqual(error.exception.status_code,503)
        finally:gif_optimizer.processing.release()
        for failure in (subprocess.TimeoutExpired('worker',60),None):
            context = patch('app.services.media.gif_optimizer.run_worker', side_effect=failure) if failure else patch('app.services.media.gif_optimizer.run_worker',return_value=1)
            with context:
                with self.assertRaises(HTTPException) as error:gif_optimizer.prepare_gif(gif())
                self.assertEqual(error.exception.status_code,422)
            self.assertEqual(gif_optimizer.prepare_gif(gif()),gif())
