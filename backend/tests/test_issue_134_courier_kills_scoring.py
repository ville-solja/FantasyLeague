"""
Tests for plan-issue-134-courier-kills-scoring.md (resolves GitHub issue #134).

Courier kills become a scored stat for season 17: OpenDota's parse-only
`players[].courier_kills` is stored per player per game in a new
`player_match_stats.courier_kills` column (default 0), weighted by a new
`courier_kills` weight (default 1.0) through `scoring.SCORING_STATS`, shown in
the player popup, How to Play, the point simulator and the Partial stats
tooltip, and kept out of the card-modifier pool. Past matches are not
backfilled, so every stored season 16 number stays the same. One class per
user story, one stub per acceptance criterion plus the primary failure path.

Developer notes
---------------

  Every place a stat is named today (`grep -rn roshan_kills backend frontend`,
  verified 2026-11-17). Mirror courier_kills in each one unless noted:
    - backend/scoring.py: `SCORING_STATS` (13 entries; order is display order
      nowhere, but keep it next to roshan_kills) and `STAT_LABELS` (card-image /
      Weekly Report label, e.g. "Couriers"; test_issue_152 requires a label for
      every SCORING_STATS entry + deaths). `stat_dict_from_row` builds from
      SCORING_STATS, so ORM rows and Core rows pick the new column up only when
      the row (or the SELECT) carries it; a missing key reads as 0 silently.
    - backend/seed.py `DEFAULT_WEIGHTS` ({"key": "courier_kills", "label":
      "Courier kills", "value": 1.0}). `seed_weights()` raises ValueError at
      startup if a SCORING_STATS key has no DEFAULT_WEIGHTS entry. Behaviour
      confirmed: a key missing from the DB is inserted (env override first,
      else default); an existing key's VALUE changes only when it is in
      WEIGHTS_JSON; labels are re-synced for every key. It opens
      `seed.SessionLocal()` (the real DB): patch it, as `seed_env` in
      tests/test_seed.py does (`patch("seed.SessionLocal", side_effect=Session)`).
      Optional: repo-root `weights.json` is a reference copy (already lacks
      assists); nothing reads it.
    - backend/models.py `PlayerMatchStats.courier_kills = Column(Integer,
      default=0)`. NOTE `_VALID_STAT_KEYS_LIST = list(SCORING_STATS) + ["deaths"]`
      feeds the `ck_card_modifiers_stat_key` CHECK on card_modifiers: a fresh DB
      will allow 'courier_kills', a migrated one (DDL from _m025) will not. That
      is harmless because nothing assigns it; do NOT add a card_modifiers table
      rebuild for this issue. Either leave the constraint as is or build it from
      the same modifier pool as card_utils (then fresh and migrated DBs agree).
    - backend/migrate.py: add `_m047_pms_courier_kills` (next free number after
      046) with a `PRAGMA table_info(player_match_stats)` guard and
      `ALTER TABLE player_match_stats ADD COLUMN courier_kills INTEGER DEFAULT 0`
      (DEFAULT 0 so existing rows read 0, not NULL), and register
      ("047_pms_courier_kills", ...) in `MIGRATIONS`. Do NOT edit the legacy
      lists in `_m005_pms_expanded_stats` (line ~114) or the card_modifiers
      CHECK lists in `_m008` (~169/180) and `_m025` (~414/425): they are
      historical, already applied, and `_m025`'s rebuild trigger is
      `"'assists'" not in ddl`. `backend/migrate_scoring_stats.py` is a legacy
      one-off script (db-sustainability.md); leave it.
      tests/test_migrate.py::TestSchemaCoverage catches a missing migration.
    - backend/ingest.py: the row is built in `_build_stat_row(p, match_id,
      radiant_team_id, dire_team_id, weights)` (~line 475), shared by first
      ingest (`_store_match_payload` -> `ingest_match` / `store_manual_match`)
      and the parse retry (`refresh_match_stats`, which deletes and re-adds the
      rows and then `_reapply_mvp_bonus` -> `card_points.refresh_card_points`).
      Add `courier_kills=p.get("courier_kills", 0)` (use `or 0`, like
      teamfight_participation, if OpenDota can send null) and add courier_kills
      to the PARSE RETRY comment (~line 546). `fantasy_points=fantasy_score(p,
      weights)` reads the raw payload dict, so a null value there needs the
      same care. `find_unparsed_match_ids`' signature stats stay as they are.
    - backend/card_utils.py `_SCORED_STAT_COLS = list(SCORING_STATS) + ["deaths"]`
      is the modifier pool for `_assign_modifiers` (`random.sample(pool,
      min(count, len(pool)))`). Every draw path (routers/cards.py draw, booster,
      reroll; own_card.py) goes through `_assign_modifiers`. Build the pool from
      SCORING_STATS minus a `NO_MODIFIER_STATS = {"courier_kills"}` set, plus
      deaths. image.py and the Weekly Report label modifiers through
      `scoring.STAT_LABELS`; no change needed there.
    - backend/card_points.py: nothing to edit. `weights_fingerprint` hashes
      every weight key/value, so adding the courier_kills weight changes it and
      `ensure_card_points_current(db)` (called from main.py's lifespan AFTER
      `seed_weights()`) rebuilds via `rebuild_all(db)`; `_compute` reads ORM rows
      through `stat_dict_from_row`, so the new column flows in.
    - backend/routers/leaderboard.py: the endpoint is `POST /simulate/{match_id}`
      (`simulate_match(match_id, db, body)`, wrapper `simulate_match_route`,
      rate limited) and `GET /simulate` returns `_SIMULATE_DOCS`. Add
      `courier_kills: float | None = None` to `SimulateBody`, a
      `request_body.fields.courier_kills` docs entry, a
      `response.players[].stats.courier_kills` docs entry, `s.courier_kills` in
      the SELECT and `"courier_kills": r.courier_kills or 0` in `stats`.
      `weights_used` already iterates SCORING_STATS. Pre-existing gap: assists
      is missing from SimulateBody, the docs, the SELECT and `stats` (so
      simulate scores assists as 0); not this issue, but worth fixing alongside.
    - backend/routers/players.py `get_player` SELECT (~line 81) lists the stat
      columns explicitly: add `s.courier_kills`, otherwise
      `player_insights.points_by_source(r, ...)` sees no courier_kills and a
      game's breakdown no longer sums to its fantasy_points.
    - backend/player_insights.py `SOURCE_GROUPS` "objectives" ->
      ["towers_killed", "roshan_kills", "courier_kills"]. `_STAT_COLS =
      SCORING_STATS + ["deaths"]` feeds `league_aggregates`' SELECT,
      `team_insights._ROW_STATS` and `modifier_values` (the popup's and team
      popup's "A +10 % modifier is worth most on" list). modifier_values should
      leave courier_kills out (it can never be a modifier): iterate the
      card_utils pool there, not `_STAT_COLS`.
    - backend/manual_match.py `STAT_FIELDS` (replay JSON schema): add
      `"courier_kills": (int, 0, 10)`. Every STAT_FIELDS key is REQUIRED per
      player (`_REQUIRED_PLAYER`), and `store_manual_match` marks a replay with
      any `missing_stats` as "unparseable" (Partial stats). There is no
      per-player form: "the admin form" is the Add match dialog, which takes an
      OpenDota match id (stored through `_build_stat_row`, gets courier_kills
      from OpenDota) or a replay JSON written by
      backend/scripts/replay_to_match.py.
    - backend/scripts/replay_to_match.py: the odota parser's "interval" events
      carry no courier-kill counter (`_INTERVAL_STATS` maps roshan_kills to
      `roshans_killed`; there is nothing for couriers). OpenDota derives
      courier_kills from DOTA_COMBATLOG_DEATH events whose targetname is a
      courier. Count those per attacker hero (map `attackername` to a slot with
      `_hero_names(interval["unit"])`), add courier_kills to `STAT_ORDER`
      (test_issue_224 pins `STAT_ORDER == list(manual_match.STAT_FIELDS)`), and
      decide when it counts as "missing". If the script just lists it under
      missing_stats, EVERY replay import becomes Partial stats.
    - frontend/app-init.js `loadHowToPlay`: `statsKeys` array and
      `statsLabels` map ("Courier kills").
    - frontend/app-player-popup.js `_popupMatchStats(m)`: add e.g.
      ["Couriers", m.courier_kills ?? 0] right after ["Roshan", ...]; and
      `_POPUP_SOURCE_LABELS` needs no change (objectives already exists).
    - frontend/app-players.js `_PARTIAL_STATS_TOOLTIP` (shared by the popup and
      the Schedule player tables, issue 244).
    - Docs: markdown/features/core/cards.md (formula ~line 64, "Valid modifier
      targets" ~line 89), core/players.md, reference/point-simulator.md,
      reference/unparseable-match-handling.md, reference/matches-outside-the-
      league.md (replay schema).

  Older tests that pin these lists and must be updated together
    - tests/test_scoring.py::test_scoring_stats_has_thirteen_entries
      (`len(SCORING_STATS) == 13` -> 14).
    - tests/test_issue_208_player_popup_visualizations.py:
      test_points_by_source_has_planned_source_groups (objectives group pinned
      to ["towers_killed", "roshan_kills"]); test_get_player_modifier_values_per_stat_top_three
      (`sorted(stats) == sorted(SCORING_STATS + ["deaths"])`, must drop
      courier_kills); test_history_details_panel_lists_every_stat (exact
      <dt>/<dd> dict); line ~1460 exact Partial stats tooltip markup.
    - Tooltip text: tests/test_unparseable_match_handling.py ~line 405
      (substring "wards, stuns, teamfight, runes and camps count as 0"),
      tests/test_issue_244_schedule_player_performance.py `_PARTIAL_TIP`
      (~line 205, exact), test_issue_208 ~line 1460 (exact).
    - Replay schema: tests/test_issue_224_matches_outside_the_league.py
      `_stats()` helper (needs courier_kills or every replay payload fails
      "is required"), test_validate_replay_accepts_valid_payload (key set from
      STAT_FIELDS), test_replay_to_match_lists_missing_stats
      (`missing_stats == ["teamfight_participation"]`),
      test_replay_to_match_output_passes_server_validation (STAT_ORDER pin),
      test_replay_to_match_aggregates_fixture.
    - tests/test_issue_152_weekly_recap_animations.py: STAT_LABELS must cover
      SCORING_STATS + deaths. tests/test_seed.py: every SCORING_STATS key in
      DEFAULT_WEIGHTS. tests/test_migrate.py::TestSchemaCoverage.
    - No test pins the How to Play `statsKeys`, the `/simulate` docs keys, or
      `_SCORED_STAT_COLS`.

  Fixtures and helpers to reuse
    - conftest `db` (plain in-memory) is enough for function-level tests. For
      TestClient tests (GET /players/{id}) use a StaticPool `db` override as in
      test_issue_208 / test_issue_224, plus test_issue_208's `_client`,
      `_weights(db, **over)` (DEFAULT_WEIGHTS rows), `_match`, `_stat`
      (fantasy_points from the formula), `_seed_player`, `_get`, `_row` and the
      autouse `_no_opendota` (hero maps + league cache).
    - Ingest: test_issue_224's `_od_player(i)` / `_od(...)` payload builders,
      the `quiet` fixture (stubs `_bust_panel_cache`, `request_parse`,
      schedule caches) and `_fake_od(monkeypatch, calls, payloads)` (patches
      `ingest.opendota_get_json`). `_build_stat_row` can be called directly.
    - Card points: test_issue_141's `_seed(db)` (users, cards incl. modifiers,
      weeks, rosters, matches) with `_stored(db)` ({(card_id, match_id):
      points}) and `_all_readers(db)` (weekly/season totals, rosters). Expected
      card points: `card_utils._compute_card_points(stat_dict_from_row(row),
      card.card_type, *card_utils._load_weights(db), mods)`; after seeding
      stats directly call `card_points.rebuild_all(db)`. Compare displayed
      values with `display_points(exact)`.
    - Raw points (#244): `schedule.game_players(db, match_id)` recomputes
      `raw_points = display_points(fantasy_score(stat_dict_from_row(row),
      weights))`; test_issue_244's `_seed_game` / `_expected_raw`.
    - Accolades: `accolades.compute_awards(db)` reads stored
      `player_match_stats.fantasy_points` (never recomputed by this change).
    - Migration on a legacy file DB: test_issue_224's `_legacy_file_engine`
      pattern (create_all, drop the column with `ALTER TABLE ... DROP COLUMN`,
      record every migration below "047" as applied, then
      `migrate.run_migrations(engine)`).
    - Node harness for the popup: test_issue_208's `_popup_src()` / `_js(body)`
      (skips without node). How to Play: read `frontend/app-init.js` and
      slice `loadHowToPlay` (test_how_to_play_role_subtabs `_extract_js_function`).

  Testing "past points unchanged"
    Seed stats WITHOUT a courier_kills weight (all rows courier_kills = 0),
    `card_points.rebuild_all(db)`, snapshot `_stored(db)`, leaderboard totals,
    `schedule.game_players` raw points, `PlayerMatchStats.fantasy_points` and
    `accolades.compute_awards(db)`. Then add the weight the way startup does
    (`seed_weights()` with `seed.SessionLocal` patched to this DB, or add the
    Weight row directly) and call `card_points.ensure_card_points_current(db)`:
    it must return a row count (the fingerprint changed, so it rebuilt), and
    every snapshot must be equal afterwards.

  Testing "never a courier_kills modifier" deterministically
    Either set `modifier_count_<rarity>` to a number >= the pool size so
    `random.sample` returns the whole pool (assert the chosen set equals
    SCORING_STATS - {courier_kills} + {deaths}), or monkeypatch
    `card_utils.random.sample` with a recorder that captures the population
    and returns it. Run for common (count 0: no modifiers), rare, epic,
    legendary.

Run with: cd backend && python3 -m pytest tests/test_issue_134_courier_kills_scoring.py -v
"""

