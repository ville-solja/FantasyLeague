"""
Tests for plan-issue-129-automatic-bench-substitution.md (resolves GitHub issue #129).

When a week locks, `weeks._snapshot_week` saves each user's bench (with its order)
alongside the active cards in `weekly_roster_entries`. SUBSTITUTION_DELAY_HOURS
(default 24) after the week's end_time, `weeks.run_substitutions(db, week)` marks
every active card whose player played 0 scored matches as `subbed_out` and brings in
the first bench card (by `bench_order`) whose player played as `subbed_in`. Every
reader counts an entry when `(is_bench = 0 AND subbed_out = 0) OR subbed_in = 1`.

  Story 1: Bench Saved at Lock
  Story 2: Automatic Substitution After the Week
  Story 3: Points Count the Substituted Roster
  Story 4: See What Was Substituted
  Story 5: Admin Re-Run

Decisions confirmed with the product owner (2026-10-01), each pinned by a test:
  - weeks without a bench snapshot (locked before this release) get no substitutions;
  - empty roster slots are never filled from the bench;
  - an active card whose player played is never replaced, however few points it scored.

Approach notes:

- `db` fixture from conftest (in-memory SQLite, `Base.metadata.create_all`).
- Seeding: build users/players/teams/cards/weeks/matches/stats/weights directly, like
  `_seed` in test_issue_141_stored_card_points.py, then call `card_points.rebuild_all(db)`
  — every reader sums stored `card_match_points` rows (lessons-learned 2026-09-30), so
  without the rebuild all card totals read as zero.
- Canonical scenario (plan Verification): user has active A (slot 0, played),
  B (slot 1, 0 matches) and bench C (slot_index 0, played), D (slot_index 1, played).
  After substitution: B subbed_out, C subbed_in; week points = A + C.
- Lock snapshot: create cards (active + bench, `slot_index` set), then call
  `weeks.auto_lock_weeks(db)` under `patch("clock.time.time", return_value=...)` as in
  test_weeks.py, or call `weeks._snapshot_week(db, week)` directly.
- Clock: weeks.py reads "now" through `clock.now(db)`, which falls back to
  `time.time()`; control it with `patch("clock.time.time", return_value=T)` (DEMO_MODE
  unset). The delay is read from SUBSTITUTION_DELAY_HOURS: set it with
  `monkeypatch.setenv(...)`; if the implementation caches it in a module constant,
  monkeypatch that constant instead.
- "Played" = >=1 match in the week window (start/end, or `Match.week_override_id`) that
  passes `match_scoring.scored_match_sql()` (`excluded_from_scoring` = 0).
- Readers are called directly: `routers.cards._build_roster_response(db, user_id, week_id)`,
  `routers.leaderboard.weekly_leaderboard(week_id=..., db=db)`,
  `routers.leaderboard.compute_season_standings(db)`,
  `routers.leaderboard.season_leaderboard(db=db)`.
- HTTP tests (GET /roster/{user_id}, POST /admin/weeks/{week_id}/substitutions auth):
  build a minimal FastAPI app with the cards / admin_weeks / auth routers on a
  StaticPool in-memory engine, like `session_env` in test_issue_117_longer_sessions.py.
  Sessions are server-side rows now: log in through `POST /login`, or use
  `{"sid": sessions.create_session(db, user)}` (lessons-learned 2026-10-01). The re-run
  endpoint is not destructive, so it must NOT need `POST /reauth`. Never reload or
  import `main` in-process (lessons-learned 2026-09-27 / 2026-09-28); inspect main.py as
  source text only.
- Admin endpoint logic can also be called as a plain function with `db=db` and an admin
  dict, as test_issue_141 does for other admin routers.
- Migration tests use a legacy in-memory engine with the pre-029 `weekly_roster_entries`
  and `weeks` tables (see tests/test_migrate.py) and call `migrate.run_migrations`.
- Frontend criteria are static text checks of `frontend/*.js` and `frontend/index.html`.

Run with: cd backend && python -m pytest tests/test_issue_129_automatic_bench_substitution.py -v
"""

import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect as sa_inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

import card_points
import migrate
import weeks
from auth import hash_password
from database import Base
from models import (
    AuditLog, Card, CardMatchPoints, Match, Player, PlayerMatchStats, Team, User, Week,
    WeeklyRosterEntry, Weight,
)
from routers import admin_weeks
from routers.cards import _build_roster_response, get_roster
from routers.leaderboard import compute_season_standings, season_leaderboard, weekly_leaderboard
from routers.weekly_summary import _build_week_summary
from scoring import fantasy_score

REPO = Path(__file__).resolve().parents[2]
_ADMIN = {"user_id": 99, "username": "admin", "is_admin": True}
_PASSWORD = "correct-horse-battery"

_WEIGHTS = {
    "kills": 0.3, "gold_per_min": 0.002,
    "death_pool": 3.0, "death_deduction": 0.3, "mvp_bonus_pct": 10.0,
    "rarity_common": 0.0, "rarity_rare": 1.0, "rarity_epic": 2.0, "rarity_legendary": 3.0,
    "modifier_count_common": 0.0, "modifier_count_rare": 1.0, "modifier_count_epic": 2.0,
    "modifier_count_legendary": 3.0, "modifier_bonus_pct": 10.0, "team_booster_cost": 3.0,
}

# Week 1 = [0, 1000]; Week 2 = [1001, 2000].
WEEK_END = 1000
A, B, C, D, E = 101, 102, 103, 104, 105
# (match_id, start_time, {player_id: (kills, deaths, gpm)})
_MATCHES = [
    (1, 100, {A: (5, 2, 437), C: (3, 1, 391), D: (6, 0, 512)}),
    (2, 200, {A: (2, 1, 403), C: (4, 0, 455), D: (1, 3, 377)}),
]


def _add_match(db, match_id, start, players, week_override_id=None, excluded=False):
    db.add(Match(match_id=match_id, radiant_team_id=1, dire_team_id=2, start_time=start,
                 radiant_win=True, league_id=1, week_override_id=week_override_id,
                 excluded_from_scoring=excluded))
    for pid, (kills, deaths, gpm) in players.items():
        stats = {"kills": kills, "deaths": deaths, "gold_per_min": gpm}
        db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=1,
                                fantasy_points=round(fantasy_score(stats, _WEIGHTS), 4),
                                is_mvp=False, **stats))


