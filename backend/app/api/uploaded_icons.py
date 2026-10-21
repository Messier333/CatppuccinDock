import asyncio
from threading import BoundedSemaphore
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import require_mutation_header, require_user
from app.db.models import UploadedIcon, User
from app.db.session import SessionLocal
from app.services.auth import record_attempt
from app.services.media import media_policy, storage, uploaded_icons as icons

router = APIRouter(prefix='/api/uploaded-icons')
upload_slot = BoundedSemaphore(1)


@router.get('')
def listing(q: str = Query('', max_length=80), user: User = Depends(require_user)):
    with SessionLocal() as db:
        rows = db.scalars(select(UploadedIcon).where(UploadedIcon.user_id == user.id).order_by(UploadedIcon.created_at.desc()))
        items = [icons.metadata(db, row) for row in rows if q.lower() in row.name.lower()]
        return {'items': items, 'limits': {'max_files': icons.MAX_FILES, 'max_input_bytes': icons.MAX_INPUT, 'size': 128}}


def save(user, raw, name):
    normalized = icons.prepare(raw)
    with SessionLocal.begin() as db:
        media_policy.policy(db, locked=True)
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        return icons.metadata(db, icons.store(db, user, normalized, name))


@router.post('', dependencies=[Depends(require_mutation_header)])
async def upload(request: Request, user: User = Depends(require_user)):
    await run_in_threadpool(record_attempt, request, 'icon-upload:'+str(user.id))
    if not upload_slot.acquire(blocking=False):
        raise HTTPException(503, '다른 아이콘을 업로드하고 있어요. 잠시 후 다시 시도해 주세요.')
    try:
        return await receive_upload(request, user)
    finally:
        upload_slot.release()


async def receive_upload(request, user):
    length = request.headers.get('content-length', '')
    if length.isdecimal() and int(length) > icons.MAX_INPUT:
        raise HTTPException(413, '아이콘 원본은 최대 5MB까지 업로드할 수 있습니다.')
    data = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(data)+len(chunk) > icons.MAX_INPUT:
                    raise HTTPException(413, '아이콘 원본은 최대 5MB까지 업로드할 수 있습니다.')
                data.extend(chunk)
    except TimeoutError as error:
        raise HTTPException(408, '아이콘 업로드 시간이 초과됐어요.') from error
    return await run_in_threadpool(save, user, bytes(data), request.headers.get('x-file-name', ''))


@router.get('/{identifier}/content')
def content(identifier: UUID, request: Request, user: User = Depends(require_user)):
    with SessionLocal() as db:
        row = icons.find(db, 'upload:'+str(identifier), user)
        headers = {'ETag': '"'+row.sha256+'"', 'Cache-Control':'private, no-cache', 'Vary':'Cookie',
            'Content-Disposition':'inline; filename="icon.png"', 'Content-Security-Policy':"default-src 'none'; sandbox"}
        supplied = [value.strip().removeprefix('W/') for value in request.headers.get('if-none-match', '').split(',')]
        if headers['ETag'] in supplied or '*' in supplied:
            return Response(status_code=304, headers=headers)
        return Response(storage.read(row), media_type='image/png', headers=headers)


@router.delete('/{identifier}', dependencies=[Depends(require_mutation_header)])
def remove(identifier: UUID, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        row = icons.find(db, 'upload:'+str(identifier), user, locked=True, owned=True)
        used, in_trash = icons.references(db, row)
        if used or in_trash:
            raise HTTPException(409, '북마크·공개 링크·휴지통에서 사용 중인 아이콘입니다. 먼저 다른 아이콘으로 변경해 주세요.')
        storage.queue_delete(db, row); db.delete(row)
    return {'ok': True}
