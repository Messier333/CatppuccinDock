import httpx
from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, HTTPException, Request
from joserfc.errors import JoseError
from sqlalchemy import select
from starlette.responses import RedirectResponse

from app.db.models import OIDCIdentity, Setting, User
from app.db.session import SessionLocal
from app.services.auth import begin_login
from app.services.oidc import configuration, create_client, frontend_base


router = APIRouter(prefix='/api/auth/oidc')


@router.get('/login')
async def login(request: Request):
    config = configuration()
    client = create_client(config)
    frontend_base(config)
    request.session['oidc_config_revision'] = config['revision']
    try:
        metadata = await client.load_server_metadata()
        if metadata.get('issuer') != config['issuer']:
            raise HTTPException(503, 'OIDC Issuer 주소가 인증 서비스와 일치하지 않습니다.')
        return await client.authorize_redirect(request, config['redirect_uri'])
    except (httpx.HTTPError, ValueError, RuntimeError) as error:
        raise HTTPException(503, 'SSO 인증 서비스에 연결하지 못했습니다.') from error


@router.get('/callback')
async def callback(request: Request):
    config = configuration()
    client = create_client(config)
    base = frontend_base(config)
    if request.session.pop('oidc_config_revision', None) != config['revision']:
        return RedirectResponse(base+'login/?sso_error=1', status_code=302)
    try:
        token = await client.authorize_access_token(request, claims_options={'iss': {'essential': True, 'value': config['issuer']}}, leeway=30)
        info = token.get('userinfo')
        if not info or not isinstance(info.get('sub'), str) or not 1 <= len(info['sub']) <= 256 or info.get('iss') != config['issuer']:
            raise ValueError('Missing verified OpenID identity')
    except (OAuthError, JoseError, httpx.HTTPError, ValueError, KeyError, RuntimeError):
        return RedirectResponse(base+'login/?sso_error=1', status_code=302)
    with SessionLocal.begin() as db:
        # Serialize identity lookup with explicit account links.
        db.scalar(select(Setting).where(Setting.key == 'portal').with_for_update())
        identity = db.scalar(select(OIDCIdentity).where(OIDCIdentity.issuer == info['iss'], OIDCIdentity.subject == str(info['sub'])))
        if identity:
            user = db.get(User, identity.user_id)
        else:
            return RedirectResponse(base+'login/?sso_error=1', status_code=302)
        if not user or not user.active:
            return RedirectResponse(base+'login/?sso_error=1', status_code=302)
    response = RedirectResponse(base, status_code=302)
    begin_login(user, request, response, auth_method='oidc')
    return response
