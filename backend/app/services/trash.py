"""User-owned deletion snapshots and bounded, conflict-aware undo."""
import time
from fastapi import HTTPException
from sqlalchemy import delete, select
from app.db.models import Bookmark, BookmarkVisit, Category, SharedPlacement, Tab, TrashItem

MODELS = {'tabs': Tab, 'categories': Category, 'bookmarks': Bookmark}

def columns(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}

def snapshot(db, user_id, *, tab_id=None, category_id=None, bookmark_id=None):
    tabs = list(db.scalars(select(Tab).where(Tab.user_id==user_id).order_by(Tab.id))) if not category_id and not bookmark_id else []
    if tab_id:
        tabs = [row for row in tabs if row.id==tab_id]
    categories = list(db.scalars(select(Category).where(Category.user_id==user_id).order_by(Category.id))) if not bookmark_id else []
    if tab_id:
        categories = [row for row in categories if row.tab_id==tab_id]
    if category_id:
        categories = [row for row in categories if row.id==category_id]
    bookmarks = list(db.scalars(select(Bookmark).where(Bookmark.user_id==user_id).order_by(Bookmark.id)))
    if tab_id or category_id:
        ids = {row.id for row in categories}
        bookmarks = [row for row in bookmarks if row.category_id in ids]
    if bookmark_id:
        bookmarks = [row for row in bookmarks if row.id==bookmark_id]
    ids = [row.id for row in bookmarks]
    placements = list(db.scalars(select(SharedPlacement).where(SharedPlacement.bookmark_id.in_(ids)).order_by(SharedPlacement.bookmark_id)))
    return {'tabs': [columns(row) for row in tabs], 'categories': [columns(row) for row in categories],
            'bookmarks': [columns(row) for row in bookmarks], 'placements': [columns(row) for row in placements]}

def remember(db, user_id, kind, label, data):
    db.execute(delete(TrashItem).where(TrashItem.user_id==user_id, TrashItem.expires_at < time.time()))
    row = TrashItem(user_id=user_id, kind=kind, label=label[:160], snapshot=data, expires_at=time.time()+30*86400)
    db.add(row); db.flush()
    # Keep the last 100 operations, including hierarchy snapshots.
    old = list(db.scalars(select(TrashItem).where(TrashItem.user_id==user_id).order_by(TrashItem.created_at.desc(), TrashItem.id.desc()).offset(100)))
    for item in old: db.delete(item)
    return row.id

def erase(db, data):
    ids = [row['id'] for row in data['bookmarks']]
    db.execute(delete(BookmarkVisit).where(BookmarkVisit.bookmark_id.in_(ids)))
    db.execute(delete(SharedPlacement).where(SharedPlacement.bookmark_id.in_(ids)))
    db.execute(delete(Bookmark).where(Bookmark.id.in_(ids)))
    db.execute(delete(Category).where(Category.id.in_([row['id'] for row in data['categories']])))
    db.execute(delete(Tab).where(Tab.id.in_([row['id'] for row in data['tabs']])))

def restore(db, item, user):
    data = item.snapshot
    if item.kind == 'bookmark-edit':
        for before,after in zip(data['before'],data['after']):
            row=db.get(Bookmark,before['id'])
            if not row or row.user_id!=user.id or columns(row)!=after: raise HTTPException(409,'편집 후 변경된 항목이 있어 되돌릴 수 없습니다.')
            parent=db.get(Category,before['category_id'])
            if not parent or parent.user_id!=user.id: raise HTTPException(409,'이전 카테고리를 먼저 복원해 주세요.')
            for key,value in before.items(): setattr(row,key,value)
    elif item.kind == 'order':
        model = MODELS[data['kind']]
        query = select(model).where(model.user_id==user.id)
        if model is Category: query = query.where(Category.tab_id==data['parent_id'])
        if model is Bookmark: query = query.where(Bookmark.category_id==data['parent_id'])
        rows = list(db.scalars(query.order_by(model.position, model.id)))
        if [row.id for row in rows] != data['after']:
            raise HTTPException(409, '목록이 변경되어 이 순서 변경을 되돌릴 수 없습니다.')
        by_id = {row.id: row for row in rows}
        for index, row_id in enumerate(data['before']): by_id[row_id].position = index
    else:
        if item.kind == 'replace':
            if data.get('previous_preferences') is not None:
                from app.db.models import PersonalPreference
                personal=db.get(PersonalPreference,user.id)
                if (personal.values if personal else {}) != data['expected_preferences']: raise HTTPException(409,'개인 설정이 변경되어 되돌릴 수 없습니다.')
                if personal: personal.values=data['previous_preferences']
                else: db.add(PersonalPreference(user_id=user.id,values=data['previous_preferences']))
            if data.get('previous_settings') is not None:
                from app.db.models import Setting
                if user.role != 'admin': raise HTTPException(403, '공통 설정은 관리자만 되돌릴 수 있습니다.')
                setting = db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
                if setting.value != data['expected_settings']: raise HTTPException(409, '공통 설정이 변경되어 되돌릴 수 없습니다.')
                setting.value = data['previous_settings']
            # Older snapshots precede the favorite column; its old value was false.
            for part in (data['expected'],data['previous']):
                for values in part['bookmarks']: values.setdefault('favorite',False)
            current = snapshot(db, user.id)
            if current != data['expected']:
                raise HTTPException(409, '복원 후 편집한 내용이 있어 덮어쓰기를 취소할 수 없습니다.')
            erase(db, current)
            data = data['previous']
        for key, model in MODELS.items():
            for values in data[key]:
                if values['user_id'] != user.id or db.get(model, values['id']):
                    raise HTTPException(409, '동일 항목이 이미 존재합니다. 현재 목록을 확인해 주세요.')
                if model is Tab and values.get('background_id'):
                    from app.db.models import BackgroundImage
                    image = db.get(BackgroundImage, values['background_id'])
                    if not image or image.user_id != user.id:
                        raise HTTPException(409, '배경 GIF가 삭제되어 복원할 수 없습니다.')
                if model is Category:
                    parent = db.get(Tab, values['tab_id'])
                    if not parent or parent.user_id != user.id:
                        raise HTTPException(409, '상위 탭을 먼저 복원해 주세요.')
                if model is Bookmark:
                    parent = db.get(Category, values['category_id'])
                    if not parent or parent.user_id != user.id:
                        raise HTTPException(409, '상위 카테고리를 먼저 복원해 주세요.')
                db.add(model(**values))
            db.flush()
        from app.db.models import SharedLink
        for placement in data['placements']:
            if db.get(SharedLink, placement['link_id']): db.add(SharedPlacement(**placement))
            else:
                # Never turn an unavailable managed bookmark into a personal one.
                row = db.get(Bookmark, placement['bookmark_id'])
                if row: db.delete(row)
    db.delete(item)

def references_image(data, image_id):
    if 'previous' in data: return references_image(data['previous'], image_id)
    return any(row.get('background_id') == image_id for row in data.get('tabs', []))