import json
import os
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models  # noqa: F401  (registers every table for the db fixture)
import accolades
import card_points
import card_utils
import ingest
import manual_match
import migrate
import player_insights
import schedule
import scoring
import seed
from database import Base, get_db
from models import (
    Card, CardMatchPoints, CardModifier, Match, Player, PlayerMatchStats, Team, Weight,
)
from scoring import SCORING_STATS, display_points, fantasy_score, stat_dict_from_row
from seed import DEFAULT_WEIGHTS
from tests.test_issue_224_matches_outside_the_league import (  # noqa: F401  (quiet is a fixture)
    _fake_od, _od, _od_player, _replay, _replay_player, _script, quiet,
)

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_MID = 7001
_POOL = [k for k in SCORING_STATS if k != "courier_kills"] + ["deaths"]


@pytest.fixture
def db():
    """In-memory database on one shared connection, so a TestClient's request thread
    sees the same data (overrides conftest's `db`)."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_hero_fetch(monkeypatch):
    """The popup's hero map and the schedule caches never reach OpenDota."""
    monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
    monkeypatch.setattr(schedule, "warm_hero_maps_in_background", lambda: None)
    monkeypatch.setattr(schedule, "_hero_icon_cache", None)
    monkeypatch.setattr(schedule, "_hero_name_cache", {})
    schedule._game_players_cache.clear()
    player_insights.clear_league_cache()
    yield
    schedule._game_players_cache.clear()
    player_insights.clear_league_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _default_weights(**over):
    w = {x["key"]: x["value"] for x in DEFAULT_WEIGHTS}
    w.update(over)
    return w