def _seed(db, cards=None, matches=_MATCHES, lock=True, extra_users=()):
    """alice (1): active A (card 1, slot 0, played), B (card 2, slot 1, 0 matches);
    bench C (card 3, slot_index 0, played), D (card 4, slot_index 1, played).
    `cards` overrides the card list: (card_id, owner_id, player_id, is_active, slot_index)."""
    for key, value in _WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.add(User(id=1, username="alice", email="a@test", password_hash=hash_password(_PASSWORD),
                tokens=5))
    for uid, name in extra_users:
        db.add(User(id=uid, username=name, email=f"{name}@test",
                    password_hash=hash_password(_PASSWORD), tokens=5))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    for pid in (A, B, C, D, E):
        db.add(Player(id=pid, name=f"P{pid}", is_active=True))
    if cards is None:
        cards = [(1, 1, A, True, 0), (2, 1, B, True, 1), (3, 1, C, False, 0), (4, 1, D, False, 1)]
    for cid, owner, pid, active, slot in cards:
        db.add(Card(id=cid, player_id=pid, owner_id=owner, card_type="common",
                    is_active=active, slot_index=slot))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=WEEK_END, is_locked=False))
    db.add(Week(id=2, label="Week 2", start_time=1001, end_time=2000, is_locked=False))
    for match_id, start, players in matches:
        _add_match(db, match_id, start, players)
    db.commit()
    card_points.rebuild_all(db)
    if lock:
        _lock(db, 1)


def _lock(db, week_id):
    week = db.get(Week, week_id)
    weeks._snapshot_week(db, week)
    week.is_locked = True
    db.commit()
    return week


def _sub(db, week_id=1):
    n = weeks.run_substitutions(db, db.get(Week, week_id))
    db.commit()
    return n


def _entries(db, week_id=1, user_id=1):
    return {e.card_id: e for e in db.query(WeeklyRosterEntry)
            .filter_by(week_id=week_id, user_id=user_id).all()}


def _flags(db, week_id=1, user_id=1):
    return {cid: (bool(e.subbed_in), bool(e.subbed_out)) for cid, e in _entries(db, week_id, user_id).items()}


def _card_week_pts(db, card_id, week_id=1):
    w = db.get(Week, week_id)
    return db.execute(text("""
        SELECT COALESCE(SUM(cmp.points), 0) FROM card_match_points cmp
        JOIN matches m ON m.match_id = cmp.match_id AND COALESCE(m.excluded_from_scoring, 0) = 0
        WHERE cmp.card_id = :cid AND (m.week_override_id = :wid
              OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
    """), {"cid": card_id, "wid": week_id, "ws": w.start_time, "we": w.end_time}).scalar()


def _week_total(db, user_id=1, week_id=1):
    return {r["id"]: r["week_points"] for r in weekly_leaderboard(week_id=week_id, db=db)}[user_id]


def _season_total(db, user_id=1):
    return {r["id"]: r["points"] for r in compute_season_standings(db)}[user_id]


def _audits(db, action):
    return db.query(AuditLog).filter_by(action=action).all()


def _read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def _at(ts):
    return patch("clock.time.time", return_value=ts)


# ---------------------------------------------------------------------------
# Story 1: Bench Saved at Lock
# ---------------------------------------------------------------------------

def test_snapshot_week_saves_bench_cards_with_bench_order(db):
    """When a week locks, every bench card is saved with is_bench=1 and bench_order 0..n
    from My Team's bench order (slot_index), alongside the active cards (is_bench=0)."""
    _seed(db, lock=False)
    with _at(500):
        weeks.auto_lock_weeks(db)
    e = _entries(db)
    assert set(e) == {1, 2, 3, 4}
    assert [bool(e[c].is_bench) for c in (1, 2)] == [False, False]
    assert (e[3].is_bench, e[3].bench_order) == (True, 0)
    assert (e[4].is_bench, e[4].bench_order) == (True, 1)


def test_snapshot_week_bench_order_null_slot_index_last_then_card_id(db):
    """Bench order is (slot_index IS NULL, slot_index, card id): cards without a
    slot_index come after ordered ones, ties broken by card id."""
    _seed(db, cards=[(1, 1, A, True, 0), (5, 1, B, False, None), (3, 1, C, False, None),
                     (4, 1, D, False, 2), (6, 1, E, False, 2)])
    e = _entries(db)
    order = sorted((x.bench_order, cid) for cid, x in e.items() if x.is_bench)
    assert [cid for _, cid in order] == [4, 6, 3, 5]
    assert [o for o, _ in order] == [0, 1, 2, 3]


def test_snapshot_week_skips_bench_cards_of_deactivated_players(db):
    """Bench cards whose player has players.is_active = 0 are not saved to
    weekly_roster_entries."""
    _seed(db, lock=False)
    db.get(Player, C).is_active = False
    db.commit()
    _lock(db, 1)
    e = _entries(db)
    assert 3 not in e
    assert e[4].bench_order == 0


def test_snapshot_week_skips_unowned_bench_cards(db):
    """Cards with no owner (owner_id NULL) are never saved as bench entries."""
    _seed(db, cards=[(1, 1, A, True, 0), (3, None, C, False, 0), (4, 1, D, False, 1)])
    rows = db.query(WeeklyRosterEntry).filter_by(week_id=1).all()
    assert {r.card_id for r in rows} == {1, 4}
    assert all(r.user_id is not None for r in rows)


def test_snapshot_week_is_idempotent_for_bench_rows(db):
    """Calling auto_lock_weeks / _snapshot_week twice for the same week writes each
    bench card once (no duplicate bench rows)."""
    _seed(db)
    weeks._snapshot_week(db, db.get(Week, 1))
    db.commit()
    with _at(500):
        weeks.auto_lock_weeks(db)
    rows = db.query(WeeklyRosterEntry).filter_by(week_id=1).all()
    assert sorted(r.card_id for r in rows) == [1, 2, 3, 4]


