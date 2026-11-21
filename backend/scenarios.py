"""Season scenarios (issue #145): replace the game data with a named, deterministic season
and set the demo clock to match. Demo Mode only (see routers/admin_demo.py).

The data comes from `season_generator` with a fixed seed per scenario. The wipe reuses
`season_reset.clear()` and then deletes the tables Reset keeps, except KEPT_TABLES and
the caller's own user and session rows. Weeks lock through the production path: the
clock is stepped week by week and `auto_lock_weeks`, `due_substitutions` and
`generate_weekly_summaries` run each time, so roster snapshots, substitutions and Weekly
Reports come from the same code as a real season.
"""

import os
import secrets
import time
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import func, select

import card_points
import clock
import season_generator
import season_reset
from auth import PASSWORD_MAX_BYTES, hash_password
from database import Base
from models import (AuditLog, Card, CardModifier, League, Match, Player, PlayerMatchStats,
                    Team, User, Week, WeeklyRosterEntry, Weight)
from scoring import apply_mvp_bonus_to_row
from weeks import auto_lock_weeks, due_substitutions, generate_weekly_summaries

SCENARIO_LEAGUE_ID = 990001
SCENARIO_LEAGUE_NAME = "Scenario League"
# Week 1 starts Monday 2026-01-05 00:00 UTC; scenario data never depends on the real time.
SCENARIO_START = 1767571200
ACCOUNT_NAMES = ("scenario-admin", "scenario1", "scenario2", "scenario3", "scenario4", "scenario5")
ADMIN_ACCOUNT = "scenario-admin"
SECRET_ENV_NAME = "DEMO_ACCOUNT_PASSWORD"
MISSING_SECRET_DETAIL = f"{SECRET_ENV_NAME} is not set: scenario accounts need a password. Set it and restart."
# The registration rule (RegisterBody.password: at least 6 characters, at most 72 bytes).
SECRET_MIN_LENGTH = 6
WEAK_SECRET_DETAIL = (f"{SECRET_ENV_NAME} does not meet the password rules (at least "
                      f"{SECRET_MIN_LENGTH} characters, at most {PASSWORD_MAX_BYTES} bytes). "
                      "Change it and restart.")
# The final clock sits this long before the next week's lock (all ended weeks processed).
CLOCK_LEAD_SECONDS = 12 * 3600

_SEASON = dict(weeks=10, teams=8, players_per_team=5, games_per_team_week=2, roster_size=5,
               window_days=5, start=SCENARIO_START)
_CARDS = (12, 15, 10, 13, 11, 14)

SCENARIOS = {
    "pre-season": dict(seed=145_001, locked_weeks=0, cards_per_user=(3,) * len(ACCOUNT_NAMES)),
    "mid-season": dict(seed=145_002, locked_weeks=5, cards_per_user=_CARDS, mvp_skip_every=5,
                       sit_out_week=3, special_week=4, unparsed=1, excluded=1),
    "season-end": dict(seed=145_003, locked_weeks=10, cards_per_user=_CARDS, mvp_skip_every=5,
                       sit_out_week=3),
}

# What a scenario load keeps: settings and the audit trail. demo_clock is kept and set.
KEPT_TABLES = ("weights", "scoring_state", "tag_definitions", "audit_logs", "demo_clock")
# Deleted on top of season_reset.CLEARED_TABLES: every other table, so scenario history
# never mixes with real data. users and user_sessions keep the caller's rows.
EXTRA_DELETED_TABLES = tuple(sorted(
    (set(season_reset.KEPT_TABLES) | set(season_reset.UPDATED_TABLES)) - set(KEPT_TABLES)))
_CALLER_KEPT = {"users": "id", "user_sessions": "user_id"}


@contextmanager
def _one_transaction(db):
    """Run the production week jobs inside one transaction: they commit as they go, so
    their commits become flushes until the load finishes. Any error rolls back all of it,
    the wipe included."""
    db.commit = db.flush
    try:
        yield
    except BaseException:
        del db.commit
        db.rollback()
        raise
    del db.commit
    db.commit()


