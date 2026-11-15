"""Viewer MVP vote (issue #234): routes under /twitch/mvp-poll.

The broadcaster opens a timed vote for one match from Quick Actions (the same
series -> match picker as the MVP tool). Joined viewers who are eligible for drops
vote in the panel, one vote each, changeable until the poll closes. The poll closes
lazily: every read (and the daily cleanup) closes a poll whose closes_at has passed
and writes its per-player tally. The broadcaster confirms the result through the
existing POST /twitch/mvp with `poll_id` (twitch.set_mvp), so the MVP row, the
fantasy bonus and the token drop work exactly as for a picked MVP.

Chat and PubSub carry counts only, never voter ids. Votes are deleted 30 days after
their poll ends (cleanup_votes, from main's daily maintenance) and on Leave.
"""
import json
import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import text_safety
import twitch
import twitch_channels
from database import get_db
from deps import _audit
from models import LiveMatch, Match, TwitchMvpPoll, TwitchMvpVote
from rate_limit import key_by_twitch_viewer_or_ip, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twitch", tags=["twitch"])

DURATION_CHOICES = (60, 120, 180)
DEFAULT_DURATION = 120
VOTE_RETENTION_DAYS = 30
# How long GET /twitch/mvp-poll keeps showing a closed or confirmed poll's result.
RESULT_SHOWN_SECONDS = 30 * 60

OPEN, CLOSED, CANCELLED, CONFIRMED = "open", "closed", "cancelled", "confirmed"

_TEAM_NAME_MAX = 32

DbId = Annotated[int, Field(ge=1, le=2**63 - 1)]


def _now() -> int:
    return int(time.time())


class PollOpenBody(BaseModel):
    match_id: DbId
    duration_seconds: int = DEFAULT_DURATION


class VoteBody(BaseModel):
    player_id: DbId


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chat_team_name(name) -> str:
    cleaned = text_safety.clean_display_text(name, _TEAM_NAME_MAX)
    if not cleaned or text_safety.looks_like_url(cleaned):
        return "TBD"
    return cleaned


