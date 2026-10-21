from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select

from app.api.dependencies import require_admin, require_mutation_header, require_user
from app.db.models import Bookmark, Category, SharedLink, SharedPlacement, SharedUserGrant, SharedGroupGrant, User, UserGroup, Setting
from app.db.session import SessionLocal
from app.schemas.library import AddSharedLink, AddSharedLinks, SharedLinkData
from app.services.icons import validate_icon
from app.services.library import admin_link, allowed_link_ids, link_allowed, public_link
from app.services.proxy import url_key


router = APIRouter(prefix='/api')


@router.get('/library')
def library(user: User = Depends(require_user)):
    with SessionLocal() as db:
        existing = {url_key(url) for url in db.scalars(select(Bookmark.url).where(Bookmark.user_id == user.id))}
        return [public_link(link) | {'added': url_key(link.url) in existing} for link in db.scalars(
            select(SharedLink).where(SharedLink.id.in_(allowed_link_ids(db, user))).order_by(SharedLink.name, SharedLink.id))]


@router.post('/library/{link_id}/add', dependencies=[Depends(require_mutation_header)])
def add_link(link_id: str, payload: AddSharedLink, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        link = db.scalar(select(SharedLink).where(SharedLink.id == link_id).with_for_update())
        if not link_allowed(db, link, user):
            raise HTTPException(404, '공개된 링크를 찾을 수 없습니다.')
        category = db.scalar(select(Category).where(Category.id == payload.category_id, Category.user_id == user.id))
        if not category:
            raise HTTPException(404, '본인 카테고리를 선택해 주세요.')
        existing = {url_key(url) for url in db.scalars(select(Bookmark.url).where(Bookmark.user_id == user.id))}
        if url_key(link.url) in existing:
            raise HTTPException(409, '이미 내 북마크에 추가한 링크입니다.')
        position = db.scalar(select(func.max(Bookmark.position)).where(Bookmark.category_id == category.id)) or 0
        bookmark = Bookmark(user_id=user.id, category_id=category.id, name=link.name, url=link.url,
                            icon=link.icon, icon_color=link.icon_color, position=position+1)
        db.add(bookmark)
        db.flush()
        db.add(SharedPlacement(bookmark_id=bookmark.id, link_id=link.id))
        return {'id': bookmark.id}


@router.post('/library/add', dependencies=[Depends(require_mutation_header)])
def add_links(payload: AddSharedLinks, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        category = db.scalar(select(Category).where(Category.id == payload.category_id, Category.user_id == user.id))
        if not category:
            raise HTTPException(404, '본인 카테고리를 선택해 주세요.')
        ids = set(payload.link_ids)
        links = list(db.scalars(select(SharedLink).where(SharedLink.id.in_(ids), SharedLink.id.in_(allowed_link_ids(db, user))).order_by(SharedLink.id).with_for_update()))
        if len(links) != len(ids):
            raise HTTPException(409, '공개 목록이 변경되었어요. 새로고침 후 다시 선택해 주세요.')
        existing = {url_key(url) for url in db.scalars(select(Bookmark.url).where(Bookmark.user_id == user.id))}
        position = db.scalar(select(func.max(Bookmark.position)).where(Bookmark.category_id == category.id)) or 0
        added = 0
        by_id = {link.id: link for link in links}
        for link_id in dict.fromkeys(payload.link_ids):
            link = by_id[link_id]
            if url_key(link.url) in existing:
                continue
            added += 1
            bookmark = Bookmark(user_id=user.id, category_id=category.id, name=link.name, url=link.url,
                                icon=link.icon, icon_color=link.icon_color, position=position+added)
            db.add(bookmark)
            db.flush()
            db.add(SharedPlacement(bookmark_id=bookmark.id, link_id=link.id))
        return {'added': added, 'duplicates': len(ids)-added}


@router.get('/admin/library', dependencies=[Depends(require_admin)])
def admin_library():
    with SessionLocal() as db:
        return [admin_link(db, link) for link in db.scalars(select(SharedLink).order_by(SharedLink.name, SharedLink.id))]


@router.put('/admin/library/{link_id}', dependencies=[Depends(require_admin), Depends(require_mutation_header)])
def update_link(link_id: str, payload: SharedLinkData, user: User = Depends(require_admin)):
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
        validate_icon(payload.icon, db=db, user=user)
        link = db.scalar(select(SharedLink).where(SharedLink.id == link_id).with_for_update())
        if not link:
            raise HTTPException(404, '공개 링크를 찾을 수 없습니다.')
        if payload.access_mode is not None:
            users, groups = set(payload.user_ids or []), set(payload.group_ids or [])
            if users != set(db.scalars(select(User.id).where(User.id.in_(users)))) or groups != set(db.scalars(select(UserGroup.id).where(UserGroup.id.in_(groups)))):
                raise HTTPException(422, '존재하는 사용자와 그룹을 선택해 주세요.')
            for model in (SharedUserGrant, SharedGroupGrant):
                db.execute(delete(model).where(model.link_id == link_id))
            if payload.access_mode == 'restricted':
                db.add_all(SharedUserGrant(link_id=link_id, user_id=value) for value in users)
                db.add_all(SharedGroupGrant(link_id=link_id, group_id=value) for value in groups)
        for key, value in payload.model_dump(exclude={'user_ids', 'group_ids'}, exclude_none=True).items():
            setattr(link, key, value)
        db.flush()
        return admin_link(db, link)
