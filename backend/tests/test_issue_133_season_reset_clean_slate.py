"""
Tests for plan-issue-133-season-reset-clean-slate.md (resolves GitHub issue #133).

Reset Season clears every season table (including weekly_summaries,
weekly_summary_reveals, weekly_summary_seen, live_matches, match_timings and the
demo clock override) and the in-memory season caches; End Season stores a season
summary (season_player_stats, season_team_results) and lets the admin choose its
parts (awards, champions, Played, summary); the pre-reset backup is a permanent
season backup (`fantasy.db.season-<label>-<timestamp>`); and a guided flow leads
from End Season to a Reset preview (`GET /admin/season/reset-preview`). One class
per user story, one stub per acceptance criterion plus the primary failure path.

Developer notes
---------------

  Existing code these tests target (verified 2026-11-17)
    - backend/routers/admin_season.py is 229 lines; test_issue_85
      (`test_no_new_admin_module_exceeds_350_lines`) caps every
      routers/admin_*.py at 350. Two new routes (`POST /admin/season/summary`,
      `GET /admin/season/reset-preview`), four booleans and the reset list will
      not fit if written inline: keep the routes thin and put the work in
      `season_summary.py` (summary build/store) and a reset helper module (e.g.
      `season_reset.py`: CLEARED_TABLES / KEPT_TABLES, `preview(db)`,
      `clear(db)`, `bust_caches()`).
    - `SeasonEndBody(season_label: str 1..100, champions: list[SeasonEndChampions]
      | None, max 2)`; `SeasonResetBody(force: bool = False)`. Reset takes NO
      label today, yet the season backup must be named after one: decide where
      it comes from (suggest: the newest `season_archive.season_label` by
      `archived_at`, else `accolades.current_season_label(db)` read BEFORE the
      leagues are unmonitored) and show it in the preview.
    - Route dependencies: `require_recent_reauth` then
      `require_typed_confirmation("<action>")` (deps.py; phrases in
      `deps.CONFIRM_PHRASES`: season_end "END SEASON", season_reset "RESET
      SEASON", backup_download "DOWNLOAD BACKUP"; mirrored in
      `ADMIN_CONFIRM_PHRASES` in frontend/app-admin.js ~line 320). The summary
      route needs one: reuse "season_end" or add a "season_summary" phrase to
      BOTH lists. `require_typed_confirmation` reads `confirm` from the query or
      the JSON body; `require_admin` checks the database.
    - `end_season`: 409 "Season '<label>' is already archived"; writes
      SeasonArchive rows from `routers.leaderboard.compute_season_standings`,
      then `accolades.record_season(db, label, champions, actor_id)` inside
      try/except -> rollback + 500 "Recording accolades failed; nothing was
      archived" (pinned verbatim by test_issue_50). Audit
      "admin_season_archived" detail `season_label=… users=N accolades=N
      champions=M` (test_issue_50 pins "accolades=8 champions=2"). Response keys
      today: season_label, archived_users, accolades, awards, champions, played,
      + note / warning. Keep all of them; add a `parts` dict (pinned below).
      Call the summary build inside the same try block, before the commit.
    - `accolades.record_season` does three things in one: awards via
      `compute_awards` + `insert_ignore` (AWARD_KINDS most_points, best_average,
      best_match, most_mvps PLUS fantasy_winner rows), champions via
      `insert_ignore`, played via `played_player_ids` + `insert_ignore`, then
      `grant_winner_tag(db, user_id, actor_id)` for each fantasy winner. Its
      `awards` count INCLUDES fantasy_winner rows. Split it into
      record_awards / record_champions / record_played (keep record_season as a
      wrapper: test_issue_50 monkeypatches `accolades.record_season` to force a
      failure, so end_season must still call something that the patch reaches,
      or update that test). The winner tag belongs to the awards part.
    - `accolades_preview` (GET /admin/season/accolades-preview) takes NO label
      today; `season_label` is `accolades.current_season_label(db)` and
      `champions_recorded` is {div: count} for that label. Add an optional
      `season_label` query param (bounded, max 100) and `recorded` counts per
      kind for it; calls without it must keep working (test_issue_50,
      test_issue_248). The dialog loads the preview BEFORE the admin edits the
      label, so the counts must be re-fetched (or fetched per label) when the
      label changes.
    - accolades.KINDS also has runner_up / third_place (set_placement, issue
      233), which End Season never records.
    - Raw points: `scoring.fantasy_score(stat_dict_from_row(row), weights)`,
      weights `{w.key: w.value for w in db.query(Weight)}` (see
      `schedule.game_players`, issue 244: no rarity, no modifiers, NO MVP
      bonus). The awards use stored `fantasy_points`, which INCLUDES the MVP
      bonus, so the summary's best game can differ from the Best Single Match
      award. Excluded games: `match_scoring.scored_match_sql("m")` on a joined
      matches row (or `scored_stat_sql()` without a join).
      `display_points` rounds to one decimal: store exact or rounded, but say
      which (stubs compare with display_points).
    - Player wins: `player_insights.won(team_id, radiant_team_id,
      dire_team_id, radiant_win)` with the stat row's team_id (None = unknown,
      not a loss). A player can play for several teams in a season: the plan's
      single "team name" is underspecified; suggest the team with most scored
      games (ties by name).
    - Team rows: `team_insights.team_list(db, data)` already returns, per row of
      `teams`, `division` (team_insights.team_divisions: from league names,
      "Lower" = div2, None when unknown), `series_wins`, `series_losses`,
      `series_draws`, `wins`, `losses`, `matches` (scored games). Series come
      from the SCHEDULE FEED (`team_insights.feed_series` ->
      `schedule.get_schedule`, which fetches over HTTP when its cache is cold
      and the feed env is set; `feed_data` returns {} on failure, then series
      are 0). Draws exist (a 1-1 group series): the plan's "series won and
      lost" drops them; store `series_drawn` too. `schedule.resolve_series_result`
      resolves one named pair only; `finals.standings` is Div 1 only. Tests must
      stub `schedule.get_schedule` (or `team_insights.feed_data`) so End
      Season never reaches the network.
    - Week ids ARE reused. `Week.id` is `Integer, primary_key=True,
      autoincrement=True` with no `sqlite_autoincrement`, so the table is
      `id INTEGER NOT NULL PRIMARY KEY` (rowid alias, no AUTOINCREMENT keyword;
      migrate.py never rebuilds weeks). Checked with an in-memory engine: three
      weeks (1, 2, 3), delete all, the next week gets id 1; deleting only the
      max id also reuses it. PRAGMA foreign_keys is OFF, so stale
      weekly_summary_* rows survive the weeks delete. Tables keyed by week id:
      weekly_roster_entries, weekly_summaries (PK), weekly_summary_reveals,
      weekly_summary_seen.last_seen_week_id / last_prompted_week_id,
      matches.week_override_id.
    - Demo clock: `clock.clear_override(db)` sets `override_timestamp=None` on
      the singleton DemoClock row (id 1) and keeps the row; it does not commit.
      Count it as cleared (1/0) but don't delete the row, or delete it: either
      way `clock.get_override(db)` must be None after reset.
    - In-memory season caches and their clear functions (grep verified; there
      is NO accolades or history cache, contrary to the plan):
        schedule._cache + schedule._game_players_cache -> schedule.bust_cache()
          (hero icon/name caches are not season data; leave them)
        twitch._panel_cache -> twitch.bust_panel_cache()
        finals._public_cache / _available_cache / _site_cache -> finals.clear_caches()
        team_insights._league_cache + _list_cache -> team_insights.clear_league_cache()
        player_insights._league_cache -> player_insights.clear_league_cache()
      Not season data: player_lookup._lookup_cache (OpenDota names),
      toornament._token_cache, ingest._league_status / _parse_requested (ingest
      bookkeeping keyed by league / match id; optional to clear).
      Bust the caches AFTER db.commit() so a request in between can't refill
      them with the old season.
    - Tables (models.py, 55 model classes; plus the raw `schema_migrations`
      table created by migrate.py, which has no model and is not in
      Base.metadata). Plan lists, checked against every __tablename__:
        cleared (delete): matches, player_match_stats, card_match_points,
          match_bans, weeks, weekly_roster_entries, twitch_mvp,
          twitch_token_drops, players, teams, cards, card_modifiers,
          own_player_card_grants, weekly_summaries, weekly_summary_reveals,
          weekly_summary_seen, live_matches, match_timings
        updated, not deleted: users (tokens), leagues (is_monitored),
          demo_clock (override) -- the plan names none of them in the kept
          list; the module constant needs a third "updated" group or must put
          them in KEPT.
        kept per plan: users, tag_definitions, user_tags, audit_logs,
          season_archive, season_accolades, finals_brackets,
          finals_predictions, team_signup_periods, team_signups,
          team_signup_players, promo_codes, token_grant_events, notifications,
          weights, player_profiles, twitch_mvp_polls, twitch_pending_tokens,
          + new season_player_stats, season_team_results
        FORGOTTEN by the plan (decide; suggested kept unless noted):
          leagues, code_redemptions, token_grant_claims (pairs with
          token_grant_events), notification_dismissals (pairs with
          notifications), twitch_mvp_votes (pairs with twitch_mvp_polls;
          already purged 30 days after the poll), twitch_link_codes,
          twitch_oauth_states, steam_login_states, steam_openid_nonces,
          steam_pending_signups, twitch_merge_log, twitch_starter_grants,
          twitch_channel_approvals, password_reset_tokens, user_sessions,
          twitch_presence, toornament_sync_log, scoring_state (holds
          card_points.FINGERPRINT_KEY: keep), demo_clock, schema_migrations
          (raw; exclude from the check, or list it explicitly).
      The coverage test compares the lists with `Base.metadata.tables`.
    - Backups (database.py): `backup_sqlite_db()` writes
      `{db}.backup-%Y%m%d-%H%M%S` (mode 0600), returns the path or None for a
      non-SQLite URL / missing file. `list_sqlite_backups()` globs
      `{db.name}.backup-*` newest first, so `fantasy.db.season-*` is ALREADY
      outside it and outside `cleanup_old_backups(retention_days)` (which
      iterates list_sqlite_backups). Add a second list (e.g.
      `list_season_backups()`) and `backup_sqlite_db(kind="season", label=…)`
      (trailing optional params). All read `database.DATABASE_URL` at call time:
      tests point it at tmp_path (`db_file_env` in test_issue_132).
    - routers/admin_backups.py (75 lines): GET /admin/backups returns
      {retention_days, backups}; add e.g. `season_backups` beside it.
      download_backup matches the filename ONLY against list_sqlite_backups()
      basenames (never joins a path) behind require_recent_reauth +
      typed confirmation "backup_download"; extend the lookup to season
      backups the same way. create_backup's 60 s cooldown reads
      list_sqlite_backups()[0]: season files don't count.
    - .gitignore ignores `data/*.backup-*` only: `git check-ignore
      data/fantasy.db.season-Season-16-20261117-120000` is NOT ignored today, so
      a season backup (password hashes, emails) could be committed. Add
      `data/*.season-*`. .dockerignore already drops `data/` and `*.db.backup-*`
      (add `*.db.season-*` too).
    - Reset's response today: {status, initial_tokens, counts, kept:
      {"season_accolades": N}, backup_path} (full path). Add `backup_file`
      (basename) for the result line.
    - Frontend: End Season = `endSeason()` (loads accolades-preview, fills
      #endSeasonModal: #endSeasonDialogLabel, #endSeasonAwards, #endSeasonPlayed,
      #endSeasonTeam_div1/2, #endSeasonPlayers_*, #endSeasonAdd_*,
      #endSeasonChampWarning, #endSeasonContinueBtn) -> `confirmEndSeason()`
      CLOSES the dialog, then `typedConfirm("season_end", …)`, POSTs, and writes
      the result to the status line #seasonLifecycleStatus. So "the dialog's
      result" in the plan is really that status line (or a new result area):
      pick one; the stub only pins the text and the button. Reset =
      `openSeasonResetConfirm()` / `confirmSeasonReset()` on #seasonResetModal
      (index.html ~line 1819; shown with style.display, not the hidden class),
      typed input #seasonResetConfirmInput, status #seasonResetModalStatus;
      success writes "Season reset complete". Backups panel: `loadBackups()` in
      app-admin-backups.js fills #dbBackupsBody, "No backups yet",
      `downloadBackup(filename)` through adminFetch + typedConfirm.

  Existing tests that pin this code (update them with the change)
    - Zero-argument backup stubs: `lambda: …` patched onto
      `routers.admin_season.backup_sqlite_db` in test_issue_81 (`_stub_backup`,
      pinned verbatim by test_issue_85 line 183), test_issue_135 (1251 path,
      1262 None = the abort test), test_issue_141 (596), test_issue_50 (421,
      assigned directly), test_issue_150 (1411), test_issue_220 (1208),
      test_issue_237 (915). Calling `backup_sqlite_db(kind=…, label=…)` breaks
      all of them (TypeError); calling a NEW function name instead leaves them
      unpatched and backs up the real data/fantasy.db. Change the stubs to
      `lambda *a, **k: …` (keeping the `monkeypatch.setattr(admin_season_module,
      "backup_sqlite_db"` text test_issue_85 greps for).
    - test_issue_50 `test_season_reset_keeps_all_accolade_rows`:
      `result["kept"] == {"season_accolades": 3}` (exact) and audit detail
      contains "kept_season_accolades=3". The plan's kept dict lists every kept
      table: change it to `result["kept"]["season_accolades"] == 3` and keep the
      audit token.
    - test_issue_188 `test_season_reset_clears_grants` greps
      `inspect.getsource(admin_season.reset_season)` for
      `"own_player_card_grants": db.query(OwnPlayerCardGrant).delete(` --
      breaks when the deletes move to a helper; point it at the helper.
    - test_issue_81 `TestSeasonReset` (seed: `_seed_full_season_state`),
      asserts `result["counts"]["matches"] == 1` and "matches=1" in the audit
      detail; test_issue_141 asserts `counts["card_match_points"] > 0`;
      test_issue_135 asserts `result["backup_path"] == backup`.
    - test_issue_237 `test_season_reset_keeps_finals_tables`; test_issue_220
      `test_season_reset_leaves_listings_intact` (team signup tables kept).
    - test_issue_150 `_destructive_request`: season_end posts
      {"season_label": "S16"} through the full app (End Season will now build
      the summary: stub the schedule feed there if it reaches the network);
      backup_download patches only `admin_backups.list_sqlite_backups`.
    - test_issue_132: `_BACKUP_NAME_RE = ^fantasy\\.db\\.backup-\\d{8}-\\d{6}$`
      for POST /admin/backups (default kind must keep that name), list tests
      assert exact name lists (`names == [backup.name]`), "No backups yet" in
      app-admin-backups.js, `<script src="/app-admin-backups.js">`.
      test_db_sustainability and test_issue_126 pin scripts/backup-db.sh and
      .gitignore's `data/*.backup-*` line (keep it, add the season line).
    - test_issue_214: SETTINGS_TAB_IDS_BEFORE_214 keeps endSeasonLabel,
      seasonArchivesBody, seasonLifecycleStatus, dbBackupsRetention,
      createBackupBtn, dbBackupsBody, dbBackupsStatus; the Season section's
      LAST button must be `<button class="danger"
      onclick="openSeasonResetConfirm()">Reset Season…</button>` and its last
      panel title "Season Lifecycle" (put the Continue button and preview lists
      inside the modals, which live outside the section). Lessons: a new
      Settings panel goes before the danger panel and updates the panel count.
    - test_issue_50 `test_end_season_dialog_champion_picker_and_warning_source`:
      in `confirmEndSeason`, `_endSeasonChampions()` comes before
      `typedConfirm("season_end"` and "champions" appears after JSON.stringify;
      the HTML keeps "No champions recorded; add them in Player management".
      test_issue_248 pins `_END_SEASON_AWARDS` (most_mvps after best_match).
      test_issue_213 drives adminFetch("/admin/season/end").
      test_issue_117: `loadBackups` has no "download=".

  Reusable helpers / fixtures
    - test_issue_50: `db` (StaticPool), `_user`, `_client(db, login, reauth)`
      (mounts admin_season among others, signed session + re-auth),
      `_admin_client(db)`, `_acc(...)`, `_rows`, `_audits`, `_seed_season(db)`
      (players 1-4, teams 100 "Reds"/200 "Blues", match 1004 excluded),
      `_standings(monkeypatch, rows)`, `_end(db, label, champions)`.
      Copy what you need rather than importing fixtures.
    - test_issue_81 `TestSeasonReset._seed_full_season_state(db)` (league,
      player, team, match, stats, ban, MVP, drop, user, card, week, roster).
    - test_issue_132 `db_file_env` (DATABASE_URL -> tmp_path/fantasy.db) and its
      `_make_backup(db_file, suffix, mtime)`-style helper (line ~98).
    - test_issue_244 `_seed_game` / `_expected_raw` for raw points.
    - Node harness for frontend logic: `_fn_source`, `_run_node` (test_issue_50).

  Pitfalls
    - Lessons: plain `:memory:` is invisible to TestClient threads; use the
      StaticPool `db` below. Point backups at tmp_path, never data/fantasy.db.
    - New tables come from create_all; no migrate.py change, but
      test_migrate's coverage test still runs.
    - Unique keys: season_player_stats (season_label, player_id),
      season_team_results (season_label, team_id): no nullable parts.
    - Season label in a file name: reduce to [A-Za-z0-9-] (spaces -> "-"),
      collapse repeats, cap the length, and fall back (e.g. "season") when
      nothing is left; the result must never contain "/" or "..".
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Float, Integer, String, Text, select, text
from starlette.middleware.sessions import SessionMiddleware

# Registers every existing table on Base before the db fixture runs create_all.
import models  # noqa: F401
import accolades
import clock
import database
import season_reset
import season_summary
from database import Base, get_db
from models import (
    AuditLog, Card, CardModifier, League, LiveMatch, Match, MatchBan, MatchTiming,
    OwnPlayerCardGrant, Player, PlayerMatchStats, SeasonAccolade, SeasonArchive,
    SeasonPlayerStats, SeasonTeamResult, TagDefinition, Team, TwitchMVP, TwitchTokenDrop,
    User, UserTag, Week, WeeklyRosterEntry, WeeklySummary, WeeklySummaryReveal,
    WeeklySummarySeen, Weight,
)
from scoring import display_points, fantasy_score, stat_dict_from_row


@pytest.fixture
def db():
    """In-memory database on one shared connection, so a TestClient's request
    thread sees the same data (overrides conftest's `db`)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_SEASON_NAME_RE = re.compile(r"^fantasy\.db\.season-Season-16-\d{8}-\d{6}$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_caches():
    """Every test starts and ends with empty season caches, so a filled cache never
    leaks into another test on the same worker (and the schedule cache's divisions
    don't depend on test order)."""
    season_reset.bust_caches()
    yield
    season_reset.bust_caches()


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fe(name):
    return _read("frontend", name)


def _fn_source(js, name):
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}\n", start) + 2]


