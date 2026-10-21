import asyncio
import hashlib
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import require_mutation_header, require_user
from app.db.models import BackgroundImage, Tab, TrashItem, User
from app.db.session import SessionLocal
from app.services.media.backgrounds import MAX_BYTES, MAX_INPUT_BYTES, MAX_FILES, image_name, inspect_gif
from app.services.media.gif_optimizer import prepare_gif, prepare_video
from app.schemas.backgrounds import BackgroundImport, GifSearchProvider
from app.services.media import gif_search, media_policy, storage

router = APIRouter(prefix='/api/backgrounds')
UPLOAD_TIMEOUT = 120


def metadata(image, used_by=0):
    return {key: getattr(image, key) for key in ('id', 'name', 'byte_size', 'width', 'height', 'frames', 'source')} | {'used_by': used_by}


def find_owned(db, image_id, user_id):
    row = db.scalar(select(BackgroundImage).where(BackgroundImage.id == str(image_id), BackgroundImage.user_id == user_id))
    if not row:
        raise HTTPException(404, 'GIF 배경을 찾을 수 없습니다.')
    return row


@router.get('')
def images(user: User = Depends(require_user)):
    with SessionLocal() as db:
        usage = dict(db.execute(select(Tab.background_id, func.count()).where(Tab.user_id == user.id, Tab.background_id.is_not(None)).group_by(Tab.background_id)).all())
        rows = db.scalars(select(BackgroundImage).where(BackgroundImage.user_id == user.id).order_by(BackgroundImage.created_at.desc(), BackgroundImage.id))
        return {'items': [metadata(row, usage.get(row.id, 0)) for row in rows], 'limits': {'max_bytes': MAX_BYTES, 'max_input_bytes': MAX_INPUT_BYTES, 'max_files': MAX_FILES}, 'usage': media_policy.usage(db,user)}


def store_image(user_id, data, encoded_name, source=None, *, key=None, prepared=False):
    raw_key = media_policy.raw_key(data)
    with SessionLocal() as db:
        existing = media_policy.cached_image(db,user_id,raw_key)
        if existing and not source:
            used_by = db.scalar(select(func.count()).select_from(Tab).where(Tab.background_id==existing.id,Tab.user_id==user_id))
            return metadata(existing,used_by)
    if not prepared:
        data = prepare_gif(data)
    width, height, frames = inspect_gif(data)
    digest = hashlib.sha256(data).hexdigest()
    with SessionLocal.begin() as db:
        config = media_policy.policy(db,locked=True)
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        existing = db.scalar(select(BackgroundImage).where(BackgroundImage.user_id == user_id, BackgroundImage.sha256 == digest))
        if existing:
            if source and not existing.source:
                existing.source = source
            media_policy.remember_asset(db,user_id,raw_key,existing.id)
            if key:
                media_policy.remember_asset(db,user_id,key,existing.id)
            used_by = db.scalar(select(func.count()).select_from(Tab).where(Tab.user_id == user_id, Tab.background_id == existing.id))
            return metadata(existing, used_by)
        count = db.scalar(select(func.count()).select_from(BackgroundImage).where(BackgroundImage.user_id == user_id))
        if count >= MAX_FILES:
            raise HTTPException(409, 'GIF는 사용자별 최대 20개까지 저장할 수 있습니다. 사용하지 않는 배경을 삭제해 주세요.')
        media_policy.check_storage(db,user,config,len(data))
        row = BackgroundImage(user_id=user_id, name=image_name(encoded_name), sha256=digest, byte_size=len(data), width=width, height=height, frames=frames, source=source)
        storage.write(db, row, data)
        db.add(row)
        db.flush()
        media_policy.remember_asset(db,user_id,raw_key,row.id)
        if key:
            media_policy.remember_asset(db,user_id,key,row.id)
        return metadata(row)


@router.get('/providers')
def providers(user: User = Depends(require_user)):
    configured=bool(media_policy.provider_key('pixabay'))
    return {'items':[{'value':'all','label':'통합 검색'},*({'value':key,'label':name,'disabled':key=='pixabay' and not configured} for key,name in gif_search.PROVIDERS.items())]}


@router.get('/search')
def search(provider: GifSearchProvider = 'all', q: str = Query(default='', max_length=80),
           page: int = Query(default=1, ge=1, le=20), user: User = Depends(require_user)):
    query = q.strip()
    if not query:
        return {'items': [], 'page': page, 'has_more': False, 'provider': provider}
    gif_search.check_budget(user.id, 'search')
    try:
        return gif_search.search(provider, query, page)
    except gif_search.NETWORK_ERRORS as error:
        raise gif_search.public_error(error) from error


