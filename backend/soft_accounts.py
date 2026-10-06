"""Soft accounts created by the Twitch extension's Join (issue #157).

A soft account is a `users` row with account_type="twitch", keyed by the viewer's
opaque Twitch id (`twitch_user_id`). It has no username, email or password, so it
can never sign in on the website, and it is hidden from every ranking. The optional
real Twitch user id from the extension's identity share is kept in
`twitch_account_id`.

Issue #160: when a website account connects the same Twitch account (Twitch
sign-in), the id moves to the website account and `merge_soft_into` can later move
the soft account's cards and tokens there, writing an undo log (`twitch_merge_log`)
that `reverse_merge` uses.

Every function here leaves committing to the caller except where noted.
"""
import json
import logging
import os
import time

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

import card_points
from deps import _audit
from models import (Card, CardModifier, CodeRedemption, NotificationDismissal,
                    PasswordResetToken, TokenGrantClaim, TwitchLinkCode, TwitchMergeLog,
                    TwitchPresence, User, UserSession, UserTag, Week, WeeklyRosterEntry,
                    WeeklySummaryReveal, WeeklySummarySeen)

logger = logging.getLogger(__name__)

SOFT = "twitch"
FULL = "full"

# Activity is written at most this often per account (GET /twitch/me is polled).
LAST_SEEN_RESOLUTION = 3600

# Issue #160: a merge can be reversed by an admin for this long; older undo-log rows
# are deleted by the daily clean-up.
MERGE_UNDO_DAYS = 30
MERGE_UNDO_SECONDS = MERGE_UNDO_DAYS * 86400

_ROSTER_FIELDS = ("id", "week_id", "card_id", "is_bench", "bench_order", "subbed_in",
                  "subbed_out", "subbed_for_entry_id")


def retention_days() -> int:
    """TWITCH_SOFT_ACCOUNT_RETENTION_DAYS (default 365): idle days before a soft account is purged."""
    try:
        return max(1, int(os.getenv("TWITCH_SOFT_ACCOUNT_RETENTION_DAYS", "365")))
    except ValueError:
        return 365


def find_by_opaque_id(db, opaque_id: str) -> User | None:
    """The account (soft or code-linked website account) for an opaque Twitch id."""
    if not opaque_id:
        return None
    return db.query(User).filter(User.twitch_user_id == opaque_id).first()


def record_twitch_account_id(db, user: User, real_id: str | None) -> None:
    """Store the real Twitch user id from the identity share.

    Sets the column only when it is empty; never overwrites a different id. Refuses
    with 409 when another account already holds that id (the column is unique)."""
    if not real_id:
        return
    real_id = str(real_id)
    if user.twitch_account_id:
        return  # already set: same id is a no-op, a different id is never written
    holder = (db.query(User.id)
              .filter(User.twitch_account_id == real_id, User.id != user.id).first())
    if holder:
        raise HTTPException(status_code=409, detail="twitch_identity_in_use")
    user.twitch_account_id = real_id


def get_or_create_soft_account(db, opaque_id: str, real_id: str | None) -> tuple[User, bool]:
    """Return (account, created) for an opaque Twitch id, creating a soft account when
    no account (soft or website) holds it. Commits.

    Race-safe: two simultaneous joins both try the insert; the unique constraint on
    users.twitch_user_id lets one win and the other re-reads the winner's row."""
    existing = find_by_opaque_id(db, opaque_id)
    if existing:
        record_twitch_account_id(db, existing, real_id)
        db.commit()
        return existing, False

    now = int(time.time())
    user = User(
        username=None, email=None, password_hash=None,
        is_admin=False, is_tester=False,
        tokens=int(os.getenv("INITIAL_TOKENS", "5")),
        created_at=now, last_seen_at=now,
        twitch_user_id=opaque_id,
        account_type=SOFT,
    )
    if real_id:
        holder = db.query(User.id).filter(User.twitch_account_id == str(real_id)).first()
        if holder:
            raise HTTPException(status_code=409, detail="twitch_identity_in_use")
        user.twitch_account_id = str(real_id)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = find_by_opaque_id(db, opaque_id)
        if existing is None:
            raise
        return existing, False
    _audit(db, "twitch_soft_account_created", actor_id=user.id,
           actor_username=user.display_name, detail=f"user_id={user.id}")
    db.commit()
    return user, True