def _add_weights(db, skip=(), **over):
    for w in DEFAULT_WEIGHTS:
        if w["key"] in skip:
            continue
        db.add(Weight(key=w["key"], label=w["label"], value=over.get(w["key"], w["value"])))
    db.commit()


def _db_weights(db):
    return {w.key: w.value for w in db.query(Weight).all()}


def _rows(db, match_id=_MID):
    return {r.player_id: r for r in db.query(PlayerMatchStats).filter_by(match_id=match_id)}


def _stored(db) -> dict:
    return {(r.card_id, r.match_id): r.points
            for r in db.execute(select(CardMatchPoints.card_id, CardMatchPoints.match_id,
                                       CardMatchPoints.points)).all()}


def _expected_card_points(db, card):
    weights, rarity = card_utils._load_weights(db)
    mods = card_utils._card_modifiers_map(db, [card.id]).get(card.id, {})
    out = {}
    for row in db.query(PlayerMatchStats).filter_by(player_id=card.player_id):
        mvp = card_utils._mvp_bonus_delta(row, weights) if row.is_mvp else 0.0
        out[(card.id, row.match_id)] = card_utils._compute_card_points(
            stat_dict_from_row(row), card.card_type, weights, rarity, mods,
            mvp_bonus=mvp, match_count=1)
    return out


def _seed_game(db, mid=900, courier=None, weights=None):
    """Teams 1 and 2, one league match, ten players with distinct stats.
    `courier` maps a player index to its courier kills (others 0)."""
    courier = courier or {}
    weights = weights if weights is not None else _db_weights(db)
    if db.get(Team, 1) is None:
        db.add_all([Team(id=1, name="Reds"), Team(id=2, name="Blues")])
    db.add(Match(match_id=mid, league_id=1, radiant_team_id=1, dire_team_id=2, radiant_win=True,
                 start_time=1_760_000_000 + mid, duration=2400, parse_status="parsed"))
    pids = []
    for i in range(10):
        pid = mid * 100 + i
        if db.get(Player, pid) is None:
            db.add(Player(id=pid, name=f"P{pid}"))
        stats = dict(kills=i, deaths=10 - i, assists=2 * i + 1, last_hits=40 + 7 * i,
                     gold_per_min=300 + 20 * i, obs_placed=i % 3, towers_killed=i % 2,
                     roshan_kills=1 if i == 0 else 0, teamfight_participation=0.1 * i,
                     camps_stacked=i % 4, rune_pickups=i, firstblood_claimed=1 if i == 2 else 0,
                     stuns=1.5 * i, courier_kills=courier.get(i, 0))
        db.add(PlayerMatchStats(player_id=pid, match_id=mid, team_id=1 if i < 5 else 2,
                                hero_id=i + 1, is_mvp=(i == 4),
                                fantasy_points=fantasy_score(stats, weights), **stats))
        pids.append(pid)
    db.commit()
    return pids


def _seed_cards(db, pids):
    """One card per rarity on the first four players, with a modifier on the rare one."""
    from models import User
    db.add(User(id=1, username="alice", email="a@test", password_hash="x"))
    for cid, (pid, rarity) in enumerate(zip(pids, ("common", "rare", "epic", "legendary")), start=1):
        db.add(Card(id=cid, player_id=pid, owner_id=1, card_type=rarity, is_active=False))
    db.add(CardModifier(card_id=2, stat_key="kills", bonus_pct=10.0))
    db.commit()


