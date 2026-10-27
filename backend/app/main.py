from contextlib import asynccontextmanager
import os
import asyncio
from contextlib import suppress

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.account import router as account_router
from app.api.account_sessions import router as account_sessions_router
from app.api.uploaded_icons import router as uploaded_icons_router
from app.api.admin import router as admin_router
from app.api.oidc import router as oidc_router
from app.api.portal import router as portal_router
from app.api.proxy import router as proxy_router
from app.api.library import router as library_router
from app.api.icons import router as icons_router
from app.api.search import router as search_router
from app.api.backgrounds import router as backgrounds_router
from app.api.media_settings import router as media_settings_router
from app.api.weather import router as weather_router
from app.api.groups import router as groups_router
from app.api.trash import router as trash_router
from app.api.backups import router as backups_router
from app.api.monitoring import router as monitoring_router
from app.api.proxy_sync import router as proxy_sync_router
from app.api.footer import router as footer_router
from app.api.navigation import router as navigation_router
from app.api.bookmark_tools import router as bookmark_tools_router
from app.api.integrations import router as integrations_router
from app.services.background_jobs import run as background_jobs
from app.services import monitoring
from app.services.media import storage
from app.db.session import check_database
from app.db.migrations import migrate
from app.core.security import cipher
from app.services.audit import configure_audit, log_auth_failure
from starlette.middleware.sessions import SessionMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    cipher()
    configure_audit()
    migrate()
    if storage.backend() == 's3':
        storage.configuration()
    monitoring.start()
    task = asyncio.create_task(background_jobs())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await asyncio.to_thread(monitoring.stop)


app = FastAPI(title="CatppuccinDock", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=os.getenv('AUTH_ENCRYPTION_KEY', ''), session_cookie='catppuccindock_oidc', max_age=600,
                   same_site='lax', https_only=os.getenv('COOKIE_SECURE', 'false').lower() == 'true')
for router in (auth_router, account_router, oidc_router, portal_router, admin_router, proxy_router, library_router, icons_router, search_router, backgrounds_router, weather_router, groups_router, trash_router, backups_router, monitoring_router, proxy_sync_router, footer_router, navigation_router, bookmark_tools_router):
    app.include_router(router)
app.include_router(media_settings_router)
app.include_router(account_sessions_router)
app.include_router(uploaded_icons_router)
app.include_router(integrations_router)


@app.middleware("http")
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    if request.method == 'POST' and request.url.path in ('/api/auth/login', '/api/auth/mfa', '/api/auth/setup') and response.status_code in (401, 403, 422, 429):
        log_auth_failure(request, response.status_code)
    if not response.headers.get('Cache-Control'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def home() -> dict[str, str]:
    return {"message": "CatppuccinDock API"}


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        check_database()
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    storage.check()
    return {"status": "ok", "database": "ok", "storage": storage.backend()}
