"""Owned, normalized icon assets and permission-aware shared-link previews."""
import hashlib
from io import BytesIO
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
import time
from urllib.parse import unquote
from uuid import UUID

from fastapi import HTTPException
from PIL import Image
from sqlalchemy import String, cast, func, select

from app.db.models import Bookmark, SharedLink, SharedPlacement, TrashItem, UploadedIcon
from app.services.library import allowed_link_ids
from app.services.media import storage

MAX_INPUT = 5*1024*1024
MAX_BYTES = 96*1024
MAX_FILES = 100
SERVER_BYTES = 128*1024*1024
processing = BoundedSemaphore(1)


def icon_id(name):
    if not name.startswith('upload:'):
        return None
    try:
        value = str(UUID(name[7:]))
        if name != 'upload:'+value:
            raise ValueError()
        return value
    except ValueError as error:
        raise HTTPException(422, '올바른 업로드 아이콘을 선택해 주세요.') from error


def prepare(raw):
    if not raw or len(raw) > MAX_INPUT:
        raise HTTPException(413, '아이콘 원본은 최대 5MB까지 업로드할 수 있습니다.')
    if not processing.acquire(blocking=False):
        raise HTTPException(503, '다른 아이콘을 처리하고 있어요. 잠시 후 다시 시도해 주세요.')
    try:
        with TemporaryDirectory(prefix='dock-icon-') as directory:
            root = Path(directory); (root/'input').write_bytes(raw)
            try:
                result = subprocess.run([sys.executable, '-m', 'app.services.media.icon_worker', directory],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            except subprocess.TimeoutExpired as error:
                raise HTTPException(422, '아이콘 처리 시간이 초과됐어요. 더 작은 파일을 선택해 주세요.') from error
            output = root/'output.png'
            if result.returncode or not output.exists() or output.stat().st_size > MAX_BYTES:
                raise HTTPException(422, '이미지를 읽을 수 없어요. PNG·JPG·WebP·SVG·ICO·GIF 파일을 확인해 주세요. SVG의 외부 리소스는 지원하지 않습니다.')
            data = output.read_bytes(); inspect(data); return data
    finally:
        processing.release()


def inspect(raw):
    if len(raw) > MAX_BYTES or len(raw) < 24 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR' or raw[16:24] != b'\x00\x00\x00\x80\x00\x00\x00\x80':
        raise ValueError('Icon too large')
    with Image.open(BytesIO(raw)) as image:
        if image.format != 'PNG' or image.size != (128, 128) or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Not a normalized icon')
        image.verify()
    with Image.open(BytesIO(raw)) as image:
        image.load()


def accessible(db, row, user):
    if row.user_id == user.id:
        return True
    name = 'upload:'+row.id
    links = select(SharedLink.id).where(SharedLink.icon == name)
    if user.role == 'admin' and db.scalar(links.limit(1)):
        return True
    allowed = allowed_link_ids(db, user)
    if db.scalar(links.where(SharedLink.id.in_(allowed)).limit(1)):
        return True
    # A user may have customized the placement while its source remains allowed.
    return bool(db.scalar(select(Bookmark.id).join(SharedPlacement, SharedPlacement.bookmark_id == Bookmark.id)
        .where(Bookmark.user_id == user.id, Bookmark.icon == name, SharedPlacement.link_id.in_(allowed)).limit(1)))


def find(db, name, user, *, locked=False, owned=False):
    identifier = icon_id(name)
    query = select(UploadedIcon).where(UploadedIcon.id == identifier)
    if locked:
        query = query.with_for_update()
    row = db.scalar(query)
    if not row or (row.user_id != user.id if owned else not accessible(db, row, user)):
        raise HTTPException(404, '사용할 수 있는 업로드 아이콘을 찾을 수 없습니다.')
    return row


def references(db, row):
    name = 'upload:'+row.id
    count = db.scalar(select(func.count()).select_from(Bookmark).where(Bookmark.icon == name))
    count += db.scalar(select(func.count()).select_from(SharedLink).where(SharedLink.icon == name))
    in_trash = bool(db.scalar(select(TrashItem.id).where(TrashItem.expires_at > time.time(), cast(TrashItem.snapshot, String).contains('"'+name+'"')).limit(1)))
    return count, in_trash


def metadata(db, row):
    count, in_trash = references(db, row)
    return {'id': row.id, 'icon': 'upload:'+row.id, 'name': row.name, 'byte_size': row.byte_size,
            'used_by': count, 'in_trash': in_trash}


def store(db, user, raw, name):
    inspect(raw)
    digest = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(select(UploadedIcon).where(UploadedIcon.user_id == user.id, UploadedIcon.sha256 == digest))
    if existing:
        return existing
    count = db.scalar(select(func.count()).select_from(UploadedIcon).where(UploadedIcon.user_id == user.id))
    if count >= MAX_FILES:
        raise HTTPException(409, '업로드 아이콘은 계정별 최대 100개입니다. 사용하지 않는 아이콘을 삭제해 주세요.')
    size = db.scalar(select(func.coalesce(func.sum(UploadedIcon.byte_size), 0)))
    if size+len(raw) > SERVER_BYTES:
        raise HTTPException(409, '서버의 업로드 아이콘 저장 한도에 도달했습니다.')
    safe_name = ''.join(character for character in unquote(name) if ord(character) >= 32 and ord(character) != 127)
    filename = ' '.join(safe_name.replace('\\', '/').rsplit('/', 1)[-1].split())[:120] or '업로드 아이콘'
    row = UploadedIcon(user_id=user.id, name=filename, sha256=digest, byte_size=len(raw))
    storage.write(db, row, raw, namespace='icons', extension='png', content_type='image/png')
    db.add(row); db.flush(); return row
