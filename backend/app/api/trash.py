import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from app.api.dependencies import require_mutation_header, require_user
from app.db.models import TrashItem, User
from app.db.session import SessionLocal
from app.services.trash import restore

router = APIRouter(prefix='/api/trash', dependencies=[Depends(require_user)])

@router.get('')
def items(user: User = Depends(require_user)):
    with SessionLocal() as db:
        return [{key: getattr(row, key) for key in ('id','kind','label','created_at','expires_at')} for row in db.scalars(
            select(TrashItem).where(TrashItem.user_id==user.id, TrashItem.expires_at > time.time()).order_by(TrashItem.created_at.desc(), TrashItem.id.desc()))]

def owned(db, item_id, user_id):
    row = db.scalar(select(TrashItem).where(TrashItem.id==item_id, TrashItem.user_id==user_id, TrashItem.expires_at > time.time()).with_for_update())
    if not row: raise HTTPException(404, '휴지통 항목을 찾을 수 없습니다.')
    return row

@router.post('/{item_id}/restore', dependencies=[Depends(require_mutation_header)])
def restore_item(item_id: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        restore(db, owned(db, item_id, user.id), user)
    return {'ok': True}

@router.delete('/{item_id}', dependencies=[Depends(require_mutation_header)])
def purge(item_id: str, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        db.delete(owned(db, item_id, user.id))
    return {'ok': True}