def _wipe(db, caller_id: int) -> None:
    season_reset.clear(db)
    for table in reversed(Base.metadata.sorted_tables):  # children first
        if table.name not in EXTRA_DELETED_TABLES:
            continue
        stmt = table.delete()
        if table.name in _CALLER_KEPT:
            stmt = stmt.where(table.c[_CALLER_KEPT[table.name]] != caller_id)
        db.execute(stmt)
    # Forget the deleted rows' objects, so new rows that reuse their ids don't collide.
    db.flush()
    db.expunge_all()


def _ensure_weights(db) -> dict:
    if db.query(Weight).first() is None:
        from seed import DEFAULT_WEIGHTS
        for w in DEFAULT_WEIGHTS:
            db.add(Weight(key=w["key"], label=w["label"], value=w["value"]))
        db.flush()
    return {w.key: w.value for w in db.query(Weight).all()}


def _week_jobs(db, timestamp: int) -> None:
    """The same sequence as POST /admin/demo/clock."""
    clock.set_override(db, timestamp)
    db.flush()
    auto_lock_weeks(db)
    due_substitutions(db)
    generate_weekly_summaries(db)


def _accounts(db, caller, password: str, created_at: int) -> tuple[list[User], str | None]:
    """The scenario accounts and scenario-admin's one-time password. The players share
    DEMO_ACCOUNT_PASSWORD; scenario-admin gets its own random password, so a tester given
    a player login does not also have the admin login."""
    player_hash = hash_password(password)
    tokens = season_reset.initial_tokens()
    out, admin_password = [], None
    for name in ACCOUNT_NAMES:
        if caller is not None and (caller.username or "").lower() == name:
            out.append(caller)  # the caller already is this account: it plays it
            continue
        if name == ADMIN_ACCOUNT:
            admin_password = secrets.token_urlsafe(12)
            password_hash = hash_password(admin_password)
        else:
            password_hash = player_hash
        user = User(username=name, email=f"{name}@demo.local", password_hash=password_hash,
                    is_admin=name == ADMIN_ACCOUNT, is_tester=False, is_demo=True,
                    account_type="full", tokens=tokens, created_at=created_at)
        db.add(user)
        out.append(user)
    db.flush()
    return out, admin_password


def _insert_matches(db, matches, weights) -> int:
    rows = 0
    stat_cols = set(PlayerMatchStats.__table__.columns.keys())
    for m in matches:
        db.add(Match(match_id=m["match_id"], radiant_team_id=m["radiant_team_id"],
                     dire_team_id=m["dire_team_id"], league_id=SCENARIO_LEAGUE_ID,
                     start_time=m["start_time"], radiant_win=m["radiant_win"],
                     duration=m["duration"], parse_status=m["parse_status"],
                     excluded_from_scoring=m["excluded_from_scoring"], source="league"))
        for s in m["stats"]:
            row = PlayerMatchStats(match_id=m["match_id"],
                                   **{k: v for k, v in s.items() if k in stat_cols})
            apply_mvp_bonus_to_row(row, weights, bool(s["is_mvp"]))
            db.add(row)
            rows += 1
    db.flush()
    return rows


def _change_roster(cards: list[Card], week_number: int, roster_size: int) -> None:
    """Before a lock, swap one active card of the account for its first bench card."""
    active = sorted((c for c in cards if c.is_active), key=lambda c: c.slot_index)
    bench = sorted((c for c in cards if not c.is_active), key=lambda c: c.id)
    if not active or not bench:
        return
    out = active[(week_number - 2) % min(roster_size, len(active))]
    slot = out.slot_index
    out.is_active, out.slot_index = False, None
    bench[0].is_active, bench[0].slot_index = True, slot


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar() or 0