def touch_last_seen(db, user: User, now: int | None = None) -> bool:
    """Refresh last_seen_at when it is older than an hour. Returns True when written
    (the caller commits)."""
    now = int(now if now is not None else time.time())
    if user.last_seen_at is not None and now - user.last_seen_at < LAST_SEEN_RESOLUTION:
        return False
    user.last_seen_at = now
    return True


def delete_soft_account(db, soft: User) -> None:
    """Delete a soft account and every row it owns: cards (with their modifiers and
    stored points), roster snapshots, per-user state and its presence row. Refuses a
    website account. The caller audits and commits."""
    if soft.account_type != SOFT:
        raise ValueError("delete_soft_account called for a website account")
    uid = soft.id
    card_ids = [r[0] for r in db.query(Card.id).filter(Card.owner_id == uid).all()]
    if card_ids:
        card_points.delete_card_points(db, card_ids=card_ids)
        db.query(CardModifier).filter(CardModifier.card_id.in_(card_ids)).delete(synchronize_session=False)
        db.query(WeeklyRosterEntry).filter(WeeklyRosterEntry.card_id.in_(card_ids)).delete(synchronize_session=False)
        db.query(Card).filter(Card.id.in_(card_ids)).delete(synchronize_session=False)
    for model in (WeeklyRosterEntry, WeeklySummaryReveal, WeeklySummarySeen, CodeRedemption,
                  TokenGrantClaim, NotificationDismissal, UserSession, UserTag,
                  TwitchLinkCode, PasswordResetToken):
        db.query(model).filter(model.user_id == uid).delete(synchronize_session=False)
    if soft.twitch_user_id:
        db.query(TwitchPresence).filter(
            TwitchPresence.twitch_user_id == soft.twitch_user_id).delete(synchronize_session=False)
    db.delete(soft)
    db.flush()


def purge_inactive_soft_accounts(db, now: int, days: int) -> int:
    """Delete soft accounts idle (last_seen_at, else created_at) for more than `days`
    days, with one audit entry each. Website accounts are never touched. Commits.
    Returns the number deleted."""
    cutoff = int(now) - int(days) * 86400
    idle = (db.query(User)
            .filter(User.account_type == SOFT,
                    or_(User.last_seen_at < cutoff,
                        (User.last_seen_at.is_(None)) & (or_(User.created_at.is_(None),
                                                             User.created_at < cutoff))))
            .all())
    for user in idle:
        uid = user.id
        delete_soft_account(db, user)
        _audit(db, "twitch_soft_account_deleted", actor_id=None, actor_username="system",
               detail=f"user_id={uid} reason=retention days={days}")
    if idle:
        db.commit()
        logger.info("Purged %d inactive Twitch soft account(s)", len(idle))
    return len(idle)


# ---------------------------------------------------------------------------
# Issue #160: merge into a website account, undo log, reversal
# ---------------------------------------------------------------------------

def find_by_twitch_account_id(db, real_id) -> User | None:
    """The account (soft or website) holding this real Twitch user id, if any."""
    if not real_id:
        return None
    return db.query(User).filter(User.twitch_account_id == str(real_id)).first()


