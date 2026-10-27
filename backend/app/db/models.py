import time
import uuid

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Owner(Base):
    """Legacy tables stay intact so upgrades preserve the original account."""
    __tablename__ = "dock_owner"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))


class LegacySession(Base):
    __tablename__ = "dock_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("dock_owner.id"))
    expires_at: Mapped[float] = mapped_column(Float)


class User(Base):
    __tablename__ = "dock_users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'member')"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_counter: Mapped[int] = mapped_column(Integer, default=-1)


class LoginSession(Base):
    __tablename__ = "dock_user_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    last_seen_at: Mapped[float] = mapped_column(Float, default=time.time)
    user_agent: Mapped[str] = mapped_column(String(512), default='')
    ip_address: Mapped[str] = mapped_column(String(45), default='')


class LoginAttempt(Base):
    __tablename__ = "dock_login_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[float] = mapped_column(Float, index=True)


class MFAChallenge(Base):
    __tablename__ = "dock_mfa_challenges"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), index=True)
    expires_at: Mapped[float] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    auth_method: Mapped[str] = mapped_column(String(16), default='local', server_default='local')


class TOTPEnrollment(Base):
    __tablename__ = "dock_totp_enrollments"
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), primary_key=True)
    secret: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)


class RecoveryCode(Base):
    __tablename__ = "dock_recovery_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), index=True)


class OIDCIdentity(Base):
    __tablename__ = "dock_oidc_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), index=True)
    issuer: Mapped[str] = mapped_column(String(1024))
    subject: Mapped[str] = mapped_column(String(256))


class OAuthState(Base):
    __tablename__ = "dock_oauth_states"
    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)


class Setting(Base):
    __tablename__ = "dock_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Migration(Base):
    __tablename__ = "dock_migrations"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)


class PortalSeed(Base):
    __tablename__ = "dock_portal_seeds"
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), primary_key=True)


def new_id():
    return str(uuid.uuid4())


class BackgroundImage(Base):
    __tablename__ = 'dock_background_images'
    __table_args__ = (UniqueConstraint('user_id', 'sha256'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    frames: Mapped[int] = mapped_column(Integer)
    source: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True, nullable=True)
    storage_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class UploadedIcon(Base):
    __tablename__ = 'dock_uploaded_icons'
    __table_args__ = (UniqueConstraint('user_id', 'sha256'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True, nullable=True)
    storage_bucket: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class BackgroundTransfer(Base):
    __tablename__ = 'dock_background_transfers'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=True)
    charged_bytes: Mapped[int] = mapped_column(Integer, default=0)


class MediaObjectDeletion(Base):
    """Committed file deletions survive storage outages and process restarts."""
    __tablename__ = 'dock_media_object_deletions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bucket: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class BackgroundAssetKey(Base):
    """Only server-verified imports create shared provider cache entries."""
    __tablename__ = 'dock_background_asset_keys'
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), primary_key=True)
    key: Mapped[str] = mapped_column(String(224), primary_key=True)
    image_id: Mapped[str] = mapped_column(ForeignKey('dock_background_images.id', ondelete='CASCADE'), index=True)


class Tab(Base):
    __tablename__ = "dock_tabs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    banner: Mapped[str] = mapped_column(String(32), default="none")
    background_id: Mapped[str | None] = mapped_column(ForeignKey('dock_background_images.id'), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class Category(Base):
    __tablename__ = "dock_categories"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), index=True)
    tab_id: Mapped[str] = mapped_column(ForeignKey("dock_tabs.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer, default=0)


class Bookmark(Base):
    __tablename__ = "dock_bookmarks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("dock_users.id"), index=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("dock_categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048))
    icon: Mapped[str] = mapped_column(String(64), default="world")
    icon_color: Mapped[str] = mapped_column(String(7), default="auto")
    position: Mapped[int] = mapped_column(Integer, default=0)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')


class PersonalPreference(Base):
    __tablename__ = 'dock_personal_preferences'
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id', ondelete='CASCADE'), primary_key=True)
    values: Mapped[dict] = mapped_column(JSON, default=dict)


class BookmarkVisit(Base):
    __tablename__ = 'dock_bookmark_visits'
    bookmark_id: Mapped[str] = mapped_column(ForeignKey('dock_bookmarks.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id', ondelete='CASCADE'), index=True)
    visited_at: Mapped[float] = mapped_column(Float, index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)


