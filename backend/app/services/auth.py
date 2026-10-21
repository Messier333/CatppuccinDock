"""Session issuance, lookup, login challenges and attempt throttling."""
import os
import secrets
import time

from fastapi import HTTPException, Request
from sqlalchemy import delete, func, select, update

from app.core.security import hash_password, token_hash
from app.db.models import LoginAttempt, LoginSession, MFAChallenge, User
from app.db.session import SessionLocal
from app.services.audit import client_address


COOKIE_NAME = 'catppuccindock_session'


MFA_COOKIE = 'catppuccindock_mfa'


SESSION_SECONDS = 60 * 60 * 24 * 7
ACTIVITY_INTERVAL = 60


DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def record_attempt(request: Request, scope='login'):
    client_ip = client_address(request)
    client = scope + ':' + token_hash(client_ip)
    now = time.time()
    with SessionLocal.begin() as db:
        db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < now - 900))
        count = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.client == client))
        if count >= 10:
            raise HTTPException(429, '시도가 너무 많습니다. 15분 후 다시 시도해 주세요.', headers={'Retry-After': '900'})
        db.add(LoginAttempt(client=client, created_at=now))


def current_user(request: Request):
    token = request.cookies.get(COOKIE_NAME, '')
    if not token or len(token) > 128:
        return None
    with SessionLocal() as db:
        session = db.get(LoginSession, token_hash(token))
        now = time.time()
        if not session or session.expires_at <= now:
            return None
        user = db.get(User, session.user_id)
        if not user or not user.active:
            return None
        if session.last_seen_at <= now - ACTIVITY_INTERVAL:
            db.execute(update(LoginSession).where(
                LoginSession.token_hash == session.token_hash,
                LoginSession.last_seen_at <= now - ACTIVITY_INTERVAL,
                LoginSession.expires_at > now,
            ).values(last_seen_at=now, **session_metadata(request)))
            db.commit()
        return user


def session_metadata(request):
    return {'user_agent': ' '.join(request.headers.get('user-agent', '').split())[:512],
            'ip_address': client_address(request)}


def cookie_options():
    return {'httponly': True, 'samesite': 'lax', 'path': '/', 'secure': os.getenv('COOKIE_SECURE', 'false').lower() == 'true'}


def create_session(request, response, user_id):
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        if not user or not user.active:
            raise HTTPException(401, '로그인이 필요합니다.')
        db.execute(delete(LoginSession).where(LoginSession.expires_at <= time.time()))
        previous = request.cookies.get(COOKIE_NAME)
        if previous:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(previous)))
        now = time.time()
        db.add(LoginSession(token_hash=token_hash(token), user_id=user_id, created_at=now,
                            last_seen_at=now, expires_at=now + SESSION_SECONDS, **session_metadata(request)))
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, **cookie_options())
    response.delete_cookie(MFA_COOKIE, path='/')


def begin_login(user, request, response, auth_method='local'):
    if not user.totp_secret:
        create_session(request, response, user.id)
        return {'username': user.username, 'mfa_required': False}
    token = secrets.token_urlsafe(32)
    with SessionLocal.begin() as db:
        db.execute(delete(MFAChallenge).where(MFAChallenge.expires_at <= time.time()))
        previous = request.cookies.get(MFA_COOKIE)
        if previous:
            db.execute(delete(MFAChallenge).where(MFAChallenge.token_hash == token_hash(previous)))
        db.add(MFAChallenge(token_hash=token_hash(token), user_id=user.id, expires_at=time.time() + 300, auth_method=auth_method))
        # An intermediate login must never retain an authenticated session.
        previous_session = request.cookies.get(COOKIE_NAME)
        if previous_session:
            db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(previous_session)))
    response.delete_cookie(COOKIE_NAME, path='/')
    response.set_cookie(MFA_COOKIE, token, max_age=300, **cookie_options())
    return {'mfa_required': True}
