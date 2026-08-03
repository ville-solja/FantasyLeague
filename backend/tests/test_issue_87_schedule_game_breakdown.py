"""
Tests for plan-issue-87-schedule-game-breakdown.

Covers the three user stories from markdown/plans/plan-issue-87-schedule-game-breakdown.md
that are testable via pytest (the frontend rendering steps — `frontend/app-players.js`
child-row rendering and `frontend/style.css` classes — are UI-only and produce no
stub here; they are covered by the plan's manual verification steps instead):

  Story: Expand Series into Individual Game Rows
    - `get_schedule()`'s `series_result` gains a `games` array (one entry per
      resolved `match_id`) for series with one or more resolved games
    - Each `games[]` entry has duration (seconds, or None), team1_kills/team2_kills,
      and team1_heroes/team2_heroes (mapped by the series' team1_id/team2_id, not
      raw radiant/dire) — 5-slot lists padded with None
    - Each `games[]` entry retains its `match_id` so the existing per-game OpenDota
      link can still be built
    - Upcoming (unresolved) series keep their existing date/time/stream fields and
      gain no `games` array
    - A series whose teams don't resolve to any match (`series_result` is None)
      still renders as "vs" with no expandable content — no `games` array

  Story: Store Match Duration at Ingest Time
    - `ingest_match()` passes `duration=data.get("duration")` into the `Match(...)`
      constructor
    - `ingest_match()` stores `duration=None` (not a crash, not 0) when the OpenDota
      payload has no `duration` key
    - Migration `022_matches_duration` adds `matches.duration` on a legacy DB,
      guarded by a `PRAGMA table_info` check, per this repo's schema migration rule
    - The migration is idempotent — safe to run twice
    - A `games[]` entry for a match ingested before this change (`duration IS NULL`)
      surfaces `duration: None` rather than raising

  Story: Show Hero Icons for Each Game
    - `_fetch_hero_icon_map()` builds `{hero_id: full_icon_url}` using the CDN base
      `https://cdn.cloudflare.steamstatic.com` + each hero's `"icon"` field from
      `GET /constants/heroes` (via the shared throttled `opendota_client.get_json()`)
    - `_fetch_hero_icon_map()` is cached for the process lifetime — a second call
      does not re-invoke the OpenDota client
    - `_fetch_hero_icon_map()` degrades to `{}` (not an exception) if the OpenDota
      call fails
    - A hero with an unresolved icon (unknown `hero_id`, or the constants fetch
      failed) shows a placeholder rather than a broken image
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text

import models as _models  # noqa: F401 — registers all tables in Base.metadata
from database import Base
from models import Match, PlayerMatchStats, Team

import ingest
import schedule
from migrate import run_migrations


def _csv_for_series(team1, team2, dt):
    """Minimal single-series CSV matching schedule.parse_schedule()'s expected shape."""
    date_str = dt.strftime("%d.%m.%Y")
    time_str = dt.strftime("%H:%M")
    return (
        "Week 1,,,,,,,,,,,\n"
        "Upper,,,,,,,,,,,\n"
        "Team 1,Team 2,Date,Time,Stream,,Team 1,Team 2,Date,Time,Stream,\n"
        f"{team1},{team2},{date_str},{time_str},,,,,,,,\n"
    )


LEGACY_MATCHES_TABLE_SQL = """
    CREATE TABLE matches (
        match_id INTEGER PRIMARY KEY,
        radiant_team_id INTEGER, dire_team_id INTEGER,
        league_id INTEGER, start_time INTEGER,
        radiant_win BOOLEAN, week_override_id INTEGER
    )
"""


def _legacy_engine_missing_duration():
    """In-memory SQLite engine whose matches table predates the duration column,
    with every other table created fresh via the current ORM schema."""
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text(LEGACY_MATCHES_TABLE_SQL))
        conn.commit()
    Base.metadata.create_all(engine)
    return engine


# ---------------------------------------------------------------------------
# Story: Expand Series into Individual Game Rows
# ---------------------------------------------------------------------------

