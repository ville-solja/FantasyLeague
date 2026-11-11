"""Pre-season team signup (issue #220): signup periods, captains' listings, the daily
shuffle, the "Not on this team" removal, the organiser's CSV and the 60-day retention.

Routes are thin wrappers in routers/team_signup.py (public, captains, players) and
routers/admin_team_signup.py (admins). Pass `now` (Unix seconds) to make time explicit.
"""
import csv
import hashlib
import io
import json
import time

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import player_lookup
from player_links import verified_player_id
from models import Player, TeamSignup, TeamSignupPeriod, TeamSignupPlayer, User
from player_rank import medal_name
from text_safety import clean_display_text, looks_like_url

LABEL_MAX = 40
NAME_MIN, NAME_MAX = 2, 32
NOTE_MAX = 280
CONTACT_MAX = 100
MAX_PLAYERS = 7
TEAM_SIZE = 5
ROLES = (1, 2, 3, 4, 5)
RETENTION_DAYS = 60
DAY = 86400
_CLEAN_CAP = 2000   # clean first, then check the real limit, so an over-long value is refused, not cut

CSV_COLUMNS = ["period", "team", "captain username", "contact", "full", "open roles", "note",
               "Dota id", "name", "medal", "verified", "also on another team", "updated at"]
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _now(now) -> int:
    return int(time.time()) if now is None else int(now)


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

def open_period(db, now=None) -> TeamSignupPeriod | None:
    """The period open now: not closed, and its closing time (if any) not passed."""
    now = _now(now)
    return (db.query(TeamSignupPeriod)
            .filter(TeamSignupPeriod.closed_at.is_(None))
            .filter((TeamSignupPeriod.closes_at.is_(None)) | (TeamSignupPeriod.closes_at > now))
            .order_by(TeamSignupPeriod.id.desc()).first())


def is_open(db, now=None) -> bool:
    return open_period(db, now) is not None


def last_period(db) -> TeamSignupPeriod | None:
    return db.query(TeamSignupPeriod).order_by(TeamSignupPeriod.id.desc()).first()


def close_expired(db, now=None) -> None:
    """Record closed_at = closes_at on periods whose closing time has passed (the lazy
    close), so the one-open-period index and the retention see them as closed."""
    now = _now(now)
    for p in (db.query(TeamSignupPeriod)
              .filter(TeamSignupPeriod.closed_at.is_(None), TeamSignupPeriod.closes_at.isnot(None),
                      TeamSignupPeriod.closes_at <= now).all()):
        p.closed_at = p.closes_at
    db.flush()


def start_period(db, label: str, closes_at: int | None, admin_user_id: int, now=None) -> TeamSignupPeriod:
    now = _now(now)
    clean = clean_display_text(label, _CLEAN_CAP)
    if not clean or len(clean) > LABEL_MAX:
        raise HTTPException(status_code=422, detail=f"The label needs 1-{LABEL_MAX} characters")
    if closes_at is not None and closes_at <= now:
        raise HTTPException(status_code=422, detail="The closing time must be in the future")
    close_expired(db, now)
    if open_period(db, now) is not None:
        raise HTTPException(status_code=409, detail="A signup period is already open")
    p = TeamSignupPeriod(label=clean, opened_at=now, closes_at=closes_at, opened_by_user_id=admin_user_id)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A signup period is already open")
    return p


def close_period(db, now=None) -> TeamSignupPeriod:
    now = _now(now)
    p = open_period(db, now)
    if p is None:
        raise HTTPException(status_code=409, detail="No signup period is open")
    p.closed_at = now
    db.flush()
    return p


def _period_json(p: TeamSignupPeriod | None, now: int) -> dict | None:
    if p is None:
        return None
    is_open_now = p.closed_at is None and (p.closes_at is None or p.closes_at > now)
    return {"id": p.id, "label": p.label, "opened_at": p.opened_at, "closes_at": p.closes_at,
            "closed_at": p.closed_at if p.closed_at is not None else (None if is_open_now else p.closes_at),
            "open": is_open_now}


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