def test_snapshot_week_user_with_only_bench_cards_gets_bench_rows_only(db):
    """A user with no active cards but some bench cards gets bench rows only
    (is_bench=1); no active entries are invented."""
    _seed(db, cards=[(3, 1, C, False, 0), (4, 1, D, False, 1)])
    e = _entries(db)
    assert set(e) == {3, 4}
    assert all(x.is_bench for x in e.values())


def test_bench_entries_do_not_count_before_substitution(db):
    """Saved bench entries don't count towards any points total unless substituted in:
    My Team (locked week), weekly leaderboard, season leaderboard and
    compute_season_standings all exclude a played bench card that was not subbed in."""
    _seed(db)
    a = _card_week_pts(db, 1)
    assert _card_week_pts(db, 3) != 0
    assert _build_roster_response(db, 1, 1)["combined_value"] == pytest.approx(a)
    assert _build_roster_response(db, 1, 1)["season_points"] == pytest.approx(a)
    assert _week_total(db) == pytest.approx(round(a, 2))
    assert _season_total(db) == pytest.approx(round(a, 2))
    assert {r["id"]: r["season_points"] for r in season_leaderboard(db=db)}[1] == pytest.approx(round(a, 2))


def test_locked_week_roster_lists_bench_entries_on_bench_not_active(db):
    """For a locked week, _build_roster_response puts is_bench entries in `bench`, not in
    `active` (today every snapshot row is returned as active)."""
    _seed(db)
    r = _build_roster_response(db, 1, 1)
    assert [c["id"] for c in r["active"]] == [1, 2]
    assert [c["id"] for c in r["bench"]] == [3, 4]


def test_leaderboard_card_lists_exclude_uncounted_bench_entries(db):
    """The `cards` lists returned by the weekly and season leaderboards do not include
    bench entries that were not subbed in."""
    _seed(db)
    weekly = {r["id"]: r for r in weekly_leaderboard(week_id=1, db=db)}[1]
    season = {r["id"]: r for r in season_leaderboard(db=db)}[1]
    assert {c["card_id"] for c in weekly["cards"]} == {1}
    assert {c["card_id"] for c in season["cards"]} == {1}
    _sub(db)
    weekly = {r["id"]: r for r in weekly_leaderboard(week_id=1, db=db)}[1]
    season = {r["id"]: r for r in season_leaderboard(db=db)}[1]
    assert {c["card_id"] for c in weekly["cards"]} == {1, 3}
    assert {c["card_id"] for c in season["cards"]} == {1, 3}


def _legacy_engine():
    """Current schema, but weeks and weekly_roster_entries in their pre-029 shape with
    one existing row each."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE weekly_roster_entries"))
        conn.execute(text("DROP TABLE weeks"))
        conn.execute(text("""CREATE TABLE weeks (id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT, start_time INTEGER, end_time INTEGER, is_locked BOOLEAN DEFAULT 0)"""))
        conn.execute(text("""CREATE TABLE weekly_roster_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, week_id INTEGER, user_id INTEGER, card_id INTEGER)"""))
        conn.execute(text("INSERT INTO weeks (id, label, start_time, end_time, is_locked) "
                          "VALUES (1, 'Week 1', 0, 1000, 1)"))
        conn.execute(text("INSERT INTO weekly_roster_entries (week_id, user_id, card_id) VALUES (1, 1, 1)"))
        conn.commit()
        # A production DB has every earlier migration applied (010 would wipe the rows).
        migrate._ensure_migrations_table(conn)
        for migration_id, _ in migrate.MIGRATIONS:
            if migration_id < "029":
                migrate._record(conn, migration_id)
    return engine


def _cols(engine, table):
    return {c["name"] for c in sa_inspect(engine).get_columns(table)}


def test_migration_029_adds_substitution_columns(db):
    """Migration 029_weekly_roster_entries_substitution adds is_bench, bench_order,
    subbed_in and subbed_out to weekly_roster_entries (and the substitutions-run
    timestamp column to weeks) on a legacy schema."""
    engine = _legacy_engine()
    assert "is_bench" not in _cols(engine, "weekly_roster_entries")
    migrate.run_migrations(engine)
    assert {"is_bench", "bench_order", "subbed_in", "subbed_out",
            "subbed_for_entry_id"} <= _cols(engine, "weekly_roster_entries")
    assert "substitutions_at" in _cols(engine, "weeks")


def test_migration_029_existing_rows_remain_active_non_substituted(db):
    """Existing weekly_roster_entries rows read is_bench=0, subbed_in=0, subbed_out=0
    after migration 029, and existing weeks have no substitutions-run timestamp."""
    engine = _legacy_engine()
    migrate.run_migrations(engine)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT is_bench, subbed_in, subbed_out, bench_order, "
                                "subbed_for_entry_id FROM weekly_roster_entries")).one()
        assert tuple(row) == (0, 0, 0, None, None)
        assert conn.execute(text("SELECT substitutions_at FROM weeks")).scalar() is None


def test_migration_029_is_registered_and_idempotent(db):
    """029_weekly_roster_entries_substitution is in migrate.MIGRATIONS after 028, and
    running run_migrations twice does not fail or duplicate columns."""
    ids = [m[0] for m in migrate.MIGRATIONS]
    assert "029_weekly_roster_entries_substitution" in ids
    assert ids.index("029_weekly_roster_entries_substitution") > ids.index("028_users_session_version")
    engine = _legacy_engine()
    migrate.run_migrations(engine)
    migrate.run_migrations(engine)
    with engine.connect() as conn:
        migrate._m029_weekly_roster_entries_substitution(conn)  # re-run the body directly
        names = [r[1] for r in conn.execute(text("PRAGMA table_info(weekly_roster_entries)")).fetchall()]
    assert names.count("is_bench") == 1 and names.count("subbed_for_entry_id") == 1


# ---------------------------------------------------------------------------
# Story 2: Automatic Substitution After the Week
# ---------------------------------------------------------------------------

DELAY = 24 * 3600


def test_due_substitutions_runs_after_delay(db, monkeypatch):
    """SUBSTITUTION_DELAY_HOURS (default 24) after a locked week's end_time,
    due_substitutions runs that week's substitutions for every user."""
    monkeypatch.delenv("SUBSTITUTION_DELAY_HOURS", raising=False)
    _seed(db, cards=[(1, 1, A, True, 0), (2, 1, B, True, 1), (3, 1, C, False, 0),
                     (7, 2, B, True, 0), (8, 2, D, False, 0)], extra_users=[(2, "bob")])
    with _at(WEEK_END + DELAY):
        assert weeks.due_substitutions(db) == 1
    assert db.get(Week, 1).substitutions_at == WEEK_END + DELAY
    assert _flags(db, user_id=1)[3] == (True, False)
    assert _flags(db, user_id=2)[8] == (True, False)


