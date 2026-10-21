"""Prepare untrusted GIFs in a bounded, disposable worker process."""
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from fastapi import HTTPException

from app.services.media.backgrounds import MAX_BYTES, MAX_INPUT_BYTES

processing = BoundedSemaphore(1)
WORKER_TIMEOUT = 60


def prepare_gif(data):
    return prepare(data,'gif')


def prepare_video(data):
    return prepare(data,'video')


def run_worker(directory, mode):
    process=subprocess.Popen([sys.executable,'-m','app.services.media.gif_worker',directory,mode],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        process.wait(timeout=WORKER_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Kill the entire worker group, including a running video decoder.
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait()
        raise
    return process.returncode


def prepare(data,mode):
    if not data or len(data) > MAX_INPUT_BYTES:
        raise HTTPException(413, '원본 GIF는 최대 100MB까지 가져올 수 있습니다.')
    if not processing.acquire(blocking=False):
        raise HTTPException(503, '다른 GIF를 최적화하고 있습니다. 잠시 후 다시 시도해 주세요.')
    try:
        with TemporaryDirectory(prefix='dock-gif-') as directory:
            root = Path(directory)
            (root / 'input.gif').write_bytes(data)
            try:
                returncode = run_worker(directory,mode)
            except subprocess.TimeoutExpired as error:
                raise HTTPException(422, 'GIF 최적화 시간이 초과되었습니다. 더 짧은 GIF를 선택해 주세요.') from error
            if returncode or not (root / 'result.json').exists():
                raise HTTPException(422, 'GIF가 손상되었거나 처리 가능한 해상도·프레임 범위를 넘었습니다.')
            info = json.loads((root / 'result.json').read_text())
            if info.get('error'):
                raise HTTPException(422, info['error'])
            if info['optimized']:
                output = root / 'output.gif'
                if not output.exists() or output.stat().st_size > MAX_BYTES:
                    raise HTTPException(422, 'GIF 크기를 충분히 줄이지 못했습니다. 다른 GIF를 선택해 주세요.')
                return output.read_bytes()
            return data
    finally:
        processing.release()
