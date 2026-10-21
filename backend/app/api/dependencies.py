"""Authentication, role and mutation-header dependencies for API routes."""
from fastapi import Depends, HTTPException, Request

from app.db.models import User
from app.services.auth import current_user


def require_mutation_header(request: Request):
    if request.headers.get('x-catppuccindock') != '1':
        raise HTTPException(403, '허용되지 않은 요청입니다.')


def require_user(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(401, '로그인이 필요합니다.')
    return user


def require_admin(user: User = Depends(require_user)):
    if user.role != 'admin':
        raise HTTPException(403, '관리자 권한이 필요합니다.')
    return user
