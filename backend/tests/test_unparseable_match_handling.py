"""Acceptance-criterion stubs for markdown/plans/plan-unparseable-match-handling.md.

Covers four user stories:

  Story: See When a Match Score Is Partial
    - GET /players/{id} match history carries parse_status and excluded_from_scoring
    - Excluded matches stay listed in match history (flagged, not dropped)
    - Static JS check: frontend/app-players.js renders "Partial stats" / "Not scored"

  Story: Track Parse Status in the Admin Match Table
    - GET /admin/matches includes parse_status and excluded_from_scoring
    - POST /admin/matches/{id}/retry-parse: refreshed path, requested path, cooldown,
      404 unknown match, 409 when INGEST_LOCK is held, audit `admin_match_retry_parse`,
      admin-only

  Story: Mark a Match Unparseable and Choose How It Scores
    - PATCH /admin/matches/{id}/scoring sets flags, audits old/new as
      `admin_match_scoring`, clearing restores behaviour, admin-only, 404 unknown
    - Unparseable matches are skipped by find_unparsed_match_ids()/retry pass
    - Excluded match removes exactly its points from: weekly leaderboard, season
      leaderboard, roster leaderboard, roster card points (_build_roster_response),
      weekly summary points, card_draw proportionality

  Story: Flag Stuck Matches Automatically
    - retry_unparsed_matches() marks still-unparsed matches older than the retry window
      as unparseable, audits `match_marked_unparseable`, never sets excluded_from_scoring

  Plus schema/ingest plumbing:
    - Migration 027_match_parse_status adds both columns and backfills parse_status
    - ingest_match() / refresh_match_stats() set parse_status from _is_unparsed(data)

Conventions (copied from test_opendota_parse_retry.py and test_issue_132_admin_db_backup.py):
  - Never hit the network. Monkeypatch ``ingest.opendota_get_json`` and
    ``ingest.opendota_post_json`` with lambdas returning canned payloads (a parsed payload
    has ``"version": 21``; an unparsed one has ``"version": None``).
  - Reset module state: ``monkeypatch.setattr(ingest, "_parse_requested", {})`` before any
    test touching request_parse()/cooldown.
  - ``retry_unparsed_matches()`` opens its own session: patch
    ``monkeypatch.setattr(ingest, "SessionLocal", lambda: db)``.
  - Endpoint tests call router functions directly, passing every Depends argument
    explicitly (``db=db, _=_ADMIN`` / ``admin=_ADMIN``).
  - 403: ``require_admin({"user_id": 2, "username": "u", "is_admin": False}, db=db)`` raises
    HTTPException(403); also assert the route declares Depends(require_admin) by inspecting
    ``admin_matches.router.routes`` so the guard can't be dropped silently.
  - 409: acquire ``ingest.INGEST_LOCK`` in the test and release it in ``finally``.
  - Exclusion fixtures: one parsed + one unparsed match for the same two players in the
    same week; exclude the unparsed one and assert each aggregate drops by exactly that
    match's points (and nothing else).

Manual verification (not automated):
  - Player popup marker tooltip text renders and is readable; points show as a dash
    for excluded matches; parsed matches show no marker.
  - Admin Matches Parse column shows Parsed / Unparsed / Unparseable; Retry parse button
    only on unparsed rows; table refreshes after retry and shows which outcome happened.
  - Scoring-flag edit control on each admin row; "Unparseable only" filter works.
  - Excluded match still appears in schedules and match lists labelled "Not scored".
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

import card_draw
import ingest  # noqa: F401
import migrate
from database import Base
from deps import require_admin  # noqa: F401
from migrate import run_migrations
from models import (  # noqa: F401 — registers tables on Base for the db fixture
    AuditLog, Card, League, Match, Player, PlayerMatchStats, Team, User, Week, Weight,
    WeeklyRosterEntry,
)
from routers import admin_matches  # noqa: F401
from routers.cards import _build_roster_response
from routers.leaderboard import (
    compute_season_standings, leaderboard, roster_leaderboard, top_performances,
    weekly_leaderboard,
)
from routers.players import get_player
from routers.weekly_summary import _build_week_summary
from scoring import fantasy_score

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
_ADMIN = {"user_id": 1, "username": "admin"}
_NOW = int(time.time())
_HOUR = 3600

_PARSED_MATCH = 9001
_UNPARSED_MATCH = 9002

_SCORING_WEIGHTS = {
    "kills": 1.0, "obs_placed": 0.5, "stuns": 0.1, "teamfight_participation": 2.0,
    "death_pool": 3.0, "death_deduction": 0.5, "mvp_bonus_pct": 10.0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_scoring(db):
    """Two users (alice id 10 holding player 101, bob id 11 holding player 102) with
    both cards on the locked Week 1 roster. Both players play parsed match 9001 and
    signature-zero match 9002 (player 101 is MVP there, so the MVP queries are exercised)."""
    for key, value in _SCORING_WEIGHTS.items():
        db.add(Weight(key=key, label=key, value=value))
    db.add(User(id=10, username="alice", email="a@test", password_hash="x", tokens=0))
    db.add(User(id=11, username="bob", email="b@test", password_hash="x", tokens=0))
    db.add(Team(id=1, name="Radiant"))
    db.add(Team(id=2, name="Dire"))
    db.add(Player(id=101, name="P101"))
    db.add(Player(id=102, name="P102"))
    db.add(Card(id=1, player_id=101, owner_id=10, card_type="common", is_active=True, slot_index=0))
    db.add(Card(id=2, player_id=102, owner_id=11, card_type="rare", is_active=True, slot_index=0))
    db.add(Week(id=1, label="Week 1", start_time=0, end_time=999999, is_locked=True))
    db.add(WeeklyRosterEntry(week_id=1, user_id=10, card_id=1))
    db.add(WeeklyRosterEntry(week_id=1, user_id=11, card_id=2))

    db.add(Match(match_id=_PARSED_MATCH, radiant_team_id=1, dire_team_id=2, start_time=500,
                 radiant_win=True, parse_status="parsed"))
    db.add(PlayerMatchStats(player_id=101, match_id=_PARSED_MATCH, team_id=1, fantasy_points=12.0,
                            kills=4, deaths=1, obs_placed=3, stuns=10.0, teamfight_participation=0.5))
    db.add(PlayerMatchStats(player_id=102, match_id=_PARSED_MATCH, team_id=2, fantasy_points=6.0,
                            kills=2, deaths=2, obs_placed=0, stuns=5.0, teamfight_participation=0.4))

    db.add(Match(match_id=_UNPARSED_MATCH, radiant_team_id=1, dire_team_id=2, start_time=600,
                 radiant_win=False, parse_status="unparsed"))
    db.add(PlayerMatchStats(player_id=101, match_id=_UNPARSED_MATCH, team_id=1, fantasy_points=4.4,
                            kills=1, deaths=0, obs_placed=0, stuns=0.0, teamfight_participation=0.0,
                            is_mvp=True))
    db.add(PlayerMatchStats(player_id=102, match_id=_UNPARSED_MATCH, team_id=2, fantasy_points=5.5,
                            kills=3, deaths=1, obs_placed=0, stuns=0.0, teamfight_participation=0.0))
    db.commit()


def _set_excluded(db, match_id, value):
    db.get(Match, match_id).excluded_from_scoring = value
    db.commit()


def _delete_stats(db, match_id):
    for row in db.query(PlayerMatchStats).filter_by(match_id=match_id).all():
        db.delete(row)
    db.commit()


def _assert_exclusion_removes_exactly_that_match(db, measure):
    """Excluding the unparsed match gives the same numbers as deleting its stat rows
    (so exactly its contribution disappears), differs from the baseline, and clearing
    the flag restores the baseline."""
    _seed_scoring(db)
    before = measure(db)
    _set_excluded(db, _UNPARSED_MATCH, True)
    excluded = measure(db)
    _set_excluded(db, _UNPARSED_MATCH, False)
    restored = measure(db)
    _delete_stats(db, _UNPARSED_MATCH)
    removed = measure(db)

    assert excluded == pytest.approx(removed)
    assert excluded != pytest.approx(before)
    assert restored == pytest.approx(before)


def _weekly(db):
    return {r["username"]: r["week_points"] for r in weekly_leaderboard(week_id=1, db=db)}


def _season(db):
    return {r["username"]: r["points"] for r in compute_season_standings(db)}


def _roster_lb(db):
    return {r["username"]: r["roster_value"] for r in roster_leaderboard(db=db)}


def _roster_cards(db):
    result = _build_roster_response(db, user_id=10, week_id=1)
    return {
        "active": result["active"][0]["total_points"],
        "combined": result["combined_value"],
        "season": result["season_points"],
    }


def _all_aggregates(db):
    return {**{f"w_{k}": v for k, v in _weekly(db).items()},
            **{f"s_{k}": v for k, v in _season(db).items()},
            **{f"r_{k}": v for k, v in _roster_lb(db).items()},
            **{f"c_{k}": v for k, v in _roster_cards(db).items()}}


def _patch_opendota(monkeypatch, payload, post_calls=None):
    get_calls = []

    def _get(url, *a, **k):
        get_calls.append(url)
        return payload

    def _post(url, *a, **k):
        if post_calls is not None:
            post_calls.append(url)
        return {"job": {"jobId": 1}}

    monkeypatch.setattr(ingest, "opendota_get_json", _get)
    monkeypatch.setattr(ingest, "opendota_post_json", _post)
    monkeypatch.setattr(ingest, "_parse_requested", {})
    return get_calls


def _seed_unparsed_match(db, match_id, start_time, parse_status="unparsed"):
    db.add(Match(match_id=match_id, start_time=start_time, radiant_team_id=1, dire_team_id=2,
                 parse_status=parse_status))
    db.add(PlayerMatchStats(player_id=501, match_id=match_id, team_id=1, kills=1, fantasy_points=1.0,
                            teamfight_participation=0.0, stuns=0.0, obs_placed=0))
    db.add(PlayerMatchStats(player_id=502, match_id=match_id, team_id=2, kills=0, fantasy_points=0.0,
                            teamfight_participation=0.0, stuns=0.0, obs_placed=0))
    db.commit()


_PARSED_PAYLOAD = {
    "version": 21, "duration": 2400, "radiant_win": True,
    "radiant_team_id": 1, "dire_team_id": 2,
    "players": [
        {"account_id": 501, "isRadiant": True, "kills": 7, "obs_placed": 4,
         "teamfight_participation": 0.5, "stuns": 12.5},
        {"account_id": 502, "isRadiant": False, "kills": 2, "obs_placed": 0,
         "teamfight_participation": 0.2, "stuns": 0},
    ],
}
_UNPARSED_PAYLOAD = {**_PARSED_PAYLOAD, "version": None}


def _audit_rows(db, action):
    return db.query(AuditLog).filter_by(action=action).all()


def _route(path, method):
    for route in admin_matches.router.routes:
        if getattr(route, "path", None) == path and method in route.methods:
            return route
    raise AssertionError(f"{method} {path} not registered")


def _legacy_matches_engine():
    """Current schema minus the two new matches columns, with three matches:
    1 = signature-zero stats, 2 = parsed stats, 3 = no stats."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE matches DROP COLUMN parse_status"))
        conn.execute(text("ALTER TABLE matches DROP COLUMN excluded_from_scoring"))
        for mid in (1, 2, 3):
            conn.execute(text("INSERT INTO matches (match_id, start_time) VALUES (:m, 100)"), {"m": mid})
        conn.execute(text("""
            INSERT INTO player_match_stats (player_id, match_id, kills, teamfight_participation, stuns, obs_placed)
            VALUES (1, 1, 3, 0, 0, 0), (2, 1, 1, 0, 0, 0),
                   (1, 2, 3, 0.4, 0, 0), (2, 2, 1, 0, 2.5, 1)
        """))
        conn.commit()
    return engine


