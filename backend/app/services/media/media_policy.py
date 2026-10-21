"""Durable admission, byte reservations and verified reuse for GIF transfers."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import time
from threading import RLock
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.core.security import cipher
from app.db.models import BackgroundAssetKey, BackgroundImage, BackgroundTransfer, Setting, User
from app.db.session import SessionLocal
from app.schemas.media_policy import MediaPolicy
from app.services.media.backgrounds import MAX_FILES, MAX_INPUT_BYTES

MIB = 1024*1024
POLICY_KEY = 'media-policy'
mutex = RLock()
clock = time.time


def defaults():
    return MediaPolicy().model_dump() | {'pixabay_key_encrypted': ''}


def policy(db, locked=False):
    query = select(Setting).where(Setting.key == POLICY_KEY)
    row = db.scalar(query.with_for_update() if locked else query)
    return defaults() | (row.value if row else {})


def public_settings(config):
    return {key: config[key] for key in MediaPolicy.model_fields} | {'has_pixabay_key': bool(config.get('pixabay_key_encrypted'))}


def provider_key(name):
    with SessionLocal() as db:
        token = policy(db).get(name+'_key_encrypted')
    return cipher().decrypt(token.encode()).decode() if token else ''


def daily_start(db, now):
    row = db.get(Setting, 'portal')
    timezone = (row.value.get('clock', {}).get('timezone') if row else None) or 'Asia/Seoul'
    zone = ZoneInfo(timezone)
    today = datetime.fromtimestamp(now, zone).replace(hour=0, minute=0, second=0, microsecond=0)
    return today.timestamp(), timezone


def totals(db, user_id, start):
    where = [BackgroundTransfer.created_at >= start]
    if user_id is not None:
        where.append(BackgroundTransfer.user_id == user_id)
    return db.execute(select(func.count(), func.coalesce(func.sum(BackgroundTransfer.charged_bytes), 0)).where(*where)).one()


def stored(db, user_id=None):
    query = select(func.count(), func.coalesce(func.sum(BackgroundImage.byte_size), 0))
    if user_id is not None:
        query = query.where(BackgroundImage.user_id == user_id)
    return db.execute(query).one()


def ensure_permission(user, kind, config):
    if user.role != 'admin' and not config['member_'+kind]:
        raise HTTPException(403, '관리자가 일반 사용자의 GIF '+('가져오기' if kind == 'import' else '업로드')+'를 비활성화했습니다. 저장된 GIF를 선택해 주세요.')


def usage(db, user):
    config = policy(db); now = clock(); start, timezone = daily_start(db, now)
    count, size = totals(db, user.id, start); files, storage = stored(db, user.id)
    member = user.role != 'admin'
    return {'today_count': count, 'today_bytes': size, 'stored_bytes': storage,
            'daily_count_limit': config['member_per_day'] if member else None,
            'daily_bytes_limit': config['member_daily_mb']*MIB if member else None,
            'storage_bytes_limit': config['member_storage_mb']*MIB if member else MAX_FILES*10*MIB,
            'allow_import': not member or config['member_import'], 'allow_upload': not member or config['member_upload'],
            'timezone': timezone, 'max_files': MAX_FILES}


def check_storage(db, user, config, extra=0):
    files, size = stored(db, user.id)
    if files >= MAX_FILES:
        raise HTTPException(409, '저장된 GIF가 20개입니다. 새 파일을 가져오기 전에 사용하지 않는 GIF를 삭제해 주세요.')
    if user.role != 'admin' and (size+extra > config['member_storage_mb']*MIB or (not extra and size >= config['member_storage_mb']*MIB)):
        raise HTTPException(409, '개인 GIF 저장 용량이 부족합니다. 사용하지 않는 GIF를 삭제해 주세요.')
    total = stored(db)[1]
    if total+extra > config['server_storage_mb']*MIB or (not extra and total >= config['server_storage_mb']*MIB):
        raise HTTPException(409, '서버의 GIF 저장 용량이 부족합니다. 관리자에게 문의해 주세요.')


class Transfer:
    def __init__(self, identifier, limit):
        self.id, self.limit, self.received = identifier, limit, 0

    def progress(self, amount):
        self.received += amount


@contextmanager
def transfer(user, kind, *, cached=False):
    now = clock()
    # PostgreSQL's policy row serializes reservations across users/processes.
    # The process lock also makes SQLite's no-op FOR UPDATE safe in tests.
    with mutex, SessionLocal.begin() as db:
        config = policy(db, locked=True)
        current = db.get(User, user.id)
        ensure_permission(current, kind, config)
        check_storage(db, current, config)
        start, _ = daily_start(db, now)
        count, size = totals(db, user.id, start)
        global_count, global_size = totals(db, None, start)
        limit = min(MAX_INPUT_BYTES, config['server_daily_mb']*MIB-global_size)
        if current.role != 'admin':
            recent = db.scalar(select(func.count()).select_from(BackgroundTransfer).where(BackgroundTransfer.user_id==user.id, BackgroundTransfer.created_at > now-60))
            if recent >= config['member_per_minute']:
                raise HTTPException(429, 'GIF 추가는 잠시 간격을 두고 시도해 주세요.', headers={'Retry-After':'60'})
            if count >= config['member_per_day']:
                raise HTTPException(429, '오늘의 GIF 추가 횟수를 모두 사용했습니다. 삭제해도 사용량은 초기화되지 않습니다.')
            limit = min(limit, config['member_daily_mb']*MIB-size)
        if global_count >= config['server_per_day'] or (not cached and limit <= 0):
            raise HTTPException(429, '오늘의 GIF 다운로드 한도에 도달했습니다. 다음 날 다시 시도해 주세요.')
        active = db.scalar(select(BackgroundTransfer.id).where(BackgroundTransfer.pending.is_(True), BackgroundTransfer.expires_at > now).limit(1))
        if active:
            raise HTTPException(503, '다른 GIF를 처리하고 있습니다. 잠시 후 다시 시도해 주세요.', headers={'Retry-After':'5'})
        db.execute(delete(BackgroundTransfer).where(BackgroundTransfer.created_at < start-8*86400))
        row = BackgroundTransfer(user_id=user.id, kind=kind, created_at=now, expires_at=now+300, charged_bytes=0 if cached else limit)
        db.add(row); db.flush()
        job = Transfer(row.id, max(0,limit))
    try:
        yield job
    finally:
        with mutex, SessionLocal.begin() as db:
            policy(db, locked=True)
            row = db.get(BackgroundTransfer, job.id)
            if row:
                row.pending = False
                row.charged_bytes = min(job.limit, job.received)


def asset_key(provider, item_id):
    return provider+':'+item_id


def cached_image(db, user_id, key, *, public=False):
    query = select(BackgroundImage).join(BackgroundAssetKey, BackgroundAssetKey.image_id==BackgroundImage.id).where(BackgroundAssetKey.key==key)
    if not public:
        query = query.where(BackgroundAssetKey.user_id==user_id)
    return db.scalar(query.order_by(BackgroundImage.created_at).limit(1))


def remember_asset(db, user_id, key, image_id):
    row = db.get(BackgroundAssetKey,(user_id,key))
    if row:
        row.image_id = image_id
    else:
        db.add(BackgroundAssetKey(user_id=user_id,key=key,image_id=image_id))


def raw_key(data):
    return 'sha256:'+hashlib.sha256(data).hexdigest()
