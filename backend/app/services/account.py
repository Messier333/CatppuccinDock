"""Shared account reauthentication, revocation and recovery-code operations."""
import re
import secrets
import time

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.security import cipher, token_hash, totp_counter, verify_password
from app.db.models import LoginSession, MFAChallenge, RecoveryCode
from app.services.auth import COOKIE_NAME


def revoke_sessions(db, user_id):
    db.execute(delete(LoginSession).where(LoginSession.user_id == user_id))
    db.execute(delete(MFAChallenge).where(MFAChallenge.user_id == user_id))


def reauthenticate(db, user, payload, request, second_factor=False):
    if user.password_hash:
        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(403, '현재 비밀번호가 올바르지 않습니다.')
    else:
        session = db.get(LoginSession, token_hash(request.cookies.get(COOKIE_NAME, '')))
        if not session or session.created_at < time.time() - 600:
            raise HTTPException(403, '안전한 설정 변경을 위해 SSO로 다시 로그인해 주세요.')
    if second_factor and not verify_second_factor(db, user, payload.code.strip()):
        raise HTTPException(403, '인증 코드가 올바르지 않거나 이미 사용한 코드입니다.')


def issue_recovery_codes(db, user_id):
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user_id))
    codes = [secrets.token_hex(10) for _ in range(10)]
    for code in codes:
        db.add(RecoveryCode(user_id=user_id, code_hash=token_hash(code)))
    return ['-'.join(code[i:i+4] for i in range(0, len(code), 4)) for code in codes]


def verify_second_factor(db, user, code):
    if not user.totp_secret:
        return False
    normalized = re.sub(r'[\s-]', '', code).lower()
    if re.fullmatch(r'[a-f0-9]{20}', normalized):
        recovery = db.scalar(select(RecoveryCode).where(RecoveryCode.user_id == user.id, RecoveryCode.code_hash == token_hash(normalized)).with_for_update())
        if recovery:
            db.delete(recovery)
            return True
        return False
    counter = totp_counter(cipher().decrypt(user.totp_secret.encode()).decode(), code, user.totp_counter)
    if counter is None:
        return False
    user.totp_counter = counter
    return True