class TestExpandSeriesIntoIndividualGameRows:

    def test_get_schedule_attaches_games_array_for_resolved_series(self, db, monkeypatch):
        """get_schedule()'s series_result gains a `games` list with one entry per
        resolved match_id, for a series between two DB-known teams with a single
        finished match within the ±4-day window of the scheduled date."""
        monkeypatch.setattr(schedule, "_hero_icon_cache", {1: "http://icon-a", 2: "http://icon-b"})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        past_dt = datetime.now() - timedelta(days=1)
        db.add(Match(
            match_id=8001, radiant_team_id=1, dire_team_id=2, radiant_win=True,
            start_time=int(past_dt.timestamp()), duration=1900,
        ))
        db.add(PlayerMatchStats(player_id=101, match_id=8001, team_id=1, kills=22, hero_id=1))
        db.add(PlayerMatchStats(player_id=102, match_id=8001, team_id=2, kills=18, hero_id=2))
        db.commit()

        csv_text = _csv_for_series("TeamA", "TeamB", past_dt)
        monkeypatch.setattr(schedule, "fetch_csv_text", lambda: csv_text)
        schedule.bust_cache()

        data = schedule.get_schedule(db)

        series = data["weeks"][0]["div1"][0]
        result = series["series_result"]
        assert result is not None
        assert "games" in result
        assert len(result["games"]) == 1
        assert result["games"][0]["match_id"] == 8001

    def test_game_entry_shape_duration_kills_and_hero_icons(self, db, monkeypatch):
        """Each games[] entry has match_id, duration (seconds), team1_kills/team2_kills
        (SUM(kills) grouped by team_id, mapped via the series' team1_id/team2_id — not
        raw radiant/dire), and team1_heroes/team2_heroes as 5-slot lists of icon URLs
        (padded with None) built from a stubbed _fetch_hero_icon_map()."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {1: "http://icon-a", 2: "http://icon-b"})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(
            match_id=8002, radiant_team_id=1, dire_team_id=2, radiant_win=False,
            start_time=1_700_000_000, duration=2200,
        ))
        db.add(PlayerMatchStats(player_id=201, match_id=8002, team_id=1, kills=30, hero_id=1))
        db.add(PlayerMatchStats(player_id=202, match_id=8002, team_id=2, kills=35, hero_id=2))
        db.commit()

        team_lookup = {"teama": 1, "teamb": 2}
        result = schedule.resolve_series_result(db, "TeamA", "TeamB", team_lookup)

        assert result is not None
        game = result["games"][0]
        assert game["match_id"] == 8002
        assert game["duration"] == 2200
        assert game["team1_kills"] == 30
        assert game["team2_kills"] == 35
        assert game["team1_heroes"] == ["http://icon-a", None, None, None, None]
        assert game["team2_heroes"] == ["http://icon-b", None, None, None, None]

    def test_games_array_preserves_per_game_opendota_link_match_id(self, db, monkeypatch):
        """Each games[] entry retains its own match_id, in the same order as the
        series' existing match_ids list, so the existing per-game OpenDota link
        ("G1 ↗", "G2 ↗", ...) can still be built for each specific game."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(match_id=9001, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                      start_time=1_700_000_000, duration=1500))
        db.add(Match(match_id=9002, radiant_team_id=2, dire_team_id=1, radiant_win=False,
                      start_time=1_700_003_000, duration=1600))
        db.commit()

        team_lookup = {"teama": 1, "teamb": 2}
        result = schedule.resolve_series_result(db, "TeamA", "TeamB", team_lookup)

        assert result["match_ids"] == [9001, 9002]
        assert [g["match_id"] for g in result["games"]] == [9001, 9002]

    def test_upcoming_series_unaffected_by_games_array(self, db, monkeypatch):
        """An upcoming (future-dated) series keeps datetime_iso, match_status
        == "upcoming", stream_label/stream_url exactly as before, and gains no
        `games` key — the game-breakdown feature does not touch unresolved series."""
        monkeypatch.setattr(schedule, "_hero_icon_cache", {})
        future_dt = datetime.now() + timedelta(days=3)
        csv_text = _csv_for_series("TeamA", "TeamB", future_dt)
        monkeypatch.setattr(schedule, "fetch_csv_text", lambda: csv_text)
        schedule.bust_cache()

        data = schedule.get_schedule(db)

        series = data["weeks"][0]["div1"][0]
        assert series["match_status"] == "upcoming"
        assert series["datetime_iso"] is not None
        assert series["stream_label"] is None
        assert series["stream_url"] is None
        # No DB-known teams/matches exist in this test, so the series stays unresolved
        # entirely — meaning there is no `games` array to speak of either.
        assert series["series_result"] is None

    def test_series_with_no_resolved_games_has_no_games_array(self, db, monkeypatch):
        """A series whose team names don't resolve to any DB match (series_result
        is None, as resolve_series_result() already returns today) still renders
        as "vs" with no expandable content — no `games` array is attached."""
        result = schedule.resolve_series_result(db, "UnknownTeam1", "UnknownTeam2", {})
        assert result is None