def _clean_field(value, max_len: int, label: str, *, min_len: int = 0, no_links: bool = False) -> str:
    text = clean_display_text(value, _CLEAN_CAP)
    if len(text) < min_len or len(text) > max_len:
        if min_len:
            raise HTTPException(status_code=422, detail=f"{label} needs {min_len}-{max_len} characters")
        raise HTTPException(status_code=422, detail=f"{label} is at most {max_len} characters")
    if no_links and looks_like_url(text):
        raise HTTPException(status_code=422, detail=f"Links aren't allowed in the {label.lower()}")
    return text


def _clean_roles(roles) -> list[int]:
    out = []
    for r in roles or []:
        if isinstance(r, bool) or not isinstance(r, int) or r not in ROLES:
            raise HTTPException(status_code=422, detail="Open roles are positions 1-5")
        if r not in out:
            out.append(r)
    return sorted(out)


def _players_of(db, signup_id: int) -> list[TeamSignupPlayer]:
    return (db.query(TeamSignupPlayer).filter(TeamSignupPlayer.signup_id == signup_id)
            .order_by(TeamSignupPlayer.verified.desc(), TeamSignupPlayer.added_at, TeamSignupPlayer.id).all())


def _own_listing(db, period_id: int, user_id: int) -> TeamSignup | None:
    return (db.query(TeamSignup)
            .filter(TeamSignup.period_id == period_id, TeamSignup.captain_user_id == user_id).first())


def _require_open(db, now: int) -> TeamSignupPeriod:
    p = open_period(db, now)
    if p is None:
        raise HTTPException(status_code=409, detail="Signup is closed")
    return p


def _require_website_account(user: User | None) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if getattr(user, "account_type", None) == "twitch":
        # Defensive: deps never resolves a soft account's session on the website.
        raise HTTPException(status_code=403, detail="Log in with a website account to list a team")
    return user


def save_listing(db, user: User, *, team_name, players, open_roles=None, note="", contact="",
                 is_full=False, now=None) -> TeamSignup:
    """Create or update the user's one listing in the open period. Players are typed
    Dota or Steam64 ids; the user's Steam-verified player is always first. Names and
    medals are stored with the listing (kept for ids already on it), from the pool and
    the lookup cache only."""
    now = _now(now)
    _require_website_account(user)
    period = _require_open(db, now)
    name = _clean_field(team_name, NAME_MAX, "Team name", min_len=NAME_MIN, no_links=True)
    note = _clean_field(note, NOTE_MAX, "Note", no_links=True)
    contact = _clean_field(contact, CONTACT_MAX, "Contact", min_len=1)
    roles = _clean_roles(open_roles)

    own = verified_player_id(user)
    ids = [own] if own else []
    for raw in players or []:
        pid = player_lookup.to_account_id(raw)
        if pid == own:
            continue
        if pid in ids:
            raise HTTPException(status_code=422, detail=f"Dota id {pid} is listed twice")
        ids.append(pid)
    if not ids:
        raise HTTPException(status_code=422, detail="List at least one player")
    if len(ids) > MAX_PLAYERS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_PLAYERS} players")

    signup = _own_listing(db, period.id, user.id)
    if signup is None:
        signup = TeamSignup(period_id=period.id, captain_user_id=user.id, created_at=now,
                            team_name=name, contact=contact, updated_at=now)
        db.add(signup)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Your listing was saved meanwhile; reload and try again")
    signup.team_name, signup.contact, signup.note = name, contact, note or None
    signup.open_roles_json = json.dumps(roles)
    signup.is_full = bool(is_full)
    signup.updated_at = now

    existing = {r.account_id: r for r in _players_of(db, signup.id)}
    for pid, row in existing.items():
        if pid not in ids:
            db.delete(row)
    known = {pid: (r.name, r.rank_tier, r.leaderboard_rank, "stored") for pid, r in existing.items()}
    new_ids = [pid for pid in ids if pid not in existing]
    # No OpenDota call while saving: the form looked the ids up first, so they are
    # normally cached; anything else is stored as "Unknown player".
    for info in player_lookup.describe(db, new_ids, known, fetch=False):
        db.add(TeamSignupPlayer(signup_id=signup.id, account_id=info["account_id"], name=info["name"],
                                rank_tier=info["rank_tier"], leaderboard_rank=info["leaderboard_rank"],
                                verified=info["account_id"] == own, added_at=now))
    for pid, row in existing.items():
        if pid in ids:
            row.verified = pid == own
    db.flush()
    return signup