@router.post('/import', dependencies=[Depends(require_mutation_header)])
def import_gif(payload: BackgroundImport, user: User = Depends(require_user)):
    key = media_policy.asset_key(payload.provider,payload.item_id)
    cached = None
    with SessionLocal() as db:
        media_policy.ensure_permission(user,'import',media_policy.policy(db))
        existing = media_policy.cached_image(db,user.id,key)
        if existing:
            used_by = db.scalar(select(func.count()).select_from(Tab).where(Tab.background_id==existing.id,Tab.user_id==user.id))
            return metadata(existing,used_by)
        existing = media_policy.cached_image(db,user.id,key,public=True)
        if existing:
            cached = existing.id
    with media_policy.transfer(user,'import',cached=cached is not None) as job:
        if cached:
            with SessionLocal() as db:
                image=db.get(BackgroundImage,cached)
                if not image:
                    raise HTTPException(409,'저장된 GIF 목록이 변경됐습니다. 다시 선택해 주세요.')
                data,name,source=storage.read(image),image.source['title'] if image.source else image.name,image.source
        else:
            try:
                data, name, source = gif_search.download(payload.provider, payload.item_id,max_bytes=job.limit,on_chunk=job.progress)
                # Also account for provider adapters/mocked fetchers that return
                # a complete body without invoking the incremental callback.
                job.received = max(job.received,len(data))
            except gif_search.NETWORK_ERRORS as error:
                raise gif_search.public_error(error) from error
        if payload.provider=='pixabay' and not cached:
            data=prepare_video(data)
        return store_image(user.id,data,quote(name,safe=''),source,key=key,prepared=cached is not None or payload.provider=='pixabay')


@router.post('', dependencies=[Depends(require_mutation_header)])
async def upload(request: Request, user: User = Depends(require_user)):
    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() not in ('image/gif', 'application/octet-stream'):
        raise HTTPException(415, 'GIF 파일만 업로드할 수 있습니다.')
    length = request.headers.get('content-length')
    if length and length.isdecimal() and int(length) > MAX_INPUT_BYTES:
        raise HTTPException(413, '원본 GIF는 최대 100MB까지 업로드할 수 있습니다.')
    admission = media_policy.transfer(user,'upload')
    job = await run_in_threadpool(admission.__enter__)
    try:
        if length and length.isdecimal() and int(length) > job.limit:
            raise HTTPException(429, '오늘 남은 GIF 용량보다 큰 파일입니다.')
        data = bytearray()
        try:
            async with asyncio.timeout(UPLOAD_TIMEOUT):
                async for chunk in request.stream():
                    job.progress(len(chunk))
                    if len(data) + len(chunk) > min(MAX_INPUT_BYTES,job.limit):
                        raise HTTPException(413, 'GIF 파일이 허용된 업로드 용량을 넘었습니다.')
                    data.extend(chunk)
        except TimeoutError as error:
            raise HTTPException(408,'GIF 업로드 시간이 초과되었습니다. 다시 시도해 주세요.') from error
        return await run_in_threadpool(store_image, user.id, bytes(data), request.headers.get('x-file-name', ''))
    finally:
        await run_in_threadpool(admission.__exit__,None,None,None)


@router.get('/{image_id}/content')
def content(image_id: UUID, request: Request, user: User = Depends(require_user)):
    with SessionLocal() as db:
        row = find_owned(db, image_id, user.id)
        etag = '"'+row.sha256+'"'
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache', 'Vary': 'Cookie',
                   'Content-Disposition': 'inline; filename="background.gif"',
                   'Content-Security-Policy': "default-src 'none'; sandbox"}
        supplied = [value.strip().removeprefix('W/') for value in request.headers.get('if-none-match', '').split(',')]
        if etag in supplied or '*' in supplied:
            return Response(status_code=304, headers=headers)
        return Response(content=storage.read(row), media_type='image/gif', headers=headers)


@router.delete('/{image_id}', dependencies=[Depends(require_mutation_header)])
def delete_image(image_id: UUID, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        row = find_owned(db, image_id, user.id)
        if db.scalar(select(func.count()).select_from(Tab).where(Tab.background_id == row.id)):
            raise HTTPException(409, '탭에서 사용 중인 GIF입니다. 먼저 해당 탭의 배경을 바꾸고 저장해 주세요.')
        from app.services.trash import references_image
        import time
        if any(references_image(item.snapshot, row.id) for item in db.scalars(select(TrashItem).where(TrashItem.user_id==user.id, TrashItem.expires_at > time.time()))):
            raise HTTPException(409, '휴지통의 탭에서 사용한 GIF입니다. 해당 항목을 복원하거나 영구 삭제한 뒤 다시 시도해 주세요.')
        storage.queue_delete(db, row)
        db.delete(row)
    return {'ok': True}