def _match_statuses(engine):
    with engine.connect() as conn:
        return {r[0]: r[1] for r in conn.execute(
            text("SELECT match_id, parse_status FROM matches ORDER BY match_id")).fetchall()}


# ---------------------------------------------------------------------------
# Schema: migration 027_match_parse_status
# ---------------------------------------------------------------------------

def test_migration_027_adds_parse_status_and_excluded_from_scoring_columns():
    """Migration 027 adds matches.parse_status and matches.excluded_from_scoring (default false) to a legacy DB."""
    engine = _legacy_matches_engine()
    run_migrations(engine)
    with engine.connect() as conn:
        cols = {r[1]: r for r in conn.execute(text("PRAGMA table_info(matches)")).fetchall()}
        assert "parse_status" in cols
        assert "excluded_from_scoring" in cols
        excluded = [r[0] for r in conn.execute(
            text("SELECT excluded_from_scoring FROM matches")).fetchall()]
        assert excluded == [0, 0, 0]
        conn.execute(text("INSERT INTO matches (match_id) VALUES (4)"))
        assert conn.execute(text(
            "SELECT excluded_from_scoring FROM matches WHERE match_id = 4")).scalar() == 0


def test_migration_027_backfills_parse_status_from_unparsed_signature():
    """Backfill sets 'unparsed' for signature-zero matches and 'parsed' for the rest."""
    engine = _legacy_matches_engine()
    run_migrations(engine)
    assert _match_statuses(engine) == {1: "unparsed", 2: "parsed", 3: "parsed"}