def load(db, name: str, caller_id: int) -> dict:
    """Replace the game data with scenario `name` and set the demo clock. Commits once at
    the end; on any error nothing changes. 409 when DEMO_ACCOUNT_PASSWORD is missing or
    fails the password rules."""
    if name not in SCENARIOS:
        raise HTTPException(status_code=422, detail="Unknown scenario")
    password = os.getenv(SECRET_ENV_NAME, "")
    if not password:
        raise HTTPException(status_code=409, detail=MISSING_SECRET_DETAIL)
    if len(password) < SECRET_MIN_LENGTH or len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise HTTPException(status_code=409, detail=WEAK_SECRET_DETAIL)
    spec = dict(SCENARIOS[name])
    seed, locked = spec.pop("seed"), spec.pop("locked_weeks")
    season = season_generator.generate(seed, users=len(ACCOUNT_NAMES), **_SEASON, **spec)

    with _one_transaction(db):
        _wipe(db, caller_id)
        caller = db.get(User, caller_id)
        weights = _ensure_weights(db)
        db.add(League(id=SCENARIO_LEAGUE_ID, name=SCENARIO_LEAGUE_NAME, is_monitored=True))
        for t in season["teams"]:
            db.add(Team(id=t["id"], name=t["name"]))
        for p in season["players"]:
            db.add(Player(id=p["id"], name=p["name"], is_active=True))
        weeks = []
        for w in season["weeks"]:
            week = Week(label=w["label"], start_time=w["start_time"], end_time=w["end_time"],
                        is_locked=False)
            db.add(week)
            weeks.append(week)
        accounts, admin_password = _accounts(db, caller, password, SCENARIO_START - season_generator.WEEK)
        cards_by_account = []
        for user, gu in zip(accounts, season["users"]):
            cards = []
            for gc in gu["cards"]:
                card = Card(player_id=gc["player_id"], owner_id=user.id, card_type=gc["card_type"],
                            league_id=SCENARIO_LEAGUE_ID, is_active=gc["is_active"],
                            slot_index=gc["slot_index"])
                db.add(card)
                cards.append(card)
            db.flush()
            for card, gc in zip(cards, gu["cards"]):
                for mod in gc["modifiers"]:
                    db.add(CardModifier(card_id=card.id, **mod))
            cards_by_account.append(cards)
        db.flush()

        stat_rows = 0
        for week, w in zip(weeks[:locked], season["weeks"]):
            number = w["number"]
            if number >= 2:
                _change_roster(cards_by_account[-1], number, _SEASON["roster_size"])
            _week_jobs(db, week.start_time)
            stat_rows += _insert_matches(
                db, [m for m in season["matches"] if m["week"] == number], weights)
        final = SCENARIO_START + locked * season_generator.WEEK - CLOCK_LEAD_SECONDS
        _week_jobs(db, final)
        card_points.rebuild_all(db)

        counts = {
            "accounts": len(accounts), "teams": len(season["teams"]),
            "players": len(season["players"]), "weeks": len(weeks), "locked_weeks": locked,
            "matches": _count(db, Match), "stat_rows": stat_rows, "cards": _count(db, Card),
            "roster_entries": _count(db, WeeklyRosterEntry),
            "substitutions": db.query(WeeklyRosterEntry).filter(
                WeeklyRosterEntry.subbed_in == True).count(),  # noqa: E712
        }
        db.add(AuditLog(timestamp=int(time.time()), actor_id=caller_id,
                        actor_username=caller.username if caller else None,
                        action="demo_scenario_loaded",
                        detail=f"name={name} users={len(accounts)} matches={counts['matches']}"))
    season_reset.bust_caches()
    return {"scenario": name, "override_timestamp": final, "effective_now": clock.now(db),
            "accounts": [u.username for u in accounts], "counts": counts,
            # Shown once; never logged or audited. None when the caller is scenario-admin.
            "admin_password": admin_password}
