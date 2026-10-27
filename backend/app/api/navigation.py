"""Account-specific settings navigation order, constrained by the current role."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from app.api.dependencies import require_mutation_header, require_user
from app.db.models import Setting, User
from app.db.session import SessionLocal

router = APIRouter(prefix='/api/navigation')
MEMBER_ITEMS = ['bookmarks', 'preferences', 'library', 'backup', 'trash', 'security', 'proxmox']
ADMIN_ITEMS = ['groups', 'footer', 'monitoring', 'sync', 'users', 'import', 'shared', 'settings', 'backgrounds', 'sso']


class NavigationOrder(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order: list[str] = Field(min_length=1, max_length=32)


def available(user):
    return MEMBER_ITEMS + (ADMIN_ITEMS if user.role == 'admin' else [])


@router.get('')
def navigation(user: User = Depends(require_user)):
    with SessionLocal() as db:
        row = db.get(Setting, f'navigation:{user.id}')
        items = available(user)
        saved = list(dict.fromkeys(key for key in row.value.get('order', []) if key in items)) if row else []
        return {'order': saved + [key for key in items if key not in saved]}


@router.put('', dependencies=[Depends(require_mutation_header)])
def save(payload: NavigationOrder, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        current = db.scalar(select(User).where(User.id == user.id).with_for_update())
        if len(payload.order) != len(set(payload.order)) or set(payload.order) != set(available(current)):
            raise HTTPException(409, '설정 메뉴 구성이 변경됐습니다. 새로 불러온 뒤 순서를 변경하세요.')
        key = f'navigation:{user.id}'
        row = db.get(Setting, key)
        if row: row.value = {'order': payload.order}
        else: db.add(Setting(key=key, value={'order': payload.order}))
    return {'ok': True}


@router.delete('', dependencies=[Depends(require_mutation_header)])
def reset(user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        db.execute(delete(Setting).where(Setting.key == f'navigation:{user.id}'))
    return {'ok': True}