def test_migration_027_is_idempotent():
    """Running migrations twice does not fail or overwrite an existing parse_status (e.g. 'unparseable')."""
    engine = _legacy_matches_engine()
    run_migrations(engine)
    with engine.connect() as conn:
        conn.execute(text("UPDATE matches SET parse_status = 'unparseable' WHERE match_id = 1"))
        conn.commit()
    run_migrations(engine)
    with engine.connect() as conn:
        migrate._m027_match_parse_status(conn)  # guarded body re-run directly
    assert _match_statuses(engine) == {1: "unparseable", 2: "parsed", 3: "parsed"}


# ---------------------------------------------------------------------------
# Ingest keeps parse_status current
# ---------------------------------------------------------------------------

def test_ingest_match_sets_parse_status_parsed_for_parsed_payload(db, monkeypatch):
    """ingest_match() with a payload whose version is set stores parse_status='parsed'."""
    _patch_opendota(monkeypatch, _PARSED_PAYLOAD)
    ingest.ingest_match(db, 7201, 1, set(), set(), {"kills": 1.0})
    assert db.get(Match, 7201).parse_status == "parsed"


def test_ingest_match_sets_parse_status_unparsed_for_unparsed_payload(db, monkeypatch):
    """ingest_match() with version=None stores parse_status='unparsed'."""
    _patch_opendota(monkeypatch, _UNPARSED_PAYLOAD)
    ingest.ingest_match(db, 7202, 1, set(), set(), {"kills": 1.0})
    assert db.get(Match, 7202).parse_status == "unparsed"


