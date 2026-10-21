from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from app.api.dependencies import require_admin, require_mutation_header
from app.db.models import GroupMember, SharedGroupGrant, User, UserGroup
from app.db.session import SessionLocal

router = APIRouter(prefix='/api/admin/groups', dependencies=[Depends(require_admin)])

class GroupData(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    user_ids: list[int] = Field(default_factory=list, max_length=1000)

def representation(db, row):
    return {'id': row.id, 'name': row.name, 'user_ids': list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == row.id)))}

@router.get('')
def groups():
    with SessionLocal() as db:
        return [representation(db, row) for row in db.scalars(select(UserGroup).order_by(UserGroup.name))]

def save(db, payload, group_id=None):
    # Shared publication and group changes serialize on the same setting row.
    from app.db.models import Setting
    db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
    row = db.get(UserGroup, group_id) if group_id else UserGroup()
    if not row:
        raise HTTPException(404, '그룹을 찾을 수 없습니다.')
    from sqlalchemy import func
    if not group_id and db.scalar(select(func.count()).select_from(UserGroup)) >= 200:
        raise HTTPException(409, '그룹은 최대 200개까지 등록할 수 있습니다.')
    duplicate = db.scalar(select(UserGroup).where(UserGroup.name == payload.name))
    if duplicate and duplicate.id != row.id:
        raise HTTPException(409, '같은 이름의 그룹이 있습니다.')
    if set(payload.user_ids) != set(db.scalars(select(User.id).where(User.id.in_(payload.user_ids)))):
        raise HTTPException(422, '존재하는 사용자를 선택해 주세요.')
    row.name = payload.name
    db.add(row); db.flush()
    db.execute(delete(GroupMember).where(GroupMember.group_id == row.id))
    db.add_all(GroupMember(group_id=row.id, user_id=value) for value in set(payload.user_ids))
    db.flush()
    return representation(db, row)

@router.post('', dependencies=[Depends(require_mutation_header)])
def create(payload: GroupData):
    with SessionLocal.begin() as db:
        return save(db, payload)

@router.put('/{group_id}', dependencies=[Depends(require_mutation_header)])
def update(group_id: str, payload: GroupData):
    with SessionLocal.begin() as db:
        return save(db, payload, group_id)

@router.delete('/{group_id}', dependencies=[Depends(require_mutation_header)])
def remove(group_id: str):
    from app.db.models import Setting
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key=='portal').with_for_update())
        row = db.get(UserGroup, group_id)
        if not row:
            raise HTTPException(404, '그룹을 찾을 수 없습니다.')
        db.execute(delete(SharedGroupGrant).where(SharedGroupGrant.group_id == group_id))
        db.execute(delete(GroupMember).where(GroupMember.group_id == group_id))
        db.delete(row)
    return {'ok': True}
