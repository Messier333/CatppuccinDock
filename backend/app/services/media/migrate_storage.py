"""Resumable operator-only migration: python -m app.services.media.migrate_storage."""
import argparse

from sqlalchemy import select

from app.db.models import BackgroundImage
from app.db.session import SessionLocal
from app.services.media import storage


def migrate(*, apply=False):
    if storage.backend() != 's3':
        raise RuntimeError('Configure MEDIA_STORAGE_BACKEND=s3 before migration')
    storage.check()
    with SessionLocal() as db:
        ids = list(db.scalars(select(BackgroundImage.id).where(BackgroundImage.storage_key.is_(None))))
    if not apply:
        return len(ids)
    migrated = 0
    for image_id in ids:
        # Commit one verified file at a time: interruption can safely be resumed.
        with SessionLocal.begin() as db:
            row = db.scalar(select(BackgroundImage).where(BackgroundImage.id == image_id).with_for_update())
            if row is None or row.storage_key:
                continue
            raw = storage.read(row)
            storage.write(db, row, raw, verify=True)
        migrated += 1
    return migrated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Copy, verify and clear legacy DB file bytes')
    args = parser.parse_args()
    print(f'{"Migrated" if args.apply else "Pending"}: {migrate(apply=args.apply)} GIF files')


if __name__ == '__main__':
    main()