def test_due_substitutions_skips_week_before_delay(db, monkeypatch):
    """Before end_time + delay (e.g. end_time + 23h59m with the default), no
    substitutions are made and the week is not marked as run."""
    monkeypatch.delenv("SUBSTITUTION_DELAY_HOURS", raising=False)
    _seed(db)
    with _at(WEEK_END + DELAY - 60):
        assert weeks.due_substitutions(db) == 0
    assert db.get(Week, 1).substitutions_at is None
    assert all(f == (False, False) for f in _flags(db).values())
    assert not _audits(db, "weekly_substitutions")


def test_due_substitutions_skips_unlocked_week(db):
    """A week that is not locked is never picked, even long after its end_time."""
    _seed(db, lock=False)
    with _at(WEEK_END + 100 * DELAY):
        assert weeks.due_substitutions(db) == 0
    assert db.get(Week, 1).substitutions_at is None


def test_due_substitutions_runs_once_per_week(db):
    """After a week's substitutions run, its substitutions-run timestamp is set and a
    second due_substitutions call does not run it again (no second audit entry)."""
    _seed(db)
    with _at(WEEK_END + DELAY):
        assert weeks.due_substitutions(db) == 1
    with _at(WEEK_END + 2 * DELAY):
        assert weeks.due_substitutions(db) == 0
    assert db.get(Week, 1).substitutions_at == WEEK_END + DELAY
    assert len(_audits(db, "weekly_substitutions")) == 1


def test_substitution_delay_hours_default_and_override(db, monkeypatch):
    """With SUBSTITUTION_DELAY_HOURS unset the delay is 24 hours; setting it (e.g. 2)
    changes when the week becomes due."""
    monkeypatch.delenv("SUBSTITUTION_DELAY_HOURS", raising=False)
    assert weeks.substitution_delay_hours() == 24
    _seed(db)
    monkeypatch.setenv("SUBSTITUTION_DELAY_HOURS", "2")
    with _at(WEEK_END + 2 * 3600 - 1):
        assert weeks.due_substitutions(db) == 0
    with _at(WEEK_END + 2 * 3600):
        assert weeks.due_substitutions(db) == 1


def test_run_substitutions_replaces_non_playing_active_with_first_playing_bench(db):
    """Canonical case: active A (played), B (0 matches), bench C, D (both played):
    B is marked subbed_out, C subbed_in, D untouched, A untouched."""
    _seed(db)
    assert _sub(db) == 1
    assert _flags(db) == {1: (False, False), 2: (False, True), 3: (True, False), 4: (False, False)}
    e = _entries(db)
    assert e[3].subbed_for_entry_id == e[2].id


def test_run_substitutions_skips_bench_card_whose_player_did_not_play(db):
    """Bench C didn't play but D did: D comes in for B, C stays on the bench."""
    _seed(db, matches=[(1, 100, {A: (5, 2, 437), D: (6, 0, 512)})])
    _sub(db)
    f = _flags(db)
    assert f[3] == (False, False) and f[4] == (True, False) and f[2] == (False, True)


def test_run_substitutions_checks_active_cards_in_slot_order(db):
    """Active cards are checked in roster slot order: with two non-playing active cards
    and one eligible bench card, the earlier slot's card gets the substitute."""
    # card 9 (E, slot 0) and card 2 (B, slot 1) both didn't play; card id order is reversed
    _seed(db, cards=[(2, 1, B, True, 1), (9, 1, E, True, 0), (3, 1, C, False, 0)])
    _sub(db)
    e = _entries(db)
    assert e[3].subbed_in and e[3].subbed_for_entry_id == e[9].id
    assert e[9].subbed_out and e[2].subbed_out


def test_run_substitutions_bench_card_subbed_in_only_once(db):
    """Two non-playing active cards and bench C, D (both played): C replaces the first,
    D the second; no bench card is used twice."""
    _seed(db, cards=[(2, 1, B, True, 0), (9, 1, E, True, 1), (3, 1, C, False, 0), (4, 1, D, False, 1)])
    assert _sub(db) == 2
    e = _entries(db)
    assert e[3].subbed_for_entry_id == e[2].id
    assert e[4].subbed_for_entry_id == e[9].id


def test_run_substitutions_skips_bench_duplicate_of_counted_player(db):
    """A bench card of a player already counted on that week's roster (same player as a
    playing active card, or already subbed in) is skipped; the next eligible one comes in."""
    # bench: A again (duplicate of active), C, C again (duplicate of a subbed-in card), D
    _seed(db, cards=[(1, 1, A, True, 0), (2, 1, B, True, 1), (9, 1, E, True, 2),
                     (10, 1, A, False, 0), (3, 1, C, False, 1), (11, 1, C, False, 2),
                     (4, 1, D, False, 3)])
    assert _sub(db) == 2
    f = _flags(db)
    assert f[10] == (False, False)
    assert f[3] == (True, False)
    assert f[11] == (False, False)
    assert f[4] == (True, False)


def test_run_substitutions_no_eligible_bench_card_leaves_slot_without_points(db):
    """If no bench card qualifies, the active card is still marked subbed_out, nothing
    is subbed in, and the week total is unchanged (the slot scored nothing anyway)."""
    _seed(db, cards=[(1, 1, A, True, 0), (2, 1, B, True, 1), (9, 1, E, False, 0)])
    before = _week_total(db)
    assert _sub(db) == 0
    f = _flags(db)
    assert f[2] == (False, True) and f[9] == (False, False)
    assert _week_total(db) == before