# ---------------------------------------------------------------------------
# Story: Store Match Duration at Ingest Time
# ---------------------------------------------------------------------------

class TestStoreMatchDurationAtIngestTime:

    def test_ingest_match_stores_duration_from_opendota_payload(self, db, monkeypatch):
        """ingest_match() passes duration=data.get("duration") into the Match(...)
        constructor — a match payload with "duration": 2143 results in a persisted
        Match row with match.duration == 2143."""
        payload = {
            "duration": 2143,
            "radiant_team_id": 1,
            "dire_team_id": 2,
            "radiant_name": "TeamA",
            "dire_name": "TeamB",
            "start_time": 1_700_000_000,
            "radiant_win": True,
            "players": [],
            "picks_bans": [],
        }
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, label=None: payload)

        ingest.ingest_match(db, 12345, league_id=1, seen_players=set(), seen_teams=set(), weights={})

        match = db.query(Match).filter_by(match_id=12345).first()
        assert match is not None
        assert match.duration == 2143

    def test_ingest_match_duration_none_when_payload_omits_duration(self, db, monkeypatch):
        """When the OpenDota match payload has no "duration" key, ingest_match()
        stores Match.duration as None rather than 0 or raising a KeyError."""
        payload = {
            "radiant_team_id": 1,
            "dire_team_id": 2,
            "radiant_name": "TeamA",
            "dire_name": "TeamB",
            "start_time": 1_700_000_000,
            "radiant_win": True,
            "players": [],
            "picks_bans": [],
        }
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, label=None: payload)

        ingest.ingest_match(db, 12346, league_id=1, seen_players=set(), seen_teams=set(), weights={})

        match = db.query(Match).filter_by(match_id=12346).first()
        assert match is not None
        assert match.duration is None

    def test_migration_022_adds_duration_column_to_legacy_matches_table(self):
        """Migration 022_matches_duration ALTER TABLEs `duration INTEGER` onto a
        matches table created without it (PRAGMA table_info check finds it absent
        beforehand, present afterward), applied via migrate.run_migrations()."""
        engine = _legacy_engine_missing_duration()

        with engine.connect() as conn:
            cols_before = [r[1] for r in conn.execute(text("PRAGMA table_info(matches)")).fetchall()]
        assert "duration" not in cols_before

        run_migrations(engine)

        with engine.connect() as conn:
            cols_after = [r[1] for r in conn.execute(text("PRAGMA table_info(matches)")).fetchall()]
        assert "duration" in cols_after

    def test_migration_022_idempotent_on_already_migrated_table(self):
        """Running migrate.run_migrations() twice against the same engine does not
        raise (e.g. duplicate-column error) once 022_matches_duration has already
        been applied and recorded in schema_migrations."""
        engine = _legacy_engine_missing_duration()

        run_migrations(engine)
        run_migrations(engine)  # must not raise (e.g. duplicate-column error)

        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(matches)")).fetchall()]
        assert cols.count("duration") == 1

    def test_game_entry_duration_none_for_pre_migration_match(self, db, monkeypatch):
        """A resolved match ingested before this change (duration IS NULL in the DB)
        produces a games[] entry with duration: None rather than the schedule
        response erroring or omitting the game row."""
        monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(
            match_id=8003, radiant_team_id=1, dire_team_id=2, radiant_win=True,
            start_time=1_700_000_000, duration=None,
        ))
        db.commit()

        team_lookup = {"teama": 1, "teamb": 2}
        result = schedule.resolve_series_result(db, "TeamA", "TeamB", team_lookup)

        assert result is not None
        assert len(result["games"]) == 1
        assert result["games"][0]["duration"] is None