def _user(db, username, admin=False, tokens=10):
    from auth import hash_password
    u = User(username=username, email=f"{username}@example.com", password_hash=hash_password("secret123"),
             is_admin=admin, tokens=tokens, created_at=int(time.time()))
    db.add(u)
    db.commit()
    return u


def _client(db, login=None, reauth=True):
    """A small app around admin_season and admin_backups sharing `db`, signed in as
    `login` (with a recent re-auth unless reauth=False)."""
    import rate_limit
    import sessions
    from routers import admin_backups, admin_season
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-133")
    app.state.limiter = rate_limit.limiter
    app.include_router(admin_season.router)
    app.include_router(admin_backups.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db

    @app.post("/_test/login/{user_id}")
    def _login(user_id: int, request: Request, fresh: bool = True):
        sessions.start_session(request, db, db.get(User, user_id))
        if fresh:
            sessions.mark_reauth(sessions.current_row(request, db))
        db.commit()
        return {"ok": True}

    client = TestClient(app)
    if login is not None:
        assert client.post(f"/_test/login/{login.id}", params={"fresh": reauth}).status_code == 200
    return client


def _admin_client(db, reauth=True):
    admin = db.query(User).filter_by(username="admin").first() or _user(db, "admin", admin=True)
    return _client(db, login=admin, reauth=reauth)


_T0 = 1_000_000
_DAY = 86400
# (match, radiant, dire, radiant_win, start, excluded, league)
_MATCHES = [
    (1001, 100, 200, True, _T0, False, 1),
    (1002, 100, 200, False, _T0 + 3600, False, 1),     # same series as 1001: 1-1
    (1003, 200, 100, True, _T0 + 7 * _DAY, False, 1),  # a new series: Blues 1-0
    (1004, 100, 300, True, _T0 + 8 * _DAY, True, 2),   # excluded from scoring
    (1005, 300, 200, False, _T0 + 9 * _DAY, False, 2),  # Blues beat Greens
]
# (player, team, match, kills, deaths, assists, is_mvp, stored fantasy_points)
_STATS = [
    (1, 100, 1001, 10, 2, 5, True, 30.0), (1, 100, 1002, 3, 5, 2, False, 8.0),
    (1, 100, 1003, 5, 1, 8, False, 15.0), (1, 100, 1004, 99, 0, 99, True, 999.0),
    (2, 100, 1001, 4, 4, 4, False, 10.0), (2, 100, 1002, 6, 2, 1, False, 12.0),
    (2, 300, 1005, 1, 7, 3, False, 2.0),
    (3, 200, 1001, 2, 6, 9, False, 9.0), (3, 200, 1002, 8, 1, 4, True, 25.0),
    (3, 200, 1003, 7, 0, 6, True, 28.0), (3, 200, 1005, 12, 1, 2, False, 26.0),
    (4, 300, 1004, 20, 0, 0, False, 50.0),  # only an excluded game
]


def _weights(db, **over):
    from seed import DEFAULT_WEIGHTS
    for w in DEFAULT_WEIGHTS:
        db.add(Weight(key=w["key"], label=w["label"], value=over.get(w["key"], w["value"])))
    db.commit()


def _seed_season(db, weights=True):
    if weights:
        _weights(db)
    db.add(League(id=1, name="Kanaliiga Season 16", is_monitored=True))
    db.add(League(id=2, name="Kanaliiga Season 16 Lower", is_monitored=True))
    for tid, name in ((100, "Reds"), (200, "Blues"), (300, "Greens")):
        db.add(Team(id=tid, name=name))
    for pid, name in ((1, "Alpha"), (2, "Bravo"), (3, "Charlie"), (4, "Delta")):
        db.add(Player(id=pid, name=name, is_active=True))
    for mid, rad, dire, rw, start, excl, league in _MATCHES:
        db.add(Match(match_id=mid, radiant_team_id=rad, dire_team_id=dire, radiant_win=rw,
                     start_time=start, excluded_from_scoring=excl, league_id=league))
    for pid, tid, mid, k, d, a, mvp, pts in _STATS:
        db.add(PlayerMatchStats(player_id=pid, team_id=tid, match_id=mid, kills=k, deaths=d,
                                assists=a, is_mvp=mvp, fantasy_points=pts, last_hits=10 * k))
    db.commit()


def _end(db, label="Season 16", champions=None, **parts):
    from routers.admin_season import SeasonEndBody, end_season
    body = SeasonEndBody(season_label=label, champions=champions, **parts)
    return end_season(body, db=db, admin=dict(_ADMIN))


def _reset(db, monkeypatch, backup="/tmp/claude-133-fake-backup.db", force=True, label=None):
    from routers import admin_season
    from routers.admin_season import SeasonResetBody, reset_season
    monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda *a, **k: backup)
    return reset_season(SeasonResetBody(force=force, season_label=label), db=db, admin=dict(_ADMIN))