class ProxySource(Base):
    __tablename__ = 'dock_proxy_sources'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(16))
    base_url: Mapped[str] = mapped_column(String(2048))
    token_encrypted: Mapped[str] = mapped_column(Text)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[str] = mapped_column(String(64))
    custom_api: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ProxyPreview(Base):
    __tablename__ = 'dock_proxy_previews'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey('dock_proxy_sources.id'), index=True)
    source_revision: Mapped[str] = mapped_column(String(64))
    entries: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class SharedLink(Base):
    __tablename__ = 'dock_shared_links'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str | None] = mapped_column(ForeignKey('dock_proxy_sources.id'), nullable=True)
    source_name: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    icon: Mapped[str] = mapped_column(String(64), default='world')
    icon_color: Mapped[str] = mapped_column(String(7), default='auto')
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    access_mode: Mapped[str] = mapped_column(String(16), default='all', server_default='all')


class SharedPlacement(Base):
    __tablename__ = 'dock_shared_placements'
    bookmark_id: Mapped[str] = mapped_column(ForeignKey('dock_bookmarks.id', ondelete='CASCADE'), primary_key=True)
    link_id: Mapped[str] = mapped_column(ForeignKey('dock_shared_links.id'), index=True)


class UserGroup(Base):
    __tablename__ = 'dock_groups'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class GroupMember(Base):
    __tablename__ = 'dock_group_members'
    group_id: Mapped[str] = mapped_column(ForeignKey('dock_groups.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), primary_key=True)


class SharedUserGrant(Base):
    __tablename__ = 'dock_shared_user_grants'
    link_id: Mapped[str] = mapped_column(ForeignKey('dock_shared_links.id', ondelete='CASCADE'), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), primary_key=True)


class SharedGroupGrant(Base):
    __tablename__ = 'dock_shared_group_grants'
    link_id: Mapped[str] = mapped_column(ForeignKey('dock_shared_links.id', ondelete='CASCADE'), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey('dock_groups.id', ondelete='CASCADE'), primary_key=True)


class TrashItem(Base):
    __tablename__ = 'dock_trash'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(160))
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class OperationPreview(Base):
    __tablename__ = 'dock_operation_previews'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    payload_encrypted: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class ServiceMonitor(Base):
    __tablename__ = 'dock_service_monitors'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    link_url: Mapped[str] = mapped_column(String(2048), unique=True)
    check_url: Mapped[str] = mapped_column(String(2048))
    allow_private: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval: Mapped[int] = mapped_column(Integer, default=300)
    state: Mapped[str] = mapped_column(String(16), default='pending')
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(String(160), default='')
    checked_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_check: Mapped[float] = mapped_column(Float, default=0, index=True)
    checking_until: Mapped[float] = mapped_column(Float, default=0, server_default='0')
    revision: Mapped[str] = mapped_column(String(64))


class ProxySync(Base):
    __tablename__ = 'dock_proxy_sync'
    source_id: Mapped[str] = mapped_column(ForeignKey('dock_proxy_sources.id', ondelete='CASCADE'), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval: Mapped[int] = mapped_column(Integer, default=900)
    scheme: Mapped[str] = mapped_column(String(8), default='auto')
    public_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    baseline: Mapped[list] = mapped_column(JSON, default=list)
    inventory: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[str] = mapped_column(String(64), default='')
    checked_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    next_check: Mapped[float] = mapped_column(Float, default=0, index=True)
    error: Mapped[str] = mapped_column(String(240), default='')


class FooterMetric(Base):
    __tablename__ = 'dock_footer_metrics'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    config: Mapped[dict] = mapped_column(JSON)
    token_encrypted: Mapped[str] = mapped_column(Text, default='')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempted_at: Mapped[float] = mapped_column(Float, default=0)
    next_check: Mapped[float] = mapped_column(Float, default=0, index=True)
    revision: Mapped[str] = mapped_column(String(64))


class ServiceIntegration(Base):
    __tablename__ = 'dock_service_integrations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    provider: Mapped[str] = mapped_column(String(24), default='proxmox')
    config: Mapped[dict] = mapped_column(JSON)
    token_encrypted: Mapped[str] = mapped_column(Text)
    revision: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[float | None] = mapped_column(Float)
    next_check: Mapped[float] = mapped_column(Float, default=0)
    checking_until: Mapped[float] = mapped_column(Float, default=0)
    action_until: Mapped[float] = mapped_column(Float, default=0)
    detail_after: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str] = mapped_column(String(240), default='')


class IntegrationTask(Base):
    __tablename__ = 'dock_integration_tasks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    integration_id: Mapped[str] = mapped_column(ForeignKey('dock_service_integrations.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('dock_users.id'), index=True)
    revision: Mapped[str] = mapped_column(String(64))
    node: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(160))
    upid: Mapped[str] = mapped_column(String(512), default='')
    state: Mapped[str] = mapped_column(String(24), default='submitting')
    detail: Mapped[str] = mapped_column(String(240), default='')
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    checked_at: Mapped[float] = mapped_column(Float, default=0)
