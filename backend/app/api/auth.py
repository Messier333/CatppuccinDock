import hmac
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import require_mutation_header, require_user
from app.core.security import hash_password, token_hash, verify_password
from app.db.models import LoginSession, MFAChallenge, Setting, User
from app.db.session import SessionLocal
from app.schemas.auth import Credentials, MFACode, SetupCredentials
from app.services.account import verify_second_factor
from app.services.auth import COOKIE_NAME, DUMMY_PASSWORD_HASH, MFA_COOKIE, begin_login, create_session, current_user, record_attempt
from app.services.oidc import configuration, password_login_enabled, public_configuration
from app.services.portal import seed_portal


router = APIRouter(prefix='/api/auth')


@router.get('/status')
def status(request: Request):
    config = configuration()
    sso = public_configuration(config)
    user = current_user(request)
    with SessionLocal() as db:
        setup_required = not db.scalar(select(func.count()).select_from(User))
        challenge = db.get(MFAChallenge, token_hash(request.cookies.get(MFA_COOKIE, '')))
        password_allowed = password_login_enabled(config)
        mfa_pending = bool(challenge and challenge.expires_at > time.time() and challenge.attempts < 5
                           and (challenge.auth_method == 'oidc' or password_allowed))
    return {'authenticated': user is not None, 'username': user.username if user else None,
            'role': user.role if user else None, 'setup_required': setup_required,
            'mfa_required': mfa_pending, 'sso_enabled': sso['enabled'] and sso['configured'], 'sso_label': sso['label'],
            'password_login_enabled': password_allowed}


@router.post('/setup', dependencies=[Depends(require_mutation_header)])
def setup(payload: SetupCredentials, request: Request, response: Response):
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User)):
            raise HTTPException(409, '관리자 계정이 이미 등록되어 있습니다.')
    record_attempt(request, 'setup')
    expected = os.getenv('ADMIN_SETUP_CODE', '')
    if not expected or not hmac.compare_digest(payload.setup_code.encode(), expected.encode()):
        raise HTTPException(403, '설정 코드가 올바르지 않습니다.')
    username = payload.username.strip()
    if not username:
        raise HTTPException(422, '아이디를 입력해 주세요.')
    try:
        with SessionLocal.begin() as db:
            db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
            if db.scalar(select(func.count()).select_from(User)):
                raise HTTPException(409, '관리자 계정이 이미 등록되어 있습니다.')
            user = User(username=username, password_hash=hash_password(payload.password), role='admin')
            db.add(user)
            db.flush()
            seed_portal(db, user.id)
            user_id = user.id
    except IntegrityError as error:
        raise HTTPException(409, '관리자 계정이 이미 등록되어 있습니다.') from error
    create_session(request, response, user_id)
    return {'username': username}


@router.post('/login', dependencies=[Depends(require_mutation_header)])
def login(payload: Credentials, request: Request, response: Response):
    if not password_login_enabled():
        raise HTTPException(409, '이 포털은 SSO 로그인만 허용합니다. SSO로 로그인해 주세요.')
    record_attempt(request)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == payload.username.strip()))
    valid = verify_password(payload.password, user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH)
    if not user or not user.active or not user.password_hash or not valid:
        raise HTTPException(401, '아이디 또는 비밀번호가 올바르지 않습니다.')
    return begin_login(user, request, response)


@router.post('/mfa', dependencies=[Depends(require_mutation_header)])
def complete_mfa(payload: MFACode, request: Request, response: Response):
    record_attempt(request, 'mfa')
    failure = None
    user_id = None
    with SessionLocal.begin() as db:
        challenge = db.scalar(select(MFAChallenge).where(MFAChallenge.token_hash == token_hash(request.cookies.get(MFA_COOKIE, ''))).with_for_update())
        if not challenge or challenge.expires_at <= time.time() or challenge.attempts >= 5:
            failure = '인증 시간이 만료됐습니다. 다시 로그인해 주세요.'
        elif challenge.auth_method != 'oidc' and not password_login_enabled(configuration(db)):
            db.delete(challenge)
            failure = '이 포털은 SSO 로그인만 허용합니다. SSO로 다시 로그인해 주세요.'
        else:
            challenge.attempts += 1
            user = db.scalar(select(User).where(User.id == challenge.user_id).with_for_update())
            if user and user.active and verify_second_factor(db, user, payload.code.strip()):
                user_id = user.id
                db.delete(challenge)
            else:
                failure = '인증 코드가 올바르지 않거나 이미 사용한 코드입니다.'
                if challenge.attempts >= 5:
                    db.delete(challenge)
    if failure:
        raise HTTPException(401, failure)
    create_session(request, response, user_id)
    return {'authenticated': True}


@router.post('/logout', dependencies=[Depends(require_mutation_header)])
def logout(request: Request, response: Response):
    with SessionLocal.begin() as db:
        db.execute(delete(LoginSession).where(LoginSession.token_hash == token_hash(request.cookies.get(COOKIE_NAME, ''))))
        db.execute(delete(MFAChallenge).where(MFAChallenge.token_hash == token_hash(request.cookies.get(MFA_COOKIE, ''))))
    response.delete_cookie(COOKIE_NAME, path='/', httponly=True, samesite='lax')
    response.delete_cookie(MFA_COOKIE, path='/')
    return {'ok': True}


@router.get('/check')
def check(user: User = Depends(require_user)):
    return {'username': user.username, 'role': user.role}
