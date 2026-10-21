from fastapi import HTTPException
from sqlalchemy import or_, select

from app.db.models import GroupMember, SharedGroupGrant, SharedLink, SharedPlacement, SharedUserGrant


def allowed_link_ids(db, user):
    query = select(SharedLink.id).where(SharedLink.published.is_(True))
    if user.role != 'admin':
        groups = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
        query = query.where(or_(SharedLink.access_mode == 'all',
            SharedLink.id.in_(select(SharedUserGrant.link_id).where(SharedUserGrant.user_id == user.id)),
            SharedLink.id.in_(select(SharedGroupGrant.link_id).where(SharedGroupGrant.group_id.in_(groups)))))
    return set(db.scalars(query))


def link_allowed(db, link, user):
    return bool(link and link.id in allowed_link_ids(db, user))


def shared_links_for_bookmarks(db, bookmark_ids):
    return {placement.bookmark_id: link for placement, link in db.execute(
        select(SharedPlacement, SharedLink).join(SharedLink, SharedLink.id == SharedPlacement.link_id)
        .where(SharedPlacement.bookmark_id.in_(bookmark_ids)))}


def resolve_shared(db, bookmark, user=None):
    placement = db.get(SharedPlacement, bookmark.id)
    if not placement:
        return None
    link = db.get(SharedLink, placement.link_id)
    if not link or not link.published or user is not None and not link_allowed(db, link, user):
        raise HTTPException(404, '관리자가 공개를 해제한 링크입니다.')
    return link


def public_link(link):
    return {key: getattr(link, key) for key in ('id', 'name', 'url', 'icon', 'icon_color', 'source_name', 'published')}


def admin_link(db, link):
    return public_link(link) | {'access_mode': link.access_mode,
        'user_ids': list(db.scalars(select(SharedUserGrant.user_id).where(SharedUserGrant.link_id == link.id))),
        'group_ids': list(db.scalars(select(SharedGroupGrant.group_id).where(SharedGroupGrant.link_id == link.id)))}