def _legacy_file_engine(tmp_path, stats=()):
    """A file DB from create_all with courier_kills dropped, every migration below 047
    recorded as applied, and `stats` ((player_id, match_id, kills, fantasy_points), ...)
    stored before the upgrade."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE player_match_stats DROP COLUMN courier_kills"))
        for pid, mid, kills, pts in stats:
            conn.execute(text(
                "INSERT INTO player_match_stats (player_id, match_id, kills, roshan_kills, fantasy_points) "
                "VALUES (:p, :m, :k, 1, :f)"), {"p": pid, "m": mid, "k": kills, "f": pts})
        conn.commit()
        migrate._ensure_migrations_table(conn)
        for migration_id, _ in migrate.MIGRATIONS:
            if migration_id < "047":
                migrate._record(conn, migration_id)
        conn.commit()
    return engine


def _pms_columns(engine):
    with engine.connect() as conn:
        return {r[1]: r for r in conn.execute(text("PRAGMA table_info(player_match_stats)")).fetchall()}


def _node():
    return shutil.which("node")


def _run_node(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def _popup_js(body):
    from tests.test_issue_208_player_popup_visualizations import _js
    return _js(body)


def _players_client(db):
    from routers import players
    import rate_limit
    app = FastAPI()
    app.state.limiter = rate_limit.limiter
    app.include_router(players.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _leaderboard_client(db):
    from routers import leaderboard
    app = FastAPI()
    app.state.limiter = leaderboard.limiter

    def _get_db():
        yield db
    app.include_router(leaderboard.router)
    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


def _seed_env_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


# ===========================================================================
# Story 1: Courier Kills Earn Fantasy Points
# ===========================================================================

class TestCourierKillsEarnFantasyPoints:

    # --- Stored -----------------------------------------------------------

    def test_player_match_stats_courier_kills_column_defaults_to_zero(self, db):
        """PlayerMatchStats has an Integer `courier_kills` column; a row inserted without it (ORM and raw SQL INSERT) reads back courier_kills == 0."""
        col = PlayerMatchStats.__table__.c.courier_kills
        assert str(col.type) == "INTEGER"
        db.add(PlayerMatchStats(player_id=1, match_id=1, kills=3))
        db.commit()
        db.execute(text("INSERT INTO player_match_stats (player_id, match_id, kills) VALUES (2, 1, 4)"))
        db.commit()
        db.expire_all()
        values = {r.player_id: r.courier_kills for r in db.query(PlayerMatchStats).all()}
        assert values == {1: 0, 2: 0}

    def test_build_stat_row_stores_courier_kills_from_payload(self, db, quiet):
        """ingest._build_stat_row on an OpenDota player entry with courier_kills=2 returns a row with courier_kills == 2; storing a full payload via ingest._store_match_payload persists it per player."""
        w = _default_weights()
        row = ingest._build_stat_row(_od_player(0, courier_kills=2), _MID, 11, 12, w)
        assert row.courier_kills == 2
        assert row.fantasy_points == pytest.approx(
            fantasy_score(_od_player(0, courier_kills=0), w) + 2 * w["courier_kills"])

        _add_weights(db)
        players = [_od_player(i, courier_kills=i % 3) for i in range(10)]
        assert ingest._store_match_payload(db, _od(players=players), _MID, 1, w) == "stored"
        stored = _rows(db)
        assert {pid: r.courier_kills for pid, r in stored.items()} == {100 + i: i % 3 for i in range(10)}

    def test_build_stat_row_without_courier_kills_stores_zero(self, db):
        """Failure path: an entry without the courier_kills key (unparsed match) and one with courier_kills=None both store courier_kills == 0, and fantasy_points does not raise."""
        w = _default_weights()
        absent = _od_player(1)
        absent.pop("courier_kills", None)
        null = _od_player(1, courier_kills=None)
        expected = fantasy_score(_od_player(1, courier_kills=0), w)
        for entry in (absent, null):
            row = ingest._build_stat_row(entry, _MID, 11, 12, w)
            assert row.courier_kills == 0
            assert row.fantasy_points == pytest.approx(expected)

    def test_migration_adds_courier_kills_column_to_legacy_db(self, tmp_path):
        """On a legacy file DB whose player_match_stats lacks courier_kills (migrations below 047 recorded as applied), run_migrations adds the column (type INTEGER, default 0) and records '047_pms_courier_kills' in schema_migrations."""
        engine = _legacy_file_engine(tmp_path)
        assert "courier_kills" not in _pms_columns(engine)
        migrate.run_migrations(engine)
        col = _pms_columns(engine)["courier_kills"]
        assert col[2].upper() == "INTEGER"
        assert str(col[4]) == "0"
        with engine.connect() as conn:
            assert migrate._applied(conn, "047_pms_courier_kills")
        assert ("047_pms_courier_kills", migrate._m047_pms_courier_kills) in migrate.MIGRATIONS
        engine.dispose()

    def test_migration_courier_kills_is_idempotent(self, tmp_path):
        """Running run_migrations twice, and calling the migration function directly on a DB that already has the column, raises nothing and leaves exactly one courier_kills column with existing values (e.g. 2) unchanged."""
        engine = _legacy_file_engine(tmp_path, stats=[(1, 10, 3, 4.5)])
        migrate.run_migrations(engine)
        with engine.connect() as conn:
            conn.execute(text("UPDATE player_match_stats SET courier_kills = 2"))
            conn.commit()
        migrate.run_migrations(engine)
        with engine.connect() as conn:
            migrate._m047_pms_courier_kills(conn)
            migrate._m047_pms_courier_kills(conn)
            names = [r[1] for r in conn.execute(text("PRAGMA table_info(player_match_stats)")).fetchall()]
            values = [r[0] for r in conn.execute(text("SELECT courier_kills FROM player_match_stats"))]
        assert names.count("courier_kills") == 1
        assert values == [2]
        engine.dispose()

    # --- Scored -----------------------------------------------------------

    def test_scoring_stats_include_courier_kills_with_label(self):
        """'courier_kills' is in scoring.SCORING_STATS (14 entries, deaths still excluded) and scoring.STAT_LABELS has a non-empty label for it."""
        assert "courier_kills" in SCORING_STATS
        assert len(SCORING_STATS) == 14 and len(set(SCORING_STATS)) == 14
        assert "deaths" not in SCORING_STATS
        assert SCORING_STATS.index("courier_kills") == SCORING_STATS.index("roshan_kills") + 1
        assert scoring.STAT_LABELS["courier_kills"].strip()

    def test_fantasy_score_adds_courier_kills_times_weight(self, db):
        """fantasy_score({"courier_kills": 2, "deaths": 0}, w) - fantasy_score({"deaths": 0}, w) == 2 * w["courier_kills"] for DEFAULT_WEIGHTS (2.0 at weight 1.0); stat_dict_from_row reads courier_kills from an ORM row and from a Core Row."""
        w = _default_weights()
        delta = fantasy_score({"courier_kills": 2, "deaths": 0}, w) - fantasy_score({"deaths": 0}, w)
        assert delta == pytest.approx(2 * w["courier_kills"]) and delta == pytest.approx(2.0)

        db.add(PlayerMatchStats(player_id=1, match_id=1, courier_kills=3))
        db.commit()
        orm = db.query(PlayerMatchStats).one()
        assert stat_dict_from_row(orm)["courier_kills"] == 3
        core = db.execute(text("SELECT s.courier_kills, s.kills, s.deaths FROM player_match_stats s")).first()
        assert stat_dict_from_row(core)["courier_kills"] == 3

    def test_card_points_and_raw_points_include_courier_kills(self, db):
        """After rebuild_all, a card on a player with courier_kills=1 stores card points equal to card_utils._compute_card_points for its stats (courier weight × rarity included), and schedule.game_players raw_points for that player equals display_points(fantasy_score(...)) including the courier weight."""
        _add_weights(db, courier_kills=2.0)
        pids = _seed_game(db, courier={1: 1})
        _seed_cards(db, pids)
        card_points.rebuild_all(db)

        rare = db.get(Card, 2)  # player index 1, the courier killer
        expected = _expected_card_points(db, rare)
        stored = _stored(db)
        assert stored[(2, 900)] == pytest.approx(expected[(2, 900)])
        # The courier kill is worth weight × (1 + rarity) on the card.
        row = _rows(db, 900)[pids[1]]
        weights, rarity = card_utils._load_weights(db)
        without = card_utils._compute_card_points(
            dict(stat_dict_from_row(row), courier_kills=0), "rare", weights, rarity, {"kills": 10.0},
            match_count=1)
        assert stored[(2, 900)] - without == pytest.approx(2.0 * (1 + rarity["mod_rare"]))

        data = schedule.game_players(db, 900)
        raw = {p["player_id"]: p["raw_points"] for t in data["teams"] for p in t["players"]}
        w = _db_weights(db)
        assert raw[pids[1]] == display_points(fantasy_score(stat_dict_from_row(row), w))
        assert fantasy_score(stat_dict_from_row(row), w) - fantasy_score(
            dict(stat_dict_from_row(row), courier_kills=0), w) == pytest.approx(2.0)

    # --- Weight -----------------------------------------------------------

    def test_default_weights_include_courier_kills(self):
        """seed.DEFAULT_WEIGHTS has exactly one entry key 'courier_kills' with label 'Courier kills' and value 1.0."""
        entries = [w for w in DEFAULT_WEIGHTS if w["key"] == "courier_kills"]
        assert entries == [{"key": "courier_kills", "label": "Courier kills", "value": 1.0}]

    def test_seed_weights_adds_courier_kills_to_existing_db_without_touching_others(self, monkeypatch):
        """seed_weights() (seed.SessionLocal patched) on a DB that already has every other weight, some edited away from their defaults (e.g. kills=0.9), inserts courier_kills=1.0 and leaves every other key's value unchanged."""
        monkeypatch.delenv("WEIGHTS_JSON", raising=False)
        Session = _seed_env_session()
        s = Session()
        _add_weights(s, skip=("courier_kills",), kills=0.9, roshan_kills=2.5)
        before = _db_weights(s)
        s.close()
        with patch("seed.SessionLocal", side_effect=Session):
            seed.seed_weights()
        s = Session()
        after = _db_weights(s)
        s.close()
        assert after.pop("courier_kills") == 1.0
        assert after == before
        assert after["kills"] == 0.9 and after["roshan_kills"] == 2.5

    def test_seed_weights_json_overrides_courier_kills(self, monkeypatch):
        """With WEIGHTS_JSON='{"courier_kills": 2.5}', seed_weights() stores courier_kills=2.5 for a new DB and updates an existing courier_kills row to 2.5; GET /weights lists it."""
        monkeypatch.setenv("WEIGHTS_JSON", '{"courier_kills": 2.5}')
        new_db = _seed_env_session()
        with patch("seed.SessionLocal", side_effect=new_db):
            seed.seed_weights()
        s = new_db()
        assert s.get(Weight, "courier_kills").value == 2.5
        s.close()

        existing = _seed_env_session()
        s = existing()
        _add_weights(s)
        assert s.get(Weight, "courier_kills").value == 1.0
        s.close()
        with patch("seed.SessionLocal", side_effect=existing):
            seed.seed_weights()
        s = existing()
        assert s.get(Weight, "courier_kills").value == 2.5
        res = _leaderboard_client(s).get("/weights")
        s.close()
        assert res.status_code == 200
        assert {"key": "courier_kills", "label": "Courier kills", "value": 2.5} in res.json()

    # --- Re-parse ---------------------------------------------------------

    def _store_unparsed(self, db):
        _add_weights(db)
        players = [_od_player(i) for i in range(10)]
        for p in players:
            p.pop("courier_kills", None)
        ingest._store_match_payload(db, _od(version=None, players=players), _MID, 1, _db_weights(db))
        assert db.get(Match, _MID).parse_status == "unparsed"
        from models import User
        db.add(User(id=1, username="alice", email="a@test", password_hash="x"))
        db.add(Card(id=1, player_id=103, owner_id=1, card_type="epic", is_active=False))
        db.commit()
        card_points.rebuild_all(db)
        return players

    def test_refresh_match_stats_stores_courier_kills_on_reparse(self, db, monkeypatch, quiet):
        """A match first stored unparsed (version None, no courier_kills) is refreshed by ingest.refresh_match_stats with a parsed payload where one player has courier_kills=1: returns "refreshed", that row's courier_kills == 1, its fantasy_points include the courier weight, and its stored card points are refreshed to match."""
        self._store_unparsed(db)
        assert all(r.courier_kills == 0 for r in _rows(db).values())
        before_card = _stored(db)[(1, _MID)]
        before_pts = _rows(db)[103].fantasy_points

        parsed = _od(players=[_od_player(i, courier_kills=1 if i == 3 else 0) for i in range(10)])
        _fake_od(monkeypatch, quiet, {_MID: parsed})
        w = _db_weights(db)
        assert ingest.refresh_match_stats(db, _MID, w) == "refreshed"
        db.expire_all()
        rows = _rows(db)
        assert rows[103].courier_kills == 1
        assert all(r.courier_kills == 0 for pid, r in rows.items() if pid != 103)
        assert rows[103].fantasy_points == pytest.approx(fantasy_score(stat_dict_from_row(rows[103]), w))
        assert rows[103].fantasy_points - before_pts == pytest.approx(w["courier_kills"])
        card = db.get(Card, 1)
        after_card = _stored(db)[(1, _MID)]
        assert after_card == pytest.approx(_expected_card_points(db, card)[(1, _MID)])
        assert after_card > before_card

    def test_refresh_match_stats_unparsed_payload_leaves_rows(self, db, monkeypatch, quiet):
        """Failure path: when OpenDota still answers unparsed (version None), refresh_match_stats returns "unparsed" and the stored rows (courier_kills 0, fantasy_points) are unchanged."""
        players = self._store_unparsed(db)
        before = {pid: (r.id, r.courier_kills, r.fantasy_points) for pid, r in _rows(db).items()}
        cards_before = _stored(db)
        still = _od(version=None, players=[dict(p, courier_kills=2) for p in players])
        _fake_od(monkeypatch, quiet, {_MID: still})
        assert ingest.refresh_match_stats(db, _MID, _db_weights(db)) == "unparsed"
        db.expire_all()
        assert {pid: (r.id, r.courier_kills, r.fantasy_points) for pid, r in _rows(db).items()} == before
        assert all(v[1] == 0 for v in before.values())
        assert _stored(db) == cards_before

    # --- Manual matches ---------------------------------------------------

    def test_validate_replay_accepts_courier_kills_zero_to_ten(self, db, quiet):
        """manual_match.STAT_FIELDS["courier_kills"] == (int, 0, 10); validate_replay accepts courier_kills 0 and 10 per player and replay_to_store_payload + store_manual_match store them on the rows."""
        assert manual_match.STAT_FIELDS["courier_kills"] == (int, 0, 10)
        players = [_replay_player(i, courier_kills=10 if i == 0 else 0) for i in range(10)]
        replay = manual_match.validate_replay(_replay(players=players), known_hero_ids=range(1, 200))
        assert [p["courier_kills"] for p in replay["players"]] == [10] + [0] * 9
        assert replay["missing_stats"] == []

        _add_weights(db)
        db.add_all([Team(id=11, name="Alpha"), Team(id=12, name="Bravo")])
        db.commit()
        payload = manual_match.replay_to_store_payload(replay)
        assert ingest.store_manual_match(db, payload, 1, 11, 12, "replay") == "stored"
        rows = _rows(db, replay["match_id"])
        assert {pid: r.courier_kills for pid, r in rows.items()} == {200 + i: (10 if i == 0 else 0)
                                                                      for i in range(10)}
        assert db.get(Match, replay["match_id"]).parse_status == "parsed"

    def test_validate_replay_rejects_courier_kills_out_of_range(self, db):
        """Failure path: courier_kills 11, -1, 1.5 or true on players[0] raises ManualMatchError with field 'players[0].courier_kills' (422) and nothing is stored."""
        for bad in (11, -1, 1.5, True):
            players = [_replay_player(i) for i in range(10)]
            players[0]["courier_kills"] = bad
            with pytest.raises(manual_match.ManualMatchError) as exc:
                manual_match.validate_replay(_replay(players=players), known_hero_ids=range(1, 200))
            assert exc.value.field == "players[0].courier_kills"
            assert exc.value.status_code == 422
        assert db.query(PlayerMatchStats).count() == 0 and db.query(Match).count() == 0

    def test_validate_replay_without_courier_kills_is_partial(self, db, quiet):
        """An older replay JSON without courier_kills is still accepted: every player stores 0, missing_stats lists courier_kills and the match is stored as Partial stats (unparseable)."""
        players = [_replay_player(i) for i in range(10)]
        for p in players:
            p.pop("courier_kills")
        replay = manual_match.validate_replay(_replay(players=players, missing=["stuns"]),
                                              known_hero_ids=range(1, 200))
        assert replay["missing_stats"] == ["courier_kills", "stuns"]
        assert all(p["courier_kills"] == 0 for p in replay["players"])
        _add_weights(db)
        db.add_all([Team(id=11, name="Alpha"), Team(id=12, name="Bravo")])
        db.commit()
        ingest.store_manual_match(db, manual_match.replay_to_store_payload(replay), 1, 11, 12, "replay")
        assert db.get(Match, replay["match_id"]).parse_status == "unparseable"
        assert all(r.courier_kills == 0 for r in _rows(db, replay["match_id"]).values())

    def test_replay_to_match_counts_courier_kills_from_combat_log(self):
        """scripts/replay_to_match.py aggregate(): a DOTA_COMBATLOG_DEATH event whose targetname is a courier and attackername is slot N's hero gives that player courier_kills == 1 (others 0); STAT_ORDER == list(manual_match.STAT_FIELDS); courier_kills is not added to missing_stats when the parser output has combat-log deaths, so a replay import is not marked Partial stats for it."""
        mod = _script()
        assert mod.STAT_ORDER == list(manual_match.STAT_FIELDS)
        from tests.test_issue_224_matches_outside_the_league import _fixture_events
        events = [e for e in _fixture_events(mod) if e.get("type") != "DOTA_COMBATLOG_DEATH"]
        # Lion (slot 6) kills a courier; a summon's courier kill and a hero death are not credited.
        events += [
            {"time": 700, "type": "DOTA_COMBATLOG_DEATH", "attackername": "npc_dota_hero_lion",
             "targetname": "npc_dota_courier"},
            {"time": 800, "type": "DOTA_COMBATLOG_DEATH", "attackername": "npc_dota_lone_druid_bear1",
             "targetname": "npc_dota_courier"},
            {"time": 900, "type": "DOTA_COMBATLOG_DEATH", "attackername": "npc_dota_hero_lion",
             "targetname": "npc_dota_hero_axe"},
        ]
        out = mod.aggregate(events)
        assert [p["courier_kills"] for p in out["players"]] == [1 if s == 6 else 0 for s in range(10)]
        assert "courier_kills" not in out["missing_stats"]
        assert manual_match.validate_replay(json.loads(json.dumps(out))) == out

        # Two-word hero names map through both combat-log spellings (shadow_shaman, slot 4).
        events2 = [e for e in events if e.get("type") != "DOTA_COMBATLOG_DEATH"] + [
            {"time": 700, "type": "DOTA_COMBATLOG_DEATH", "attackername": "npc_dota_hero_shadow_shaman",
             "targetname": "npc_dota_courier"}]
        assert [p["courier_kills"] for p in mod.aggregate(events2)["players"]] == \
            [1 if s == 4 else 0 for s in range(10)]

        # Without any combat-log deaths the counter is unknown: 0 and listed as missing.
        bare = mod.aggregate([e for e in events if e.get("type") != "DOTA_COMBATLOG_DEATH"])
        assert "courier_kills" in bare["missing_stats"]
        assert all(p["courier_kills"] == 0 for p in bare["players"])