def _dummy(col, i):
    if isinstance(col.type, Boolean):
        return False
    if isinstance(col.type, Integer):
        return 1000 + i
    if isinstance(col.type, Float):
        return 1.0
    return f"x{i}"


def _fill(db, name, n=2, **over):
    """n rows in any table: primary keys and required columns get dummy values."""
    table = Base.metadata.tables[name]
    for i in range(n):
        row = {c.name: _dummy(c, i) for c in table.columns
               if c.primary_key or (not c.nullable and c.default is None and c.server_default is None)}
        row.update({k: (v(i) if callable(v) else v) for k, v in over.items()})
        db.execute(table.insert().values(**row))
    db.commit()


_FILL_OVERRIDES = {"card_modifiers": {"stat_key": "kills"},
                   # At most one open signup period (ux_team_signup_periods_open).
                   "team_signup_periods": {"closed_at": lambda i: 2000 + i}}


def _fill_cleared(db, n=2):
    for name in season_reset.CLEARED_TABLES:
        _fill(db, name, n, **_FILL_OVERRIDES.get(name, {}))


def _snapshot(db, names):
    db.expire_all()
    return {name: sorted(map(tuple, db.execute(select(Base.metadata.tables[name])).fetchall()), key=repr)
            for name in names}


def _count(db, name):
    return db.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar()


def _fill_caches():
    import finals
    import player_insights
    import schedule
    import team_insights
    import twitch
    schedule._cache.update(data={"weeks": [], "extra_results": []}, fetched_at=datetime.now())
    schedule._game_players_cache[1001] = (time.monotonic(), {"match_id": 1001})
    twitch._panel_cache.update(at=time.monotonic(), body={"old": True})
    finals._public_cache.update(at=time.monotonic(), entry={"old": True})
    finals._available_cache.update(at=time.monotonic(), value=True)
    finals._site_cache.update(at=time.monotonic(), value={"old": True}, filled=True)
    team_insights._league_cache.update(key="k", at=time.monotonic(), value={"old": True})
    team_insights._list_cache.update(key="k", at=time.monotonic(), value=[1])
    player_insights._league_cache.update(key="k", at=time.monotonic(), value={"old": True})


def _caches_state():
    import finals
    import player_insights
    import schedule
    import team_insights
    import twitch
    return {"schedule": schedule._cache["data"], "game_players": dict(schedule._game_players_cache),
            "panel": twitch._panel_cache["body"], "public": finals._public_cache["entry"],
            "available": finals._available_cache["value"], "site": finals._site_cache["value"],
            "team_league": team_insights._league_cache["value"],
            "team_list": team_insights._list_cache["value"],
            "player_league": player_insights._league_cache["value"]}


def _caches_empty():
    state = _caches_state()
    return state["game_players"] == {} and all(v is None for k, v in state.items() if k != "game_players")


def _expected_players(db):
    """Per player: the summary computed straight from the ORM rows of scored matches."""
    weights = {w.key: w.value for w in db.query(Weight)}
    excluded = {m.match_id for m in db.query(Match) if m.excluded_from_scoring}
    out = {}
    for row in db.query(PlayerMatchStats).order_by(PlayerMatchStats.match_id):
        if row.match_id in excluded:
            continue
        raw = fantasy_score(stat_dict_from_row(row), weights)
        p = out.setdefault(row.player_id, {"games": 0, "total": 0.0, "best": None, "best_match": None,
                                           "kills": 0, "deaths": 0, "assists": 0, "mvps": 0})
        p["games"] += 1
        p["total"] += raw
        if p["best"] is None or raw > p["best"]:
            p["best"], p["best_match"] = raw, row.match_id
        p["kills"] += row.kills
        p["deaths"] += row.deaths
        p["assists"] += row.assists
        p["mvps"] += 1 if row.is_mvp else 0
    return out


def _player_rows(db, label="Season 16"):
    db.expire_all()
    return {r.player_id: r for r in db.query(SeasonPlayerStats).filter_by(season_label=label)}


def _team_rows(db, label="Season 16"):
    db.expire_all()
    return {r.team_id: r for r in db.query(SeasonTeamResult).filter_by(season_label=label)}


def _node():
    return shutil.which("node") or ("/usr/local/bin/node" if os.path.exists("/usr/local/bin/node") else None)