def test_refresh_match_stats_sets_parse_status_parsed_when_now_parsed(db, monkeypatch):
    """refresh_match_stats() returning 'refreshed' flips parse_status from 'unparsed' to 'parsed'."""
    _seed_unparsed_match(db, 7203, _NOW - _HOUR)
    _patch_opendota(monkeypatch, _PARSED_PAYLOAD)
    assert ingest.refresh_match_stats(db, 7203, {"kills": 1.0}) == "refreshed"
    assert db.get(Match, 7203).parse_status == "parsed"


# ---------------------------------------------------------------------------
# Story: See When a Match Score Is Partial
# ---------------------------------------------------------------------------

def test_get_player_match_history_includes_parse_status_and_excluded_flag(db):
    """GET /players/{id} match_history rows carry parse_status and excluded_from_scoring."""
    _seed_scoring(db)
    history = {r["match_id"]: r for r in get_player(101, db=db)["match_history"]}
    assert history[_PARSED_MATCH]["parse_status"] == "parsed"
    assert history[_UNPARSED_MATCH]["parse_status"] == "unparsed"
    assert history[_PARSED_MATCH]["excluded_from_scoring"] is False
    assert history[_UNPARSED_MATCH]["excluded_from_scoring"] is False


def test_get_player_match_history_lists_excluded_match_with_flag(db):
    """An excluded match still appears in match history with excluded_from_scoring=True."""
    _seed_scoring(db)
    _set_excluded(db, _UNPARSED_MATCH, True)
    result = get_player(101, db=db)
    history = {r["match_id"]: r for r in result["match_history"]}
    assert set(history) == {_PARSED_MATCH, _UNPARSED_MATCH}
    assert history[_UNPARSED_MATCH]["excluded_from_scoring"] is True
    assert history[_PARSED_MATCH]["excluded_from_scoring"] is False
    assert result["total_points"] == pytest.approx(12.0)


def test_get_player_unknown_player_returns_404(db):
    """GET /players/{id} for an unknown player still returns 404 after the history change."""
    with pytest.raises(HTTPException) as exc:
        get_player(424242, db=db)
    assert exc.value.status_code == 404


def test_frontend_player_popup_contains_partial_stats_and_not_scored_markers():
    """Static check: frontend/app-players.js references 'Partial stats' and 'Not scored' and escapes via _escHtml."""
    src = (FRONTEND_DIR / "app-players.js").read_text()
    assert "Partial stats" in src
    assert "Not scored" in src
    assert "parse_status" in src
    assert "excluded_from_scoring" in src
    helper = src[src.index("function _matchPointsCellHtml"):]
    helper = helper[:helper.index("\n}\n")]
    assert "_escHtml(" in helper
    assert "wards, stuns, teamfight, runes and camps count as 0" in src


# ---------------------------------------------------------------------------
# Story: Track Parse Status in the Admin Match Table
# ---------------------------------------------------------------------------

def test_list_matches_includes_parse_status_and_excluded_from_scoring(db):
    """GET /admin/matches returns parse_status and excluded_from_scoring for every match."""
    _seed_scoring(db)
    _set_excluded(db, _UNPARSED_MATCH, True)
    rows = {r["match_id"]: r for r in admin_matches.list_matches(db=db, _=_ADMIN)}
    assert rows[_PARSED_MATCH]["parse_status"] == "parsed"
    assert rows[_PARSED_MATCH]["excluded_from_scoring"] is False
    assert rows[_UNPARSED_MATCH]["parse_status"] == "unparsed"
    assert rows[_UNPARSED_MATCH]["excluded_from_scoring"] is True


