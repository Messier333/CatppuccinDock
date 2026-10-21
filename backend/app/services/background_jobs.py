import asyncio,logging,time
from sqlalchemy import delete
from app.db.models import OperationPreview,TrashItem
from app.db.session import SessionLocal
from app.services import proxy_sync, footer
from app.services.media import storage
logger=logging.getLogger(__name__)

def cleanup():
    with SessionLocal.begin() as db:
        db.execute(delete(OperationPreview).where(OperationPreview.expires_at<time.time()))
        db.execute(delete(TrashItem).where(TrashItem.expires_at<time.time()))

async def run():
    # Nothing is contacted unless an administrator explicitly configures targets.
    while True:
        await asyncio.sleep(30)
        results=await asyncio.gather(asyncio.to_thread(proxy_sync.run_due),asyncio.to_thread(footer.run_due),asyncio.to_thread(cleanup),asyncio.to_thread(storage.cleanup),return_exceptions=True)
        for result in results:
            if isinstance(result,Exception):logger.warning('Background operation failed: %s',type(result).__name__)