def _run_node(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    res = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


_DOM_STUBS = r"""
const __els = {};
function __mk(id) {
  const cls = new Set();
  return {id, value: "", checked: false, textContent: "", innerHTML: "", hidden: false, style: {}, cls,
          classList: {add: c => cls.add(c), remove: c => cls.delete(c), contains: c => cls.has(c)}};
}
const document = {getElementById: id => __els[id] || (__els[id] = __mk(id))};
const API = "";
const ADMIN_CONFIRM_PHRASES = {season_end: "END SEASON", season_reset: "RESET SEASON", season_summary: "SAVE SUMMARY"};
const __calls = {fetch: [], adminFetch: [], status: {}};
function setStatus(id, msg, ok) { __calls.status[id] = msg; document.getElementById(id).textContent = msg; }
function accoladeValueText(kind, v) { return `${v} MVPs`; }
function typedConfirm(action, text) { __calls.typed = action; return Promise.resolve(ADMIN_CONFIRM_PHRASES[action]); }
let __fetchReply = {};
async function fetch(url) { __calls.fetch.push(url); return {ok: true, json: async () => __fetchReply}; }
let __adminReply = {};
async function adminFetch(url, opts) {
  __calls.adminFetch.push({url, body: opts && opts.body ? JSON.parse(opts.body) : null});
  return {ok: true, json: async () => __adminReply};
}
function loadAdminWeeks() {}
function loadLeagues() {}
function loadBackups() { __calls.backups = true; }
function loadSeasonAccolades() {}
"""


def _season_harness(body):
    """app-admin-season.js loaded whole (it has no top-level side effects) under a
    fake DOM, then `body` inside an async function that sets `out`."""
    js = _fe("app-admin-season.js")
    escape = _fn_source(_fe("app-globals.js"), "_escHtml")
    return _run_node(_DOM_STUBS + escape + "\n" + js + """
loadSeasonArchives = async () => {};
(async () => {
  let out = null;
""" + body + """
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
""")


def _season_db_file(tmp_path, monkeypatch):
    db_file = tmp_path / "fantasy.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    conn.execute("INSERT INTO users (username) VALUES ('alice')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    return db_file


def _backup_file(db_file, kind, suffix, age_seconds=0.0):
    path = db_file.parent / f"{db_file.name}.{kind}-{suffix}"
    path.write_bytes(b"SQLite format 3\x00" + suffix.encode())
    ts = time.time() - age_seconds
    os.utime(path, (ts, ts))
    return path


# ===========================================================================
# Story 1: Reset Leaves Nothing of the Old Season Behind
# ===========================================================================

class TestResetLeavesNothingBehind:

    def test_reset_table_lists_cover_every_table_exactly_once(self):
        """Every table in Base.metadata.tables is in exactly one of the reset module's cleared, updated and kept lists, and the lists name no table that doesn't exist; season_player_stats and season_team_results are in the kept list."""
        groups = season_reset.TABLE_GROUPS
        listed = [name for group in groups.values() for name in group]
        assert len(listed) == len(set(listed)), "a table is in more than one group"
        assert set(listed) == set(Base.metadata.tables), (
            set(Base.metadata.tables) ^ set(listed))
        assert "schema_migrations" not in listed
        assert {"season_player_stats", "season_team_results"} <= set(season_reset.KEPT_TABLES)
        assert set(season_reset.UPDATED_TABLES) == {"users", "leagues", "demo_clock"}
        assert "twitch_presence" in season_reset.CLEARED_TABLES

    def test_reset_season_still_clears_existing_season_tables(self, db, monkeypatch):
        """After reset_season(force=True) on a full season: matches, player_match_stats, card_match_points, match_bans, weeks, weekly_roster_entries, twitch_mvp, twitch_token_drops, players, teams, cards, card_modifiers and own_player_card_grants are empty; every user's tokens equal INITIAL_TOKENS; no league is monitored."""
        monkeypatch.setenv("INITIAL_TOKENS", "7")
        _seed_season(db)
        alice = _user(db, "alice", tokens=99)
        card = Card(player_id=1, owner_id=alice.id, card_type="common", is_active=True)
        db.add(card)
        db.flush()
        db.add(CardModifier(card_id=card.id, stat_key="kills", bonus_pct=10.0))
        db.add(MatchBan(match_id=1001, hero_id=5))
        db.add(TwitchMVP(match_id=1001, player_id=1, channel_id="c1", selected_at=_T0))
        db.add(TwitchTokenDrop(channel_id="c1", series_id="s1", dropped_at=_T0, count=3))
        db.add(OwnPlayerCardGrant(user_id=alice.id, player_id=1, outcome="granted", granted_at=_T0))
        week = Week(label="Week 1", start_time=_T0, end_time=_T0 + _DAY, is_locked=False)
        db.add(week)
        db.flush()
        db.add(WeeklyRosterEntry(week_id=week.id, user_id=alice.id, card_id=card.id))
        db.commit()
        import card_points
        card_points.rebuild_all(db)
        db.commit()
        assert _count(db, "card_match_points") > 0
        _reset(db, monkeypatch)
        for name in ("matches", "player_match_stats", "card_match_points", "match_bans", "weeks",
                     "weekly_roster_entries", "twitch_mvp", "twitch_token_drops", "players", "teams",
                     "cards", "card_modifiers", "own_player_card_grants"):
            assert _count(db, name) == 0, name
        db.expire_all()
        assert {u.tokens for u in db.query(User)} == {7}
        assert db.query(League).filter(League.is_monitored == True).count() == 0  # noqa: E712
        assert db.query(League).count() == 2

    def test_reset_season_clears_weekly_summary_and_live_tables(self, db, monkeypatch):
        """reset_season deletes every row of weekly_summaries, weekly_summary_reveals, weekly_summary_seen, live_matches and match_timings (including match_timings rows for match ids that never had a matches row)."""
        _seed_season(db)
        alice = _user(db, "alice")
        db.add(Week(id=1, label="Week 1", start_time=_T0, end_time=_T0 + _DAY))
        db.add(WeeklySummary(week_id=1, generated_at=_T0))
        db.add(WeeklySummaryReveal(week_id=1, user_id=alice.id, revealed_at=_T0))
        db.add(WeeklySummarySeen(user_id=alice.id, last_seen_week_id=1, last_prompted_week_id=1))
        db.add(LiveMatch(match_id=1001, league_id=1, players_json="[]", first_seen_at=_T0, last_seen_at=_T0))
        db.add(MatchTiming(match_id=1001, ingested_at=_T0))
        db.add(MatchTiming(match_id=777777, live_first_seen_at=_T0))  # never a matches row
        db.commit()
        result = _reset(db, monkeypatch)
        for name in ("weekly_summaries", "weekly_summary_reveals", "weekly_summary_seen",
                     "live_matches", "match_timings"):
            assert _count(db, name) == 0, name
        assert result["counts"]["match_timings"] == 2
        assert result["counts"]["weekly_summaries"] == 1

    def test_reset_season_clears_demo_clock_override(self, db, monkeypatch):
        """With a demo clock override set (clock.set_override), after reset clock.get_override(db) is None."""
        clock.set_override(db, _T0 + 5 * _DAY)
        db.commit()
        assert clock.get_override(db) == _T0 + 5 * _DAY
        result = _reset(db, monkeypatch)
        db.expire_all()
        assert clock.get_override(db) is None
        assert result["counts"]["demo_clock_override"] == 1

    def test_reset_season_week_with_reused_id_has_no_report_state(self, db, monkeypatch):
        """Weeks 1..3 with a weekly_summaries row, reveals and a weekly_summary_seen row (last_seen and last_prompted = 3); after reset a new Week gets id 1 (the old id) and has no weekly_summaries row, no reveal for any user, and no user's weekly_summary_seen points at it."""
        alice = _user(db, "alice")
        for i in range(3):
            w = Week(label=f"Week {i + 1}", start_time=_T0 + i * 7 * _DAY, end_time=_T0 + (i + 1) * 7 * _DAY)
            db.add(w)
            db.flush()
            db.add(WeeklySummary(week_id=w.id, generated_at=_T0))
            db.add(WeeklySummaryReveal(week_id=w.id, user_id=alice.id, revealed_at=_T0))
        db.add(WeeklySummarySeen(user_id=alice.id, last_seen_week_id=3, last_prompted_week_id=3))
        db.commit()
        assert sorted(w.id for w in db.query(Week)) == [1, 2, 3]
        _reset(db, monkeypatch)
        new = Week(label="Week 1", start_time=_T0 + 100 * _DAY, end_time=_T0 + 107 * _DAY)
        db.add(new)
        db.commit()
        assert new.id == 1  # SQLite reuses the id once the table is empty
        assert db.get(WeeklySummary, new.id) is None
        assert db.query(WeeklySummaryReveal).filter_by(week_id=new.id).count() == 0
        assert db.query(WeeklySummarySeen).filter(
            (WeeklySummarySeen.last_seen_week_id == new.id)
            | (WeeklySummarySeen.last_prompted_week_id == new.id)).count() == 0

    def test_reset_season_busts_in_memory_season_caches(self, db, monkeypatch):
        """With schedule._cache, schedule._game_players_cache, twitch._panel_cache, finals._public_cache/_available_cache/_site_cache, team_insights._league_cache/_list_cache and player_insights._league_cache all filled, after reset each is empty (data/body/value None, game players {}), so the first request after it reads the empty season."""
        _fill_caches()
        assert not _caches_empty()
        _reset(db, monkeypatch)
        assert _caches_empty(), _caches_state()

    def test_reset_season_keeps_kept_tables(self, db, monkeypatch):
        """Rows in tag_definitions, user_tags, audit_logs, season_archive, season_accolades, finals_brackets, finals_predictions, team_signup_periods, team_signups, team_signup_players, promo_codes, token_grant_events, notifications, weights, player_profiles, twitch_mvp_polls, twitch_pending_tokens and every other kept table are all still there, unchanged, after reset; user accounts stay (only their tokens change)."""
        for name in season_reset.KEPT_TABLES:
            _fill(db, name, 2, **_FILL_OVERRIDES.get(name, {}))
        alice = _user(db, "alice")
        before = _snapshot(db, season_reset.KEPT_TABLES)
        assert all(len(rows) == 2 for rows in before.values())
        _reset(db, monkeypatch)
        # The reset adds its own audit row; every earlier row is unchanged.
        after = _snapshot(db, season_reset.KEPT_TABLES)
        audit_ids = {r[0] for r in before["audit_logs"]}
        after["audit_logs"] = [r for r in after["audit_logs"] if r[0] in audit_ids]
        assert after == before
        assert db.get(User, alice.id).username == "alice"

    def test_reset_season_response_counts_and_kept_cover_lists(self, db, monkeypatch):
        """The reset response's `counts` has a key for every cleared table (plus users_tokens_reset, leagues_unmonitored and demo_clock_override) with the number of rows deleted, and `kept` has a key for every kept table with its row count (kept["season_accolades"] still present)."""
        _fill_cleared(db, 2)
        for name in season_reset.KEPT_TABLES:
            _fill(db, name, 3, **_FILL_OVERRIDES.get(name, {}))
        _user(db, "alice")
        db.add(League(id=1, name="L", is_monitored=True))
        db.commit()
        result = _reset(db, monkeypatch)
        counts = result["counts"]
        assert set(counts) == set(season_reset.CLEARED_TABLES) | {
            "users_tokens_reset", "leagues_unmonitored", "demo_clock_override"}
        assert all(counts[name] == 2 for name in season_reset.CLEARED_TABLES), counts
        assert counts["users_tokens_reset"] == 1 and counts["leagues_unmonitored"] == 1
        assert set(result["kept"]) == set(season_reset.KEPT_TABLES)
        assert result["kept"]["season_accolades"] == 3
        assert result["kept"]["audit_logs"] == 3  # counted before the reset's own audit row

    def test_reset_season_locked_weeks_without_archive_refuses_and_clears_nothing(self, db, monkeypatch):
        """Failure path: a locked week and no newer season_archive, force=False: 409, and weekly_summaries, live_matches, match_timings rows, the demo clock override and the filled caches are all untouched."""
        db.add(Week(id=1, label="Week 1", start_time=_T0, end_time=_T0 + _DAY, is_locked=True))
        db.add(WeeklySummary(week_id=1, generated_at=_T0))
        db.add(LiveMatch(match_id=1, league_id=1, players_json="[]", first_seen_at=_T0, last_seen_at=_T0))
        db.add(MatchTiming(match_id=1, ingested_at=_T0))
        clock.set_override(db, _T0)
        db.commit()
        _fill_caches()
        with pytest.raises(HTTPException) as exc:
            _reset(db, monkeypatch, force=False)
        assert exc.value.status_code == 409
        db.rollback()
        for name in ("weeks", "weekly_summaries", "live_matches", "match_timings"):
            assert _count(db, name) == 1, name
        assert clock.get_override(db) == _T0
        assert not _caches_empty()


# ===========================================================================
# Story 2: Season Stats Survive the Reset
# ===========================================================================

class TestSeasonStatsSurvive:

    def test_end_season_stores_player_summary_rows(self, db):
        """End Season with label "Season 16" stores one season_player_stats row per player with a scored match: player_id, player_name, team_name, games, wins, raw_points_total, raw_points_avg, best_raw_points, best_match_id, kills, deaths, assists, mvps matching the live stats; a player with only excluded games gets no row."""
        _seed_season(db)
        expected = _expected_players(db)
        result = _end(db)
        assert result["summary"] == {"players": 3, "teams": 3}
        rows = _player_rows(db)
        assert sorted(rows) == [1, 2, 3]  # Delta (4) played only an excluded game
        names = {1: "Alpha", 2: "Bravo", 3: "Charlie"}
        teams = {1: "Reds", 2: "Reds", 3: "Blues"}  # Bravo: 2 games for Reds, 1 for Greens
        wins = {1: 1, 2: 1, 3: 3}
        for pid, r in rows.items():
            e = expected[pid]
            assert (r.player_name, r.team_name, r.games, r.wins) == (names[pid], teams[pid], e["games"], wins[pid])
            assert r.raw_points_total == pytest.approx(e["total"])
            assert r.raw_points_avg == pytest.approx(e["total"] / e["games"])
            assert r.best_raw_points == pytest.approx(e["best"]) and r.best_match_id == e["best_match"]
            assert (r.kills, r.deaths, r.assists, r.mvps) == (e["kills"], e["deaths"], e["assists"], e["mvps"])
        assert rows[1].mvps == 1  # the MVP in excluded match 1004 is left out

    def test_end_season_stores_team_summary_rows(self, db):
        """End Season stores one season_team_results row per team with team_id, team_name, division (div1/div2 from the schedule cache when it is already cached, None otherwise; never fetched), series_won, series_lost, series_drawn (each team pair's scored games clustered into series by schedule.SERIES_GAP_SECONDS) and games_won, games_lost from scored matches."""
        import schedule
        _seed_season(db)
        monkeypatch_get = schedule.get_schedule
        schedule.get_schedule = lambda db: (_ for _ in ()).throw(AssertionError("fetched the schedule"))
        try:
            _end(db)
        finally:
            schedule.get_schedule = monkeypatch_get
        rows = _team_rows(db)
        got = {tid: (r.team_name, r.division, r.series_won, r.series_lost, r.series_drawn, r.games_won, r.games_lost)
               for tid, r in rows.items()}
        assert got == {
            100: ("Reds", None, 0, 1, 1, 1, 2),     # 1-1 draw, then lost 0-1
            200: ("Blues", None, 2, 0, 1, 3, 1),    # draw, won 1-0, beat Greens
            300: ("Greens", None, 0, 1, 0, 0, 1),   # excluded 1004 left out
        }
        # With the schedule already cached, the division is read from it.
        schedule._cache.update(fetched_at=datetime.now(), data={
            "weeks": [{"div1": [{"team1_id": 100, "team2_id": 200}],
                       "div2": [{"team1_id": 300, "team2_id": 200}]}],
            "extra_results": [{"team1_id": 200, "team2_id": 100, "division": "div1"}]})
        _end(db, label="Season 16b")
        assert {tid: r.division for tid, r in _team_rows(db, "Season 16b").items()} == {
            100: "div1", 200: "div1", 300: "div2"}

    def test_end_season_summary_raw_points_use_current_weights_and_skip_excluded(self, db):
        """Each player's raw_points_total equals the sum of scoring.fantasy_score(stat_dict_from_row(row), weights) over scored matches only (no MVP bonus, no rarity), with the Weight rows in force at End Season; a game with excluded_from_scoring=1 changes no count, total, best game or MVP count."""
        _weights(db, kills=2.0, assists=1.0, mvp_bonus=50.0)
        _seed_season(db, weights=False)
        weights = {w.key: w.value for w in db.query(Weight)}
        alpha = [r for r in db.query(PlayerMatchStats).filter_by(player_id=1) if r.match_id != 1004]
        total = sum(fantasy_score(stat_dict_from_row(r), weights) for r in alpha)
        _end(db)
        row = _player_rows(db)[1]
        assert row.raw_points_total == pytest.approx(total)
        assert display_points(row.raw_points_total) == display_points(total)
        assert row.games == 3 and row.best_match_id != 1004 and row.mvps == 1
        # Stored fantasy_points (which include the MVP bonus) play no part.
        assert row.raw_points_total != pytest.approx(30.0 + 8.0 + 15.0)

    def test_end_season_summary_failure_stores_nothing(self, db, monkeypatch):
        """Failure path: when building the summary raises, End Season answers 500 and no season_archive, season_accolades, season_player_stats or season_team_results row is committed."""
        _seed_season(db)
        _user(db, "alice")

        def boom(*a, **k):
            raise RuntimeError("summary failed")
        monkeypatch.setattr(season_summary, "team_rows", boom)
        with pytest.raises(HTTPException) as exc:
            _end(db, champions=[{"division": "div1", "team_name": "Reds", "player_account_ids": [1]}])
        assert exc.value.status_code == 500
        assert exc.value.detail == "Storing the season summary failed; nothing was archived"
        db.expire_all()
        for model in (SeasonArchive, SeasonAccolade, SeasonPlayerStats, SeasonTeamResult):
            assert db.query(model).count() == 0, model.__name__
        assert db.query(UserTag).count() == 0

    def test_end_season_same_label_twice_409_without_duplicate_summary(self, db):
        """A second End Season with the same label answers 409 and the season_player_stats / season_team_results counts for that label are unchanged."""
        _seed_season(db)
        _user(db, "alice")
        _end(db)
        before = (len(_player_rows(db)), len(_team_rows(db)))
        with pytest.raises(HTTPException) as exc:
            _end(db)
        assert exc.value.status_code == 409
        db.rollback()
        assert (len(_player_rows(db)), len(_team_rows(db))) == before == (3, 3)

    def test_season_summary_endpoint_stores_summary_for_archived_label(self, db):
        """POST /admin/season/summary {season_label, confirm} (admin, recent re-auth) for a label already in season_archive with no summary stores the player and team rows from the live data (same rows End Season would store) and writes an audit row."""
        _seed_season(db)
        _user(db, "alice")
        _end(db, label="Season 15", store_summary=False)
        _end(db, label="Reference")  # what End Season itself stores
        client = _admin_client(db)
        resp = client.post("/admin/season/summary", json={"season_label": "Season 15", "confirm": "SAVE SUMMARY"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"season_label": "Season 15", "players": 3, "teams": 3}

        def strip(rows):
            return {k: {c: v for c, v in vars(r).items() if c not in ("_sa_instance_state", "id", "season_label", "created_at")}
                    for k, r in rows.items()}
        assert strip(_player_rows(db, "Season 15")) == strip(_player_rows(db, "Reference"))
        assert strip(_team_rows(db, "Season 15")) == strip(_team_rows(db, "Reference"))
        audit = db.query(AuditLog).filter_by(action="admin_season_summary").one()
        assert "season_label=Season 15" in audit.detail and "players=3" in audit.detail

    def test_season_summary_endpoint_existing_summary_returns_409(self, db):
        """Failure path: POST /admin/season/summary for a label that already has season_player_stats rows answers 409 and adds no rows."""
        _seed_season(db)
        _user(db, "alice")  # End Season archives one row per user
        _end(db)
        client = _admin_client(db)
        resp = client.post("/admin/season/summary", json={"season_label": "Season 16", "confirm": "SAVE SUMMARY"})
        assert resp.status_code == 409
        assert len(_player_rows(db)) == 3 and len(_team_rows(db)) == 3

    def test_season_summary_endpoint_refuses_without_live_matches(self, db, monkeypatch):
        """Failure path: after Reset (no matches, no player_match_stats), POST /admin/season/summary for an archived label is refused (409) and stores nothing."""
        _seed_season(db)
        _user(db, "alice")  # End Season archives one row per user
        _end(db, store_summary=False)
        _reset(db, monkeypatch)
        client = _admin_client(db)
        resp = client.post("/admin/season/summary", json={"season_label": "Season 16", "confirm": "SAVE SUMMARY"})
        assert resp.status_code == 409
        assert "already been reset" in resp.json()["detail"]
        assert db.query(SeasonPlayerStats).count() == 0 and db.query(SeasonTeamResult).count() == 0

    def test_season_summary_endpoint_refuses_unarchived_label(self, db):
        """Failure path: POST /admin/season/summary for a label with no season_archive rows answers 404 and stores nothing."""
        _seed_season(db)
        client = _admin_client(db)
        resp = client.post("/admin/season/summary", json={"season_label": "Season 99", "confirm": "SAVE SUMMARY"})
        assert resp.status_code == 404
        assert db.query(SeasonPlayerStats).count() == 0 and db.query(SeasonTeamResult).count() == 0

    def test_season_summary_endpoint_requires_reauth_and_confirmation(self, db):
        """Failure path: POST /admin/season/summary answers 401/403 for anonymous and non-admin users, 403 reauth_required without a recent re-auth, and 400 confirmation_required without the typed phrase."""
        import deps
        assert deps.CONFIRM_PHRASES["season_summary"] == "SAVE SUMMARY"
        assert 'season_summary:  "SAVE SUMMARY"' in _fe("app-admin.js")
        _seed_season(db)
        _end(db, store_summary=False)
        body = {"season_label": "Season 16", "confirm": "SAVE SUMMARY"}
        assert _client(db).post("/admin/season/summary", json=body).status_code in (401, 403)
        bob = _user(db, "bob")
        assert _client(db, login=bob).post("/admin/season/summary", json=body).status_code == 403
        stale = _admin_client(db, reauth=False).post("/admin/season/summary", json=body)
        assert stale.status_code == 403 and stale.json()["detail"] == "reauth_required"
        unconfirmed = _admin_client(db).post("/admin/season/summary", json={"season_label": "Season 16"})
        assert unconfirmed.status_code == 400 and unconfirmed.json()["detail"] == "confirmation_required"
        assert db.query(SeasonPlayerStats).count() == 0

    def test_reset_season_keeps_season_summary_rows(self, db, monkeypatch):
        """reset_season deletes no season_player_stats or season_team_results row, and lists both in `kept` with their counts."""
        _seed_season(db)
        _end(db)
        result = _reset(db, monkeypatch)
        assert result["kept"]["season_player_stats"] == 3
        assert result["kept"]["season_team_results"] == 3
        assert db.query(SeasonPlayerStats).count() == 3 and db.query(SeasonTeamResult).count() == 3
        assert db.query(Match).count() == 0


# ===========================================================================
# Story 3: Choose What End Season Records
# ===========================================================================

def _kinds(db, label="Season 16"):
    db.expire_all()
    out = {}
    for r in db.query(SeasonAccolade).filter_by(season_label=label):
        out[r.kind] = out.get(r.kind, 0) + 1
    return out


def _winner_standings(monkeypatch, db):
    import routers.leaderboard as lb
    from routers import admin_season
    jiri = _user(db, "jiri")
    rows = [{"id": jiri.id, "username": "jiri", "points": 120.0}]
    monkeypatch.setattr(lb, "compute_season_standings", lambda db: [dict(r) for r in rows])
    monkeypatch.setattr(admin_season, "compute_season_standings", lambda db: [dict(r) for r in rows])
    return jiri


def _winner_tags(db):
    db.expire_all()
    tag = db.query(TagDefinition).filter_by(key="season_winner").first()
    return 0 if tag is None else db.query(UserTag).filter_by(tag_id=tag.id).count()


_CHAMPS = [{"division": "div1", "team_name": "Blues", "player_account_ids": [3]}]


class TestChooseEndSeasonParts:

    def test_end_season_body_parts_default_true(self, db, monkeypatch):
        """SeasonEndBody has record_awards, record_champions, record_played and store_summary, all defaulting to True; End Season without them records awards, champions, played rows, the winner tag and the summary as before."""
        from routers.admin_season import SeasonEndBody
        body = SeasonEndBody(season_label="Season 16")
        assert (body.record_awards, body.record_champions, body.record_played, body.store_summary) == (True,) * 4
        _seed_season(db)
        _winner_standings(monkeypatch, db)
        _end(db, champions=_CHAMPS)
        kinds = _kinds(db)
        assert kinds["most_points"] >= 1 and kinds["fantasy_winner"] == 1
        assert kinds["champion"] == 1 and kinds["played"] == 3
        assert _winner_tags(db) == 1
        assert len(_player_rows(db)) == 3 and len(_team_rows(db)) == 3

    def test_end_season_record_awards_false_skips_awards_and_winner_tag(self, db, monkeypatch):
        """With record_awards=false, no most_points, best_average, best_match, most_mvps or fantasy_winner row is added for the label and no season_winner user tag is granted; champions, played and summary still run."""
        _seed_season(db)
        _winner_standings(monkeypatch, db)
        result = _end(db, champions=_CHAMPS, record_awards=False)
        assert _kinds(db) == {"champion": 1, "played": 3}
        assert _winner_tags(db) == 0
        assert result["awards"] == 0 and len(_player_rows(db)) == 3

    def test_end_season_record_champions_false_ignores_champions(self, db):
        """With record_champions=false (even if champions are sent), no champion row is added."""
        _seed_season(db)
        result = _end(db, champions=_CHAMPS, record_champions=False)
        assert "champion" not in _kinds(db)
        assert result["champions"] == 0 and "warning" not in result
        assert _kinds(db)["played"] == 3

    def test_end_season_record_played_false_skips_played_rows(self, db):
        """With record_played=false, no played row is added for the label."""
        _seed_season(db)
        _end(db, record_played=False)
        kinds = _kinds(db)
        assert "played" not in kinds and kinds["most_points"] >= 1

    def test_end_season_store_summary_false_skips_summary(self, db):
        """With store_summary=false, no season_player_stats or season_team_results row is stored; POST /admin/season/summary can store it later."""
        _seed_season(db)
        _user(db, "alice")  # End Season archives one row per user
        result = _end(db, store_summary=False)
        assert result["summary"] is None
        assert db.query(SeasonPlayerStats).count() == 0 and db.query(SeasonTeamResult).count() == 0
        resp = _admin_client(db).post("/admin/season/summary",
                                      json={"season_label": "Season 16", "confirm": "SAVE SUMMARY"})
        assert resp.status_code == 200, resp.text
        assert len(_player_rows(db)) == 3

    def test_end_season_all_parts_off_still_archives_standings(self, db):
        """With all four flags false, End Season still writes the season_archive rows (archived_users matches) and records no accolade or summary row."""
        _seed_season(db)
        _user(db, "alice")
        _user(db, "bob")
        result = _end(db, champions=_CHAMPS, record_awards=False, record_champions=False,
                      record_played=False, store_summary=False)
        assert result["archived_users"] == 2
        assert db.query(SeasonArchive).filter_by(season_label="Season 16").count() == 2
        assert db.query(SeasonAccolade).count() == 0
        assert db.query(SeasonPlayerStats).count() == 0 and db.query(SeasonTeamResult).count() == 0

    def test_end_season_response_and_audit_name_parts_run(self, db):
        """The response has `parts` {"archive": true, "awards": bool, "champions": bool, "played": bool, "summary": bool} as applied, and the admin_season_archived audit detail names the parts that ran (still containing "accolades=N champions=M")."""
        _seed_season(db)
        result = _end(db, champions=_CHAMPS, record_played=False)
        assert result["parts"] == {"archive": True, "awards": True, "champions": True,
                                   "played": False, "summary": True}
        detail = db.query(AuditLog).filter_by(action="admin_season_archived").one().detail
        assert f"accolades={result['accolades']} champions=1" in detail
        assert "parts=archive,awards,champions,summary" in detail
        assert "summary_players=3 summary_teams=3" in detail

    def test_end_season_never_changes_hand_entered_rows(self, db):
        """Hand-entered rows (source="admin") for the label, including a near-duplicate with another value, are neither changed nor deleted by End Season with every part on."""
        _seed_season(db)
        now = int(time.time())
        hand = [
            SeasonAccolade(season_label="Season 16", kind="most_points", player_account_id=1,
                           player_name="Alpha (hand)", value=1.0, source="admin", created_at=now),
            SeasonAccolade(season_label="Season 16", kind="champion", division="div1", team_name="Blues FC",
                           player_account_id=3, player_name="Charlie", source="admin", created_at=now),
            SeasonAccolade(season_label="S16", kind="most_points", player_account_id=1,
                           player_name="Alpha", value=999.0, source="admin", created_at=now),
        ]
        db.add_all(hand)
        db.commit()
        before = [(r.id, r.season_label, r.kind, r.player_name, r.team_name, r.value, r.source)
                  for r in db.query(SeasonAccolade).order_by(SeasonAccolade.id)]
        _end(db, champions=_CHAMPS)
        db.expire_all()
        after = [(r.id, r.season_label, r.kind, r.player_name, r.team_name, r.value, r.source)
                 for r in db.query(SeasonAccolade).filter(SeasonAccolade.id.in_([b[0] for b in before]))
                 .order_by(SeasonAccolade.id)]
        assert after == before

    def test_end_season_non_boolean_part_flag_returns_422(self, db):
        """Failure path: POST /admin/season/end with record_awards="maybe" (not a boolean) answers 422 and archives nothing."""
        _seed_season(db)
        client = _admin_client(db)
        resp = client.post("/admin/season/end", json={"season_label": "Season 16", "confirm": "END SEASON",
                                                      "record_awards": "maybe"})
        assert resp.status_code == 422, resp.text
        db.expire_all()
        assert db.query(SeasonArchive).count() == 0 and db.query(SeasonAccolade).count() == 0

    def test_accolades_preview_counts_existing_accolades_for_label(self, db):
        """GET /admin/season/accolades-preview?season_label=Season 16 returns per-kind counts of existing season_accolades rows for that label (awards total incl. fantasy_winner, champion, played); without the param it still answers as today for the current label."""
        _seed_season(db)
        now = int(time.time())
        for kind in ("most_points", "best_average", "best_match", "most_mvps"):
            db.add(SeasonAccolade(season_label="Season 16", kind=kind, player_account_id=1, source="admin", created_at=now))
        db.add(SeasonAccolade(season_label="Season 16", kind="fantasy_winner", user_id=9, source="admin", created_at=now))
        for pid in (1, 2):
            db.add(SeasonAccolade(season_label="Season 16", kind="champion", division="div1", player_account_id=pid,
                                  source="admin", created_at=now))
        db.add(SeasonAccolade(season_label="Season 16", kind="played", player_account_id=3, source="admin", created_at=now))
        db.add(SeasonAccolade(season_label="Season 15", kind="played", player_account_id=3, source="admin", created_at=now))
        db.commit()
        client = _admin_client(db)
        data = client.get("/admin/season/accolades-preview", params={"season_label": "Season 16"}).json()
        assert data["season_label"] == "Season 16"
        rec = data["recorded"]
        assert (rec["awards"], rec["champion"], rec["played"]) == (5, 2, 1)
        assert rec["by_kind"]["fantasy_winner"] == 1
        other = client.get("/admin/season/accolades-preview", params={"season_label": "Season 15"}).json()["recorded"]
        assert (other["awards"], other["champion"], other["played"]) == (0, 0, 1)
        plain = client.get("/admin/season/accolades-preview")
        assert plain.status_code == 200
        assert plain.json()["season_label"] == accolades.current_season_label(db)
        assert {"awards", "played_count", "teams", "champions_recorded", "recorded"} <= set(plain.json())

    def test_accolades_preview_overlong_label_returns_422(self, db):
        """Failure path: GET /admin/season/accolades-preview with a season_label over 100 characters answers 422."""
        client = _admin_client(db)
        assert client.get("/admin/season/accolades-preview", params={"season_label": "x" * 101}).status_code == 422
        assert client.get("/admin/season/accolades-preview", params={"season_label": "x" * 100}).status_code == 200

    def test_end_season_dialog_lists_parts_with_checkboxes(self):
        """Source-reading (index.html, app-admin-season.js): the End Season dialog has checkboxes for Archive standings (checked and disabled), Record awards, Record champions, Record Played and Store season summary, and confirmEndSeason sends record_awards, record_champions, record_played and store_summary in the body."""
        html = _fe("index.html")
        modal = html[html.index('id="endSeasonModal"'):html.index("<!-- End Season result")]
        assert '<input type="checkbox" id="endSeasonPart_archive" checked disabled /> Archive standings' in modal
        for part, label in (("awards", "Record awards"), ("champions", "Record champions"),
                            ("played", "Record Played"), ("summary", "Store season summary")):
            assert f'id="endSeasonPart_{part}" checked onchange="endSeasonPartChanged()" /> {label}' in modal
        confirm = _fn_source(_fe("app-admin-season.js"), "confirmEndSeason")
        sent = confirm[confirm.index("JSON.stringify"):]
        for key in ("record_awards", "record_champions", "record_played", "store_summary"):
            assert f"{key}: parts.{key}" in sent

    def test_end_season_dialog_unticks_parts_already_recorded(self):
        """Node harness: for preview counts {awards: 5, champion: 0, played: 0} the dialog shows "5 awards already recorded for Season 16" and Record awards starts unticked while champions, Played and summary start ticked."""
        out = _season_harness("""
  _applyEndSeasonRecorded({awards: 5, champion: 0, played: 0}, "Season 16");
  const el = id => document.getElementById(id);
  out = {awards: el("endSeasonPart_awards").checked, champions: el("endSeasonPart_champions").checked,
         played: el("endSeasonPart_played").checked, summary: el("endSeasonPart_summary").checked,
         text: el("endSeasonRecorded_awards").textContent, champText: el("endSeasonRecorded_champions").textContent};
""")
        assert out["text"] == "5 awards already recorded for Season 16"
        assert out["awards"] is False
        assert out["champions"] is True and out["played"] is True and out["summary"] is True
        assert out["champText"] == ""

    def test_end_season_dialog_hides_champion_pickers_when_off(self):
        """Node harness: with Record champions unticked the Div 1 / Div 2 pickers are hidden and the request body's champions is empty (none sent)."""
        out = _season_harness("""
  _endSeasonPreview = {teams: [{team_id: 100, team_name: "Reds", players: [{account_id: 1, name: "Alpha", matches: 3}]}]};
  _endSeasonPicks.div1 = [{account_id: 1, name: "Alpha", checked: true}];
  const el = id => document.getElementById(id);
  el("endSeasonTeam_div1").value = "100";
  ["awards", "champions", "played", "summary"].forEach(p => el(`endSeasonPart_${p}`).checked = true);
  endSeasonPartChanged();
  const onBefore = {hidden: el("endSeasonChampsBlock").hidden, champions: _endSeasonChampions().length};
  el("endSeasonPart_champions").checked = false;
  endSeasonPartChanged();
  const hidden = el("endSeasonChampsBlock").hidden;
  const warning = el("endSeasonChampWarning").hidden;
  el("endSeasonDialogLabel").value = "Season 16";
  __adminReply = {season_label: "Season 16", archived_users: 2, accolades: 3, champions: 0, summary: null};
  await confirmEndSeason();
  out = {onBefore, hidden, warning, body: __calls.adminFetch[0].body};
""")
        assert out["onBefore"] == {"hidden": False, "champions": 1}
        assert out["hidden"] is True and out["warning"] is True
        assert out["body"]["champions"] == [] and out["body"]["record_champions"] is False
        assert out["body"]["record_awards"] is True and out["body"]["store_summary"] is True


# ===========================================================================
# Story 4: The Raw Season Data Is Kept as a File
# ===========================================================================

class TestSeasonBackupFile:

    def test_backup_sqlite_db_season_kind_names_file_after_label(self, tmp_path, monkeypatch):
        """With DATABASE_URL at tmp_path/fantasy.db, backup_sqlite_db(kind="season", label="Season 16") writes tmp_path/fantasy.db.season-Season-16-YYYYMMDD-HHMMSS (mode 0600, a readable SQLite copy); backup_sqlite_db() with no arguments still writes fantasy.db.backup-YYYYMMDD-HHMMSS."""
        db_file = _season_db_file(tmp_path, monkeypatch)
        path = database.backup_sqlite_db(kind="season", label="Season 16")
        p = os.path.basename(path)
        assert os.path.dirname(path) == str(db_file.parent)
        assert _SEASON_NAME_RE.match(p), p
        assert os.stat(path).st_mode & 0o777 == 0o600
        conn = sqlite3.connect(path)
        assert conn.execute("SELECT username FROM users").fetchall() == [("alice",)]
        conn.close()
        daily = database.backup_sqlite_db()
        assert re.match(r"^fantasy\.db\.backup-\d{8}-\d{6}$", os.path.basename(daily))

    def test_backup_sqlite_db_season_label_is_sanitised(self, tmp_path, monkeypatch):
        """Failure path: a label like "../../etc/S 16!" gives a file inside the live DB's directory whose label part matches [A-Za-z0-9-]+ (no "/", no ".."); a label with no usable characters still gives a valid name."""
        db_file = _season_db_file(tmp_path, monkeypatch)
        path = database.backup_sqlite_db(kind="season", label="../../etc/S 16!")
        assert os.path.dirname(path) == str(db_file.parent)
        m = re.match(r"^fantasy\.db\.season-([A-Za-z0-9-]+)-\d{8}-\d{6}$", os.path.basename(path))
        assert m and m.group(1) == "etc-S-16"
        assert database.season_label_slug("!!! ///") == "season"
        assert database.season_label_slug("x" * 500) == "x" * database.SEASON_LABEL_MAX
        # The same names come from renaming Reset's backup.
        daily = database.backup_sqlite_db()
        renamed = database.rename_to_season_backup(daily, "..")
        assert os.path.basename(renamed).startswith("fantasy.db.season-season-")
        assert os.path.dirname(renamed) == str(db_file.parent) and not os.path.exists(daily)

    def test_rename_to_season_backup_never_overwrites_an_existing_season_backup(self, tmp_path, monkeypatch):
        """Security review: two backups renamed to the same label in the same second keep both files (the second gets a -2 suffix), and both are listed as season backups."""
        db_file = _season_db_file(tmp_path, monkeypatch)
        first = _backup_file(db_file, "backup", "20261118-120000")
        second = _backup_file(db_file, "backup", "20261118-120000-copy")
        second.rename(db_file.parent / "second.tmp")
        a = database.rename_to_season_backup(str(first), "Season 16")
        again = _backup_file(db_file, "backup", "20261118-120000")
        b = database.rename_to_season_backup(str(again), "Season 16")
        assert os.path.basename(a) == "fantasy.db.season-Season-16-20261118-120000"
        assert os.path.basename(b) == "fantasy.db.season-Season-16-20261118-120000-2"
        assert os.path.exists(a) and os.path.exists(b)
        assert {p.name for p in database.list_season_backups()} >= {os.path.basename(a), os.path.basename(b)}

    def test_reset_backup_failure_hides_the_error_text(self, monkeypatch):
        """Security review: when the season backup raises, Reset answers 500 naming only the error's type (no path or message from the exception) and deletes nothing."""
        import inspect
        from routers import admin_season
        src = inspect.getsource(admin_season.reset_season)
        assert "pre-reset backup failed ({type(e).__name__})" in src
        assert "backup failed: {e}" not in src
        assert "logger.exception(" in src

    def test_cleanup_old_backups_never_deletes_season_backups(self, tmp_path, monkeypatch):
        """cleanup_old_backups(14) deletes an old fantasy.db.backup-* file but keeps a fantasy.db.season-* file with an mtime far past the retention."""
        db_file = _season_db_file(tmp_path, monkeypatch)
        old_daily = _backup_file(db_file, "backup", "20250101-000000", age_seconds=400 * 86400)
        old_season = _backup_file(db_file, "season", "Season-1-20250101-000000", age_seconds=400 * 86400)
        assert database.cleanup_old_backups(14) == 1
        assert not old_daily.exists() and old_season.exists()

    def test_list_season_backups_apart_from_daily(self, tmp_path, monkeypatch):
        """list_sqlite_backups() returns only fantasy.db.backup-* files and the season list returns only fantasy.db.season-* files, each newest first."""
        db_file = _season_db_file(tmp_path, monkeypatch)
        d_old = _backup_file(db_file, "backup", "20261001-000000", 200)
        d_new = _backup_file(db_file, "backup", "20261002-000000", 100)
        s_old = _backup_file(db_file, "season", "Season-15-20260601-000000", 300)
        s_new = _backup_file(db_file, "season", "Season-16-20261117-000000", 50)
        assert database.list_sqlite_backups() == [d_new, d_old]
        assert database.list_season_backups() == [s_new, s_old]

    def test_reset_season_takes_season_backup_named_after_label(self, db, tmp_path, monkeypatch):
        """reset_season after End Season "Season 16" takes the backup (backup_sqlite_db(), as before) and renames it to fantasy.db.season-Season-16-<timestamp> (the label the preview shows), and returns backup_file = the season backup's basename; no daily backup is left behind."""
        from routers.admin_season import SeasonResetBody, reset_season
        db_file = _season_db_file(tmp_path, monkeypatch)
        _seed_season(db)
        _user(db, "alice")  # End Season archives one row per user
        _end(db, label="Season 15", store_summary=False)
        db.query(SeasonArchive).update({SeasonArchive.archived_at: 1})
        db.commit()
        _end(db)
        assert season_reset.preview(db)["season_label"] == "Season 16"
        result = reset_season(SeasonResetBody(force=True), db=db, admin=dict(_ADMIN))
        assert _SEASON_NAME_RE.match(result["backup_file"]), result["backup_file"]
        assert result["backup_path"] == str(db_file.parent / result["backup_file"])
        # Check the file through the directory listing, not the response's path string.
        season_files = database.list_season_backups()
        assert [str(p) for p in season_files] == [result["backup_path"]]
        assert season_files[0].is_file()
        assert database.list_sqlite_backups() == []
        assert [p.name for p in season_files] == [result["backup_file"]]
        assert result["season_label"] == "Season 16"
        # An explicit label wins; without any archive the backup is "unarchived".
        assert season_reset.backup_label(db) == "Season 16"
        db.query(SeasonArchive).delete()
        db.commit()
        assert season_reset.backup_label(db) == "unarchived"

    def test_reset_season_aborts_without_deletes_when_season_backup_fails(self, db, monkeypatch):
        """Failure path: when the season backup returns None or raises, reset answers 500, deletes nothing (matches, weekly_summaries, live_matches still there), leaves the caches and the demo clock, and writes no admin_season_reset audit row."""
        import routers.admin_season as admin_season
        _seed_season(db)
        db.add(Week(id=1, label="Week 1", start_time=_T0, end_time=_T0 + _DAY))
        db.add(WeeklySummary(week_id=1, generated_at=_T0))
        db.add(LiveMatch(match_id=1, league_id=1, players_json="[]", first_seen_at=_T0, last_seen_at=_T0))
        clock.set_override(db, _T0)
        db.commit()
        _fill_caches()

        def raises(*a, **k):
            raise OSError("disk full")
        for stub in (lambda *a, **k: None, raises):
            monkeypatch.setattr(admin_season, "backup_sqlite_db", stub)
            with pytest.raises(HTTPException) as exc:
                admin_season.reset_season(admin_season.SeasonResetBody(force=True), db=db, admin=dict(_ADMIN))
            assert exc.value.status_code == 500
            db.rollback()
            for name in ("matches", "weekly_summaries", "live_matches"):
                assert _count(db, name) >= 1, name
            assert clock.get_override(db) == _T0
            assert not _caches_empty()
            assert db.query(AuditLog).filter_by(action="admin_season_reset").count() == 0

    def test_list_backups_endpoint_returns_season_backups_apart(self, db, tmp_path, monkeypatch):
        """GET /admin/backups returns daily files under `backups` and season files under `season_backups` (filename, size_bytes, created_at), never one file in both."""
        from routers import admin_backups
        db_file = _season_db_file(tmp_path, monkeypatch)
        daily = _backup_file(db_file, "backup", "20261002-000000", 100)
        season = _backup_file(db_file, "season", "Season-16-20261117-000000", 50)
        result = admin_backups.list_backups(admin=dict(_ADMIN))
        assert [b["filename"] for b in result["backups"]] == [daily.name]
        assert [b["filename"] for b in result["season_backups"]] == [season.name]
        assert set(result["season_backups"][0]) == {"filename", "size_bytes", "created_at"}
        assert result["season_backups"][0]["size_bytes"] == season.stat().st_size

    def test_download_backup_serves_season_backup(self, db, tmp_path, monkeypatch):
        """GET /admin/backups/<season file name>?confirm=DOWNLOAD BACKUP (admin, recent re-auth) answers 200 with the file as an attachment and writes an admin_db_backup_download audit row."""
        db_file = _season_db_file(tmp_path, monkeypatch)
        season = _backup_file(db_file, "season", "Season-16-20261117-000000")
        resp = _admin_client(db).get(f"/admin/backups/{season.name}", params={"confirm": "DOWNLOAD BACKUP"})
        assert resp.status_code == 200, resp.text
        assert resp.content == season.read_bytes()
        assert "attachment" in resp.headers["content-disposition"]
        assert season.name in resp.headers["content-disposition"]
        audit = db.query(AuditLog).filter_by(action="admin_db_backup_download").one()
        assert audit.detail == f"filename={season.name}"

    def test_download_season_backup_without_confirmation_or_reauth_refused(self, db, tmp_path, monkeypatch):
        """Failure path: downloading a season backup answers 400 confirmation_required without the phrase and 403 reauth_required without a recent re-auth; a traversal name ("../fantasy.db") answers 404."""
        db_file = _season_db_file(tmp_path, monkeypatch)
        season = _backup_file(db_file, "season", "Season-16-20261117-000000")
        client = _admin_client(db)
        resp = client.get(f"/admin/backups/{season.name}")
        assert resp.status_code == 400 and resp.json()["detail"] == "confirmation_required"
        stale = _admin_client(db, reauth=False).get(f"/admin/backups/{season.name}",
                                                    params={"confirm": "DOWNLOAD BACKUP"})
        assert stale.status_code == 403 and stale.json()["detail"] == "reauth_required"
        for name in ("..%2Ffantasy.db", "fantasy.db", "fantasy.db.season-..%2F..%2Fx"):
            assert client.get(f"/admin/backups/{name}", params={"confirm": "DOWNLOAD BACKUP"}).status_code == 404
        assert db.query(AuditLog).filter_by(action="admin_db_backup_download").count() == 0

    def test_backups_panel_lists_season_backups_apart(self):
        """Source-reading (index.html, app-admin-backups.js): the Database Backups panel has a separate season-backups table filled by loadBackups from season_backups, with the same Download button (downloadBackup through adminFetch), and its text says season backups are never deleted automatically."""
        html = _fe("index.html")
        panel = html[html.index('<h3 class="admin-panel-title">Database Backups</h3>'):html.index("Demo Mode panel is injected")]
        assert 'id="dbBackupsBody"' in panel and 'id="dbSeasonBackupsBody"' in panel
        assert panel.index('id="dbBackupsBody"') < panel.index('id="dbSeasonBackupsBody"')
        assert "Season backups are never deleted automatically" in panel
        js = _fe("app-admin-backups.js")
        load = _fn_source(js, "loadBackups")
        assert "data.season_backups" in load and "dbSeasonBackupsBody" in load
        assert "_backupRowsHtml(seasonBackups)" in load and "_backupRowsHtml(data.backups)" in load
        rows = _fn_source(js, "_backupRowsHtml")
        assert "downloadBackup(this.dataset.filename)" in rows
        assert "adminFetch" in _fn_source(js, "downloadBackup")

    def test_gitignore_ignores_season_backup_files(self):
        """`git check-ignore -q data/fantasy.db.season-Season-16-20261117-120000` succeeds (.gitignore has a data/*.season-* pattern next to data/*.backup-*)."""
        lines = _read(".gitignore").splitlines()
        assert "data/*.season-*" in lines and "data/*.backup-*" in lines
        assert "*.db.season-*" in _read(".dockerignore").splitlines()
        git = shutil.which("git")
        if not git or not os.path.isdir(os.path.join(_ROOT, ".git")):
            pytest.skip("not a git checkout")
        res = subprocess.run([git, "check-ignore", "-q", "data/fantasy.db.season-Season-16-20261117-120000"],
                             cwd=_ROOT, capture_output=True)
        assert res.returncode == 0


# ===========================================================================
# Story 5: One Guided End-of-Season Flow
# ===========================================================================

class TestGuidedEndOfSeasonFlow:

    def test_end_season_result_offers_continue_to_reset(self):
        """Source-reading / Node harness (app-admin-season.js): after a successful End Season the result says "Season <label> archived. The season's data is still live: continue to Reset Season to start the next season." with a "Continue to Reset Season" button that opens the Reset dialog (openSeasonResetConfirm)."""
        html = _fe("index.html")
        assert ('<button id="endSeasonResultContinueBtn" class="danger" style="flex:1;" '
                'onclick="continueToSeasonReset()">Continue to Reset Season</button>') in html
        result_modal = html[html.index('id="endSeasonResultModal"'):html.index("<!-- Player Management: Bulk Add Modal")]
        assert ">Later</button>" in result_modal
        out = _season_harness("""
  const el = id => document.getElementById(id);
  ["awards", "champions", "played", "summary"].forEach(p => el(`endSeasonPart_${p}`).checked = true);
  el("endSeasonDialogLabel").value = "Season 16";
  el("endSeasonResultModal").classList.add("hidden");
  __adminReply = {season_label: "Season 16", archived_users: 2, accolades: 3, champions: 0,
                  summary: {players: 3, teams: 2}, warning: "No champions recorded; add them in Player management"};
  await confirmEndSeason();
  const shown = !el("endSeasonResultModal").classList.contains("hidden");
  const text = el("endSeasonResultText").textContent;
  let opened = false;
  openSeasonResetConfirm = async () => { opened = true; };
  continueToSeasonReset();
  out = {shown, text, opened, closed: el("endSeasonResultModal").classList.contains("hidden"),
         status: __calls.status.seasonLifecycleStatus};
""")
        assert out["shown"] is True
        assert out["text"] == ("Season Season 16 archived. The season's data is still live: "
                               "continue to Reset Season to start the next season.")
        assert out["opened"] is True and out["closed"] is True
        assert "summary of 3 players and 2 teams" in out["status"]

    def test_reset_preview_lists_deleted_and_kept_counts(self, db, monkeypatch):
        """GET /admin/season/reset-preview (admin) returns `delete` with a row count per cleared table plus users_tokens_reset, `initial_tokens`, `keep` with a row count per kept table (including season_player_stats, season_team_results, season_accolades), and the season backup's label."""
        monkeypatch.setenv("INITIAL_TOKENS", "5")
        _seed_season(db)
        _user(db, "alice")
        _end(db)
        data = _admin_client(db).get("/admin/season/reset-preview").json()
        assert set(data["delete"]) == set(season_reset.CLEARED_TABLES) | {
            "users_tokens_reset", "leagues_unmonitored", "demo_clock_override"}
        assert data["delete"]["matches"] == 5 and data["delete"]["player_match_stats"] == len(_STATS)
        assert data["delete"]["players"] == 4 and data["delete"]["leagues_unmonitored"] == 2
        assert data["delete"]["users_tokens_reset"] == 2 and data["initial_tokens"] == 5
        assert set(data["keep"]) == set(season_reset.KEPT_TABLES)
        assert data["keep"]["season_player_stats"] == 3 and data["keep"]["season_team_results"] == 3
        assert data["keep"]["season_accolades"] == db.query(SeasonAccolade).count() > 0
        assert data["season_label"] == "Season 16"
        assert data["end_season_missing"] is False and data["warning"] is None

    def test_reset_preview_changes_nothing(self, db, monkeypatch):
        """Calling the preview leaves every table's row count, users' tokens, leagues' is_monitored, the demo clock and the caches unchanged, takes no backup and writes no audit row."""
        from routers import admin_season
        _seed_season(db)
        _user(db, "alice", tokens=42)
        clock.set_override(db, _T0)
        db.commit()
        client = _admin_client(db)
        _fill_caches()
        caches = _caches_state()
        backups = []
        monkeypatch.setattr(admin_season, "backup_sqlite_db", lambda *a, **k: backups.append(1))
        before = _snapshot(db, Base.metadata.tables)
        assert client.get("/admin/season/reset-preview").status_code == 200
        assert _snapshot(db, Base.metadata.tables) == before
        assert _caches_state() == caches
        assert backups == []
        assert clock.get_override(db) == _T0

    def test_reset_preview_counts_match_reset_counts(self, db, monkeypatch):
        """The preview's delete counts equal the counts reset_season then returns for the same data."""
        _fill_cleared(db, 3)
        _user(db, "alice")
        db.add(League(id=1, name="L", is_monitored=True))
        clock.set_override(db, _T0)
        db.commit()
        preview = season_reset.preview(db)
        result = _reset(db, monkeypatch)
        assert preview["delete"] == result["counts"]
        assert preview["keep"] == result["kept"]

    def test_reset_preview_warns_when_end_season_not_run(self, db, monkeypatch):
        """With a locked week and no newer season_archive, the preview has a warning (`end_season_missing: true` and a message) and reset_season(force=False) still answers 409."""
        db.add(Week(id=1, label="Week 1", start_time=_T0, end_time=_T0 + _DAY, is_locked=True))
        db.commit()
        data = _admin_client(db).get("/admin/season/reset-preview").json()
        assert data["end_season_missing"] is True
        assert "Run End Season first" in data["warning"]
        with pytest.raises(HTTPException) as exc:
            _reset(db, monkeypatch, force=False)
        assert exc.value.status_code == 409
        db.rollback()
        # An archive newer than the lock clears the warning.
        db.add(SeasonArchive(season_label="S", user_id=None, username="u", points=0, rank=1, archived_at=_T0 + 1))
        db.commit()
        assert season_reset.preview(db)["end_season_missing"] is False

    def test_reset_preview_requires_admin(self, db):
        """Failure path: GET /admin/season/reset-preview answers 401 for anonymous and 403 for a non-admin user."""
        assert _client(db).get("/admin/season/reset-preview").status_code == 401
        bob = _user(db, "bob")
        assert _client(db, login=bob).get("/admin/season/reset-preview").status_code == 403

    def test_reset_dialog_shows_preview_before_confirmation(self):
        """Source-reading / Node harness: openSeasonResetConfirm fetches /admin/season/reset-preview and renders the delete list (with counts and "N users' tokens reset to 5") and the keep list in #seasonResetModal before the typed RESET SEASON input is used; the preview's warning is shown when present."""
        html = _fe("index.html")
        modal = html[html.index('id="seasonResetModal"'):html.index("<!-- Typed confirmation")]
        assert modal.index('id="seasonResetDeleteList"') < modal.index('id="seasonResetConfirmInput"')
        assert modal.index('id="seasonResetKeepList"') < modal.index('id="seasonResetConfirmInput"')
        out = _season_harness("""
  __fetchReply = {season_label: "Season 16", initial_tokens: 5,
                  delete: {matches: 12, player_match_stats: 120, weeks: 0, users_tokens_reset: 3, leagues_unmonitored: 2},
                  keep: {season_accolades: 40, season_player_stats: 30, audit_logs: 0},
                  end_season_missing: true, warning: "Locked weeks exist. Run End Season first or pass force=true."};
  const el = id => document.getElementById(id);
  await openSeasonResetConfirm();
  out = {url: __calls.fetch[0], del: el("seasonResetDeleteList").innerHTML, keep: el("seasonResetKeepList").innerHTML,
         warning: el("seasonResetWarning").textContent, warnHidden: el("seasonResetWarning").hidden,
         shown: el("seasonResetModal").style.display};
""")
        assert out["url"] == "/admin/season/reset-preview"
        assert out["shown"] == "flex"
        assert "<li>Matches: 12</li>" in out["del"] and "<li>Player game stats: 120</li>" in out["del"]
        assert "Weeks" not in out["del"]  # nothing to delete there
        assert "3 users&#39; tokens reset to 5" in out["del"] or "3 users' tokens reset to 5" in out["del"]
        assert "Leagues unmonitored: 2" in out["del"]
        assert "Accolades (history): 40" in out["keep"] and "Season player summaries: 30" in out["keep"]
        assert "Season 16" in out["keep"]
        assert out["warnHidden"] is False and "Run End Season first" in out["warning"]

    def test_reset_result_lists_counts_and_backup_file_name(self):
        """Node harness: after a successful reset the result lists the deleted counts from the response and the season backup's file name (backup_file), instead of only "Season reset complete"."""
        out = _season_harness("""
  const el = id => document.getElementById(id);
  el("seasonResetConfirmInput").value = "reset season";
  __adminReply = {status: "ok", initial_tokens: 5, backup_file: "fantasy.db.season-Season-16-20261117-120000",
                  counts: {matches: 12, weeks: 9, cards: 0, users_tokens_reset: 3}};
  await confirmSeasonReset();
  out = {status: __calls.status.seasonLifecycleStatus, body: __calls.adminFetch[0].body,
         backups: !!__calls.backups};
""")
        status = out["status"]
        assert status.startswith("Season reset complete. Deleted: 12 matches, 9 weeks;")
        assert "cards" not in status
        assert "3 users' tokens reset to 5" in status
        assert status.endswith("Season backup: fantasy.db.season-Season-16-20261117-120000")
        assert out["body"]["confirm"] == "reset season" and out["backups"] is True


class TestResetDialogSavesMissingSummary:
    """Coordinator addition: the Reset dialog offers POST /admin/season/summary for a
    season archived without a summary (Season 16 in production), before the reset."""

    def test_reset_preview_reports_label_and_summary_state(self, db):
        """GET /admin/season/reset-preview reports `season_label` (newest archived label), `archived`, `has_summary` and the stored summary's player and team row counts."""
        _seed_season(db)
        _user(db, "alice")
        client = _admin_client(db)
        data = client.get("/admin/season/reset-preview").json()
        assert (data["season_label"], data["archived"], data["has_summary"]) == ("unarchived", False, False)
        _end(db, store_summary=False)
        data = client.get("/admin/season/reset-preview").json()
        assert data["season_label"] == "Season 16" and data["archived"] is True
        assert (data["has_summary"], data["summary_players"], data["summary_teams"]) == (False, 0, 0)
        resp = client.post("/admin/season/summary", json={"season_label": "Season 16", "confirm": "SAVE SUMMARY"})
        assert resp.status_code == 200, resp.text
        data = client.get("/admin/season/reset-preview").json()
        assert (data["has_summary"], data["summary_players"], data["summary_teams"]) == (True, 3, 3)
        assert data["keep"]["season_player_stats"] == 3 and data["keep"]["season_team_results"] == 3

    def test_reset_dialog_summary_notice_sits_above_lists(self):
        """Source-reading: #seasonResetSummary is inside #seasonResetModal, above the Deleted/Kept lists and the typed field; the Season section's last button is still Reset Season…"""
        html = _fe("index.html")
        modal = html[html.index('id="seasonResetModal"'):html.index("<!-- Typed confirmation")]
        assert modal.index('id="seasonResetSummary"') < modal.index('id="seasonResetDeleteList"')
        assert modal.index('id="seasonResetSummary"') < modal.index('id="seasonResetConfirmInput"')
        js = _fe("app-admin-season.js")
        save = _fn_source(js, "saveSeasonSummary")
        assert 'typedConfirm("season_summary"' in save and "adminFetch(`${API}/admin/season/summary`" in save
        assert "_escHtml(p.season_label)" in _fn_source(js, "seasonResetSummaryHtml")

    def test_reset_dialog_offers_save_summary_then_reloads_preview(self):
        """Node harness: a preview without a summary shows "Season <label> has no stored summary. Save it before resetting, or its player and team results are lost." (label escaped) and a Save season summary button; saving runs the season_summary typed confirmation, posts through adminFetch and reloads the preview, which then shows "Season summary stored: N players, M teams." and no button."""
        out = _season_harness("""
  const base = {initial_tokens: 5, delete: {matches: 2, users_tokens_reset: 1}, keep: {}, warning: null};
  __fetchReply = {...base, season_label: "S<16>", archived: true, has_summary: false, summary_players: 0, summary_teams: 0};
  const el = id => document.getElementById(id);
  await openSeasonResetConfirm();
  const before = el("seasonResetSummary").innerHTML;
  __fetchReply = {...base, season_label: "S<16>", archived: true, has_summary: true, summary_players: 3, summary_teams: 2};
  __adminReply = {season_label: "S<16>", players: 3, teams: 2};
  await saveSeasonSummary();
  const unarchived = seasonResetSummaryHtml({...base, season_label: "unarchived", archived: false, has_summary: false});
  out = {before, after: el("seasonResetSummary").innerHTML, typed: __calls.typed,
         post: __calls.adminFetch[0], fetches: __calls.fetch, status: el("seasonResetModalStatus").textContent,
         unarchived};
""")
        assert ("Season S&lt;16&gt; has no stored summary. Save it before resetting, "
                "or its player and team results are lost.") in out["before"]
        assert 'onclick="saveSeasonSummary()">Save season summary</button>' in out["before"]
        assert "S<16>" not in out["before"]
        assert out["typed"] == "season_summary"
        assert out["post"] == {"url": "/admin/season/summary", "body": {"season_label": "S<16>", "confirm": "SAVE SUMMARY"}}
        assert out["fetches"] == ["/admin/season/reset-preview", "/admin/season/reset-preview"]
        assert out["after"] == "<p>Season summary stored: 3 players, 2 teams.</p>"
        assert "Saved the summary" in out["status"]
        assert out["unarchived"] == ""