def test_retry_parse_refreshed_replaces_stats_and_points(db, monkeypatch):
    """Retry on a match whose OpenDota data is now parsed replaces stat rows/points, sets 'parsed', returns outcome 'refreshed'."""
    db.add(Weight(key="kills", label="kills", value=1.0))
    db.commit()
    _seed_unparsed_match(db, 7101, _NOW - 100 * _HOUR)
    post_calls = []
    _patch_opendota(monkeypatch, _PARSED_PAYLOAD, post_calls)

    result = admin_matches.retry_match_parse(7101, db=db, admin=_ADMIN)

    assert result["outcome"] == "refreshed"
    assert result["parse_status"] == "parsed"
    rows = {r.player_id: r for r in db.query(PlayerMatchStats).filter_by(match_id=7101).all()}
    assert rows[501].kills == 7 and rows[501].obs_placed == 4
    weights = {"kills": 1.0}
    assert rows[501].fantasy_points == pytest.approx(fantasy_score(_PARSED_PAYLOAD["players"][0], weights))
    assert rows[502].fantasy_points == pytest.approx(fantasy_score(_PARSED_PAYLOAD["players"][1], weights))
    assert rows[501].fantasy_points != pytest.approx(1.0)
    assert db.get(Match, 7101).parse_status == "parsed"
    assert post_calls == []


def test_retry_parse_still_unparsed_requests_parse(db, monkeypatch):
    """Retry on a still-unparsed match posts a parse request and returns outcome 'requested'."""
    _seed_unparsed_match(db, 7102, _NOW - _HOUR)
    post_calls = []
    _patch_opendota(monkeypatch, _UNPARSED_PAYLOAD, post_calls)

    result = admin_matches.retry_match_parse(7102, db=db, admin=_ADMIN)

    assert result["outcome"] == "requested"
    assert result["parse_status"] == "unparsed"
    assert len(post_calls) == 1 and post_calls[0].endswith("/request/7102")


def test_retry_parse_respects_rerequest_cooldown(db, monkeypatch):
    """A second retry inside the re-request cooldown does not post another parse request."""
    _seed_unparsed_match(db, 7103, _NOW - _HOUR)
    post_calls = []
    _patch_opendota(monkeypatch, _UNPARSED_PAYLOAD, post_calls)

    first = admin_matches.retry_match_parse(7103, db=db, admin=_ADMIN)
    second = admin_matches.retry_match_parse(7103, db=db, admin=_ADMIN)

    assert first["outcome"] == "requested"
    assert second["outcome"] == "cooldown"
    assert len(post_calls) == 1


def test_retry_parse_writes_audit_log(db, monkeypatch):
    """Each retry writes an 'admin_match_retry_parse' audit row naming the match."""
    _seed_unparsed_match(db, 7104, _NOW - _HOUR)
    _patch_opendota(monkeypatch, _UNPARSED_PAYLOAD)

    admin_matches.retry_match_parse(7104, db=db, admin=_ADMIN)
    admin_matches.retry_match_parse(7104, db=db, admin=_ADMIN)

    rows = _audit_rows(db, "admin_match_retry_parse")
    assert len(rows) == 2
    assert all("7104" in r.detail for r in rows)
    assert rows[0].actor_username == "admin"


def test_retry_parse_unknown_match_returns_404(db, monkeypatch):
    """POST /admin/matches/{id}/retry-parse for an unknown match raises HTTPException(404) and makes no OpenDota call."""
    post_calls = []
    get_calls = _patch_opendota(monkeypatch, _PARSED_PAYLOAD, post_calls)
    with pytest.raises(HTTPException) as exc:
        admin_matches.retry_match_parse(999999, db=db, admin=_ADMIN)
    assert exc.value.status_code == 404
    assert get_calls == [] and post_calls == []


def test_retry_parse_returns_409_when_ingest_lock_held(db, monkeypatch):
    """With ingest.INGEST_LOCK held, retry-parse raises HTTPException(409) and does not fetch."""
    _seed_unparsed_match(db, 7105, _NOW - _HOUR)
    get_calls = _patch_opendota(monkeypatch, _PARSED_PAYLOAD)
    assert ingest.INGEST_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as exc:
            admin_matches.retry_match_parse(7105, db=db, admin=_ADMIN)
        assert exc.value.status_code == 409
        assert get_calls == []
    finally:
        ingest.INGEST_LOCK.release()