def merge_soft_into(db, soft: User, full: User, now: int | None = None) -> dict:
    """Move a soft account's cards (to the bench) and tokens into a website account,
    log the merge for 30 days, then delete the soft account with every row it owns
    (delete_soft_account). The website account takes over the soft account's opaque
    id so the panel recognises it. Flushes; the caller commits once (or rolls back)."""
    if soft.account_type != SOFT or full.account_type == SOFT:
        raise ValueError("merge_soft_into needs a soft account and a website account")
    now = int(now if now is not None else time.time())
    soft_id = soft.id
    cards = db.query(Card).filter(Card.owner_id == soft_id).order_by(Card.id).all()
    card_ids = [c.id for c in cards]
    tokens = int(soft.tokens or 0)
    entries = (db.query(WeeklyRosterEntry).filter(WeeklyRosterEntry.user_id == soft_id)
               .order_by(WeeklyRosterEntry.id).all())
    roster_snapshot = [{f: (bool(getattr(e, f)) if f in ("is_bench", "subbed_in", "subbed_out")
                            else getattr(e, f)) for f in _ROSTER_FIELDS} for e in entries]
    snapshot = {
        "twitch_user_id": soft.twitch_user_id,
        # The connect step moved the shared id to the website account (the column is unique).
        "twitch_account_id": soft.twitch_account_id or full.twitch_account_id,
        "created_at": soft.created_at,
        "last_seen_at": soft.last_seen_at,
        "tokens": tokens,
    }
    log = TwitchMergeLog(full_user_id=full.id, merged_at=now, soft_snapshot=json.dumps(snapshot),
                         card_ids=json.dumps(card_ids), tokens_moved=tokens,
                         roster_entries=json.dumps(roster_snapshot), reversed_at=None)
    db.add(log)

    # S's locked-week snapshot rows go, so W's past weekly scores don't change.
    if entries:
        db.query(WeeklyRosterEntry).filter(WeeklyRosterEntry.user_id == soft_id).delete(
            synchronize_session=False)
    for card in cards:
        card.owner_id = full.id
        card.is_active = False
        card.slot_index = None
    full.tokens = int(full.tokens or 0) + tokens
    soft.tokens = 0
    opaque_id = soft.twitch_user_id
    soft.twitch_user_id = None
    soft.twitch_account_id = None
    db.flush()
    delete_soft_account(db, soft)  # cards already moved: only S's own rows remain
    if opaque_id:
        db.query(TwitchPresence).filter(TwitchPresence.twitch_user_id == opaque_id).delete(
            synchronize_session=False)
    if opaque_id:
        full.twitch_user_id = opaque_id
    if soft.last_seen_at and (full.last_seen_at or 0) < soft.last_seen_at:
        full.last_seen_at = soft.last_seen_at
    full.merged_soft_account_at = now
    full.pending_merge_user_id = None
    db.flush()
    _audit(db, "twitch_account_merged", actor_id=full.id, actor_username=full.display_name,
           detail=(f"full_user_id={full.id} soft_user_id={soft_id} cards={len(card_ids)} "
                   f"tokens={tokens} roster_entries={len(roster_snapshot)} log_id={log.id}"))
    db.flush()
    return {"cards": len(card_ids), "tokens": tokens, "log_id": log.id}


class MergeReversalError(Exception):
    """A merge that can't be reversed; the message is shown to the admin."""


def reversal_block_reason(db, log: TwitchMergeLog, now: int) -> str | None:
    """Why this merge can't be reversed now, or None when it can."""
    if log.reversed_at is not None:
        return "This merge was already reversed."
    if now - int(log.merged_at) > MERGE_UNDO_SECONDS:
        return f"This merge is older than {MERGE_UNDO_DAYS} days and can no longer be reversed."
    if db.get(User, log.full_user_id) is None:
        return "The website account of this merge no longer exists."
    card_ids = json.loads(log.card_ids or "[]")
    if card_ids and db.query(Card.id).filter(Card.id.in_(card_ids)).first() is None:
        return "The merged cards no longer exist (a season reset happened since the merge)."
    return None


