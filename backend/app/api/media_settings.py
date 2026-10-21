from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.dependencies import require_admin, require_mutation_header
from app.core.security import cipher
from app.db.models import Setting
from app.db.session import SessionLocal
from app.schemas.media_policy import MediaPolicy, MediaSettings
from app.services.media import media_policy, gif_search

router = APIRouter(prefix='/api/admin/backgrounds', dependencies=[Depends(require_admin)])


@router.get('')
def settings():
    with SessionLocal() as db:
        return media_policy.public_settings(media_policy.policy(db))


@router.put('', dependencies=[Depends(require_mutation_header)])
def save(payload: MediaSettings):
    with media_policy.mutex, SessionLocal.begin() as db:
        row = db.scalar(select(Setting).where(Setting.key==media_policy.POLICY_KEY).with_for_update())
        config = media_policy.policy(db) | {key:getattr(payload,key) for key in MediaPolicy.model_fields}
        if payload.clear_pixabay_key:
            config['pixabay_key_encrypted'] = ''
        elif payload.pixabay_key:
            config['pixabay_key_encrypted'] = cipher().encrypt(payload.pixabay_key.strip().encode()).decode()
        row.value = config
        result = media_policy.public_settings(config)
    with gif_search.lock:
        gif_search.cache.clear()
    return result