def test_retry_parse_releases_ingest_lock_after_call(db, monkeypatch):
    """INGEST_LOCK is free again after retry-parse returns, including when the fetch raises."""
    _seed_unparsed_match(db, 7106, _NOW - _HOUR)
    _patch_opendota(monkeypatch, _UNPARSED_PAYLOAD)
    admin_matches.retry_match_parse(7106, db=db, admin=_ADMIN)
    assert ingest.INGEST_LOCK.acquire(blocking=False)
    ingest.INGEST_LOCK.release()

    def _boom(*a, **k):
        raise RuntimeError("OpenDota down")

    monkeypatch.setattr(ingest, "opendota_get_json", _boom)
    with pytest.raises(RuntimeError):
        admin_matches.retry_match_parse(7106, db=db, admin=_ADMIN)
    assert ingest.INGEST_LOCK.acquire(blocking=False)
    ingest.INGEST_LOCK.release()


def test_retry_parse_route_requires_admin():
    """POST /admin/matches/{match_id}/retry-parse declares Depends(require_admin)."""
    route = _route("/admin/matches/{match_id}/retry-parse", "POST")
    assert require_admin in [d.call for d in route.dependant.dependencies]


# ---------------------------------------------------------------------------
# Story: Mark a Match Unparseable and Choose How It Scores
# ---------------------------------------------------------------------------

def _patch_scoring(db, match_id, **body):
    return admin_matches.set_match_scoring(
        match_id, admin_matches.MatchScoringBody(**body), db=db, admin=_ADMIN)


def test_patch_match_scoring_sets_both_flags(db):
    """PATCH /admin/matches/{id}/scoring with both booleans persists unparseable and excluded_from_scoring."""
    _seed_scoring(db)
    result = _patch_scoring(db, _UNPARSED_MATCH, unparseable=True, excluded_from_scoring=True)
    assert result == {"match_id": _UNPARSED_MATCH, "parse_status": "unparseable",
                      "excluded_from_scoring": True}
    match = db.get(Match, _UNPARSED_MATCH)
    assert match.parse_status == "unparseable"
    assert match.excluded_from_scoring is True


def test_patch_match_scoring_partial_body_leaves_other_flag_unchanged(db):
    """Omitting one of the optional booleans leaves that flag as it was."""
    _seed_scoring(db)
    _patch_scoring(db, _UNPARSED_MATCH, excluded_from_scoring=True)
    match = db.get(Match, _UNPARSED_MATCH)
    assert match.parse_status == "unparsed"
    assert match.excluded_from_scoring is True

    _patch_scoring(db, _UNPARSED_MATCH, unparseable=True)
    match = db.get(Match, _UNPARSED_MATCH)
    assert match.parse_status == "unparseable"
    assert match.excluded_from_scoring is True


def test_patch_match_scoring_writes_audit_with_old_and_new_values(db):
    """Each change writes an 'admin_match_scoring' audit row containing old and new values."""
    _seed_scoring(db)
    _patch_scoring(db, _UNPARSED_MATCH, unparseable=True, excluded_from_scoring=True)
    _patch_scoring(db, _UNPARSED_MATCH, excluded_from_scoring=False)
    rows = _audit_rows(db, "admin_match_scoring")
    assert len(rows) == 2
    assert str(_UNPARSED_MATCH) in rows[0].detail
    assert "unparsed->unparseable" in rows[0].detail
    assert "False->True" in rows[0].detail
    assert "True->False" in rows[1].detail
    assert rows[0].actor_username == "admin"


def test_patch_match_scoring_unknown_match_returns_404(db):
    """PATCH scoring for an unknown match raises HTTPException(404) and writes no audit row."""
    with pytest.raises(HTTPException) as exc:
        _patch_scoring(db, 999999, excluded_from_scoring=True)
    assert exc.value.status_code == 404
    assert _audit_rows(db, "admin_match_scoring") == []


def test_patch_match_scoring_route_requires_admin(db):
    """PATCH /admin/matches/{match_id}/scoring declares Depends(require_admin); non-admin gets 403."""
    route = _route("/admin/matches/{match_id}/scoring", "PATCH")
    assert require_admin in [d.call for d in route.dependant.dependencies]
    db.add(User(id=2, username="u", email="u@test", password_hash="x", is_admin=False))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        require_admin({"user_id": 2, "username": "u", "is_admin": False}, db=db)
    assert exc.value.status_code == 403


def test_find_unparsed_match_ids_skips_unparseable(db):
    """find_unparsed_match_ids() omits a signature-zero match whose parse_status is 'unparseable'."""
    _seed_unparsed_match(db, 7301, _NOW - _HOUR, parse_status="unparseable")
    _seed_unparsed_match(db, 7302, _NOW - _HOUR, parse_status="unparsed")
    assert ingest.find_unparsed_match_ids(db, 48) == [7302]