# ===========================================================================
# Story 2: Past Points Stay the Same
# ===========================================================================

def _snapshot_readers(db):
    from tests.test_issue_141_stored_card_points import _all_readers
    return _all_readers(db)


class TestPastPointsStayTheSame:

    def test_migration_sets_existing_rows_courier_kills_to_zero(self, tmp_path):
        """Stat rows stored before the migration read courier_kills == 0 (not NULL) afterwards, and their other stats and fantasy_points are unchanged."""
        engine = _legacy_file_engine(tmp_path, stats=[(1, 10, 3, 4.5), (2, 10, 7, 9.25)])
        with engine.connect() as conn:
            before = [tuple(r) for r in conn.execute(text(
                "SELECT player_id, match_id, kills, roshan_kills, fantasy_points FROM player_match_stats "
                "ORDER BY player_id"))]
        migrate.run_migrations(engine)
        with engine.connect() as conn:
            after = [tuple(r) for r in conn.execute(text(
                "SELECT player_id, match_id, kills, roshan_kills, fantasy_points, courier_kills "
                "FROM player_match_stats ORDER BY player_id"))]
        assert [r[:5] for r in after] == before
        assert [r[5] for r in after] == [0, 0]
        engine.dispose()

    def test_card_points_unchanged_after_courier_weight_added(self, db):
        """Seed cards and stats (courier_kills 0) without a courier_kills weight and rebuild_all; add the weight (1.0); ensure_card_points_current returns a row count (it rebuilt because the fingerprint changed) and every card_match_points value, weekly and season leaderboard total and roster total is identical."""
        from tests.test_issue_141_stored_card_points import _seed
        _seed(db)
        assert db.get(Weight, "courier_kills") is None
        assert all((r.courier_kills or 0) == 0 for r in db.query(PlayerMatchStats))
        assert card_points.ensure_card_points_current(db) is None  # already current
        stored_before, readers_before = _stored(db), _snapshot_readers(db)
        assert stored_before

        db.add(Weight(key="courier_kills", label="Courier kills", value=1.0))
        db.commit()
        rebuilt = card_points.ensure_card_points_current(db)
        assert isinstance(rebuilt, int) and rebuilt == len(stored_before)
        assert _stored(db) == stored_before
        assert _snapshot_readers(db) == readers_before

    def test_raw_points_fantasy_points_and_accolades_unchanged_after_courier_weight_added(self, db):
        """With the same before/after setup, schedule.game_players raw_points, every PlayerMatchStats.fantasy_points and accolades.compute_awards(db) values are identical."""
        _add_weights(db, skip=("courier_kills",))
        _seed_game(db, 900)
        _seed_game(db, 901)

        def snapshot():
            schedule._game_players_cache.clear()
            raw = {mid: {p["player_id"]: p["raw_points"]
                         for t in schedule.game_players(db, mid)["teams"] for p in t["players"]}
                   for mid in (900, 901)}
            pts = {(r.player_id, r.match_id): r.fantasy_points for r in db.query(PlayerMatchStats)}
            return raw, pts, json.loads(json.dumps(accolades.compute_awards(db)))

        before = snapshot()
        assert before[2]  # awards computed from the seeded matches
        db.add(Weight(key="courier_kills", label="Courier kills", value=1.0))
        db.commit()
        card_points.ensure_card_points_current(db)
        assert snapshot() == before

    def test_upgrade_never_refetches_past_matches(self, tmp_path, monkeypatch):
        """Failure path: with ingest.opendota_get_json / opendota_post_json patched to fail the test if called, run_migrations, seed_weights (SessionLocal patched) and ensure_card_points_current complete without any OpenDota request."""
        def _fail(*a, **k):
            pytest.fail(f"OpenDota was called: {a}")
        monkeypatch.setattr(ingest, "opendota_get_json", _fail)
        monkeypatch.setattr(ingest, "opendota_post_json", _fail)
        monkeypatch.setattr(ingest, "request_parse", _fail)
        monkeypatch.delenv("WEIGHTS_JSON", raising=False)

        engine = _legacy_file_engine(tmp_path, stats=[(1, 10, 3, 4.5)])
        Session = sessionmaker(bind=engine)
        s = Session()
        _add_weights(s, skip=("courier_kills",))
        s.add(Match(match_id=10, league_id=1, start_time=100, parse_status="unparsed"))
        s.commit()
        s.close()

        migrate.run_migrations(engine)
        with patch("seed.SessionLocal", side_effect=Session):
            seed.seed_weights()
        s = Session()
        assert card_points.ensure_card_points_current(s) is not None
        assert s.get(Weight, "courier_kills").value == 1.0
        assert s.query(PlayerMatchStats).one().fantasy_points == 4.5
        s.close()
        engine.dispose()