def test_run_substitutions_never_replaces_player_who_played(db):
    """Decision: an active card whose player played at least one scored match is never
    replaced, even with 0 or negative points and a high-scoring bench card available."""
    _seed(db, cards=[(1, 1, A, True, 0), (3, 1, C, False, 0)],
          matches=[(1, 100, {A: (0, 20, 0), C: (20, 0, 900)})])
    assert _card_week_pts(db, 1) <= 0 < _card_week_pts(db, 3)
    assert _sub(db) == 0
    assert _flags(db) == {1: (False, False), 3: (False, False)}


def test_run_substitutions_does_not_fill_empty_roster_slots(db):
    """Decision: a user with fewer than 5 active cards (all played) and playing bench
    cards gets no subbed_in entries; empty slots stay empty."""
    _seed(db, cards=[(1, 1, A, True, 0), (3, 1, C, False, 0), (4, 1, D, False, 1)])
    assert _sub(db) == 0
    assert not any(i for i, _ in _flags(db).values())


def test_run_substitutions_user_with_no_active_cards_gets_no_substitutes(db):
    """Decision: a user whose snapshot holds only bench entries (empty roster) gets no
    subbed_in entries and scores 0 for the week."""
    _seed(db, cards=[(3, 1, C, False, 0), (4, 1, D, False, 1)])
    assert _sub(db) == 0
    assert not any(i for i, _ in _flags(db).values())
    assert _week_total(db) == 0


def test_run_substitutions_week_without_bench_snapshot_makes_no_substitutions(db):
    """Decision: a week locked before this release (entries all is_bench=0, no bench
    rows) makes no subbed_in entries and its totals are unchanged."""
    _seed(db, lock=False)
    db.add(WeeklyRosterEntry(week_id=1, user_id=1, card_id=1))
    db.add(WeeklyRosterEntry(week_id=1, user_id=1, card_id=2))
    db.get(Week, 1).is_locked = True
    db.commit()
    before = (_week_total(db), _season_total(db))
    assert _sub(db) == 0
    assert all(f == (False, False) for f in _flags(db).values())
    assert (_week_total(db), _season_total(db)) == before


def test_run_substitutions_excluded_match_does_not_count_as_played(db):
    """A player whose only match in the window is excluded_from_scoring counts as not
    played: the active card is subbed out, and as a bench card it is not eligible."""
    # B's only match is excluded (active, so subbed out); E's only match is excluded
    # (bench, first in order, so skipped in favour of C).
    _seed(db, cards=[(1, 1, A, True, 0), (2, 1, B, True, 1), (9, 1, E, False, 0), (3, 1, C, False, 1)],
          matches=_MATCHES + [(3, 300, {B: (9, 0, 600), E: (9, 0, 600)})])
    db.get(Match, 3).excluded_from_scoring = True
    db.commit()
    _sub(db)
    f = _flags(db)
    assert f[2] == (False, True)
    assert f[9] == (False, False)
    assert f[3] == (True, False)


def test_run_substitutions_respects_week_override_id(db):
    """A match whose week_override_id points at the week counts as played even if its
    start_time is outside the window; one overridden to another week does not."""
    # B's only match is at 5000 but overridden into week 1 -> B played.
    # C's only match is at 300 (in window) but overridden to week 2 -> C did not play.
    _seed(db, lock=False, matches=[(1, 100, {A: (5, 2, 437), D: (6, 0, 512)})])
    _add_match(db, 3, 5000, {B: (3, 3, 400)}, week_override_id=1)
    _add_match(db, 4, 300, {C: (3, 3, 400)}, week_override_id=2)
    db.commit()
    card_points.rebuild_all(db)
    _lock(db, 1)
    assert _sub(db) == 0
    assert _flags(db)[2] == (False, False)
    # Now make B not play in week 1: C (overridden away) is skipped, D comes in.
    db.get(Match, 3).week_override_id = 2
    db.commit()
    _sub(db)
    f = _flags(db)
    assert f[2] == (False, True) and f[3] == (False, False) and f[4] == (True, False)


def test_run_substitutions_returns_count_and_writes_audit_entry(db):
    """run_substitutions returns the number of substitutions made, and each run writes
    one `weekly_substitutions` AuditLog entry for the week with that number."""
    _seed(db)
    assert _sub(db) == 1
    rows = _audits(db, "weekly_substitutions")
    assert len(rows) == 1
    assert "id=1" in rows[0].detail and "substitutions=1" in rows[0].detail
    _sub(db)
    assert len(_audits(db, "weekly_substitutions")) == 2


def test_run_substitutions_is_deterministic_on_rerun(db):
    """Running it again for a week with no data changes gives the same subbed_in /
    subbed_out flags and the same count."""
    _seed(db)
    n1 = _sub(db)
    f1 = _flags(db)
    pairs1 = {c: e.subbed_for_entry_id for c, e in _entries(db).items()}
    n2 = _sub(db)
    assert n1 == n2 and f1 == _flags(db)
    assert pairs1 == {c: e.subbed_for_entry_id for c, e in _entries(db).items()}


def test_run_substitutions_only_touches_its_own_week(db):
    """Running substitutions for one week leaves other weeks' roster entries unchanged."""
    _seed(db)
    _lock(db, 2)  # nobody played in week 2: B and A would both be subbed out there
    _sub(db, week_id=1)
    assert all(f == (False, False) for f in _flags(db, week_id=2).values())
    assert db.get(Week, 2).substitutions_at is None


def test_week_maintenance_loop_runs_substitutions_before_weekly_summaries():
    """main.py's week maintenance loop calls the due-substitutions step before
    generate_weekly_summaries (source inspection only; main is not imported)."""
    src = _read("backend/main.py")
    body = src[src.index("def _week_maintenance_loop"):]
    body = body[:body.index("\ndef ", 1)]
    assert "due_substitutions(db)" in body
    assert body.index("auto_lock_weeks(db)") < body.index("due_substitutions(db)") \
        < body.index("generate_weekly_summaries(db)")


