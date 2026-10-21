from copy import deepcopy
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, func
from app.api.dependencies import require_admin, require_user, require_mutation_header
from app.core.security import cipher
from app.db.models import FooterMetric, Setting, User
from app.db.session import SessionLocal
from app.schemas.footer import BASE_ITEMS, FooterLayout, MetricData
from app.services.footer import allowed_items, layout, public_metric, run_check

router = APIRouter(prefix='/api')

@router.get('/footer')
def footer(user: User = Depends(require_user)):
    with SessionLocal() as db:
        widgets = []
        for row in db.scalars(select(FooterMetric).order_by(FooterMetric.id)):
            if not row.config['enabled'] or (row.config['audience'] != 'all' and user.role != 'admin'): continue
            # Never send base URLs, queries, datasource IDs or credentials to members.
            widgets.append({key: row.config[key] for key in ('name','display','unit','metric','provider','interval')} | {'id': row.id, 'checked_at': row.checked_at, 'result': row.result})
        return layout(db, user) | {'metrics': widgets}

@router.put('/footer/order', dependencies=[Depends(require_mutation_header)])
def own_order(payload: FooterLayout, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        allowed = allowed_items(db, user)
        if set(payload.order) != set(allowed) or payload.hidden:
            raise HTTPException(409, '하단바 구성이 변경됐습니다. 새로 불러온 뒤 순서를 변경하세요.')
        key = f'footer:{user.id}'
        row = db.get(Setting, key)
        if row: row.value = {'order': payload.order}
        else: db.add(Setting(key=key, value={'order': payload.order}))
    return {'ok': True}

@router.delete('/footer/order', dependencies=[Depends(require_mutation_header)])
def reset_order(user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        db.execute(delete(Setting).where(Setting.key == f'footer:{user.id}'))
    return {'ok': True}

@router.get('/admin/footer', dependencies=[Depends(require_admin)])
def admin_footer():
    with SessionLocal() as db:
        metrics = [public_metric(row) for row in db.scalars(select(FooterMetric).order_by(FooterMetric.id))]
        keys = BASE_ITEMS + ['metric:' + row['id'] for row in metrics]
        row = db.get(Setting, 'footer')
        value = deepcopy(row.value) if row else {'order': [], 'hidden': []}
        value['order'] = [key for key in value['order'] if key in keys] + [key for key in keys if key not in value['order']]
        value['hidden'] = [key for key in value['hidden'] if key in keys]
        return value | {'metrics': metrics}

@router.put('/admin/footer', dependencies=[Depends(require_admin), Depends(require_mutation_header)])
def save_layout(payload: FooterLayout):
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
        keys = BASE_ITEMS + ['metric:' + mid for mid in db.scalars(select(FooterMetric.id))]
        if set(payload.order) != set(keys) or not set(payload.hidden).issubset(keys):
            raise HTTPException(409, '하단바 구성이 변경됐습니다. 다시 불러오세요.')
        row = db.get(Setting, 'footer')
        if row: row.value = payload.model_dump()
        else: db.add(Setting(key='footer', value=payload.model_dump()))
    return {'ok': True}

def save_metric(db, payload, metric_id=None):
    db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
    row = db.get(FooterMetric, metric_id) if metric_id else FooterMetric()
    if not row: raise HTTPException(404, '위젯을 찾을 수 없습니다.')
    if not metric_id and db.scalar(select(func.count()).select_from(FooterMetric)) >= 24:
        raise HTTPException(409, '모니터링 위젯은 최대 24개입니다.')
    old_config = row.config or {}
    # A saved credential must never be forwarded to a newly entered API origin.
    if payload.token:
        row.token_encrypted = cipher().encrypt(payload.token.encode()).decode()
    elif payload.clear_token or old_config.get('base_url') != str(payload.base_url):
        row.token_encrypted = ''
    row.config = payload.model_dump(mode='json', exclude={'token', 'clear_token'})
    row.result = {}; row.checked_at = None; row.attempted_at = 0; row.next_check = 0; row.revision = secrets.token_hex(16)
    db.add(row); db.flush()
    return public_metric(row)

@router.post('/admin/footer/metrics', dependencies=[Depends(require_admin), Depends(require_mutation_header)])
def create(payload: MetricData):
    with SessionLocal.begin() as db: return save_metric(db, payload)

@router.put('/admin/footer/metrics/{metric_id}', dependencies=[Depends(require_admin), Depends(require_mutation_header)])
def update(metric_id: str, payload: MetricData):
    with SessionLocal.begin() as db: return save_metric(db, payload, metric_id)

@router.delete('/admin/footer/metrics/{metric_id}', dependencies=[Depends(require_admin), Depends(require_mutation_header)])
def remove(metric_id: str):
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
        db.execute(delete(FooterMetric).where(FooterMetric.id == metric_id))
    return {'ok': True}

@router.post('/admin/footer/metrics/{metric_id}/check', dependencies=[Depends(require_admin), Depends(require_mutation_header)])
def check(metric_id: str):
    with SessionLocal() as db:
        if not db.get(FooterMetric, metric_id): raise HTTPException(404, '위젯을 찾을 수 없습니다.')
    run_check(metric_id, force=True)
    with SessionLocal() as db:
        row = db.get(FooterMetric, metric_id)
        if not row: raise HTTPException(404, '위젯을 찾을 수 없습니다.')
        return public_metric(row)