# ===========================================================================
# Story 3: See Courier Kills in the Stats and the Rules
# ===========================================================================

class TestSeeCourierKillsInStatsAndRules:

    # --- Player popup -----------------------------------------------------

    def test_get_player_match_history_includes_courier_kills(self, db):
        """GET /players/{id}: each match_history row has courier_kills (1 for a game with one courier kill) and its points_breakdown still sums to fantasy_points within display rounding."""
        _add_weights(db)
        pids = _seed_game(db, 900, courier={1: 1})
        _seed_game(db, 901)
        res = _players_client(db).get(f"/players/{pids[1]}")
        assert res.status_code == 200, res.text
        history = {m["match_id"]: m for m in res.json()["match_history"]}
        assert history[900]["courier_kills"] == 1
        for m in history.values():
            assert sum(m["points_breakdown"].values()) == pytest.approx(m["fantasy_points"], abs=0.06)
        assert history[900]["points_breakdown"]["objectives"] >= 1.0

    def test_points_by_source_objectives_include_courier_kills(self):
        """player_insights.SOURCE_GROUPS 'objectives' == ["towers_killed", "roshan_kills", "courier_kills"]; the groups still cover SCORING_STATS + deaths exactly; points_by_source puts courier_kills × weight into 'objectives'."""
        groups = {k: g for k, _, g in player_insights.SOURCE_GROUPS}
        assert groups["objectives"] == ["towers_killed", "roshan_kills", "courier_kills"]
        covered = [s for _, _, g in player_insights.SOURCE_GROUPS for s in g]
        assert sorted(covered) == sorted(SCORING_STATS + ["deaths"])
        w = _default_weights(courier_kills=1.5)
        base = {"kills": 3, "deaths": 2, "towers_killed": 1, "roshan_kills": 1}
        without = player_insights.points_by_source(base, w)
        with_ck = player_insights.points_by_source(dict(base, courier_kills=2), w)
        assert with_ck["objectives"] - without["objectives"] == pytest.approx(3.0)
        assert {k: v for k, v in with_ck.items() if k != "objectives"} == \
            {k: v for k, v in without.items() if k != "objectives"}
        assert sum(with_ck.values()) == pytest.approx(fantasy_score(dict(base, courier_kills=2), w))

    def test_popup_match_stats_lists_courier_kills_after_roshan(self):
        """Node harness (test_issue_208 _js): _popupMatchStats lists a courier-kills entry immediately after "Roshan" showing m.courier_kills."""
        out = _popup_js('out = _popupMatchStats({roshan_kills: 2, courier_kills: 3, duration: 1800});')
        labels = [k for k, _ in out]
        i = labels.index("Roshan")
        assert out[i] == ["Roshan", 2]
        assert out[i + 1] == ["Courier kills", 3]

    def test_popup_match_stats_missing_courier_kills_shows_zero(self):
        """Failure path: a match object without courier_kills (or null) shows 0 for the courier-kills entry, not "undefined"/"null"."""
        out = _popup_js("""
const a = Object.fromEntries(_popupMatchStats({duration: 60}));
const b = Object.fromEntries(_popupMatchStats({courier_kills: null, duration: 60}));
out = [a["Courier kills"], b["Courier kills"]];
""")
        assert out == [0, 0]

    # --- How to Play ------------------------------------------------------

    def test_how_to_play_scoring_list_includes_courier_kills(self):
        """frontend/app-init.js loadHowToPlay: statsKeys contains 'courier_kills' and statsLabels maps it to 'Courier kills'; the row's value comes from byKey['courier_kills'] like the others (Node or source check)."""
        js = _read("frontend", "app-init.js")
        start = js.index("async function loadHowToPlay(")
        fn = js[start:js.index("\n}\n", start) + 2]
        keys = re.search(r"const statsKeys = \[(.*?)\];", fn, re.S).group(1)
        keys = re.findall(r"'([a-z_]+)'", keys)
        assert keys.index("courier_kills") == keys.index("roshan_kills") + 1
        assert "courier_kills:           'Courier kills'," in fn

        weights = [{"key": w["key"], "label": w["label"], "value": w["value"]} for w in DEFAULT_WEIGHTS]
        for w in weights:
            if w["key"] == "courier_kills":
                w["value"] = 1.75
        script = """
const els = {};
const document = { getElementById(id) { return els[id] || (els[id] = {innerHTML: "", textContent: ""}); } };
const API = "";
function loadObsOverlayBuilder() {}
const fetch = async () => ({ ok: true, json: async () => %s });
%s
loadHowToPlay().then(() => console.log(JSON.stringify(els["howtoplay-stats-tbody"].innerHTML)));
""" % (json.dumps(weights), fn)
        html = _run_node(script)
        assert "<tr><td>Roshan kills</td><td>1</td></tr><tr><td>Courier kills</td><td>1.75</td></tr>" in html

    # --- Point simulator --------------------------------------------------

    def _seed_sim(self, db, courier=1, assists=4):
        _add_weights(db)
        db.add(Match(match_id=_MID, league_id=1, start_time=100, radiant_team_id=1, dire_team_id=2))
        db.add(Player(id=1, name="Courier hunter"))
        db.add(PlayerMatchStats(player_id=1, match_id=_MID, team_id=1, kills=2, deaths=1,
                                assists=assists, courier_kills=courier, gold_per_min=400))
        db.commit()

    def test_simulate_courier_kills_weight_override_and_stats(self, db):
        """simulate_match(mid, db, SimulateBody(courier_kills=5.0)) for a player with courier_kills=1: weights_used['courier_kills'] == 5.0, players[].stats['courier_kills'] == 1, and fantasy_points == display_points(fantasy_score(stats, weights_used), 2) including 5.0; without the override weights_used takes the DB value."""
        from routers.leaderboard import SimulateBody, simulate_match
        self._seed_sim(db)
        out = simulate_match(_MID, db, SimulateBody(courier_kills=5.0))
        assert out["weights_used"]["courier_kills"] == 5.0
        p = out["players"][0]
        assert p["stats"]["courier_kills"] == 1
        assert p["fantasy_points"] == display_points(fantasy_score(p["stats"], out["weights_used"]), 2)
        assert fantasy_score(p["stats"], out["weights_used"]) - fantasy_score(
            dict(p["stats"], courier_kills=0), out["weights_used"]) == pytest.approx(5.0)

        default = simulate_match(_MID, db, SimulateBody())
        assert default["weights_used"]["courier_kills"] == _db_weights(db)["courier_kills"] == 1.0

    def test_simulate_scores_assists(self, db):
        """Pre-existing gap fixed alongside: simulate reads assists from the row, reports them in stats, scores them with the DB weight and takes an `assists` override."""
        from routers.leaderboard import SimulateBody, simulate_match
        self._seed_sim(db, assists=4)
        w = _db_weights(db)
        out = simulate_match(_MID, db, SimulateBody())
        p = out["players"][0]
        assert p["stats"]["assists"] == 4
        assert out["weights_used"]["assists"] == w["assists"]
        assert p["fantasy_points"] == display_points(fantasy_score(p["stats"], out["weights_used"]), 2)
        assert p["fantasy_points"] == display_points(
            fantasy_score(stat_dict_from_row(db.query(PlayerMatchStats).one()), w), 2)
        over = simulate_match(_MID, db, SimulateBody(assists=1.0))
        assert over["weights_used"]["assists"] == 1.0
        assert over["players"][0]["fantasy_points"] == pytest.approx(
            p["fantasy_points"] + 4 * (1.0 - w["assists"]), abs=0.011)
        from routers.leaderboard import _SIMULATE_DOCS
        assert "assists" in _SIMULATE_DOCS["request_body"]["fields"]
        assert "assists" in _SIMULATE_DOCS["response"]["players"][0]["stats"]

    def test_simulate_docs_list_courier_kills(self, db):
        """GET /simulate (_SIMULATE_DOCS) lists courier_kills under request_body.fields and under response.players[0].stats."""
        res = _leaderboard_client(db).get("/simulate")
        assert res.status_code == 200
        docs = res.json()
        assert "courier kill" in docs["request_body"]["fields"]["courier_kills"]
        assert docs["response"]["players"][0]["stats"]["courier_kills"] == "integer"

    def test_simulate_rejects_non_numeric_courier_kills(self, db):
        """Failure path: SimulateBody with courier_kills='lots' fails validation (422 through POST /simulate/{match_id})."""
        from routers.leaderboard import SimulateBody
        with pytest.raises(ValidationError):
            SimulateBody(courier_kills="lots")
        self._seed_sim(db)
        res = _leaderboard_client(db).post(f"/simulate/{_MID}", json={"courier_kills": "lots"})
        assert res.status_code == 422
        assert any("courier_kills" in e["loc"] for e in res.json()["detail"])

    # --- Partial stats ----------------------------------------------------

    def test_partial_stats_tooltip_names_courier_kills(self):
        """frontend/app-players.js _PARTIAL_STATS_TOOLTIP mentions courier kills among the stats an unparsed replay counts as 0 (and the pins in test_unparseable_match_handling, test_issue_244 and test_issue_208 are updated to the same text)."""
        tip = "The replay has not been parsed, so wards, stuns, teamfight, runes, camps and courier kills count as 0."
        assert f'const _PARTIAL_STATS_TOOLTIP = "{tip}";' in _read("frontend", "app-players.js")
        for name in ("test_unparseable_match_handling.py", "test_issue_244_schedule_player_performance.py",
                     "test_issue_208_player_popup_visualizations.py"):
            src = _read("backend", "tests", name)
            assert "runes, camps and courier kills count as 0" in src, name
            assert "runes and camps count as 0" not in src, name


