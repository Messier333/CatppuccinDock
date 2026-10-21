"""Database-managed OIDC configuration and encrypted authorization state."""
import os
import secrets
import time

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.security import cipher
from app.db.models import MFAChallenge, OAuthState, OIDCIdentity, Setting, User
from app.db.session import SessionLocal


def seed_configuration(db):
    if db.get(Setting, 'oidc'):
        return
    secret = os.getenv('OIDC_CLIENT_SECRET', '')
    data = {'login_mode': 'both', 'issuer': os.getenv('OIDC_ISSUER_URL', ''), 'client_id': os.getenv('OIDC_CLIENT_ID', ''),
            'redirect_uri': os.getenv('OIDC_REDIRECT_URI', ''), 'label': os.getenv('OIDC_LABEL', 'SSO'),
            'secret_encrypted': cipher().encrypt(secret.encode()).decode() if secret else '', 'revision': secrets.token_hex(16)}
    data['enabled'] = all(data[key] for key in ('issuer', 'client_id', 'redirect_uri', 'secret_encrypted'))
    db.add(Setting(key='oidc', value=data))


def configuration(db=None):
    if db is not None:
        row = db.get(Setting, 'oidc')
        return dict(row.value) if row else {}
    with SessionLocal() as session:
        return configuration(session)


def is_configured(config):
    return all(config.get(key) for key in ('issuer', 'client_id', 'redirect_uri', 'secret_encrypted'))


def oidc_enabled():
    config = configuration()
    return bool(config.get('enabled') and is_configured(config))


def password_login_enabled(config=None):
    config = configuration() if config is None else config
    return config.get('login_mode', 'both') != 'sso_only'


def ensure_admin_login(db, config):
    """Account and provider edits must leave an allowed administrator login."""
    db.flush()
    admins = list(db.scalars(select(User).where(User.role == 'admin', User.active.is_(True))))
    if password_login_enabled(config) and any(user.password_hash for user in admins):
        return
    if config.get('enabled') and is_configured(config):
        linked = db.scalar(select(OIDCIdentity.id).where(
            OIDCIdentity.issuer == config['issuer'], OIDCIdentity.user_id.in_([user.id for user in admins])))
        if linked:
            return
    raise HTTPException(409, '로그인 가능한 관리자가 최소 한 명 필요합니다. 사용자 관리에서 활성 관리자에게 현재 인증 서비스의 SSO 계정을 먼저 연결해 주세요.')


def public_configuration(config=None):
    config = configuration() if config is None else config
    return {key: config.get(key, 'SSO' if key == 'label' else '') for key in ('label', 'issuer', 'client_id', 'redirect_uri')} | {
        'enabled': bool(config.get('enabled')), 'configured': bool(is_configured(config)),
        'has_secret': bool(config.get('secret_encrypted')), 'allow_signup': False,
        'login_mode': config.get('login_mode', 'both')}


def save_configuration(db, payload):
    row = db.scalar(select(Setting).where(Setting.key == 'oidc').with_for_update())
    config = dict(row.value) if row else {}
    data = payload.model_dump(exclude={'client_secret'})
    data['secret_encrypted'] = config.get('secret_encrypted', '')
    if payload.client_secret is not None:
        data['secret_encrypted'] = cipher().encrypt(payload.client_secret.encode()).decode()
    if payload.enabled and not is_configured(data):
        raise HTTPException(422, '처음 활성화할 때 Client Secret을 입력해 주세요.')
    ensure_admin_login(db, data)
    data['revision'] = secrets.token_hex(16)
    if row:
        row.value = data
    else:
        db.add(Setting(key='oidc', value=data))
    # Existing flows must restart after a configuration change.
    db.execute(delete(OAuthState))
    if not password_login_enabled(data):
        db.execute(delete(MFAChallenge).where(MFAChallenge.auth_method == 'local'))
    return public_configuration(data)


class StateCache:
    async def set(self, key, value, expires):
        with SessionLocal.begin() as db:
            db.execute(delete(OAuthState).where(OAuthState.expires_at < time.time()))
            db.merge(OAuthState(key=key, value=cipher().encrypt(value.encode()).decode(), expires_at=time.time()+min(expires,600)))

    async def get(self, key):
        with SessionLocal.begin() as db:
            row = db.scalar(select(OAuthState).where(OAuthState.key == key).with_for_update())
            if not row:
                return None
            value = cipher().decrypt(row.value.encode()).decode() if row.expires_at > time.time() else None
            db.delete(row)
            return value

    async def delete(self, key):
        with SessionLocal.begin() as db:
            db.execute(delete(OAuthState).where(OAuthState.key == key))


def create_client(config):
    if not config.get('enabled') or not is_configured(config):
        raise HTTPException(503, 'SSO 연결 설정이 아직 완료되지 않았습니다.')
    oauth = OAuth(cache=StateCache())
    oauth.register('oidc', client_id=config['client_id'], client_secret=cipher().decrypt(config['secret_encrypted'].encode()).decode(),
                   server_metadata_url=config['issuer'].rstrip('/')+'/.well-known/openid-configuration',
                   client_kwargs={'scope': 'openid profile email', 'code_challenge_method': 'S256', 'timeout': 10})
    return oauth.create_client('oidc')


def frontend_base(config):
    uri = config.get('redirect_uri', '')
    suffix = 'api/auth/oidc/callback'
    if not uri.endswith('/'+suffix):
        raise HTTPException(503, 'Callback URL을 관리자 설정에서 확인해 주세요.')
    return uri[:-len(suffix)]
