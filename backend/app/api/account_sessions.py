import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select

from app.api.dependencies import require_mutation_header, require_user
from app.core.security import token_hash
from app.db.models import LoginSession, MFAChallenge, User
from app.db.session import SessionLocal
from app.services.auth import COOKIE_NAME, MFA_COOKIE
from app.services.login_devices import session_details

router = APIRouter(prefix='/api/account/sessions')


def live_session(db, request, user):
    session = db.scalar(select(LoginSession).where(
        LoginSession.token_hash == token_hash(request.cookies.get(COOKIE_NAME, '')),
        LoginSession.user_id == user.id, LoginSession.expires_at > time.time()))
    if not session:
        raise HTTPException(401, '로그인이 필요합니다.')
    return session


@router.get('')
def sessions(request: Request, offset: int = Query(0, ge=0), limit: int = Query(5, ge=1, le=50), user: User = Depends(require_user)):
    with SessionLocal() as db:
        current = live_session(db, request, user)
        others = (LoginSession.user_id == user.id, LoginSession.expires_at > time.time(), LoginSession.token_hash != current.token_hash)
        total = db.scalar(select(func.count()).select_from(LoginSession).where(*others))
        rows = db.scalars(select(LoginSession).where(*others).order_by(LoginSession.last_seen_at.desc(), LoginSession.public_id).offset(offset).limit(limit))
        return {'current_session': session_details(current), 'items': [session_details(row) for row in rows],
                'total_others': total, 'offset': offset, 'limit': limit}


@router.post('/revoke-others', dependencies=[Depends(require_mutation_header)])
def revoke_others(request: Request, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        current = live_session(db, request, user)
        result = db.execute(delete(LoginSession).where(LoginSession.user_id == user.id, LoginSession.token_hash != current.token_hash))
        # Pending 2FA logins must not survive "log out other devices".
        db.execute(delete(MFAChallenge).where(MFAChallenge.user_id == user.id))
        return {'ok': True, 'revoked': result.rowcount}


@router.delete('/{session_id}', dependencies=[Depends(require_mutation_header)])
def revoke(session_id: UUID, request: Request, response: Response, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id == user.id).with_for_update())
        current = live_session(db, request, user)
        target = db.scalar(select(LoginSession).where(LoginSession.public_id == str(session_id), LoginSession.user_id == user.id, LoginSession.expires_at > time.time()))
        if not target:
            raise HTTPException(404, '로그인 기기를 찾을 수 없습니다. 목록을 새로고침해 주세요.')
        current_revoked = target.token_hash == current.token_hash
        db.delete(target)
        if current_revoked:
            db.execute(delete(MFAChallenge).where(MFAChallenge.token_hash == token_hash(request.cookies.get(MFA_COOKIE, ''))))
    if current_revoked:
        response.delete_cookie(COOKIE_NAME, path='/', httponly=True, samesite='lax')
        response.delete_cookie(MFA_COOKIE, path='/')
    return {'ok': True, 'current_revoked': current_revoked}