# ===========================================================================
# Story 4: Card Modifiers Leave Courier Kills Out
# ===========================================================================

class TestCardModifiersLeaveCourierKillsOut:

    def test_assign_modifiers_never_picks_courier_kills(self, db):
        """For rare, epic and legendary cards with modifier_count set >= the pool size (or random.sample recorded), _assign_modifiers never adds a CardModifier with stat_key 'courier_kills'; a common card (count 0) gets none."""
        big = len(SCORING_STATS) + 5
        weights = _default_weights(modifier_count_rare=big, modifier_count_epic=big,
                                   modifier_count_legendary=big, modifier_count_common=0)
        for cid, rarity in enumerate(("common", "rare", "epic", "legendary"), start=1):
            card = Card(id=cid, player_id=1, owner_id=1, card_type=rarity)
            db.add(card)
            db.flush()
            card_utils._assign_modifiers(db, card, weights)
        db.commit()
        chosen = {}
        for m in db.query(CardModifier):
            chosen.setdefault(m.card_id, set()).add(m.stat_key)
        assert 1 not in chosen
        for cid in (2, 3, 4):
            assert chosen[cid] == set(_POOL)
            assert "courier_kills" not in chosen[cid]

    def test_modifier_pool_keeps_every_other_stat_and_deaths(self):
        """card_utils._SCORED_STAT_COLS == every SCORING_STATS entry except courier_kills, plus 'deaths' (set equality, no duplicates)."""
        pool = card_utils._SCORED_STAT_COLS
        assert len(pool) == len(set(pool))
        assert set(pool) == set(_POOL)
        assert card_utils.NO_MODIFIER_STATS == {"courier_kills"}

    def test_existing_card_modifiers_unchanged_after_upgrade(self, tmp_path):
        """Failure path: card_modifiers rows on a legacy DB (kills, deaths, roshan_kills) are byte-identical after run_migrations adds courier_kills, and the card_modifiers DDL is not rebuilt."""
        engine = _legacy_file_engine(tmp_path)
        with engine.connect() as conn:
            for key in ("kills", "deaths", "roshan_kills"):
                conn.execute(text("INSERT INTO card_modifiers (card_id, stat_key, bonus_pct) VALUES (1, :k, 10.0)"),
                             {"k": key})
            conn.commit()

        def snapshot():
            with engine.connect() as conn:
                rows = [tuple(r) for r in conn.execute(text("SELECT * FROM card_modifiers ORDER BY id"))]
                ddl = conn.execute(text(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='card_modifiers'")).scalar()
            return rows, ddl

        before = snapshot()
        migrate.run_migrations(engine)
        assert snapshot() == before
        assert "courier_kills" in _pms_columns(engine)
        engine.dispose()

    def test_modifier_values_leave_courier_kills_out(self, db):
        """player_insights.modifier_values (player popup and team popup 'A +10 % modifier is worth most on') lists every modifier-pool stat and no 'courier_kills' row, even for a player with courier kills."""
        w = _default_weights(courier_kills=50.0)
        scored = [{"kills": 3, "deaths": 1, "courier_kills": 2, "gold_per_min": 400}] * 3
        mv = player_insights.modifier_values(scored, w)
        stats = [r["stat"] for r in mv["stats"]]
        assert "courier_kills" not in stats
        assert sorted(stats) == sorted(_POOL)

        # Through GET /players/{id} as well.
        _add_weights(db, courier_kills=50.0)
        pids = _seed_game(db, 900, courier={1: 2})
        data = _players_client(db).get(f"/players/{pids[1]}").json()
        assert "courier_kills" not in [r["stat"] for r in data["modifier_values"]["stats"]]
        assert data["modifier_values"]["stats"]

    def test_cards_doc_modifier_targets_exclude_courier_kills(self):
        """markdown/features/core/cards.md: the 'Valid modifier targets' line does not include courier_kills, and the scoring formula lists courier_kills × its weight."""
        doc = _read("markdown", "features", "core", "cards.md")
        targets = next(line for line in doc.splitlines() if line.startswith("Valid modifier targets"))
        assert "courier_kills" not in targets and "roshan_kills" in targets
        assert re.search(r"\+ courier_kills\s+× courier_weight", doc)