def open_chat_text(team1: str, team2: str, match_number: int, duration_seconds: int) -> str:
    """The chat line posted when a poll opens: teams, game number and time left only."""
    minutes = max(1, duration_seconds // 60)
    text = (f"MVP vote open for {_chat_team_name(team1)} vs {_chat_team_name(team2)}, "
            f"game {match_number}: vote in the Kana Cards panel. Closes in {minutes} min.")
    return text[:twitch._CHAT_TEXT_MAX]


def _info(poll: TwitchMvpPoll) -> dict:
    try:
        info = json.loads(poll.info_json or "{}")
    except ValueError:
        info = {}
    return info if isinstance(info, dict) else {}


def _player_ids(poll: TwitchMvpPoll) -> set[int]:
    return {p["player_id"] for t in _info(poll).get("teams", []) for p in t.get("players", [])}


def _match_info(db: Session, channel_id: str, match_id: int) -> dict | None:
    """Teams, game number and the players grouped by team, as the MVP tool lists them
    (ingested stats, or the live players of a live match)."""
    data = twitch.current_matches(payload={"channel_id": channel_id, "role": "viewer"}, db=db)
    for series in data.get("series", []):
        for m in series["matches"]:
            if m["match_id"] != match_id:
                continue
            teams: dict[str, list] = {}
            for p in m["players"]:
                teams.setdefault(p.get("team_name") or "", []).append({
                    "player_id": p["player_id"],
                    "player_name": p["player_name"],
                    "chat_name": p["chat_name"],
                })
            return {
                "team1_name": series["team1_name"],
                "team2_name": series["team2_name"],
                "match_number": m["match_number"],
                "teams": [{"team_name": k, "players": v} for k, v in teams.items()],
            }
    return None


def _live_counts(db: Session, poll_id: int) -> dict[int, int]:
    rows = (db.query(TwitchMvpVote.player_id, func.count(TwitchMvpVote.id))
              .filter(TwitchMvpVote.poll_id == poll_id)
              .group_by(TwitchMvpVote.player_id).all())
    return {int(pid): int(n) for pid, n in rows}


def counts(db: Session, poll: TwitchMvpPoll) -> dict[int, int]:
    """Per-player votes: the stored tally once closed, else counted from the votes."""
    if poll.status != OPEN and poll.tally_json:
        try:
            return {int(k): int(v) for k, v in json.loads(poll.tally_json).items()}
        except (ValueError, AttributeError):
            return {}
    return _live_counts(db, poll.id)


def poll_result(vote_counts: dict[int, int]) -> dict:
    """Total votes, the sole winner (or None), and the tied leaders on a tie."""
    total = sum(vote_counts.values())
    if total == 0:
        return {"total_votes": 0, "winner_player_id": None, "tied_player_ids": [],
                "winner_votes": 0, "winner_pct": 0}
    top = max(vote_counts.values())
    leaders = sorted(pid for pid, n in vote_counts.items() if n == top)
    sole = len(leaders) == 1
    return {
        "total_votes": total,
        "winner_player_id": leaders[0] if sole else None,
        "tied_player_ids": [] if sole else leaders,
        "winner_votes": top,
        "winner_pct": round(100 * top / total),
    }


def _close(db: Session, poll: TwitchMvpPoll, closed_at: int, broadcast: bool = True) -> bool:
    """Close an open poll and write its tally. Only the request that flips the status
    audits and broadcasts, so concurrent reads close it once.

    The status flips before the votes are counted: the flip takes the write lock, and
    a vote only lands while the poll is still open (see ``vote``), so no vote can be
    stored after the count and left out of the tally."""
    flipped = (db.query(TwitchMvpPoll)
                 .filter(TwitchMvpPoll.id == poll.id, TwitchMvpPoll.status == OPEN)
                 .update({TwitchMvpPoll.status: CLOSED, TwitchMvpPoll.closed_at: closed_at},
                         synchronize_session=False))
    if flipped != 1:
        db.refresh(poll)
        return False
    tally = _live_counts(db, poll.id)
    (db.query(TwitchMvpPoll)
       .filter(TwitchMvpPoll.id == poll.id)
       .update({TwitchMvpPoll.tally_json: json.dumps({str(k): v for k, v in tally.items()})},
               synchronize_session=False))
    result = poll_result(tally)
    _audit(db, "twitch_mvp_poll_closed", actor_id=None, actor_username="twitch",
           detail=(f"channel={poll.channel_id} match={poll.match_id} poll={poll.id}"
                   f" votes={result['total_votes']} winner={result['winner_player_id'] or 'none'}"
                   f" tie={bool(result['tied_player_ids'])}"))
    db.commit()
    db.refresh(poll)
    if broadcast:
        twitch._pubsub_broadcast(poll.channel_id, {"type": "mvp_poll", "state": CLOSED, "poll_id": poll.id})
    return True


def close_if_due(db: Session, poll: TwitchMvpPoll, now: int | None = None) -> None:
    now = _now() if now is None else now
    if poll.status == OPEN and poll.closes_at <= now:
        _close(db, poll, poll.closes_at)


def _close_due_on_channel(db: Session, channel_id: str, now: int) -> None:
    for poll in (db.query(TwitchMvpPoll)
                   .filter(TwitchMvpPoll.channel_id == channel_id, TwitchMvpPoll.status == OPEN,
                           TwitchMvpPoll.closes_at <= now).all()):
        _close(db, poll, poll.closes_at)


def _channel_poll(db: Session, channel_id: str, poll_id: int) -> TwitchMvpPoll:
    """The poll, which must belong to the caller's channel (404 otherwise)."""
    poll = db.get(TwitchMvpPoll, poll_id)
    if poll is None or poll.channel_id != channel_id:
        raise HTTPException(status_code=404, detail="Poll not found")
    return poll


def _voter_state(db: Session, payload: dict, now: int) -> dict:
    """Whether the caller may vote: ok, login (logged out of Twitch), join (no
    account) or too_new (a soft account younger than the drop age, with votes_from)."""
    if not twitch._opaque_id(payload).startswith("U"):
        return {"can_vote": False, "reason": "login", "votes_from": None}
    user = twitch._panel_account(db, payload)
    if user is None:
        return {"can_vote": False, "reason": "join", "votes_from": None}
    votes_from = twitch.drops_from(user, now)
    if votes_from is not None:
        return {"can_vote": False, "reason": "too_new", "votes_from": votes_from}
    return {"can_vote": True, "reason": "ok", "votes_from": None}


def poll_view(db: Session, poll: TwitchMvpPoll, payload: dict, now: int | None = None) -> dict:
    """The poll as the panel and the MVP tool show it. While open only the total
    number of votes; once closed each player's votes and share. Never voter ids."""
    now = _now() if now is None else now
    info = _info(poll)
    vote_counts = counts(db, poll)
    result = poll_result(vote_counts)
    view = {
        "poll_id": poll.id,
        "match_id": poll.match_id,
        "status": poll.status,
        "opened_at": poll.opened_at,
        "closes_at": poll.closes_at,
        "closed_at": poll.closed_at,
        "now": now,
        "seconds_left": max(0, poll.closes_at - now) if poll.status == OPEN else 0,
        "team1_name": info.get("team1_name"),
        "team2_name": info.get("team2_name"),
        "match_number": info.get("match_number"),
        "teams": info.get("teams", []),
        "total_votes": result["total_votes"],
        "confirmed_player_id": poll.confirmed_player_id,
    }
    if poll.status != OPEN:
        total = result["total_votes"]
        players = [p for t in view["teams"] for p in t.get("players", [])]
        results = [{
            "player_id": p["player_id"],
            "player_name": p["player_name"],
            "chat_name": p.get("chat_name"),
            "votes": vote_counts.get(p["player_id"], 0),
            "pct": round(100 * vote_counts.get(p["player_id"], 0) / total) if total else 0,
        } for p in players]
        results.sort(key=lambda r: -r["votes"])
        view.update({
            "results": results,
            "winner_player_id": result["winner_player_id"],
            "tied_player_ids": result["tied_player_ids"],
        })
    opaque_id = twitch._opaque_id(payload)
    own = None
    if opaque_id.startswith("U"):
        row = (db.query(TwitchMvpVote.player_id)
                 .filter(TwitchMvpVote.poll_id == poll.id, TwitchMvpVote.twitch_user_id == opaque_id)
                 .first())
        own = row[0] if row else None
    view["my_vote"] = own
    view["voter"] = _voter_state(db, payload, now)
    return view


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def open_poll(body: PollOpenBody, payload: dict, db: Session) -> dict:
    """Broadcaster: open a vote for one match of the series window."""
    twitch._require_broadcaster(payload)
    channel_id = payload.get("channel_id", "")
    if body.duration_seconds not in DURATION_CHOICES:
        raise HTTPException(status_code=422, detail="duration_seconds must be 60, 120 or 180")
    if not twitch.mvp_channel_allowed(channel_id, db):
        if twitch_channels.record_request(db, channel_id) is not None:
            db.commit()
        raise HTTPException(status_code=403, detail="This channel cannot set match MVPs")
    if not db.get(Match, body.match_id) and not db.get(LiveMatch, body.match_id):
        raise HTTPException(status_code=404, detail="Match not found")
    if body.match_id not in twitch._eligible_mvp_match_ids(db):
        raise HTTPException(status_code=403, detail="Match is not in the current series window")
    confirmed = (db.query(TwitchMvpPoll.id)
                   .filter(TwitchMvpPoll.match_id == body.match_id, TwitchMvpPoll.status == CONFIRMED)
                   .first())
    if confirmed:
        raise HTTPException(status_code=409, detail="This match's MVP was already chosen by a viewer vote")
    now = _now()
    _close_due_on_channel(db, channel_id, now)
    if db.query(TwitchMvpPoll.id).filter(TwitchMvpPoll.channel_id == channel_id,
                                         TwitchMvpPoll.status == OPEN).first():
        raise HTTPException(status_code=409, detail="A viewer vote is already open on this channel")
    info = _match_info(db, channel_id, body.match_id)
    if not info or not any(t["players"] for t in info["teams"]):
        raise HTTPException(status_code=409, detail="No players found for this match yet")

    poll = TwitchMvpPoll(channel_id=channel_id, match_id=body.match_id, status=OPEN,
                         opened_at=now, closes_at=now + body.duration_seconds,
                         info_json=json.dumps(info))
    db.add(poll)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A viewer vote is already open on this channel")
    _audit(db, "twitch_mvp_poll_opened", actor_id=None, actor_username="twitch",
           detail=(f"channel={channel_id} match={body.match_id} poll={poll.id}"
                   f" duration={body.duration_seconds}"))
    db.commit()
    db.refresh(poll)
    twitch._pubsub_broadcast(channel_id, {"type": "mvp_poll", "state": OPEN, "poll_id": poll.id})
    twitch._post_chat_message(channel_id, open_chat_text(
        info["team1_name"], info["team2_name"], info["match_number"], body.duration_seconds))
    return poll_view(db, poll, payload, now)


@router.post("/mvp-poll")
@limiter.limit(twitch.RATE_LIMIT_TWITCH_JOIN_IP)
def open_poll_route(request: Request, body: PollOpenBody,
                    payload: dict = Depends(twitch.verify_twitch_jwt),
                    db: Session = Depends(get_db)):
    return open_poll(body, payload, db)


def get_poll(payload: dict, db: Session) -> dict:
    """Any viewer: the channel's latest poll when it is open, or closed or confirmed
    within RESULT_SHOWN_SECONDS; {"poll": None} otherwise. Only the latest poll counts,
    so cancelling a poll never brings back an earlier one's result."""
    channel_id = payload.get("channel_id", "")
    now = _now()
    _close_due_on_channel(db, channel_id, now)
    poll = (db.query(TwitchMvpPoll)
              .filter(TwitchMvpPoll.channel_id == channel_id)
              .order_by(TwitchMvpPoll.id.desc())
              .first())
    if poll is None or poll.status == CANCELLED:
        return {"poll": None}
    if poll.status != OPEN and (poll.closed_at or 0) < now - RESULT_SHOWN_SECONDS:
        return {"poll": None}
    return {"poll": poll_view(db, poll, payload, now)}


@router.get("/mvp-poll")
@limiter.limit(twitch.RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
@limiter.limit(twitch.RATE_LIMIT_TWITCH_JOIN_IP)
def get_poll_route(request: Request, payload: dict = Depends(twitch.verify_twitch_jwt),
                   db: Session = Depends(get_db)):
    return get_poll(payload, db)


def vote(poll_id: int, body: VoteBody, payload: dict, db: Session) -> dict:
    """Joined viewer eligible for drops: vote, or change the vote, while the poll is open."""
    opaque_id = twitch._logged_in_opaque_id(payload)
    channel_id = payload.get("channel_id", "")
    poll = _channel_poll(db, channel_id, poll_id)
    now = _now()
    state = _voter_state(db, payload, now)
    if not state["can_vote"]:
        detail = "not_joined" if state["reason"] == "join" else state["reason"]
        raise HTTPException(status_code=403, detail=detail)
    close_if_due(db, poll, now)
    if poll.status != OPEN:
        raise HTTPException(status_code=409, detail="poll_closed")
    if body.player_id not in _player_ids(poll):
        raise HTTPException(status_code=422, detail="Player is not in this match")
    # Claim the poll row in this transaction, still open and before its timer: a
    # concurrent close either waits for this vote (and counts it) or has already
    # flipped the status, and the vote is refused.
    still_open = (db.query(TwitchMvpPoll)
                    .filter(TwitchMvpPoll.id == poll.id, TwitchMvpPoll.status == OPEN,
                            TwitchMvpPoll.closes_at > now)
                    .update({TwitchMvpPoll.status: TwitchMvpPoll.status}, synchronize_session=False))
    if still_open != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="poll_closed")
    insert = twitch._dialect_insert(db)
    stmt = insert(TwitchMvpVote).values(
        poll_id=poll.id, twitch_user_id=opaque_id, player_id=body.player_id, voted_at=now,
    ).on_conflict_do_update(
        index_elements=[TwitchMvpVote.poll_id, TwitchMvpVote.twitch_user_id],
        set_={"player_id": body.player_id, "voted_at": now},
    )
    db.execute(stmt)
    db.commit()
    total = db.query(func.count(TwitchMvpVote.id)).filter(TwitchMvpVote.poll_id == poll.id).scalar()
    return {"poll_id": poll.id, "my_vote": body.player_id, "total_votes": int(total or 0)}


@router.post("/mvp-poll/{poll_id}/vote")
@limiter.limit(twitch.RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
@limiter.limit(twitch.RATE_LIMIT_TWITCH_JOIN_IP)
def vote_route(request: Request, body: VoteBody,
               poll_id: int = Path(ge=1, le=2**63 - 1),
               payload: dict = Depends(twitch.verify_twitch_jwt),
               db: Session = Depends(get_db)):
    return vote(poll_id, body, payload, db)


def end_poll(poll_id: int, payload: dict, db: Session) -> dict:
    """Broadcaster: close an open poll now; returns the result."""
    twitch._require_broadcaster(payload)
    poll = _channel_poll(db, payload.get("channel_id", ""), poll_id)
    now = _now()
    close_if_due(db, poll, now)
    if poll.status != OPEN or not _close(db, poll, now):
        raise HTTPException(status_code=409, detail="The vote is not open")
    return poll_view(db, poll, payload, now)


@router.post("/mvp-poll/{poll_id}/end")
@limiter.limit(twitch.RATE_LIMIT_TWITCH_JOIN_IP)
def end_poll_route(request: Request, poll_id: int = Path(ge=1, le=2**63 - 1),
                   payload: dict = Depends(twitch.verify_twitch_jwt),
                   db: Session = Depends(get_db)):
    return end_poll(poll_id, payload, db)


def cancel_poll(poll_id: int, payload: dict, db: Session) -> dict:
    """Broadcaster: end an open (or closed, unconfirmed) poll with no result."""
    twitch._require_broadcaster(payload)
    poll = _channel_poll(db, payload.get("channel_id", ""), poll_id)
    now = _now()
    flipped = (db.query(TwitchMvpPoll)
                 .filter(TwitchMvpPoll.id == poll.id, TwitchMvpPoll.status.in_((OPEN, CLOSED)))
                 .update({TwitchMvpPoll.status: CANCELLED,
                          TwitchMvpPoll.closed_at: func.coalesce(TwitchMvpPoll.closed_at, now)},
                         synchronize_session=False))
    if flipped != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="The vote can no longer be cancelled")
    _audit(db, "twitch_mvp_poll_cancelled", actor_id=None, actor_username="twitch",
           detail=f"channel={poll.channel_id} match={poll.match_id} poll={poll.id}")
    db.commit()
    db.refresh(poll)
    twitch._pubsub_broadcast(poll.channel_id, {"type": "mvp_poll", "state": CANCELLED, "poll_id": poll.id})
    return {"poll_id": poll.id, "status": poll.status}


@router.post("/mvp-poll/{poll_id}/cancel")
@limiter.limit(twitch.RATE_LIMIT_TWITCH_JOIN_IP)
def cancel_poll_route(request: Request, poll_id: int = Path(ge=1, le=2**63 - 1),
                      payload: dict = Depends(twitch.verify_twitch_jwt),
                      db: Session = Depends(get_db)):
    return cancel_poll(poll_id, payload, db)


# ---------------------------------------------------------------------------
# Confirm through POST /twitch/mvp (twitch.set_mvp)
# ---------------------------------------------------------------------------

def confirmable_poll(db: Session, poll_id: int, channel_id: str, match_id: int) -> TwitchMvpPoll:
    """The closed poll set_mvp confirms: on the caller's channel (404), for the same
    match (409), and closed (409: still open, cancelled or already confirmed)."""
    poll = _channel_poll(db, channel_id, poll_id)
    if poll.match_id != match_id:
        raise HTTPException(status_code=409, detail="The vote is for another match")
    close_if_due(db, poll)
    if poll.status != CLOSED:
        raise HTTPException(status_code=409, detail="The vote is not closed")
    return poll


def mark_confirmed(db: Session, poll: TwitchMvpPoll, player_id: int) -> dict:
    """Claim the poll as confirmed with the chosen player (the caller commits) and
    return the vote's result, so set_mvp can tell a confirmed winner from an override.

    set_mvp calls this before it writes the MVP or drops tokens. If a concurrent
    confirm or cancel already moved the poll out of CLOSED, nothing is written: the
    transaction rolls back and the caller gets 409."""
    result = poll_result(counts(db, poll))
    claimed = (db.query(TwitchMvpPoll)
                 .filter(TwitchMvpPoll.id == poll.id, TwitchMvpPoll.status == CLOSED)
                 .update({TwitchMvpPoll.status: CONFIRMED, TwitchMvpPoll.confirmed_player_id: player_id},
                         synchronize_session=False))
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="The vote is not closed")
    return result


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def cleanup_votes(db: Session, now: int | None = None) -> int:
    """Delete the votes of polls that ended more than VOTE_RETENTION_DAYS ago; their
    tally_json keeps the per-player counts. Expired open polls are closed first so
    their tally is written. Commits; returns the number of votes deleted."""
    now = _now() if now is None else now
    for poll in (db.query(TwitchMvpPoll)
                   .filter(TwitchMvpPoll.status == OPEN, TwitchMvpPoll.closes_at <= now).all()):
        _close(db, poll, poll.closes_at, broadcast=False)
    cutoff = now - VOTE_RETENTION_DAYS * 86400
    ended = select(TwitchMvpPoll.id).where(
        TwitchMvpPoll.status != OPEN,
        func.coalesce(TwitchMvpPoll.closed_at, TwitchMvpPoll.closes_at) < cutoff,
    )
    deleted = (db.query(TwitchMvpVote)
                 .filter(TwitchMvpVote.poll_id.in_(ended))
                 .delete(synchronize_session=False))
    db.commit()
    return deleted