def test_retry_unparsed_matches_never_requests_parse_for_unparseable(db, monkeypatch):
    """The background retry pass makes no fetch or parse request for an unparseable match."""
    _seed_unparsed_match(db, 7303, _NOW - _HOUR, parse_status="unparseable")
    _seed_unparsed_match(db, 7304, _NOW - 100 * _HOUR, parse_status="unparseable")
    post_calls = []
    get_calls = _patch_opendota(monkeypatch, _UNPARSED_PAYLOAD, post_calls)
    monkeypatch.setattr(ingest, "SessionLocal", lambda: db)

    summary = ingest.retry_unparsed_matches(48)

    assert summary["checked"] == 0
    assert get_calls == [] and post_calls == []
    assert db.get(Match, 7303).parse_status == "unparseable"


def test_clearing_unparseable_flag_returns_match_to_retry_pass(db):
    """Clearing unparseable on a still-unparsed match makes find_unparsed_match_ids() return it again."""
    _seed_unparsed_match(db, 7305, _NOW - _HOUR, parse_status="unparseable")
    assert ingest.find_unparsed_match_ids(db, 48) == []

    result = _patch_scoring(db, 7305, unparseable=False)

    assert result["parse_status"] == "unparsed"
    assert ingest.find_unparsed_match_ids(db, 48) == [7305]


def test_clearing_excluded_flag_restores_points(db):
    """Clearing excluded_from_scoring restores the match's points to leaderboards and roster."""
    _seed_scoring(db)
    before = _all_aggregates(db)
    _patch_scoring(db, _UNPARSED_MATCH, excluded_from_scoring=True)
    assert _all_aggregates(db) != pytest.approx(before)
    _patch_scoring(db, _UNPARSED_MATCH, excluded_from_scoring=False)
    assert _all_aggregates(db) == pytest.approx(before)


# --- Exclusion removes exactly that match's points everywhere ---------------

def test_weekly_leaderboard_excludes_excluded_match_points(db):
    """GET /leaderboard/weekly drops exactly the excluded match's points and nothing else."""
    _assert_exclusion_removes_exactly_that_match(db, _weekly)


def test_season_leaderboard_excludes_excluded_match_points(db):
    """compute_season_standings()/GET /leaderboard/season drop exactly the excluded match's points."""
    _assert_exclusion_removes_exactly_that_match(db, _season)


def test_roster_leaderboard_excludes_excluded_match_points(db):
    """GET /leaderboard/roster drops exactly the excluded match's points."""
    _seed_scoring(db)
    assert _roster_lb(db) == pytest.approx({"alice": 16.4, "bob": 11.5})
    _set_excluded(db, _UNPARSED_MATCH, True)
    assert _roster_lb(db) == pytest.approx({"alice": 12.0, "bob": 6.0})


def test_top_performances_and_player_leaderboard_exclude_excluded_match(db):
    """GET /top and GET /leaderboard do not count the excluded match."""
    def measure(db):
        top = sorted((r["id"], r["fantasy_points"]) for r in top_performances(db=db))
        board = {r["id"]: (r["matches"], r["avg_points"]) for r in leaderboard(db=db)}
        return {"top": [p for _, p in top],
                **{f"{pid}_n": n for pid, (n, _) in board.items()},
                **{f"{pid}_avg": a for pid, (_, a) in board.items()}}

    _assert_exclusion_removes_exactly_that_match(db, measure)


def test_build_roster_response_card_points_exclude_excluded_match(db):
    """_build_roster_response() card points (raw stat sums with modifiers) omit the excluded match's stats."""
    _assert_exclusion_removes_exactly_that_match(db, _roster_cards)


def test_weekly_summary_points_exclude_excluded_match(db):
    """_build_week_summary() points omit the excluded match."""
    _seed_scoring(db)
    _set_excluded(db, _UNPARSED_MATCH, True)
    summary = _build_week_summary(db, db.get(Week, 1), revealed=True, user_id=10)
    matches = {m["match_id"]: m for s in summary["series"] for m in s["matches"]}

    assert set(matches) == {_PARSED_MATCH, _UNPARSED_MATCH}
    assert matches[_UNPARSED_MATCH]["excluded_from_scoring"] is True
    assert matches[_PARSED_MATCH]["excluded_from_scoring"] is False
    assert all(p["points"] is None for p in matches[_UNPARSED_MATCH]["players"])
    parsed_points = {p["player_id"]: p["points"] for p in matches[_PARSED_MATCH]["players"]}
    assert parsed_points == {101: 12.0, 102: 6.0}


