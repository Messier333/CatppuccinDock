"""Additive, transactional upgrade from the original single-owner release."""
import time
import uuid

from sqlalchemy import inspect, select, text, update

from app.db.models import Bookmark, LegacySession, LoginSession, Migration, Owner, Setting, User
from app.db.session import Base, SessionLocal, engine
from app.services.portal import default_config, seed_portal
from app.services.oidc import seed_configuration
from copy import deepcopy


def migrate():
    # PostgreSQL serializes initial table creation and data migration across workers.
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(80902026)"))
        Base.metadata.create_all(connection)
        session_columns = {column['name']: column for column in inspect(connection).get_columns('dock_user_sessions')}
        for name, definition in (
            ('public_id', 'VARCHAR(36)'),
            ('last_seen_at', 'FLOAT NOT NULL DEFAULT 0'),
            ('user_agent', "VARCHAR(512) NOT NULL DEFAULT ''"),
            ('ip_address', "VARCHAR(45) NOT NULL DEFAULT ''"),
        ):
            if name not in session_columns:
                connection.execute(text(f'ALTER TABLE dock_user_sessions ADD COLUMN {name} {definition}'))
        for token in connection.scalars(select(LoginSession.token_hash).where(LoginSession.public_id.is_(None))):
            connection.execute(update(LoginSession).where(LoginSession.token_hash == token).values(public_id=str(uuid.uuid4())))
        connection.execute(update(LoginSession).where(LoginSession.last_seen_at == 0).values(last_seen_at=LoginSession.created_at))
        connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_dock_user_sessions_public_id ON dock_user_sessions (public_id)'))
        if engine.dialect.name == 'postgresql' and ('public_id' not in session_columns or session_columns['public_id']['nullable']):
            connection.execute(text('ALTER TABLE dock_user_sessions ALTER COLUMN public_id SET NOT NULL'))
        image_columns = {column['name']: column for column in inspect(connection).get_columns('dock_background_images')}
        for name, size in (('storage_bucket', 255), ('storage_key', 512)):
            if name not in image_columns:
                connection.execute(text(f'ALTER TABLE dock_background_images ADD COLUMN {name} VARCHAR({size})'))
        if engine.dialect.name == 'postgresql' and not image_columns['data']['nullable']:
            connection.execute(text('ALTER TABLE dock_background_images ALTER COLUMN data DROP NOT NULL'))
        if 'source' not in {column['name'] for column in inspect(connection).get_columns('dock_background_images')}:
            connection.execute(text('ALTER TABLE dock_background_images ADD COLUMN source JSON'))
        if 'favorite' not in {column['name'] for column in inspect(connection).get_columns('dock_bookmarks')}:
            connection.execute(text('ALTER TABLE dock_bookmarks ADD COLUMN favorite BOOLEAN NOT NULL DEFAULT false'))
        if 'checking_until' not in {column['name'] for column in inspect(connection).get_columns('dock_service_monitors')}:
            connection.execute(text('ALTER TABLE dock_service_monitors ADD COLUMN checking_until FLOAT NOT NULL DEFAULT 0'))
        if 'access_mode' not in {column['name'] for column in inspect(connection).get_columns('dock_shared_links')}:
            connection.execute(text("ALTER TABLE dock_shared_links ADD COLUMN access_mode VARCHAR(16) NOT NULL DEFAULT 'all'"))
        if 'custom_api' not in {column['name'] for column in inspect(connection).get_columns('dock_proxy_sources')}:
            connection.execute(text('ALTER TABLE dock_proxy_sources ADD COLUMN custom_api JSON'))
        if 'auth_method' not in {column['name'] for column in inspect(connection).get_columns('dock_mfa_challenges')}:
            connection.execute(text("ALTER TABLE dock_mfa_challenges ADD COLUMN auth_method VARCHAR(16) NOT NULL DEFAULT 'local'"))
        if 'background_id' not in {column['name'] for column in inspect(connection).get_columns('dock_tabs')}:
            connection.execute(text('ALTER TABLE dock_tabs ADD COLUMN background_id VARCHAR(36) REFERENCES dock_background_images(id)'))
        with SessionLocal(bind=connection, join_transaction_mode="create_savepoint") as db:
            if not db.get(Migration, "multiuser-v1"):
                owner = db.get(Owner, 1)
                if owner:
                    db.add(User(id=1, username=owner.username, password_hash=owner.password_hash, role="admin"))
                    db.flush()
                    for session in db.scalars(select(LegacySession).where(LegacySession.expires_at > time.time())):
                        db.add(LoginSession(token_hash=session.token_hash, user_id=1, expires_at=session.expires_at))
                db.add(Migration(key="multiuser-v1"))
            if not db.get(Setting, "portal"):
                settings = default_config()
                settings.pop("tabs")
                db.add(Setting(key="portal", value=settings))
                db.flush()
            if not db.get(Setting, 'media-policy'):
                from app.services.media.media_policy import defaults
                db.add(Setting(key='media-policy', value=defaults()))
                db.flush()
            if not db.get(Migration, 'single-clock-search-providers-v1'):
                row = db.get(Setting, 'portal')
                config = deepcopy(row.value)
                if config['clock'].get('format') not in ('12h', '24h'):
                    config['clock']['format'] = '24h'
                config['clock'].setdefault('timezone', 'Asia/Seoul')
                config['additionalClocks'] = []
                config['search']['engines']['y'] = ['https://yandex.com/search/?text=', 'Yandex']
                row.value = config
                db.add(Migration(key='single-clock-search-providers-v1'))
            if not db.get(Migration, 'automatic-icon-colors-v1'):
                # Only untouched bundled defaults are identifiable as inherited colors.
                # Personal hex colors (including the former default blue) stay explicit.
                for tab in default_config()['tabs']:
                    for category in tab['categories']:
                        for link in category['links']:
                            db.execute(update(Bookmark).where(
                                Bookmark.name == link['name'], Bookmark.url == link['url'],
                                Bookmark.icon == link['icon'], Bookmark.icon_color == link['icon_color']
                            ).values(icon_color='auto'))
                db.add(Migration(key='automatic-icon-colors-v1'))
            for user in db.scalars(select(User)):
                seed_portal(db, user.id)
            seed_configuration(db)
            if engine.dialect.name == "postgresql":
                # Explicitly inserting the migrated id must advance the identity sequence.
                db.execute(text("SELECT setval(pg_get_serial_sequence('dock_users', 'id'), COALESCE((SELECT MAX(id) FROM dock_users), 1), EXISTS(SELECT 1 FROM dock_users))"))
            db.commit()
