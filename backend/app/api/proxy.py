import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select

from app.api.dependencies import require_admin, require_mutation_header
from app.core.security import cipher
from app.db.models import Bookmark, Category, ProxyPreview, ProxySource, ProxySync, Setting, SharedLink, User
from app.db.session import SessionLocal
from app.schemas.proxy import ImportData, PreviewData, SourceData
from app.services.proxy import fetch_hosts, normalize_hosts, public_source, url_key


router = APIRouter(prefix='/api/admin/proxy-sources', dependencies=[Depends(require_admin)])


def find_source(db, source_id):
    source = db.scalar(select(ProxySource).where(ProxySource.id == source_id).with_for_update())
    if not source:
        raise HTTPException(404, '등록된 서비스를 찾을 수 없습니다.')
    return source


@router.get('')
def sources():
    with SessionLocal() as db:
        return [public_source(row) for row in db.scalars(select(ProxySource).order_by(ProxySource.name))]


@router.get('/providers')
def providers():
    return [{'id': 'npm', 'name': 'Nginx Proxy Manager', 'short_name': 'NPM'},
            {'id': 'npg', 'name': 'Nginx Proxy Guard', 'short_name': 'NPG'},
            {'id': 'zoraxy', 'name': 'Zoraxy', 'short_name': 'Zoraxy'}]


def write_source(db, payload, source=None):
    needs_token = payload.custom_api is None or payload.custom_api.auth_type != 'none'
    auth_changed = source is not None and (source.custom_api or {}).get('auth_type') != (payload.custom_api.auth_type if payload.custom_api else None)
    if needs_token and payload.token is None and (source is None or not source.token_encrypted or source.provider != payload.provider or source.base_url != payload.base_url or auth_changed or (source.custom_api or {}).get('auth_header') != (payload.custom_api.auth_header if payload.custom_api else None)):
        raise HTTPException(422, '새 서비스 또는 변경된 API 주소에는 토큰을 다시 입력해 주세요.')
    if source is None:
        source = ProxySource()
        db.add(source)
    for key, value in payload.model_dump(exclude={'token'}).items():
        setattr(source, key, value)
    if payload.token is not None:
        source.token_encrypted = cipher().encrypt(payload.token.encode()).decode()
    if not needs_token:
        source.token_encrypted = ''
    source.revision = secrets.token_hex(16)
    sync = db.get(ProxySync, source.id) if source.id else None
    if sync:
        sync.revision = secrets.token_hex(16); sync.next_check = 0; sync.checked_at = None; sync.inventory = []
    db.flush()
    return public_source(source)


@router.post('', dependencies=[Depends(require_mutation_header)])
def add_source(payload: SourceData):
    with SessionLocal.begin() as db:
        return write_source(db, payload)


@router.put('/{source_id}', dependencies=[Depends(require_mutation_header)])
def edit_source(source_id: str, payload: SourceData):
    with SessionLocal.begin() as db:
        return write_source(db, payload, find_source(db, source_id))


@router.delete('/{source_id}', dependencies=[Depends(require_mutation_header)])
def remove_source(source_id: str):
    with SessionLocal.begin() as db:
        source = find_source(db, source_id)
        db.execute(delete(ProxyPreview).where(ProxyPreview.source_id == source_id))
        db.execute(delete(ProxySync).where(ProxySync.source_id == source_id))
        for link in db.scalars(select(SharedLink).where(SharedLink.source_id == source_id)):
            link.source_id = None
        db.flush()
        db.delete(source)
    return {'ok': True}


@router.post('/{source_id}/preview', dependencies=[Depends(require_mutation_header)])
def preview(source_id: str, payload: PreviewData, user: User = Depends(require_admin)):
    with SessionLocal() as db:
        source = find_source(db, source_id)
        # No transaction/row locks are held during the upstream network call.
        db.expunge(source)
    entries, skipped = normalize_hosts(source.provider, fetch_hosts(source), payload, source.custom_api)
    preview_id = secrets.token_urlsafe(24)
    with SessionLocal.begin() as db:
        current = find_source(db, source_id)
        if current.revision != source.revision:
            raise HTTPException(409, '서비스 설정이 바뀌었습니다. 다시 미리 보기를 실행해 주세요.')
        existing = {url_key(url) for url in db.scalars(select(Bookmark.url).where(Bookmark.user_id == user.id))}
        published = {url_key(url) for url in db.scalars(select(SharedLink.url).where(SharedLink.published.is_(True)))}
        db.execute(delete(ProxyPreview).where(ProxyPreview.expires_at < time.time()))
        db.execute(delete(ProxyPreview).where(ProxyPreview.user_id == user.id, ProxyPreview.source_id == source_id))
        db.add(ProxyPreview(id=preview_id, user_id=user.id, source_id=source_id, source_revision=source.revision, entries=entries, expires_at=time.time()+600))
    return {'preview_id': preview_id, 'entries': [entry | {'existing': url_key(entry['url']) in existing, 'published': url_key(entry['url']) in published} for entry in entries], 'skipped': skipped}


@router.post('/{source_id}/import', dependencies=[Depends(require_mutation_header)])
def import_links(source_id: str, payload: ImportData, user: User = Depends(require_admin)):
    with SessionLocal.begin() as db:
        source = find_source(db, source_id)
        preview = db.scalar(select(ProxyPreview).where(ProxyPreview.id == payload.preview_id, ProxyPreview.user_id == user.id,
                                                     ProxyPreview.source_id == source_id).with_for_update())
        if not preview or preview.expires_at < time.time() or preview.source_revision != source.revision:
            raise HTTPException(409, '미리 보기가 만료되었거나 설정이 바뀌었습니다. 다시 조회해 주세요.')
        selected = set(payload.entry_ids)
        if not selected.issubset({entry['id'] for entry in preview.entries}):
            raise HTTPException(422, '미리 보기에 없는 링크가 선택되었습니다.')
        if payload.destination == 'library':
            # Different source inventories may contain the same public domain.
            db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
            added, duplicates = 0, 0
            for entry in preview.entries:
                if entry['id'] not in selected:
                    continue
                url = url_key(entry['url'])
                link = db.scalar(select(SharedLink).where(SharedLink.url == url).with_for_update())
                if link and link.published:
                    duplicates += 1
                    continue
                if link:
                    link.published = True
                    link.source_id, link.source_name = source.id, source.name
                else:
                    db.add(SharedLink(source_id=source.id, source_name=source.name, name=entry['name'], url=url, published=True))
                added += 1
            db.delete(preview)
            return {'added': added, 'duplicates': duplicates}
        category = db.scalar(select(Category).where(Category.id == payload.category_id, Category.user_id == user.id).with_for_update())
        if not category:
            raise HTTPException(404, '본인 북마크의 저장할 카테고리를 선택해 주세요.')
        existing = {url_key(url) for url in db.scalars(select(Bookmark.url).where(Bookmark.user_id == user.id))}
        position = db.scalar(select(func.max(Bookmark.position)).where(Bookmark.category_id == category.id)) or 0
        added, duplicates = 0, 0
        for entry in preview.entries:
            if entry['id'] not in selected:
                continue
            if url_key(entry['url']) in existing:
                duplicates += 1
                continue
            added += 1
            existing.add(url_key(entry['url']))
            db.add(Bookmark(user_id=user.id, category_id=category.id, name=entry['name'], url=entry['url'], position=position+added))
        db.delete(preview)
    return {'added': added, 'duplicates': duplicates}
