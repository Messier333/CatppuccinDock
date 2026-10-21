import io
import time

import pyotp
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select

from app.api.dependencies import require_mutation_header, require_user
from app.core.security import cipher, hash_password, totp_counter, verify_password
from app.db.models import OIDCIdentity, RecoveryCode, TOTPEnrollment, User, PersonalPreference
from app.schemas.preferences import PreferencesData
from app.services.preferences import preferences
from app.db.session import SessionLocal
from app.schemas.account import ConfirmTOTP, NewPassword, Reauthentication
from app.services.account import issue_recovery_codes, reauthenticate, revoke_sessions
from app.services.auth import create_session, record_attempt


router = APIRouter(prefix='/api/account')


@router.get('/preferences')
def get_preferences(user: User = Depends(require_user)):
    with SessionLocal() as db: return preferences(db,user.id)


@router.put('/preferences', dependencies=[Depends(require_mutation_header)])
def save_preferences(payload: PreferencesData, user: User = Depends(require_user)):
    with SessionLocal.begin() as db:
        db.scalar(select(User).where(User.id==user.id).with_for_update())
        row = db.get(PersonalPreference,user.id)
        values = payload.model_dump(exclude_none=True)
        if row: row.values = values
        else: db.add(PersonalPreference(user_id=user.id,values=values))
        db.flush()
        return preferences(db,user.id)


@router.get('')
def account(user: User = Depends(require_user)):
    with SessionLocal() as db:
        remaining = db.scalar(select(func.count()).select_from(RecoveryCode).where(RecoveryCode.user_id == user.id))
        identities = [{'id': identity.id, 'issuer': identity.issuer, 'subject': identity.subject} for identity in db.scalars(select(OIDCIdentity).where(OIDCIdentity.user_id == user.id))]
    return {'username': user.username, 'role': user.role, 'has_password': bool(user.password_hash),
            'totp_enabled': bool(user.totp_secret), 'recovery_remaining': remaining, 'identities': identities}


@router.post('/password', dependencies=[Depends(require_mutation_header)])
def change_password(payload: NewPassword, request: Request, response: Response, current: User = Depends(require_user)):
    record_attempt(request, 'password:' + str(current.id))
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.id == current.id).with_for_update())
        if not user.password_hash or not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(403, '현재 비밀번호가 올바르지 않습니다.')
        user.password_hash = hash_password(payload.new_password)
        revoke_sessions(db, user.id)
    create_session(request, response, current.id)
    return {'ok': True}


@router.post('/2fa/enroll', dependencies=[Depends(require_mutation_header)])
def enroll(payload: Reauthentication, request: Request, current: User = Depends(require_user)):
    record_attempt(request, 'enroll:' + str(current.id))
    secret = pyotp.random_base32()
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.id == current.id).with_for_update())
        if user.totp_secret:
            raise HTTPException(409, '2단계 인증이 이미 설정되어 있습니다.')
        reauthenticate(db, user, payload, request)
        enrollment = db.get(TOTPEnrollment, user.id)
        if enrollment:
            db.delete(enrollment)
            db.flush()
        db.add(TOTPEnrollment(user_id=user.id, secret=cipher().encrypt(secret.encode()).decode(), expires_at=time.time()+600))
    uri = pyotp.TOTP(secret).provisioning_uri(name=current.username, issuer_name='CatppuccinDock')
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=5)
    output = io.BytesIO()
    image.save(output)
    return {'secret': secret, 'provisioning_uri': uri, 'qr_svg': output.getvalue().decode()}


@router.post('/2fa/confirm', dependencies=[Depends(require_mutation_header)])
def confirm(payload: ConfirmTOTP, request: Request, response: Response, current: User = Depends(require_user)):
    record_attempt(request, 'confirm:' + str(current.id))
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.id == current.id).with_for_update())
        enrollment = db.get(TOTPEnrollment, user.id)
        if user.totp_secret or not enrollment or enrollment.expires_at <= time.time():
            raise HTTPException(409, '설정을 처음부터 다시 시작해 주세요.')
        secret = cipher().decrypt(enrollment.secret.encode()).decode()
        counter = totp_counter(secret, payload.code)
        if counter is None:
            raise HTTPException(400, '인증 코드를 확인해 주세요.')
        user.totp_secret = enrollment.secret
        user.totp_counter = counter
        db.delete(enrollment)
        codes = issue_recovery_codes(db, user.id)
        revoke_sessions(db, user.id)
    create_session(request, response, current.id)
    return {'recovery_codes': codes}


@router.post('/2fa/disable', dependencies=[Depends(require_mutation_header)])
def disable(payload: Reauthentication, request: Request, response: Response, current: User = Depends(require_user)):
    record_attempt(request, 'disable:' + str(current.id))
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.id == current.id).with_for_update())
        if not user.totp_secret:
            raise HTTPException(409, '2단계 인증이 설정되어 있지 않습니다.')
        reauthenticate(db, user, payload, request, second_factor=True)
        user.totp_secret = None
        user.totp_counter = -1
        db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
        revoke_sessions(db, user.id)
    create_session(request, response, current.id)
    return {'ok': True}


@router.post('/2fa/recovery-codes', dependencies=[Depends(require_mutation_header)])
def regenerate(payload: Reauthentication, request: Request, current: User = Depends(require_user)):
    record_attempt(request, 'recovery:' + str(current.id))
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.id == current.id).with_for_update())
        if not user.totp_secret:
            raise HTTPException(409, '2단계 인증을 먼저 설정해 주세요.')
        reauthenticate(db, user, payload, request, second_factor=True)
        codes = issue_recovery_codes(db, user.id)
    return {'recovery_codes': codes}