def reverse_merge(db, log: TwitchMergeLog, actor: dict | None = None,
                  now: int | None = None) -> dict:
    """Undo a merge within MERGE_UNDO_DAYS: recreate the soft account (new id) from the
    snapshot, move the logged cards still on the website account back, subtract the
    moved tokens (never below 0; the shortfall is reported), restore the deleted
    roster rows, and clear the website account's Twitch fields so the owner can
    connect and merge again. Raises MergeReversalError (nothing changed). Flushes;
    the caller commits."""
    now = int(now if now is not None else time.time())
    reason = reversal_block_reason(db, log, now)
    if reason:
        raise MergeReversalError(reason)
    full = db.get(User, log.full_user_id)
    snapshot = json.loads(log.soft_snapshot or "{}")
    card_ids = json.loads(log.card_ids or "[]")
    tokens_moved = int(log.tokens_moved or 0)

    full.twitch_account_id = None
    full.twitch_user_id = None
    full.merged_soft_account_at = None
    full.pending_merge_user_id = None
    db.flush()

    opaque_id = snapshot.get("twitch_user_id")
    if opaque_id and find_by_opaque_id(db, opaque_id) is not None:
        opaque_id = None  # taken by another account since: restore without it
    real_id = snapshot.get("twitch_account_id")
    if real_id and find_by_twitch_account_id(db, real_id) is not None:
        real_id = None
    soft = User(username=None, email=None, password_hash=None, is_admin=False, is_tester=False,
                tokens=tokens_moved, created_at=snapshot.get("created_at") or now,
                last_seen_at=snapshot.get("last_seen_at") or now,
                twitch_user_id=opaque_id, twitch_account_id=real_id, account_type=SOFT)
    db.add(soft)
    db.flush()

    cards = (db.query(Card).filter(Card.id.in_(card_ids), Card.owner_id == full.id).all()
             if card_ids else [])
    for card in cards:
        card.owner_id = soft.id
        card.is_active = False
        card.slot_index = None
    returned_ids = {c.id for c in cards}

    taken = min(int(full.tokens or 0), tokens_moved)
    full.tokens = int(full.tokens or 0) - taken
    shortfall = tokens_moved - taken

    week_ids = {w for (w,) in db.query(Week.id).all()}
    id_map: dict = {}
    restored: list[tuple[WeeklyRosterEntry, dict]] = []
    for row in json.loads(log.roster_entries or "[]"):
        if row.get("week_id") not in week_ids or row.get("card_id") not in returned_ids:
            continue
        entry = WeeklyRosterEntry(week_id=row["week_id"], user_id=soft.id, card_id=row["card_id"],
                                  is_bench=bool(row.get("is_bench")), bench_order=row.get("bench_order"),
                                  subbed_in=bool(row.get("subbed_in")),
                                  subbed_out=bool(row.get("subbed_out")))
        db.add(entry)
        restored.append((entry, row))
    db.flush()
    for entry, row in restored:
        id_map[row.get("id")] = entry.id
    for entry, row in restored:
        if row.get("subbed_for_entry_id") is not None:
            entry.subbed_for_entry_id = id_map.get(row["subbed_for_entry_id"])

    log.reversed_at = now
    actor_id = actor["user_id"] if actor else None
    actor_name = actor["username"] if actor else "system"
    _audit(db, "twitch_merge_reversed", actor_id=actor_id, actor_username=actor_name,
           detail=(f"log_id={log.id} full_user_id={full.id} soft_user_id={soft.id} "
                   f"cards={len(returned_ids)} tokens={tokens_moved} token_shortfall={shortfall} "
                   f"roster_entries={len(restored)}"))
    db.flush()
    return {"log_id": log.id, "soft_user_id": soft.id, "cards_returned": len(returned_ids),
            "tokens_returned": tokens_moved, "token_shortfall": shortfall,
            "roster_entries_restored": len(restored)}


def purge_old_merge_logs(db, now: int) -> int:
    """Delete undo-log rows older than MERGE_UNDO_DAYS. The caller commits."""
    return (db.query(TwitchMergeLog)
            .filter(TwitchMergeLog.merged_at < int(now) - MERGE_UNDO_SECONDS)
            .delete(synchronize_session=False))