def delete_listing(db, user: User, now=None) -> None:
    now = _now(now)
    _require_website_account(user)
    period = _require_open(db, now)
    signup = _own_listing(db, period.id, user.id)
    if signup is None:
        raise HTTPException(status_code=404, detail="You have no listing")
    _delete_signups(db, [signup.id])


def _delete_signups(db, signup_ids: list[int]) -> int:
    if not signup_ids:
        return 0
    db.query(TeamSignupPlayer).filter(TeamSignupPlayer.signup_id.in_(signup_ids)).delete(synchronize_session=False)
    n = db.query(TeamSignup).filter(TeamSignup.id.in_(signup_ids)).delete(synchronize_session=False)
    db.flush()
    db.expire_all()
    return n


def not_on_team(db, user: User, signup_id: int) -> tuple[TeamSignup, TeamSignupPeriod, int]:
    """Delete the user's Steam-verified player from another captain's listing; returns
    the listing, its period and the removed Dota id."""
    _require_website_account(user)
    signup = db.get(TeamSignup, signup_id)
    if signup is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if signup.captain_user_id == user.id:
        raise HTTPException(status_code=403, detail="Edit your own listing instead")
    own = verified_player_id(user)
    row = None
    if own:
        row = (db.query(TeamSignupPlayer)
               .filter(TeamSignupPlayer.signup_id == signup.id, TeamSignupPlayer.account_id == own).first())
    if row is None:
        raise HTTPException(status_code=403, detail="Your Steam-verified player is not on this listing")
    db.delete(row)
    db.flush()
    return signup, db.get(TeamSignupPeriod, signup.period_id), own


def remove_listing(db, signup_id: int) -> tuple[str, TeamSignupPeriod]:
    """Admin removal of one listing and its players."""
    signup = db.get(TeamSignup, signup_id)
    if signup is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    period = db.get(TeamSignupPeriod, signup.period_id)
    info = (signup.team_name, period)
    _delete_signups(db, [signup_id])
    return info


def clear_period(db, period_id: int) -> tuple[TeamSignupPeriod, int]:
    """Delete a period's listings and players (Clear signups). The period row stays."""
    period = db.get(TeamSignupPeriod, period_id)
    if period is None:
        raise HTTPException(status_code=404, detail="Signup period not found")
    ids = [r[0] for r in db.query(TeamSignup.id).filter(TeamSignup.period_id == period_id).all()]
    return period, _delete_signups(db, ids)


def cleanup(db, now=None) -> int:
    """Daily retention: delete periods closed more than RETENTION_DAYS ago, with their
    listings and players. Returns the number of periods deleted."""
    now = _now(now)
    close_expired(db, now)
    old = (db.query(TeamSignupPeriod)
           .filter(TeamSignupPeriod.closed_at.isnot(None),
                   TeamSignupPeriod.closed_at < now - RETENTION_DAYS * DAY).all())
    for p in old:
        clear_period(db, p.id)
    n = 0
    for p in old:
        db.query(TeamSignupPeriod).filter(TeamSignupPeriod.id == p.id).delete(synchronize_session=False)
        n += 1
    db.flush()
    return n


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------

