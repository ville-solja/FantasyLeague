"""Token drop for the voters of a vote-extension MVP poll (issue #253).

The MVP Vote extension has no Join and no presence pool. A voter enters a poll's
drop by accepting Twitch's identity share: the vote then carries a keyed hash of
the real Twitch id (soft_accounts.starter_grant_hash), never the id. On Confirm MVP
up to TWITCH_DROP_MAX of those voters are picked at random:

- a picked voter whose Twitch id is on a Kana Cards account (website or soft) is
  credited at once;
- a picked voter with no account gets a row in twitch_pending_tokens, claimed when
  that Twitch id is attached to an account (Connect Twitch on the website, or the
  identity share in the full extension), until it expires after 60 days.

TWITCH_VOTE_TOKENS_ENABLED=false turns the share prompt and the drop off; voting
still works.
"""
import logging
import os
import random
import time

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

import soft_accounts
import twitch
from database import credit_tokens
from deps import _audit
from models import TwitchMvpPoll, TwitchMvpVote, TwitchPendingToken, TwitchTokenDrop, User

logger = logging.getLogger(__name__)

PENDING_TOKEN_DAYS = 60
PENDING_TOKEN_SECONDS = PENDING_TOKEN_DAYS * 86400


def tokens_enabled() -> bool:
    """TWITCH_VOTE_TOKENS_ENABLED (default true): the vote extension's token step. Off,
    no identity hash is stored, no share prompt is shown and no token is dropped."""
    return os.getenv("TWITCH_VOTE_TOKENS_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


def account_hash(real_id) -> str | None:
    """The keyed hash kept instead of a real Twitch id; None without an id."""
    return soft_accounts.starter_grant_hash(real_id) if real_id else None


def _accounts_by_hash(db: Session) -> dict[str, User]:
    """Every account with a Twitch id, keyed by that id's hash. The votes hold only
    hashes, so the match is made from the accounts' side."""
    users = db.query(User).filter(User.twitch_account_id.isnot(None)).all()
    return {soft_accounts.starter_grant_hash(u.twitch_account_id): u for u in users}


def drop_for_poll(db: Session, poll: TwitchMvpPoll, now: int | None = None) -> tuple[list[str], int, int, bool]:
    """One token each to a random sample of the poll's voters who shared their identity.
    Returns (credited account names, pending tokens created, pool size, already dropped).
    The caller commits.

    Once per channel and match, like the presence drop: the same twitch_token_drops row
    is claimed, so a match never drops through both. The names are for the audit log
    only; chat and PubSub carry the count."""
    now = int(time.time()) if now is None else now
    drop_key = str(poll.match_id)
    if db.query(TwitchTokenDrop.id).filter_by(channel_id=poll.channel_id, series_id=drop_key).first():
        return [], 0, 0, True
    pool = sorted({h for (h,) in db.query(TwitchMvpVote.account_hash)
                   .filter(TwitchMvpVote.poll_id == poll.id, TwitchMvpVote.account_hash.isnot(None))})
    if not pool:
        return [], 0, 0, False
    if not twitch._claim_drop(db, poll.channel_id, drop_key):
        return [], 0, len(pool), True
    picked = random.sample(pool, min(twitch._TWITCH_DROP_MAX, len(pool)))
    accounts = _accounts_by_hash(db)
    insert = twitch._dialect_insert(db)
    names: list[str] = []
    pending = 0
    for h in picked:
        user = accounts.get(h)
        if user is not None:
            credit_tokens(db, user.id, 1)
            names.append(user.display_name)
            continue
        stmt = insert(TwitchPendingToken).values(
            account_hash=h, poll_id=poll.id, created_at=now, expires_at=now + PENDING_TOKEN_SECONDS,
        ).on_conflict_do_nothing(index_elements=[TwitchPendingToken.account_hash, TwitchPendingToken.poll_id])
        if db.execute(stmt).rowcount == 1:
            pending += 1
    db.query(TwitchTokenDrop).filter_by(channel_id=poll.channel_id, series_id=drop_key).update(
        {TwitchTokenDrop.count: len(names) + pending}, synchronize_session=False)
    _audit(db, "twitch_token_drop", actor_id=None, actor_username="twitch",
           detail=(f"channel={poll.channel_id} match={poll.match_id} count={len(names) + pending}"
                   f" pool_size={len(pool)} excluded_new=0 poll={poll.id} pending={pending}"
                   f" winners={','.join(names)}"))
    return names, pending, len(pool), False


def has_pending_win(db: Session, poll_id: int, real_id) -> bool:
    """Whether this Twitch id won a token in the poll that is still waiting to be claimed."""
    h = account_hash(real_id)
    if h is None:
        return False
    return db.query(TwitchPendingToken.id).filter(
        TwitchPendingToken.account_hash == h, TwitchPendingToken.poll_id == poll_id,
        TwitchPendingToken.claimed_at.is_(None), TwitchPendingToken.expires_at > int(time.time()),
    ).first() is not None


def claim_pending(db: Session, user: User, real_id, now: int | None = None) -> int:
    """Credit the account every unexpired pending token of this Twitch id, once. Returns
    how many were claimed. The caller commits, so the claim and the credit land together.

    A single UPDATE ... WHERE claimed_at IS NULL claims the rows: of two requests
    arriving together (Connect Twitch and a Join), each row goes to one of them.

    One Twitch account per Kana Cards account: an account that already claimed tokens
    won by another Twitch id claims nothing, so connecting and disconnecting a series
    of Twitch accounts can't funnel their tokens into one account (the same purpose as
    the one-merge limit). Refused tokens stay unclaimed and expire. The record of a
    claim is kept for PENDING_TOKEN_DAYS after it (purge_expired)."""
    h = account_hash(real_id)
    if h is None or user is None or user.id is None:
        return 0
    now = int(time.time()) if now is None else now
    other = db.query(TwitchPendingToken.id).filter(
        TwitchPendingToken.claimed_by_user_id == user.id, TwitchPendingToken.account_hash != h).first()
    if other is not None:
        waiting = db.query(TwitchPendingToken.id).filter(
            TwitchPendingToken.account_hash == h, TwitchPendingToken.claimed_at.is_(None),
            TwitchPendingToken.expires_at > now).count()
        if waiting:
            _audit(db, "twitch_pending_tokens_refused", actor_id=user.id, actor_username=user.display_name,
                   detail=f"user_id={user.id} count={waiting} reason=other_twitch_account")
        return 0
    claimed = db.execute(
        update(TwitchPendingToken)
        .where(TwitchPendingToken.account_hash == h, TwitchPendingToken.claimed_at.is_(None),
               TwitchPendingToken.expires_at > now)
        .values(claimed_by_user_id=user.id, claimed_at=now)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed:
        credit_tokens(db, user.id, claimed)
        _audit(db, "twitch_pending_tokens_claimed", actor_id=user.id, actor_username=user.display_name,
               detail=f"user_id={user.id} count={claimed}")
    return claimed


def purge_expired(db: Session, now: int | None = None) -> int:
    """Delete unclaimed pending tokens past their expiry, and claimed ones
    PENDING_TOKEN_DAYS after the claim (until then the row is what stops the same
    account claiming for another Twitch id). Commits; returns the count."""
    now = int(time.time()) if now is None else now
    deleted = (db.query(TwitchPendingToken)
                 .filter(or_(and_(TwitchPendingToken.claimed_at.is_(None),
                                  TwitchPendingToken.expires_at <= now),
                             TwitchPendingToken.claimed_at <= now - PENDING_TOKEN_SECONDS))
                 .delete(synchronize_session=False))
    db.commit()
    return deleted