# ---------------------------------------------------------------------------
# Story: Show Hero Icons for Each Game
# ---------------------------------------------------------------------------

class TestShowHeroIconsForEachGame:

    def test_fetch_hero_icon_map_builds_full_cdn_urls_from_constants_heroes(self, monkeypatch):
        """_fetch_hero_icon_map() calls opendota_client.get_json() against
        GET /constants/heroes and returns {hero_id: "https://cdn.cloudflare.steamstatic.com" + icon}
        for each hero in the response that has both an "id" and an "icon" field."""
        monkeypatch.setattr(schedule, "_hero_icon_cache", None)
        fake_heroes = {
            "1": {"id": 1, "icon": "/apps/dota2/images/dota_react/heroes/icons/antimage.png"},
            "2": {"id": 2, "icon": "/apps/dota2/images/dota_react/heroes/icons/axe.png"},
            "3": {"id": 3},  # no icon field — must be excluded, not KeyError
        }

        def fake_get_json(url, label=None):
            assert url.endswith("/constants/heroes")
            return fake_heroes

        monkeypatch.setattr("opendota_client.get_json", fake_get_json)

        result = schedule._fetch_hero_icon_map()

        assert result == {
            1: "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/antimage.png",
            2: "https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/icons/axe.png",
        }

    def test_fetch_hero_icon_map_cached_across_calls(self, monkeypatch):
        """A second call to _fetch_hero_icon_map() in the same process returns the
        cached dict without invoking opendota_client.get_json() again — the mocked
        get_json is asserted to have been called exactly once across both calls."""
        monkeypatch.setattr(schedule, "_hero_icon_cache", None)
        calls = {"n": 0}

        def fake_get_json(url, label=None):
            calls["n"] += 1
            return {"1": {"id": 1, "icon": "/x.png"}}

        monkeypatch.setattr("opendota_client.get_json", fake_get_json)

        first = schedule._fetch_hero_icon_map()
        second = schedule._fetch_hero_icon_map()

        assert first == second == {1: "https://cdn.cloudflare.steamstatic.com/x.png"}
        assert calls["n"] == 1

    def test_fetch_hero_icon_map_degrades_to_empty_dict_on_opendota_failure(self, monkeypatch):
        """When opendota_client.get_json() returns None (as it does after exhausting
        retries) or raises, _fetch_hero_icon_map() returns {} rather than propagating
        an exception."""
        monkeypatch.setattr(schedule, "_hero_icon_cache", None)
        monkeypatch.setattr("opendota_client.get_json", lambda url, label=None: None)
        assert schedule._fetch_hero_icon_map() == {}

        monkeypatch.setattr(schedule, "_hero_icon_cache", None)

        def fake_raises(url, label=None):
            raise RuntimeError("boom")

        monkeypatch.setattr("opendota_client.get_json", fake_raises)
        assert schedule._fetch_hero_icon_map() == {}

    def test_unknown_hero_id_padded_with_none_not_broken_image(self, db, monkeypatch):
        """A player_match_stats row with a hero_id absent from the (possibly empty)
        hero icon map still produces a 5-slot team1_heroes/team2_heroes list — the
        unresolved slot is None (a placeholder), not a broken image URL or a raised
        KeyError."""
        monkeypatch.setattr(schedule, "_hero_icon_cache", {})  # no hero resolves
        db.add(Team(id=1, name="TeamA"))
        db.add(Team(id=2, name="TeamB"))
        db.add(Match(
            match_id=700, radiant_team_id=1, dire_team_id=2, radiant_win=True,
            start_time=1_700_000_000, duration=1500,
        ))
        db.add(PlayerMatchStats(player_id=1, match_id=700, team_id=1, kills=5, hero_id=999))
        db.commit()

        games = schedule._build_games(db, [700], team1_id=1, team2_id=2)

        assert len(games) == 1
        assert len(games[0]["team1_heroes"]) == 5
        assert games[0]["team1_heroes"][0] is None
        assert games[0]["team1_heroes"][1:] == [None, None, None, None]