# ---------------------------------------------------------------------------
# Story 3: Points Count the Substituted Roster
# ---------------------------------------------------------------------------

def test_build_roster_response_locked_week_uses_substituted_roster(db):
    """My Team for a substituted locked week: combined_value = A + C (B and D excluded)."""
    _seed(db)
    _sub(db)
    r = _build_roster_response(db, 1, 1)
    assert r["combined_value"] == pytest.approx(_card_week_pts(db, 1) + _card_week_pts(db, 3))


def test_build_roster_response_season_points_use_substituted_roster(db):
    """My Team's season_points sums only counted entries (A + C for the substituted week)."""
    _seed(db)
    _sub(db)
    r = _build_roster_response(db, 1, 1)
    assert r["season_points"] == pytest.approx(_card_week_pts(db, 1) + _card_week_pts(db, 3))


def test_weekly_leaderboard_uses_substituted_roster(db):
    """weekly_leaderboard week_points for the user equal A + C after substitution."""
    _seed(db)
    _sub(db)
    assert _week_total(db) == pytest.approx(round(_card_week_pts(db, 1) + _card_week_pts(db, 3), 2))


def test_season_standings_use_substituted_roster(db):
    """compute_season_standings (End Season) and season_leaderboard both count A + C
    for the substituted week."""
    _seed(db)
    _sub(db)
    expected = round(_card_week_pts(db, 1) + _card_week_pts(db, 3), 2)
    assert _season_total(db) == pytest.approx(expected)
    assert {r["id"]: r["season_points"] for r in season_leaderboard(db=db)}[1] == pytest.approx(expected)


def test_all_readers_agree_after_substitution(db):
    """After substitution, My Team combined_value, weekly leaderboard week_points and the
    season totals (single locked week) are equal for every user."""
    _seed(db, cards=[(1, 1, A, True, 0), (2, 1, B, True, 1), (3, 1, C, False, 0),
                     (7, 2, B, True, 0), (8, 2, D, False, 0), (12, 2, C, True, 1)],
          extra_users=[(2, "bob")])
    _sub(db)
    weekly = {r["id"]: r["week_points"] for r in weekly_leaderboard(week_id=1, db=db)}
    season = {r["id"]: r["points"] for r in compute_season_standings(db)}
    for uid in (1, 2):
        r = _build_roster_response(db, uid, 1)
        assert round(r["combined_value"], 2) == pytest.approx(weekly[uid])
        assert round(r["season_points"], 2) == pytest.approx(season[uid])
        assert weekly[uid] == pytest.approx(season[uid])
    assert weekly[2] == pytest.approx(round(_card_week_pts(db, 8) + _card_week_pts(db, 12), 2))


def test_totals_unchanged_before_substitution_runs(db):
    """Before substitution runs for a week, every reader's totals are exactly the totals
    of the active entries only (as today), even with bench entries saved."""
    _seed(db)
    active_only = _card_week_pts(db, 1) + _card_week_pts(db, 2)
    assert _build_roster_response(db, 1, 1)["combined_value"] == pytest.approx(active_only)
    assert _week_total(db) == pytest.approx(round(active_only, 2))
    assert _season_total(db) == pytest.approx(round(active_only, 2))


def test_substitution_does_not_change_stored_card_points(db):
    """run_substitutions and a re-run leave card_match_points rows unchanged (#141)."""
    _seed(db)

    def stored():
        return sorted(db.execute(select(CardMatchPoints.card_id, CardMatchPoints.match_id,
                                        CardMatchPoints.points)).all())
    before = stored()
    assert before
    _sub(db)
    _sub(db)
    assert stored() == before


def test_counting_rule_lives_in_one_shared_sql_helper():
    """A shared SQL helper next to scored_match_sql() in match_scoring.py holds the
    counting condition, and routers/cards.py and routers/leaderboard.py use it rather
    than repeating the condition inline."""
    import match_scoring
    cond = match_scoring.counted_roster_entry_sql("x")
    assert "x.is_bench" in cond and "x.subbed_out" in cond and "x.subbed_in" in cond
    for rel in ("backend/routers/cards.py", "backend/routers/leaderboard.py",
                "backend/routers/weekly_summary.py"):
        src = _read(rel)
        assert "counted_roster_entry_sql(" in src, rel
        assert not re.search(r"subbed_out\s*=\s*0", src), rel
        assert not re.search(r"is_bench\s*=\s*0", src), rel


# ---------------------------------------------------------------------------
# Story 4: See What Was Substituted
# ---------------------------------------------------------------------------

@pytest.fixture
def http_env():
    """Minimal app with the auth, cards and admin_weeks routers on a StaticPool engine."""
    import rate_limit
    from database import get_db
    from routers import auth as auth_router
    from routers import cards as cards_router

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    modules = (auth_router, cards_router, admin_weeks)
    limiters = {id(rate_limit.limiter): rate_limit.limiter}
    for m in modules:
        if hasattr(m, "limiter"):
            limiters[id(m.limiter)] = m.limiter
    was_enabled = {k: lim.enabled for k, lim in limiters.items()}
    for lim in limiters.values():
        lim.enabled = False
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="t" * 40)
    app.state.limiter = rate_limit.limiter
    for m in modules:
        app.include_router(m.router)
    app.dependency_overrides[get_db] = _override_get_db

    s = Session()
    _seed(s, extra_users=[(2, "bob")])
    s.add(User(id=99, username="admin", email="admin@test", password_hash=hash_password(_PASSWORD),
               is_admin=True, tokens=0))
    s.commit()
    s.close()

    def login(username):
        client = TestClient(app)
        resp = client.post("/login", json={"username": username, "password": _PASSWORD})
        assert resp.status_code == 200, resp.text
        return client

    try:
        yield {"app": app, "Session": Session, "login": login}
    finally:
        for k, lim in limiters.items():
            lim.enabled = was_enabled[k]
        engine.dispose()


