from fastapi import APIRouter, Depends

from app.api.dependencies import require_user, require_mutation_header
from app.db.models import User
from app.services.preferences import apply_preferences
from app.db.models import Setting
from app.db.session import SessionLocal
from app.services.weather import current_weather


router = APIRouter(prefix='/api/weather', dependencies=[Depends(require_user)])


@router.get('')
async def weather(user: User = Depends(require_user)):
    with SessionLocal() as db:
        config = apply_preferences(db,user.id,db.get(Setting, 'portal').value)['temperature']
    return await current_weather(config.get('location', 'Seoul'), config.get('scale', 'C'))


@router.post('/refresh', dependencies=[Depends(require_mutation_header)])
async def refresh(user: User = Depends(require_user)):
    with SessionLocal() as db:
        config = apply_preferences(db,user.id,db.get(Setting, 'portal').value)['temperature']
    return await current_weather(config.get('location', 'Seoul'), config.get('scale', 'C'), force=True)
