"""Admin view and reversal of Twitch collection merges (issue #160), and approved
streamers (issue #175).

A merge moves a Twitch soft account's cards and tokens into a website account
(twitch_oauth.merge_confirm); soft_accounts.reverse_merge undoes one within 30 days
from its twitch_merge_log row. Both routes need an admin with a recent password check.

Approved streamers: channels that may set match MVPs (twitch_channels). Listing needs
an admin; approve / reject / remove also need a recent password check.
"""
import json
import time

from fastapi import APIRouter, Depends, HTTPException

import soft_accounts
import twitch_channels
from database import get_db
from deps import require_admin, require_recent_reauth
from models import TwitchMergeLog, User

router = APIRouter()


@router.get("/admin/twitch/merges", dependencies=[Depends(require_recent_reauth)])
def list_twitch_merges(admin: dict = Depends(require_admin), db=Depends(get_db)):
    """Twitch collection merges of the last 30 days (issue #160), newest first, with
    whether each can still be reversed. No Twitch ids."""
    now = int(time.time())
    logs = (db.query(TwitchMergeLog)
            .filter(TwitchMergeLog.merged_at >= now - soft_accounts.MERGE_UNDO_SECONDS)
            .order_by(TwitchMergeLog.merged_at.desc(), TwitchMergeLog.id.desc()).limit(100).all())
    names = {u.id: u.display_name for u in
             db.query(User).filter(User.id.in_({l.full_user_id for l in logs})).all()} if logs else {}
    rows = []
    for log in logs:
        reason = soft_accounts.reversal_block_reason(db, log, now)
        rows.append({
            "id": log.id,
            "full_user_id": log.full_user_id,
            "username": names.get(log.full_user_id),
            "merged_at": log.merged_at,
            "cards": len(json.loads(log.card_ids or "[]")),
            "tokens_moved": log.tokens_moved,
            "reversed_at": log.reversed_at,
            "reversible": reason is None,
            "blocked_reason": reason,
        })
    return rows


@router.post("/admin/twitch/merges/{log_id}/reverse", dependencies=[Depends(require_recent_reauth)])
def reverse_twitch_merge(log_id: int, admin: dict = Depends(require_admin), db=Depends(get_db)):
    """Undo a Twitch collection merge within 30 days (issue #160): the soft account is
    recreated and gets its cards, tokens and roster rows back."""
    log = db.get(TwitchMergeLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Merge not found")
    try:
        result = soft_accounts.reverse_merge(db, log, actor=admin)
        db.commit()
    except soft_accounts.MergeReversalError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception:
        db.rollback()
        raise
    return result


@router.get("/admin/twitch/channels")
def list_twitch_channels(admin: dict = Depends(require_admin), db=Depends(get_db)):
    """Approved streamers (issue #175): {env, approved, pending, rejected}. Env channels
    come from TWITCH_MVP_CHANNEL_IDS and can't be removed here. Missing Twitch names are
    looked up through Helix, best effort."""
    return twitch_channels.list_channels(db)


def _decide(channel_id: str, action: str, admin: dict, db):
    try:
        row = twitch_channels.decide(db, channel_id, action, admin)
        db.commit()
    except twitch_channels.ChannelNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except twitch_channels.ChannelConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    return row


@router.post("/admin/twitch/channels/{channel_id}/approve", dependencies=[Depends(require_recent_reauth)])
def approve_twitch_channel(channel_id: str, admin: dict = Depends(require_admin), db=Depends(get_db)):
    """Let a waiting or rejected channel set match MVPs (issue #175). Audited."""
    return _decide(channel_id, "approve", admin, db)


@router.post("/admin/twitch/channels/{channel_id}/reject", dependencies=[Depends(require_recent_reauth)])
def reject_twitch_channel(channel_id: str, admin: dict = Depends(require_admin), db=Depends(get_db)):
    """Move a waiting channel to rejected (issue #175). Audited."""
    return _decide(channel_id, "reject", admin, db)


@router.post("/admin/twitch/channels/{channel_id}/remove", dependencies=[Depends(require_recent_reauth)])
def remove_twitch_channel(channel_id: str, admin: dict = Depends(require_admin), db=Depends(get_db)):
    """Move an approved channel to rejected (issue #175); 409 for a TWITCH_MVP_CHANNEL_IDS
    channel. Audited."""
    return _decide(channel_id, "remove", admin, db)