def test_get_roster_returns_substitution_flags(http_env):
    """GET /roster/{user_id}?week_id=... returns subbed_in / subbed_out per card and
    substitutions_done=true for a substituted week; C is in `active` with subbed_in, B in
    `bench` with subbed_out."""
    s = http_env["Session"]()
    _sub(s)
    s.close()
    data = http_env["login"]("alice").get("/roster/1?week_id=1").json()
    assert data["substitutions_done"] is True
    assert data["week"]["substitutions_done"] is True
    active = {c["id"]: c for c in data["active"]}
    bench = {c["id"]: c for c in data["bench"]}
    assert set(active) == {1, 3} and set(bench) == {2, 4}
    assert active[3]["subbed_in"] is True and active[3]["subbed_out"] is False
    assert bench[2]["subbed_out"] is True and bench[2]["subbed_in"] is False
    assert active[1]["subbed_in"] is False and bench[4]["subbed_out"] is False
    assert [c["id"] for c in data["bench"]] == [2, 4]  # subbed-out cards lead the bench


def test_get_roster_subbed_in_card_identifies_replaced_player(db):
    """The subbed-in card carries the replaced card's player name (for the
    "Subbed in for {player}" label)."""
    _seed(db)
    _sub(db)
    r = _build_roster_response(db, 1, 1)
    c = {x["id"]: x for x in r["active"]}[3]
    assert c["subbed_in_for"] == f"P{B}"
    assert c["slot_index"] == 1  # shown in the replaced card's slot
    assert all(x["subbed_in_for"] is None for x in r["active"] + r["bench"] if x["id"] != 3)


def test_get_roster_before_substitution_reports_not_done(db):
    """For a locked week whose substitutions haven't run, substitutions_done is false and
    every card has subbed_in = subbed_out = false."""
    _seed(db)
    r = _build_roster_response(db, 1, 1)
    assert r["substitutions_done"] is False and r["week"]["substitutions_done"] is False
    assert r["substitution_delay_hours"] == weeks.substitution_delay_hours()
    assert all(not c["subbed_in"] and not c["subbed_out"] for c in r["active"] + r["bench"])


def test_get_roster_other_users_roster_still_forbidden(db):
    """A non-admin requesting another user's roster with week_id still gets 403."""
    _seed(db, extra_users=[(2, "bob")])
    with pytest.raises(HTTPException) as exc:
        get_roster(1, week_id=1, db=db, current_user={"user_id": 2, "username": "bob"})
    assert exc.value.status_code == 403


def test_frontend_roster_shows_subbed_in_and_did_not_play_labels():
    """frontend/app-roster.js renders "Subbed in for" on subbed-in cards and
    "Did not play" on subbed-out cards."""
    src = _read("frontend/app-roster.js")
    assert "Subbed in for" in src and "Did not play" in src
    assert "_escHtml(c.subbed_in_for)" in src
    assert "c.subbed_in" in src and "c.subbed_out" in src


def test_frontend_roster_shows_pending_substitution_note():
    """frontend/app-roster.js shows "Substitutions are made {N} hours after the week ends"
    under a locked week's roster when substitutions_done is false."""
    src = _read("frontend/app-roster.js")
    assert "Substitutions are made ${hours} hours after the week ends" in src
    assert "substitutions_done" in src and "substitution_delay_hours" in src
    assert 'id="rosterSubsNote"' in _read("frontend/index.html")


def test_how_to_play_explains_bench_substitution():
    """frontend/index.html's How to Play Users subtab has one bullet under
    Roster & Weekly Lock explaining substitution: bench order matters, left first."""
    html = _read("frontend/index.html")
    section = html[html.index("Roster &amp; Weekly Lock"):]
    section = section[:section.index("</ul>")]
    bullets = [b for b in re.findall(r"<li>(.*?)</li>", section, re.S) if "substitution" in b.lower()]
    assert len(bullets) == 1
    assert "Bench order matters" in bullets[0] and "leftmost" in bullets[0]


# ---------------------------------------------------------------------------
# Story 5: Admin Re-Run
# ---------------------------------------------------------------------------

def test_admin_rerun_substitutions_resets_and_recomputes(db):
    """POST /admin/weeks/{week_id}/substitutions resets subbed_in / subbed_out and runs
    again: after moving a match of B's player into the week, B counts and C is no
    longer subbed in."""
    _seed(db)
    _sub(db)
    assert _flags(db)[3] == (True, False)
    _add_match(db, 3, 5000, {B: (4, 1, 450)}, week_override_id=1)
    db.commit()
    card_points.rebuild_all(db)
    admin_weeks.rerun_substitutions(1, db=db, admin=_ADMIN)
    assert _flags(db) == {1: (False, False), 2: (False, False), 3: (False, False), 4: (False, False)}
    assert _entries(db)[3].subbed_for_entry_id is None
    assert _week_total(db) == pytest.approx(round(_card_week_pts(db, 1) + _card_week_pts(db, 2), 2))


def test_admin_rerun_substitutions_returns_count(db):
    """The re-run returns the number of substitutions made."""
    _seed(db)
    assert admin_weeks.rerun_substitutions(1, db=db, admin=_ADMIN)["substitutions"] == 1


def test_admin_rerun_substitutions_writes_audit_entry(db):
    """The re-run writes an `admin_substitutions_rerun` AuditLog entry naming the admin
    and the week."""
    _seed(db)
    admin_weeks.rerun_substitutions(1, db=db, admin=_ADMIN)
    rows = _audits(db, "admin_substitutions_rerun")
    assert len(rows) == 1
    assert rows[0].actor_id == 99 and rows[0].actor_username == "admin"
    assert "id=1" in rows[0].detail and "Week 1" in rows[0].detail


def test_admin_rerun_substitutions_409_for_unlocked_week(db):
    """Returns 409 for a week that isn't locked; no roster entries change."""
    _seed(db)
    before = _flags(db, week_id=2)
    with pytest.raises(HTTPException) as exc:
        admin_weeks.rerun_substitutions(2, db=db, admin=_ADMIN)
    assert exc.value.status_code == 409
    assert _flags(db, week_id=2) == before
    assert not _audits(db, "admin_substitutions_rerun")


