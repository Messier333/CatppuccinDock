"""Recovery commands available only to the server operator."""
import argparse
import getpass
import secrets

from sqlalchemy import delete, select

from app.services.account import revoke_sessions
from app.db.session import SessionLocal
from app.db.models import OAuthState, RecoveryCode, Setting, TOTPEnrollment, User
from app.core.security import hash_password


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['reset-password', 'reset-2fa', 'enable-password-login'])
    parser.add_argument('username', nargs='?')
    args = parser.parse_args()
    if args.command == 'enable-password-login':
        with SessionLocal.begin() as db:
            db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
            row = db.scalar(select(Setting).where(Setting.key == 'oidc').with_for_update())
            if not row:
                raise SystemExit('SSO 설정을 찾을 수 없습니다.')
            row.value = {**row.value, 'login_mode': 'both', 'revision': secrets.token_hex(16)}
            db.execute(delete(OAuthState))
        print('비밀번호 로그인을 다시 허용했습니다. 관리자 비밀번호가 없으면 reset-password도 실행하세요.')
        return
    password = None
    if args.command == 'reset-password':
        password = getpass.getpass('새 비밀번호 (12자 이상): ')
        if not 12 <= len(password) <= 256:
            raise SystemExit('비밀번호는 12~256자로 입력하세요.')
        if password != getpass.getpass('새 비밀번호 확인: '):
            raise SystemExit('비밀번호가 일치하지 않습니다.')
    with SessionLocal.begin() as db:
        query = select(User).where(User.username == args.username) if args.username else select(User).where(User.role == 'admin').order_by(User.id)
        user = db.scalar(query.with_for_update())
        if not user:
            raise SystemExit('사용자를 찾을 수 없습니다.')
        if password:
            user.password_hash = hash_password(password)
        else:
            user.totp_secret, user.totp_counter = None, -1
            db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
            db.execute(delete(TOTPEnrollment).where(TOTPEnrollment.user_id == user.id))
        revoke_sessions(db, user.id)
        username = user.username
    print(f'{username}: 설정을 변경하고 해당 계정의 모든 세션을 종료했습니다.')


if __name__ == '__main__':
    main()
