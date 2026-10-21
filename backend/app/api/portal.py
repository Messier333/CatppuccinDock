from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select

from app.api.dependencies import require_mutation_header, require_user
from app.db.models import BackgroundImage, Bookmark, BookmarkVisit, Category, Setting, SharedPlacement, Tab, User
from app.services.preferences import apply_preferences
from app.db.session import SessionLocal
from app.schemas.portal import BookmarkData, CategoryData, ReorderData, TabData
from app.services.icons import validate_icon
from app.services.library import allowed_link_ids, resolve_shared, shared_links_for_bookmarks
from app.services.proxy import url_key
from app.services.trash import erase, remember, snapshot


router = APIRouter(prefix='/api')


@router.post('/reorder', dependencies=[Depends(require_mutation_header)])
def reorder(payload: ReorderData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        model = {'tabs': Tab, 'categories': Category, 'bookmarks': Bookmark}[payload.kind]
        statement = select(model).where(model.user_id == user.id)
        if payload.kind == 'categories':
            owned(db, Tab, payload.parent_id, user.id)
            statement = statement.where(Category.tab_id == payload.parent_id)
        elif payload.kind == 'bookmarks':
            owned(db, Category, payload.parent_id, user.id)
            statement = statement.where(Bookmark.category_id == payload.parent_id)
        rows = list(db.scalars(statement.order_by(model.position, model.id).with_for_update()))
        hidden = []
        if payload.kind == 'bookmarks':
            shared = shared_links_for_bookmarks(db, [row.id for row in rows])
            allowed = allowed_link_ids(db, user)
            hidden = [row for row in rows if row.id in shared and shared[row.id].id not in allowed]
        visible = {row.id: row for row in rows if row not in hidden}
        if set(payload.ids) != set(visible):
            raise HTTPException(409, '목록이 변경되었습니다. 새로 불러온 목록에서 다시 순서를 지정해 주세요.')
        ordered = [visible[object_id] for object_id in payload.ids] + hidden
        undo_id = remember(db, user.id, 'order', '순서 변경', {'kind': payload.kind, 'parent_id': payload.parent_id, 'before': [row.id for row in rows], 'after': [row.id for row in ordered]})
        for position, row in enumerate(ordered):
            row.position = position
    return {'ok': True, 'undo_id': undo_id}


def owned(db, model, object_id, user_id):
    row = db.scalar(select(model).where(model.id == object_id, model.user_id == user_id))
    if not row:
        raise HTTPException(404, '항목을 찾을 수 없습니다.')
    return row


def bookmark_dict(row, shared=None):
    result = {field: getattr(row, field) for field in ('id', 'category_id', 'name', 'url', 'icon', 'icon_color', 'position', 'favorite')}
    result['managed'] = shared is not None
    if shared:
        result['url'] = shared.url
    return result


@router.get('/portal')
def portal(user: User = Depends(require_user)):
    with SessionLocal() as db:
        config = apply_preferences(db,user.id,db.get(Setting, 'portal').value)
        tabs = list(db.scalars(select(Tab).where(Tab.user_id == user.id).order_by(Tab.position, Tab.id)))
        categories = list(db.scalars(select(Category).where(Category.user_id == user.id).order_by(Category.position, Category.id)))
        bookmarks = list(db.scalars(select(Bookmark).where(Bookmark.user_id == user.id).order_by(Bookmark.position, Bookmark.id)))
        shared = shared_links_for_bookmarks(db, [bookmark.id for bookmark in bookmarks])
        allowed = allowed_link_ids(db, user)
        bookmarks = [bookmark for bookmark in bookmarks if bookmark.id not in shared or shared[bookmark.id].id in allowed]
        visible_ids = {row.id for row in bookmarks}
        background_sources = dict(db.execute(select(BackgroundImage.id, BackgroundImage.source).where(BackgroundImage.user_id == user.id)).all())
        config['recentBookmarks'] = [row.bookmark_id for row in db.scalars(select(BookmarkVisit).where(BookmarkVisit.user_id==user.id).order_by(BookmarkVisit.visited_at.desc(),BookmarkVisit.bookmark_id)) if row.bookmark_id in visible_ids][:12]
        config['tabs'] = [dict(id=tab.id, name=tab.name, banner=tab.banner, background_id=tab.background_id, background_source=background_sources.get(tab.background_id), position=tab.position,
            categories=[dict(id=category.id, tab_id=category.tab_id, name=category.name, position=category.position,
                links=[bookmark_dict(bookmark, shared.get(bookmark.id)) for bookmark in bookmarks if bookmark.category_id == category.id])
                for category in categories if category.tab_id == tab.id]) for tab in tabs]
    return config


@router.post('/tabs', dependencies=[Depends(require_mutation_header)])
def create_tab(payload: TabData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        if payload.background_id:
            owned(db, BackgroundImage, str(payload.background_id), user.id)
        row = Tab(user_id=user.id, **payload.model_dump(mode='json'))
        db.add(row)
        db.flush()
        return {'id': row.id}


@router.put('/tabs/{object_id}', dependencies=[Depends(require_mutation_header)])
def update_tab(object_id: str, payload: TabData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        row = owned(db, Tab, object_id, user.id)
        if payload.background_id:
            owned(db, BackgroundImage, str(payload.background_id), user.id)
        for key, value in payload.model_dump(mode='json').items():
            setattr(row, key, value)
    return {'ok': True}


@router.delete('/tabs/{object_id}', dependencies=[Depends(require_mutation_header)])
def delete_tab(object_id: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        row = owned(db, Tab, object_id, user.id)
        if db.scalar(select(func.count()).select_from(Tab).where(Tab.user_id == user.id)) <= 1:
            raise HTTPException(409, '탭은 최소 한 개가 필요합니다.')
        data = snapshot(db, user.id, tab_id=object_id)
        trash_id = remember(db, user.id, 'tab', row.name, data)
        erase(db, data)
    return {'ok': True, 'trash_id': trash_id}


@router.post('/categories', dependencies=[Depends(require_mutation_header)])
def create_category(payload: CategoryData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        owned(db, Tab, payload.tab_id, user.id)
        row = Category(user_id=user.id, **payload.model_dump())
        db.add(row)
        db.flush()
        return {'id': row.id}


@router.put('/categories/{object_id}', dependencies=[Depends(require_mutation_header)])
def update_category(object_id: str, payload: CategoryData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        row = owned(db, Category, object_id, user.id)
        owned(db, Tab, payload.tab_id, user.id)
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    return {'ok': True}


@router.delete('/categories/{object_id}', dependencies=[Depends(require_mutation_header)])
def delete_category(object_id: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        row = owned(db, Category, object_id, user.id)
        data = snapshot(db, user.id, category_id=object_id)
        trash_id = remember(db, user.id, 'category', row.name, data)
        erase(db, data)
    return {'ok': True, 'trash_id': trash_id}


@router.get('/bookmarks/{object_id}')
def get_bookmark(object_id: str, user: User = Depends(require_user)):
    with SessionLocal() as db:
        bookmark = owned(db, Bookmark, object_id, user.id)
        return bookmark_dict(bookmark, resolve_shared(db, bookmark, user))


@router.post('/bookmarks', dependencies=[Depends(require_mutation_header)])
def create_bookmark(payload: BookmarkData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        validate_icon(payload.icon, db=db, user=user)
        owned(db, Category, payload.category_id, user.id)
        data = payload.model_dump()
        data['url'] = str(payload.url)
        row = Bookmark(user_id=user.id, **data)
        db.add(row)
        db.flush()
        return bookmark_dict(row)


@router.put('/bookmarks/{object_id}', dependencies=[Depends(require_mutation_header)])
def update_bookmark(object_id: str, payload: BookmarkData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        validate_icon(payload.icon, db=db, user=user)
        row = owned(db, Bookmark, object_id, user.id)
        shared = resolve_shared(db, row, user)
        if shared and url_key(str(payload.url)) != url_key(shared.url):
            raise HTTPException(409, '공개 링크의 주소는 관리자가 관리합니다. 이름·아이콘·카테고리는 변경할 수 있습니다.')
        owned(db, Category, payload.category_id, user.id)
        for key, value in payload.model_dump().items():
            setattr(row, key, str(value) if key == 'url' else value)
    return {'ok': True}


@router.delete('/bookmarks/{object_id}', dependencies=[Depends(require_mutation_header)])
def delete_bookmark(object_id: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        row = owned(db, Bookmark, object_id, user.id)
        data = snapshot(db, user.id, bookmark_id=object_id)
        trash_id = remember(db, user.id, 'bookmark', row.name, data)
        erase(db, data)
    return {'ok': True, 'trash_id': trash_id}
