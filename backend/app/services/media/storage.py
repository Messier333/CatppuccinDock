"""Private S3-compatible media storage, with reads for pre-migration DB files."""
import hashlib
import logging
import os
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import uuid4

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db.models import BackgroundImage, MediaObjectDeletion, UploadedIcon
from app.db.session import SessionLocal
from app.services.media.backgrounds import MAX_BYTES

logger = logging.getLogger(__name__)
ERRORS = (BotoCoreError, ClientError, OSError, ValueError)


def backend():
    value = os.getenv('MEDIA_STORAGE_BACKEND', 'database')
    if value not in ('database', 's3'):
        raise RuntimeError('MEDIA_STORAGE_BACKEND must be database or s3')
    return value


def configuration():
    values = tuple(os.getenv(key, '') for key in ('S3_ENDPOINT_URL', 'S3_REGION', 'S3_ACCESS_KEY_ID', 'S3_SECRET_ACCESS_KEY', 'S3_BUCKET'))
    endpoint, region, access, secret, bucket = values
    parsed = urlsplit(endpoint)
    if not all(values) or parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError('S3 endpoint, region, access key, secret key and bucket must be configured')
    return values


@lru_cache(maxsize=2)
def _client(endpoint, region, access, secret, bucket):
    # Explicit credentials never fall through to the host's AWS/instance profile.
    # Path addressing and non-streaming checksums work with Garage and AWS S3.
    return boto3.client('s3', endpoint_url=endpoint, region_name=region,
        aws_access_key_id=access, aws_secret_access_key=secret,
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
            connect_timeout=3, read_timeout=10, retries={'mode': 'standard', 'total_max_attempts': 2},
            request_checksum_calculation='when_required', response_checksum_validation='when_required'))


def client():
    return _client(*configuration())


def unavailable(error):
    # Do not expose endpoint URLs, signed requests or credentials in API errors.
    return HTTPException(503, '파일 저장소에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.')


def check():
    if backend() == 's3':
        try:
            client().head_bucket(Bucket=configuration()[4])
        except ERRORS as error:
            raise unavailable(error) from error


def read(image):
    if image.storage_key:
        try:
            response = client().get_object(Bucket=image.storage_bucket, Key=image.storage_key)
            stream = response['Body']
            try:
                raw = stream.read(MAX_BYTES + 1)
            finally:
                stream.close()
        except ERRORS as error:
            raise unavailable(error) from error
    else:
        raw = image.data
    if raw is None or len(raw) != image.byte_size or len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != image.sha256:
        raise HTTPException(503, '저장된 파일의 무결성을 확인하지 못했어요.')
    return raw


def write(db, image, raw, *, verify=False, namespace='backgrounds', extension='gif', content_type='image/gif'):
    if backend() != 's3':
        image.data = raw
        return
    bucket = configuration()[4]
    prefix = os.getenv('S3_KEY_PREFIX', 'catppuccindock').strip('/')
    if not prefix or len(prefix) > 300 or any(part in ('.', '..') for part in prefix.split('/')):
        raise RuntimeError('S3_KEY_PREFIX must be a non-empty object namespace')
    key = f'{prefix}/{namespace}/{image.user_id}/{uuid4()}.{extension}'
    # Unique immutable keys prevent a rolled-back write from affecting another
    # row, account, or a simultaneous upload of the same content.
    db.info.setdefault('media_uploads', []).append((bucket, key))
    try:
        client().put_object(Bucket=bucket, Key=key, Body=raw, ContentLength=len(raw), ContentType=content_type,
            Metadata={'sha256': image.sha256})
    except ERRORS as error:
        raise unavailable(error) from error
    image.storage_bucket, image.storage_key = bucket, key
    if verify:
        read(image)  # Full read + byte length + SHA-256 before dropping DB bytes.
    image.data = None


def queue_delete(db, image):
    if image.storage_key:
        db.add(MediaObjectDeletion(bucket=image.storage_bucket, object_key=image.storage_key))


def cleanup(limit=20):
    """Delete only committed tombstones. An unavailable store leaves them queued."""
    with SessionLocal.begin() as db:
        rows = db.scalars(select(MediaObjectDeletion).order_by(MediaObjectDeletion.created_at).limit(limit).with_for_update(skip_locked=True))
        for row in rows:
            # A referenced key is never eligible, even for a stale/forged queue.
            if any(db.scalar(select(model.id).where(model.storage_bucket == row.bucket, model.storage_key == row.object_key).limit(1)) for model in (BackgroundImage, UploadedIcon)):
                db.delete(row)
                continue
            try:
                client().delete_object(Bucket=row.bucket, Key=row.object_key)
            except ERRORS:
                logger.warning('Media deletion deferred: storage unavailable')
                break
            db.delete(row)


@event.listens_for(Session, 'after_commit')
def committed(session):
    session.info.pop('media_uploads', None)


@event.listens_for(Session, 'after_rollback')
def rolled_back(session):
    session.info.setdefault('media_failed_uploads', []).extend(session.info.pop('media_uploads', []))


@event.listens_for(Session, 'after_transaction_end')
def transaction_ended(session, transaction):
    if transaction.parent is not None:
        return
    uploads = session.info.pop('media_failed_uploads', [])
    if uploads:
        # Persist after the failed transaction releases its locks. Object writes
        # have unique keys, so retrying their removal cannot erase another file.
        try:
            with SessionLocal.begin() as db:
                db.add_all(MediaObjectDeletion(bucket=bucket, object_key=key) for bucket, key in uploads)
        except Exception:
            logger.warning('Unreferenced media upload cleanup could not be queued')