def daily_key(period_id: int, signup_id: int, now: int) -> str:
    """The sort key of the daily shuffle: seeded by the period and the UTC date only, so
    the order holds all day, changes the next, and editing a listing doesn't move it."""
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    return hashlib.sha256(f"{period_id}|{day}|{signup_id}".encode()).hexdigest()


def _listings(db, period_id: int) -> list[tuple[TeamSignup, list[TeamSignupPlayer]]]:
    signups = db.query(TeamSignup).filter(TeamSignup.period_id == period_id).all()
    rows = (db.query(TeamSignupPlayer).filter(TeamSignupPlayer.signup_id.in_([s.id for s in signups]))
            .order_by(TeamSignupPlayer.verified.desc(), TeamSignupPlayer.added_at, TeamSignupPlayer.id).all()
            if signups else [])
    by_signup: dict[int, list] = {s.id: [] for s in signups}
    for r in rows:
        by_signup[r.signup_id].append(r)
    return [(s, by_signup[s.id]) for s in signups]


def _listed_counts(listings) -> dict[int, int]:
    counts: dict[int, int] = {}
    for _, players in listings:
        for p in players:
            counts[p.account_id] = counts.get(p.account_id, 0) + 1
    return counts


def _roles(signup: TeamSignup) -> list[int]:
    try:
        return [r for r in json.loads(signup.open_roles_json or "[]") if r in ROLES]
    except (TypeError, ValueError):
        return []


def _team_json(signup, players, counts, *, with_contact: bool, viewer_player_id=None,
               viewer_id=None) -> dict:
    return {
        "id": signup.id,
        "team_name": signup.team_name,
        "open_roles": _roles(signup),
        "note": signup.note or "",
        "is_full": bool(signup.is_full),
        "player_count": len(players),
        "players_needed": max(0, TEAM_SIZE - len(players)),
        "updated_at": signup.updated_at,
        "is_mine": viewer_id is not None and signup.captain_user_id == viewer_id,
        "players": [{
            "account_id": p.account_id,
            "name": p.name,
            "rank_tier": p.rank_tier,
            "leaderboard_rank": p.leaderboard_rank,
            "medal": medal_name(p.rank_tier, p.leaderboard_rank),
            "verified": bool(p.verified),
            "also_listed": counts.get(p.account_id, 0) > 1,
            "is_you": viewer_player_id is not None and p.account_id == viewer_player_id,
        } for p in players],
        **({"contact": signup.contact} if with_contact else {}),
    }


def public_view(db, viewer: User | None, now=None) -> dict:
    """GET /team-signup: the open period's partial teams in the daily shuffle, full teams
    after them, and the viewer's own listing. Contacts only for a logged-in viewer;
    never user ids or emails."""
    now = _now(now)
    period = open_period(db, now)
    logged_in = viewer is not None
    viewer_pid = verified_player_id(viewer)
    out = {"period": _period_json(period or last_period(db), now), "open": period is not None,
           "logged_in": logged_in, "can_list": logged_in and period is not None,
           "teams": [], "full_teams": [], "mine": None, "own_player": None}
    if viewer_pid:
        out["own_player"] = _own_player(db, viewer_pid)
    if period is None:
        return out
    listings = _listings(db, period.id)
    counts = _listed_counts(listings)
    viewer_id = viewer.id if logged_in else None
    teams = [_team_json(s, ps, counts, with_contact=logged_in, viewer_player_id=viewer_pid, viewer_id=viewer_id)
             for s, ps in listings]
    partial = [t for t in teams if not t["is_full"]]
    partial.sort(key=lambda t: daily_key(period.id, t["id"], now))
    full = sorted((t for t in teams if t["is_full"]), key=lambda t: t["team_name"].lower())
    out["teams"], out["full_teams"] = partial, full
    out["mine"] = next((t for t in teams if t["is_mine"]), None)
    return out


