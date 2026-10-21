from copy import deepcopy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import require_admin, require_mutation_header
from app.core.security import hash_password
from app.db.models import OIDCIdentity, Setting, User
from app.db.session import SessionLocal
from app.schemas.admin import IdentityData, OIDCSettings, PortalSettings, UserCreate, UserData
from app.services.account import revoke_sessions
from app.services.oidc import configuration, ensure_admin_login, is_configured, public_configuration, save_configuration
from app.services.portal import seed_portal


router = APIRouter(prefix='/api/admin', dependencies=[Depends(require_admin)])


def public_user(user):
    return {'id': user.id, 'username': user.username, 'role': user.role, 'active': user.active,
            'totp_enabled': bool(user.totp_secret), 'has_password': bool(user.password_hash)}


@router.get('/me')
def me(user: User = Depends(require_admin)):
    return public_user(user)


@router.get('/users')
def users():
    with SessionLocal() as db:
        result = []
        for user in db.scalars(select(User).order_by(User.id)):
            row = public_user(user)
            row['identities'] = [{'id': item.id, 'issuer': item.issuer, 'subject': item.subject} for item in db.scalars(select(OIDCIdentity).where(OIDCIdentity.user_id == user.id))]
            result.append(row)
        return result


@router.post('/users', dependencies=[Depends(require_mutation_header)])
def create_user(payload: UserCreate):
    try:
        with SessionLocal.begin() as db:
            db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
            config = configuration(db)
            if payload.login_type == 'oidc' and not is_configured(config):
                raise HTTPException(409, '포털 · SSO 설정에서 OIDC 서비스를 먼저 등록해 주세요.')
            user = User(username=payload.username, password_hash=hash_password(payload.password) if payload.password else None, role=payload.role, active=payload.active)
            db.add(user)
            db.flush()
            if payload.login_type == 'oidc':
                db.add(OIDCIdentity(user_id=user.id, issuer=config['issuer'], subject=payload.oidc_subject))
            seed_portal(db, user.id)
            result = public_user(user)
    except IntegrityError as error:
        raise HTTPException(409, '이미 사용 중인 아이디 또는 OIDC 계정입니다.') from error
    return result


@router.put('/users/{user_id}', dependencies=[Depends(require_mutation_header)])
def update_user(user_id: int, payload: UserData):
    try:
        with SessionLocal.begin() as db:
            db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
            locked = list(db.scalars(select(User).order_by(User.id).with_for_update()))
            user = next((item for item in locked if item.id == user_id), None)
            if not user:
                raise HTTPException(404, '사용자를 찾을 수 없습니다.')
            admins = [item for item in locked if item.active and item.role == 'admin']
            if user in admins and len(admins) == 1 and (not payload.active or payload.role != 'admin'):
                raise HTTPException(409, '마지막 관리자는 비활성화하거나 권한을 변경할 수 없습니다.')
            changed = user.role != payload.role or user.active != payload.active or user.username != payload.username or payload.password
            user.username, user.role, user.active = payload.username, payload.role, payload.active
            if payload.password:
                user.password_hash = hash_password(payload.password)
            ensure_admin_login(db, configuration(db))
            if changed:
                revoke_sessions(db, user.id)
            result = public_user(user)
    except IntegrityError as error:
        raise HTTPException(409, '이미 사용 중인 아이디입니다.') from error
    return result


@router.post('/users/{user_id}/identities', dependencies=[Depends(require_mutation_header)])
def link_identity(user_id: int, payload: IdentityData):
    try:
        with SessionLocal.begin() as db:
            db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
            if not db.get(User, user_id):
                raise HTTPException(404, '사용자를 찾을 수 없습니다.')
            identity = OIDCIdentity(user_id=user_id, issuer=payload.issuer, subject=payload.subject)
            db.add(identity)
            db.flush()
            return {'id': identity.id}
    except IntegrityError as error:
        raise HTTPException(409, '이미 연결된 SSO 계정입니다.') from error


@router.delete('/users/{user_id}/identities/{identity_id}', dependencies=[Depends(require_mutation_header)])
def unlink_identity(user_id: int, identity_id: int):
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        row = db.scalar(select(OIDCIdentity).where(OIDCIdentity.id == identity_id, OIDCIdentity.user_id == user_id))
        if not user or not row:
            raise HTTPException(404, 'SSO 연결을 찾을 수 없습니다.')
        identities = list(db.scalars(select(OIDCIdentity).where(OIDCIdentity.user_id == user_id)))
        if not user.password_hash and len(identities) <= 1:
            raise HTTPException(409, '유일한 로그인 수단은 삭제할 수 없습니다.')
        db.delete(row)
        db.flush()
        ensure_admin_login(db, configuration(db))
        revoke_sessions(db, user.id)
    return {'ok': True}


@router.get('/sso')
def sso():
    return public_configuration()


@router.put('/sso', dependencies=[Depends(require_mutation_header)])
def update_sso(payload: OIDCSettings):
    with SessionLocal.begin() as db:
        db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
        return save_configuration(db, payload)


@router.get('/settings')
def settings():
    with SessionLocal() as db:
        config = db.get(Setting, 'portal').value
        return {'search_engine': config['search']['default'], 'search_open_mode': config['search'].get('openMode', 'same_tab'),
                'timezone': config['clock'].get('timezone', 'Asia/Seoul'),
                'clock_format': config['clock'].get('format', '24h'),
                'weather_location': config['temperature']['location'], 'temperature_scale': config['temperature']['scale'],
                'tab_animation': config.get('tabAnimation', True),
                'bookmark_shelf_display': config.get('bookmarkShelfDisplay', 'labels')}


@router.put('/settings', dependencies=[Depends(require_mutation_header)])
def update_settings(payload: PortalSettings):
    with SessionLocal.begin() as db:
        row = db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
        config = deepcopy(row.value)
        config['search']['default'] = payload.search_engine
        config['search']['openMode'] = payload.search_open_mode
        config['clock']['timezone'] = payload.timezone
        config['clock']['format'] = payload.clock_format
        config['temperature']['location'] = payload.weather_location
        config['temperature']['scale'] = payload.temperature_scale
        config['tabAnimation'] = payload.tab_animation
        config['bookmarkShelfDisplay'] = payload.bookmark_shelf_display
        row.value = config
    return {'ok': True}
