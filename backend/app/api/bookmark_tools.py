import time
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from app.api.dependencies import require_mutation_header, require_user
from app.api.portal import bookmark_dict, owned
from app.db.models import Bookmark, BookmarkVisit, Category, SharedPlacement, User
from app.db.session import SessionLocal
from app.schemas.bookmark_tools import BulkData, FavoriteData, PreviewData
from app.services.bookmark_metadata import preview
from app.services.icons import validate_icon
from app.services.library import allowed_link_ids, resolve_shared, shared_links_for_bookmarks
from app.services.proxy import url_key
from app.services.trash import columns, erase, remember

router = APIRouter(prefix='/api/bookmark-tools')


@router.post('/preview',dependencies=[Depends(require_mutation_header)])
def metadata(payload: PreviewData,user: User=Depends(require_user)):
    # A short per-account budget also caps public-site traffic from automatic typing previews.
    from app.db.models import Setting
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        key = f'preview-budget:{user.id}'; row = db.get(Setting,key); now = time.time()
        value = row.value if row and row.value.get('until',0)>now else {'until':now+60,'count':0}
        if value['count']>=20: raise HTTPException(429,'잠시 후 다시 제목을 불러와 주세요. 이름을 직접 입력해 저장할 수도 있어요.')
        value = value | {'count':value['count']+1}
        if row: row.value=value
        else: db.add(Setting(key=key,value=value))
    return preview(str(payload.url))


@router.put('/{bookmark_id}/favorite',dependencies=[Depends(require_mutation_header)])
def favorite(bookmark_id:str,payload:FavoriteData,user:User=Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        row=owned(db,Bookmark,bookmark_id,user.id); resolve_shared(db,row,user)
        row.favorite=payload.favorite
    return {'favorite':payload.favorite}


@router.post('/{bookmark_id}/visit',dependencies=[Depends(require_mutation_header)])
def visit(bookmark_id:str,user:User=Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        bookmark=owned(db,Bookmark,bookmark_id,user.id); resolve_shared(db,bookmark,user)
        row=db.get(BookmarkVisit,bookmark_id); now=time.time()
        if row: row.visited_at=now; row.count=min(row.count+1,1000000)
        else: db.add(BookmarkVisit(bookmark_id=bookmark_id,user_id=user.id,visited_at=now))
    return {'ok':True}


@router.delete('/recent',dependencies=[Depends(require_mutation_header)])
def clear_recent(user:User=Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        db.execute(delete(BookmarkVisit).where(BookmarkVisit.user_id==user.id))
    return {'ok':True}


def authorized(db,user,ids=None):
    statement=select(Bookmark).where(Bookmark.user_id==user.id).order_by(Bookmark.position,Bookmark.id)
    if ids is not None: statement=statement.where(Bookmark.id.in_(ids))
    rows=list(db.scalars(statement)); shared=shared_links_for_bookmarks(db,[row.id for row in rows]); allowed=allowed_link_ids(db,user) if shared else set()
    return [row for row in rows if row.id not in shared or shared[row.id].id in allowed],shared


@router.get('/duplicates')
def duplicates(user:User=Depends(require_user)):
    with SessionLocal() as db:
        rows,shared=authorized(db,user); grouped=defaultdict(list)
        for row in rows: grouped[url_key(shared[row.id].url if row.id in shared else row.url)].append(row)
        return [{'url':url,'bookmarks':[bookmark_dict(row,shared.get(row.id)) for row in sorted(items,key=lambda row:(not row.favorite,row.position,row.id))]} for url,items in grouped.items() if len(items)>1]


@router.post('/bulk',dependencies=[Depends(require_mutation_header)])
def bulk(payload:BulkData,user:User=Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        if payload.action=='icon': validate_icon(payload.icon, db=db, user=user)
        rows,shared=authorized(db,user,payload.ids)
        if {row.id for row in rows}!=set(payload.ids): raise HTTPException(409,'목록이나 공개 링크 권한이 변경됐어요. 다시 불러온 뒤 선택해 주세요.')
        before=[columns(row) for row in rows]
        if payload.action=='delete':
            placements=list(db.scalars(select(SharedPlacement).where(SharedPlacement.bookmark_id.in_(payload.ids))))
            data={'tabs':[],'categories':[],'bookmarks':before,'placements':[columns(row) for row in placements]}
            undo_id=remember(db,user.id,'bookmarks',f'북마크 {len(rows)}개 삭제',data); erase(db,data)
        else:
            if payload.action=='move':
                owned(db,Category,payload.category_id,user.id)
                position=db.scalar(select(func.max(Bookmark.position)).where(Bookmark.user_id==user.id,Bookmark.category_id==payload.category_id))
                position=(position if position is not None else -1)+1
                for row in rows:
                    if row.category_id!=payload.category_id: row.category_id=payload.category_id; row.position=min(position,10000); position+=1
            else:
                for row in rows: row.icon=payload.icon; row.icon_color=payload.icon_color
            db.flush()
            undo_id=remember(db,user.id,'bookmark-edit',f'북마크 {len(rows)}개 편집',{'before':before,'after':[columns(row) for row in rows]})
    return {'changed':len(rows),'undo_id':undo_id}