def _own_player(db, account_id: int) -> dict:
    """The viewer's Steam-verified player for the form: the pool's name and medal, else
    the last stored listing's; never an OpenDota call (the form looks it up if unnamed)."""
    p = db.get(Player, account_id)
    if p is not None and p.name:
        name, tier, lb = p.name, p.rank_tier, p.leaderboard_rank
    else:
        row = (db.query(TeamSignupPlayer).filter(TeamSignupPlayer.account_id == account_id,
                                                 TeamSignupPlayer.name.isnot(None))
               .order_by(TeamSignupPlayer.id.desc()).first())
        name, tier, lb = (row.name, row.rank_tier, row.leaderboard_rank) if row else (None, None, None)
    return {"account_id": account_id, "name": name, "rank_tier": tier, "leaderboard_rank": lb,
            "medal": medal_name(tier, lb), "verified": True}


# ---------------------------------------------------------------------------
# Admin view and export
# ---------------------------------------------------------------------------

def admin_view(db, now=None) -> dict:
    now = _now(now)
    periods = db.query(TeamSignupPeriod).order_by(TeamSignupPeriod.id.desc()).all()
    current = open_period(db, now) or (periods[0] if periods else None)
    listings = []
    if current is not None:
        rows = _listings(db, current.id)
        counts = _listed_counts(rows)
        names = _captain_names(db, [s.captain_user_id for s, _ in rows])
        for s, ps in sorted(rows, key=lambda x: x[0].created_at):
            listings.append({"id": s.id, "team_name": s.team_name, "captain": names.get(s.captain_user_id, ""),
                             "contact": s.contact, "is_full": bool(s.is_full), "player_count": len(ps),
                             "duplicates": sum(1 for p in ps if counts.get(p.account_id, 0) > 1),
                             "updated_at": s.updated_at})
    return {"open": open_period(db, now) is not None,
            "current": _period_json(current, now),
            "periods": [{**_period_json(p, now),
                         "listing_count": db.query(TeamSignup).filter(TeamSignup.period_id == p.id).count()}
                        for p in periods],
            "listings": listings}


def _captain_names(db, user_ids) -> dict[int, str]:
    ids = set(user_ids)
    if not ids:
        return {}
    return {u.id: u.username for u in db.query(User).filter(User.id.in_(ids)).all()}


def export_period(db, period_id: int | None, now=None) -> TeamSignupPeriod:
    """The period an export covers: the given one, else the open one, else the last one."""
    if period_id is not None:
        p = db.get(TeamSignupPeriod, period_id)
    else:
        p = open_period(db, now) or last_period(db)
    if p is None:
        raise HTTPException(status_code=404, detail="Signup period not found")
    return p


def _safe_cell(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(_FORMULA_PREFIXES) else s


def _iso(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts)) if ts else ""


def csv_rows(db, period: TeamSignupPeriod) -> list[list[str]]:
    """One row per listed player (a listing with no players left gets one row)."""
    listings = _listings(db, period.id)
    counts = _listed_counts(listings)
    names = _captain_names(db, [s.captain_user_id for s, _ in listings])
    out = []
    for s, players in sorted(listings, key=lambda x: x[0].created_at):
        base = [period.label, s.team_name, names.get(s.captain_user_id, ""), s.contact,
                "yes" if s.is_full else "no", " ".join(str(r) for r in _roles(s)), s.note or ""]
        for p in players or [None]:
            tail = ["", "", "", "", ""] if p is None else [
                p.account_id, p.name or player_lookup.UNKNOWN_PLAYER,
                medal_name(p.rank_tier, p.leaderboard_rank) or "",
                "yes" if p.verified else "no", "yes" if counts.get(p.account_id, 0) > 1 else "no"]
            out.append([_safe_cell(v) for v in base + tail + [_iso(s.updated_at)]])
    return out


def csv_text(db, period: TeamSignupPeriod) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    w.writerows(csv_rows(db, period))
    return buf.getvalue()


def export_json(db, period: TeamSignupPeriod) -> dict:
    return {"columns": CSV_COLUMNS, "period": period.label, "rows": csv_rows(db, period)}
