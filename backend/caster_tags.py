"""Automatic Caster tag for approved streamers (issue #201).

A website account (account_type "full") whose `twitch_account_id` is an approved
channel id (twitch_channels.approved_channels: TWITCH_MVP_CHANNEL_IDS plus
portal-approved rows) gets the `caster` tag with source "caster_sync". The sync
removes only rows it granted itself; admin grants (source "admin") are never touched.
"""
import logging
import time

from deps import _audit
from models import TagDefinition, User, UserTag
import twitch_channels

logger = logging.getLogger(__name__)

CASTER_TAG_KEY = "caster"
SOURCE_ADMIN = "admin"
SOURCE_SYNC = "caster_sync"
REASON_NOT_APPROVED = "channel_not_approved"


def sync(db, reason: str | None = None) -> tuple[int, int]:
    """Grant and remove automatic Caster tags; return (granted, revoked). Each change
    writes an audit entry (actor "system"). The caller commits."""
    tag = db.query(TagDefinition).filter(TagDefinition.key == CASTER_TAG_KEY).first()
    if tag is None:
        logger.warning("Caster tag sync skipped: no '%s' tag definition", CASTER_TAG_KEY)
        return 0, 0
    approved = twitch_channels.approved_channels(db)
    matching = {}
    if approved:
        matching = {uid: cid for uid, cid in
                    db.query(User.id, User.twitch_account_id)
                    .filter(User.twitch_account_id.in_(approved), User.account_type == "full").all()}
    existing = {row.user_id: row for row in db.query(UserTag).filter(UserTag.tag_id == tag.id).all()}

    granted = revoked = 0
    now = int(time.time())
    for uid, channel_id in sorted(matching.items()):
        if uid in existing:
            continue
        db.add(UserTag(user_id=uid, tag_id=tag.id, granted_by=None, granted_at=now,
                       source=SOURCE_SYNC))
        _audit(db, "caster_tag_auto_grant", actor_id=None, actor_username="system",
               detail=f"user_id={uid} channel={channel_id}")
        granted += 1
    for uid, row in sorted(existing.items()):
        if row.source != SOURCE_SYNC or uid in matching:
            continue
        db.delete(row)
        _audit(db, "caster_tag_auto_revoke", actor_id=None, actor_username="system",
               detail=f"user_id={uid} reason={reason or REASON_NOT_APPROVED}")
        revoked += 1
    if granted or revoked:
        db.flush()
    return granted, revoked


def sync_safely(db, reason: str | None = None) -> tuple[int, int]:
    """sync() inside a savepoint: a failure is logged (exception type only) and rolls
    back only the sync, so the caller's sign-in, connect or admin action still
    succeeds. Does not commit."""
    try:
        with db.begin_nested():
            return sync(db, reason)
    except Exception as exc:  # noqa: BLE001 — the sync must never break its caller
        logger.warning("Caster tag sync failed (%s)", type(exc).__name__)
        return 0, 0