def test_admin_rerun_substitutions_409_before_substitution_time(db, monkeypatch):
    """Returns 409 for a locked week whose end_time + delay hasn't been reached."""
    monkeypatch.delenv("SUBSTITUTION_DELAY_HOURS", raising=False)
    _seed(db)
    with _at(WEEK_END + DELAY - 1), pytest.raises(HTTPException) as exc:
        admin_weeks.rerun_substitutions(1, db=db, admin=_ADMIN)
    assert exc.value.status_code == 409
    assert all(f == (False, False) for f in _flags(db).values())


def test_admin_rerun_substitutions_404_for_unknown_week(db):
    """Returns 404 for a week id that doesn't exist."""
    _seed(db)
    with pytest.raises(HTTPException) as exc:
        admin_weeks.rerun_substitutions(424242, db=db, admin=_ADMIN)
    assert exc.value.status_code == 404


def test_admin_rerun_substitutions_requires_admin(http_env):
    """Over HTTP: anonymous gets 401 and a logged-in non-admin gets 403."""
    assert TestClient(http_env["app"]).post("/admin/weeks/1/substitutions").status_code == 401
    assert http_env["login"]("bob").post("/admin/weeks/1/substitutions").status_code == 403


def test_admin_rerun_substitutions_needs_no_reauth(http_env):
    """Over HTTP: a logged-in admin who has not called POST /reauth can re-run (the
    endpoint is not destructive)."""
    resp = http_env["login"]("admin").post("/admin/weeks/1/substitutions")
    assert resp.status_code == 200, resp.text
    assert resp.json()["substitutions"] == 1


def test_frontend_admin_weeks_has_rerun_substitutions_action():
    """frontend/app-admin-weeks.js offers "Re-run substitutions" on finished weeks and
    calls POST /admin/weeks/{id}/substitutions through adminFetch."""
    src = _read("frontend/app-admin-weeks.js")
    assert "Re-run substitutions" in src
    assert "w.substitutions_due" in src
    assert re.search(r"adminFetch\(`\$\{API\}/admin/weeks/\$\{weekId\}/substitutions`,\s*\{\s*method:\s*\"POST\"", src)
    assert "confirm(" not in src.split("async function rerunWeekSubstitutions")[1].split("\n}\n")[0]


def test_env_example_documents_substitution_delay_hours():
    """.env.example lists SUBSTITUTION_DELAY_HOURS with its default of 24."""
    assert re.search(r"^#?\s*SUBSTITUTION_DELAY_HOURS=24\s*$", _read(".env.example"), re.M)


# ---------------------------------------------------------------------------
# Gaps decided during implementation (Weekly Report, admin roster_count, demo
# mode, leaderboard card lists — see the plan's Critical Files)
# ---------------------------------------------------------------------------

def _summary_players(summary):
    found = []

    def walk(x):
        if isinstance(x, dict):
            if "on_roster" in x:
                found.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(summary)
    return found


def test_weekly_report_on_roster_uses_counting_rule(db):
    """The Weekly Report marks a saved bench player as on_roster only once subbed in."""
    _seed(db)
    on = lambda: {p["player_id"] for p in _summary_players(  # noqa: E731
        _build_week_summary(db, db.get(Week, 1), True, 1)) if p["on_roster"]}
    assert on() == {A}
    _sub(db)
    assert on() == {A, C}


def test_admin_weeks_roster_count_counts_active_entries_only(db):
    """GET /admin/weeks roster_count ignores saved bench rows."""
    _seed(db)
    rows = {w["id"]: w for w in admin_weeks.list_weeks_admin(db=db, _=_ADMIN)}
    assert rows[1]["roster_count"] == 2
    assert rows[1]["substitutions_due"] is True and rows[1]["substitutions_at"] is None
    assert rows[2]["substitutions_due"] is False


def test_demo_clock_runs_due_substitutions_before_summaries(db, monkeypatch):
    """Setting the demo clock runs due substitutions synchronously, before the Weekly
    Report pass."""
    from routers.admin_demo import DemoClockBody, set_demo_clock
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("SUBSTITUTION_DELAY_HOURS", raising=False)
    _seed(db)
    set_demo_clock(DemoClockBody(timestamp=WEEK_END + DELAY), db=db, admin=_ADMIN)
    assert db.get(Week, 1).substitutions_at == WEEK_END + DELAY
    assert _flags(db)[3] == (True, False)
    src = _read("backend/routers/admin_demo.py")
    body = src[src.index("def set_demo_clock"):]
    assert body.index("due_substitutions(db)") < body.index("generate_weekly_summaries(db)")


# ---------------------------------------------------------------------------
# Product decision 2026-10-01: the Weekly Report opens at week end and shows a
# "substitutions pending" note until that week's substitutions have run.
# ---------------------------------------------------------------------------

def test_weekly_report_substitutions_pending_until_run(db, monkeypatch):
    """substitutions_pending is true before the week's substitutions run and false
    after; substitutions_at and substitution_delay_hours come along."""
    monkeypatch.setenv("SUBSTITUTION_DELAY_HOURS", "12")
    _seed(db)
    before = _build_week_summary(db, db.get(Week, 1), True, 1)
    assert before["substitutions_pending"] is True
    assert before["substitutions_at"] is None
    assert before["substitution_delay_hours"] == 12
    with _at(WEEK_END + 12 * 3600):
        _sub(db)
    after = _build_week_summary(db, db.get(Week, 1), True, 1)
    assert after["substitutions_pending"] is False
    assert after["substitutions_at"] == db.get(Week, 1).substitutions_at


def test_weekly_report_frontend_shows_substitutions_pending_note():
    """The Weekly Report renders the pending note via textContent from the response
    fields, without confirm()/prompt()."""
    src = _read("frontend/app-weekly-summary.js")
    assert "data.substitutions_pending" in src
    assert "Bench substitutions are made ${data.substitution_delay_hours} hours after the week ends; roster marks may change." in src
    body = src[src.index("function renderWeeklySummaryContent"):]
    body = body[:body.index("\n}\n")]
    assert "note.textContent" in body
    assert "confirm(" not in src and "prompt(" not in src