def test_card_draw_proportionality_ignores_excluded_match(db, monkeypatch):
    """card_draw player-pick weighting uses points that omit the excluded match.

    card_draw.py weights picks by how many cards the user already owns, not by match
    points, so excluding a match must leave booster eligibility and weights unchanged."""
    _seed_scoring(db)
    calls = []

    def _choices(population, weights=None, k=1):
        calls.append((sorted(getattr(p, "id", p) for p in population), list(weights)))
        return [population[0]]

    monkeypatch.setattr(card_draw.random, "choices", _choices)
    card_draw._pick_player_from_team(db, 10, "common", 1)
    card_draw._pick_player(db, 10, "common")
    before = list(calls)
    calls.clear()

    _set_excluded(db, _UNPARSED_MATCH, True)
    card_draw._pick_player_from_team(db, 10, "common", 1)
    card_draw._pick_player(db, 10, "common")

    assert calls == before


def test_unparseable_but_not_excluded_match_still_scores(db):
    """Marking a match unparseable alone (excluded_from_scoring=False) keeps its points in every aggregate."""
    _seed_scoring(db)
    before = _all_aggregates(db)
    _patch_scoring(db, _UNPARSED_MATCH, unparseable=True)
    assert db.get(Match, _UNPARSED_MATCH).excluded_from_scoring is False
    assert _all_aggregates(db) == pytest.approx(before)


# ---------------------------------------------------------------------------
# Story: Flag Stuck Matches Automatically
# ---------------------------------------------------------------------------

def _run_retry_pass(db, monkeypatch, payload=_UNPARSED_PAYLOAD):
    monkeypatch.delenv("INGEST_PARSE_RETRY_HOURS", raising=False)
    post_calls = []
    _patch_opendota(monkeypatch, payload, post_calls)
    monkeypatch.setattr(ingest, "SessionLocal", lambda: db)
    ingest.retry_unparsed_matches(48)
    return post_calls


def test_retry_unparsed_matches_marks_old_unparsed_match_unparseable(db, monkeypatch):
    """After one retry pass, an 'unparsed' match older than INGEST_PARSE_RETRY_HOURS becomes 'unparseable'."""
    _seed_unparsed_match(db, 7401, _NOW - 72 * _HOUR)
    _run_retry_pass(db, monkeypatch)
    assert db.get(Match, 7401).parse_status == "unparseable"

    post_calls = _run_retry_pass(db, monkeypatch)
    assert post_calls == []


def test_retry_unparsed_matches_auto_mark_never_sets_excluded(db, monkeypatch):
    """Auto-marking leaves excluded_from_scoring False."""
    _seed_unparsed_match(db, 7402, _NOW - 72 * _HOUR)
    _run_retry_pass(db, monkeypatch)
    match = db.get(Match, 7402)
    assert match.parse_status == "unparseable"
    assert match.excluded_from_scoring is False


def test_retry_unparsed_matches_auto_mark_writes_audit(db, monkeypatch):
    """Auto-mark writes a 'match_marked_unparseable' audit row with the match ID."""
    _seed_unparsed_match(db, 7403, _NOW - 72 * _HOUR)
    _run_retry_pass(db, monkeypatch)
    rows = _audit_rows(db, "match_marked_unparseable")
    assert len(rows) == 1
    assert "7403" in rows[0].detail


def test_retry_unparsed_matches_does_not_mark_recent_or_parsed_matches(db, monkeypatch):
    """Unparsed matches inside the window and parsed matches older than it are left unchanged."""
    _seed_unparsed_match(db, 7404, _NOW - _HOUR)
    _seed_unparsed_match(db, 7405, _NOW - 72 * _HOUR, parse_status="parsed")
    post_calls = _run_retry_pass(db, monkeypatch)
    assert db.get(Match, 7404).parse_status == "unparsed"
    assert db.get(Match, 7405).parse_status == "parsed"
    assert len(post_calls) == 1
    assert _audit_rows(db, "match_marked_unparseable") == []


def test_frontend_admin_matches_has_parse_column_retry_and_unparseable_filter():
    """Static check: frontend/app-admin-matches.js references retry-parse, /scoring, parse_status and an unparseable filter."""
    src = (FRONTEND_DIR / "app-admin-matches.js").read_text()
    html = (FRONTEND_DIR / "index.html").read_text()
    assert "/retry-parse" in src
    assert "/scoring" in src
    assert "parse_status" in src
    assert "adminMatchesUnparseableOnly" in src
    assert 'id="adminMatchesUnparseableOnly"' in html
    assert "Unparseable only" in html
    assert "<th>Parse</th>" in html
