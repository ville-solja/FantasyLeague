"""
Tests for plan-issue-81-season-lifecycle.

Covers five user stories from markdown/plans/plan-issue-81-season-lifecycle.md:

  Story: End Season Archive
    - POST /admin/season/end snapshots the season leaderboard into season_archive
    - Tester accounts are excluded from the archive
    - Re-archiving with the same season label returns 409
    - The action writes an audit log entry with action admin_season_archived
    - Non-admin requests to POST /admin/season/end return 403

  Story: Season Reset
    - POST /admin/season/reset deletes matches, player_match_stats, match_bans,
      weeks, weekly_roster_entries, twitch_mvp, twitch_token_drops
    - All cards are set inactive; users, tags, audit logs, archives are retained
    - Every user's token balance is reset to INITIAL_TOKENS
    - All monitored leagues are unmonitored
    - 409 when locked weeks exist without a newer archive; force=true overrides
    - The action writes an audit log entry with action admin_season_reset
    - Non-admin requests to POST /admin/season/reset return 403

  Story: Past Seasons Visibility
    - GET /leaderboard/seasons lists archived season labels with dates
    - GET /leaderboard/seasons/{season_id} returns the archived standings
    - Unknown season_id returns 404
    - GET /profile/{user_id} includes a past_seasons array
    - Leaderboard "Past Seasons" selector (frontend-only)
    - Profile past placement rendering (frontend-only)

  Story: Manual Week Creation with Date-Only Inputs
    - POST /admin/weeks derives start_time as 00:00:00 UTC on start_date
    - POST /admin/weeks derives end_time as 03:00:00 UTC the day after end_date
    - PATCH /admin/weeks/{id} accepts the same date-only inputs
    - Validation still rejects end before start
    - Editing/deleting locked weeks stays blocked
    - Weeks are never auto-generated; background loop only auto-locks
    - Week forms use date inputs (frontend-only)

  Story: Retire Season Env Vars
    - generate_weeks (and season env parsing) removed from weeks.py
    - App imports cleanly with retired env vars absent
    - App imports cleanly with retired env vars still set (ignored)
    - schedule.py default URL is empty when SCHEDULE_SHEET_URL is unset
    - .env.example no longer lists the retired variables
"""

import datetime
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from models import (
    AuditLog, Card, CardModifier, League, Match, MatchBan, Player, PlayerMatchStats,
    SeasonArchive, Team, TwitchMVP, TwitchTokenDrop, User, Week, WeeklyRosterEntry,
)

_ADMIN = {"user_id": 1, "username": "admin", "is_admin": True}
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, username, is_tester=False, tokens=0):
    u = User(username=username, email=f"{username}@test.com",
             password_hash="x", tokens=tokens, is_tester=is_tester)
    db.add(u)
    db.flush()
    return u


def _make_week(db, label="Week 1", start_time=1_000_000, end_time=1_600_000, is_locked=False):
    w = Week(label=label, start_time=start_time, end_time=end_time, is_locked=is_locked)
    db.add(w)
    db.flush()
    return w


# ---------------------------------------------------------------------------
# Story: End Season Archive
# ---------------------------------------------------------------------------

class TestEndSeasonArchive:
    def test_end_season_snapshots_leaderboard_into_season_archive(self, db):
        from routers.admin import end_season, SeasonEndBody

        _make_user(db, "alice")
        _make_user(db, "bob")
        db.commit()

        result = end_season(SeasonEndBody(season_label="Season 1"), db=db, admin=_ADMIN)

        assert result["season_label"] == "Season 1"
        assert result["archived_users"] == 2
        rows = db.query(SeasonArchive).filter_by(season_label="Season 1").all()
        assert len(rows) == 2
        usernames = {r.username for r in rows}
        assert usernames == {"alice", "bob"}
        for r in rows:
            assert r.points == 0.0
            assert r.rank in (1, 2)

    def test_end_season_excludes_tester_accounts(self, db):
        from routers.admin import end_season, SeasonEndBody

        _make_user(db, "realuser")
        _make_user(db, "testeruser", is_tester=True)
        db.commit()

        result = end_season(SeasonEndBody(season_label="Season 2"), db=db, admin=_ADMIN)

        assert result["archived_users"] == 1
        rows = db.query(SeasonArchive).filter_by(season_label="Season 2").all()
        assert len(rows) == 1
        assert rows[0].username == "realuser"

    def test_end_season_duplicate_label_returns_409(self, db):
        from routers.admin import end_season, SeasonEndBody

        _make_user(db, "carol")
        db.commit()
        end_season(SeasonEndBody(season_label="Season 3"), db=db, admin=_ADMIN)

        with pytest.raises(HTTPException) as exc:
            end_season(SeasonEndBody(season_label="Season 3"), db=db, admin=_ADMIN)

        assert exc.value.status_code == 409
        rows = db.query(SeasonArchive).filter_by(season_label="Season 3").all()
        assert len(rows) == 1  # not duplicated

    def test_end_season_writes_audit_log_admin_season_archived(self, db):
        from routers.admin import end_season, SeasonEndBody

        _make_user(db, "dave")
        db.commit()

        end_season(SeasonEndBody(season_label="Season 4"), db=db, admin=_ADMIN)

        log = db.query(AuditLog).filter_by(action="admin_season_archived").first()
        assert log is not None
        assert log.actor_username == "admin"
        assert "Season 4" in log.detail

    def test_end_season_requires_admin_returns_403(self, db):
        """The route is declared with Depends(require_admin); confirm the
        guard itself rejects a non-admin caller."""
        from deps import require_admin

        with pytest.raises(HTTPException) as exc:
            require_admin({"user_id": 2, "username": "u", "is_admin": False})
        assert exc.value.status_code == 403

        admin_path = os.path.join(_BACKEND_DIR, "routers", "admin.py")
        with open(admin_path) as f:
            source = f.read()
        assert '"/admin/season/end"' in source


# ---------------------------------------------------------------------------
# Story: Season Reset
# ---------------------------------------------------------------------------

class TestSeasonReset:
    @pytest.fixture(autouse=True)
    def _stub_backup(self, monkeypatch):
        """reset_season() backs up the real configured SQLite file (database.DATABASE_URL),
        which is unrelated to this test's isolated in-memory `db` session and may not exist
        or be writable in a test environment — stub it out so these tests only exercise the
        reset logic itself, not the filesystem backup side effect."""
        import routers.admin as admin_module
        monkeypatch.setattr(admin_module, "backup_sqlite_db", lambda: "/tmp/fake-backup.db")

    def _seed_full_season_state(self, db):
        league = League(id=1, name="TestLeague", is_monitored=True)
        player = Player(id=1, name="P1")
        team = Team(id=1, name="TestTeam")
        db.add_all([league, player, team])
        db.flush()

        match = Match(match_id=1, league_id=1, start_time=1_000_000,
                      radiant_team_id=1, dire_team_id=2, radiant_win=True)
        db.add(match)
        db.flush()

        db.add(PlayerMatchStats(player_id=1, match_id=1, team_id=1, fantasy_points=10.0))
        db.add(MatchBan(match_id=1, hero_id=5))
        db.add(TwitchMVP(match_id=1, player_id=1, channel_id="c1", selected_at=1_000_000))
        db.add(TwitchTokenDrop(channel_id="c1", series_id="s1", dropped_at=1_000_000, count=3))

        user = _make_user(db, "eve", tokens=99)
        card = Card(player_id=1, owner_id=user.id, card_type="common",
                    league_id=1, is_active=True)
        db.add(card)
        db.flush()

        week = _make_week(db, start_time=1_000_000, end_time=1_600_000, is_locked=False)
        db.add(WeeklyRosterEntry(week_id=week.id, user_id=user.id, card_id=card.id))
        db.commit()
        return {"user": user, "card": card, "week": week, "league": league}

    def test_reset_deletes_all_per_season_data(self, db):
        from routers.admin import reset_season, SeasonResetBody

        self._seed_full_season_state(db)

        reset_season(SeasonResetBody(force=True), db=db, admin=_ADMIN)

        assert db.query(Match).count() == 0
        assert db.query(PlayerMatchStats).count() == 0
        assert db.query(MatchBan).count() == 0
        assert db.query(Week).count() == 0
        assert db.query(WeeklyRosterEntry).count() == 0
        assert db.query(TwitchMVP).count() == 0
        assert db.query(TwitchTokenDrop).count() == 0

    def test_reset_wipes_players_and_teams(self, db):
        """Players and Teams (including the admin-curated Player Pool) are
        cleared on reset so browse tabs don't show stale names forever —
        the admin repopulates the pool for the new season/league."""
        from routers.admin import reset_season, SeasonResetBody

        self._seed_full_season_state(db)
        assert db.query(Player).count() == 1
        assert db.query(Team).count() == 1

        reset_season(SeasonResetBody(force=True), db=db, admin=_ADMIN)

        assert db.query(Player).count() == 0
        assert db.query(Team).count() == 0

    def test_reset_deletes_cards_and_retains_users_tags_audit_archives(self, db):
        """Cards (and their modifiers) are deleted outright — not just
        deactivated — while user accounts, tags, audit logs, and season
        archives survive the reset."""
        from routers.admin import reset_season, SeasonResetBody, end_season, SeasonEndBody

        seeded = self._seed_full_season_state(db)
        db.add(CardModifier(card_id=seeded["card"].id, stat_key="kills", bonus_pct=10.0))
        end_season(SeasonEndBody(season_label="Pre-reset archive"), db=db, admin=_ADMIN)
        db.add(AuditLog(timestamp=int(time.time()), actor_id=1,
                         actor_username="admin", action="some_prior_action", detail="x"))
        db.commit()

        reset_season(SeasonResetBody(force=True), db=db, admin=_ADMIN)

        assert db.query(Card).count() == 0
        assert db.query(CardModifier).count() == 0
        assert db.get(User, seeded["user"].id) is not None
        assert db.query(SeasonArchive).filter_by(season_label="Pre-reset archive").count() == 1
        assert db.query(AuditLog).filter_by(action="some_prior_action").count() == 1

    def test_reset_restores_tokens_to_initial_tokens(self, db, monkeypatch):
        from routers.admin import reset_season, SeasonResetBody

        monkeypatch.setenv("INITIAL_TOKENS", "7")
        seeded = self._seed_full_season_state(db)
        assert seeded["user"].tokens == 99

        reset_season(SeasonResetBody(force=True), db=db, admin=_ADMIN)

        db.refresh(seeded["user"])
        assert seeded["user"].tokens == 7

    def test_reset_unmonitors_all_leagues(self, db):
        from routers.admin import reset_season, SeasonResetBody

        seeded = self._seed_full_season_state(db)
        assert seeded["league"].is_monitored is True

        reset_season(SeasonResetBody(force=True), db=db, admin=_ADMIN)

        db.refresh(seeded["league"])
        assert seeded["league"].is_monitored is False

    def test_reset_returns_409_when_locked_weeks_not_archived(self, db):
        from routers.admin import reset_season, SeasonResetBody

        _make_week(db, start_time=1_000_000, end_time=1_600_000, is_locked=True)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            reset_season(SeasonResetBody(force=False), db=db, admin=_ADMIN)

        assert exc.value.status_code == 409
        assert db.query(Week).count() == 1  # nothing deleted

    def test_reset_force_true_overrides_archive_guard(self, db):
        from routers.admin import reset_season, SeasonResetBody

        _make_week(db, start_time=1_000_000, end_time=1_600_000, is_locked=True)
        db.commit()

        result = reset_season(SeasonResetBody(force=True), db=db, admin=_ADMIN)

        assert result["status"] == "ok"
        assert db.query(Week).count() == 0

    def test_reset_writes_audit_log_admin_season_reset_with_counts(self, db):
        from routers.admin import reset_season, SeasonResetBody

        self._seed_full_season_state(db)

        result = reset_season(SeasonResetBody(force=True), db=db, admin=_ADMIN)

        assert "counts" in result
        assert result["counts"]["matches"] == 1
        log = db.query(AuditLog).filter_by(action="admin_season_reset").first()
        assert log is not None
        assert "matches=1" in log.detail

    def test_reset_requires_admin_returns_403(self, db):
        from deps import require_admin

        with pytest.raises(HTTPException) as exc:
            require_admin({"user_id": 2, "username": "u", "is_admin": False})
        assert exc.value.status_code == 403

        admin_path = os.path.join(_BACKEND_DIR, "routers", "admin.py")
        with open(admin_path) as f:
            source = f.read()
        assert '"/admin/season/reset"' in source


# ---------------------------------------------------------------------------
# Story: Past Seasons Visibility
# ---------------------------------------------------------------------------

class TestPastSeasonsVisibility:
    def test_leaderboard_seasons_lists_archived_labels_with_dates(self, db):
        from routers.admin import end_season, SeasonEndBody
        from routers.leaderboard import list_archived_seasons

        _make_user(db, "u1")
        db.commit()
        end_season(SeasonEndBody(season_label="Season A"), db=db, admin=_ADMIN)
        end_season(SeasonEndBody(season_label="Season B"), db=db, admin=_ADMIN)

        seasons = list_archived_seasons(db=db)

        labels = {s["season_label"] for s in seasons}
        assert labels == {"Season A", "Season B"}
        for s in seasons:
            assert s["archived_at"] is not None
            assert s["user_count"] == 1

    def test_leaderboard_season_detail_returns_archived_standings(self, db):
        from routers.admin import end_season, SeasonEndBody
        from routers.leaderboard import list_archived_seasons, archived_season_detail

        _make_user(db, "u2")
        db.commit()
        end_season(SeasonEndBody(season_label="Season C"), db=db, admin=_ADMIN)
        season_id = list_archived_seasons(db=db)[0]["id"]

        detail = archived_season_detail(season_id, db=db)

        assert detail["season_label"] == "Season C"
        assert len(detail["standings"]) == 1
        assert detail["standings"][0]["username"] == "u2"
        assert detail["standings"][0]["rank"] == 1

    def test_leaderboard_season_detail_unknown_id_returns_404(self, db):
        from routers.leaderboard import archived_season_detail

        with pytest.raises(HTTPException) as exc:
            archived_season_detail(999999, db=db)

        assert exc.value.status_code == 404

    def test_profile_includes_past_seasons_array(self, db):
        from routers.admin import end_season, SeasonEndBody
        from routers.profile import get_profile

        user = _make_user(db, "u3")
        db.commit()
        end_season(SeasonEndBody(season_label="Season D"), db=db, admin=_ADMIN)

        profile = get_profile(user.id, db=db)

        assert "past_seasons" in profile
        assert len(profile["past_seasons"]) == 1
        assert profile["past_seasons"][0]["season_label"] == "Season D"
        assert profile["past_seasons"][0]["rank"] == 1

    def test_leaderboard_shows_past_seasons_selector(self):
        # frontend-only: Past Seasons selector rendering lives in
        # frontend/app-leaderboard.js / frontend/index.html
        pytest.skip(
            "frontend-only: not testable via pytest — "
            "verify a Past Seasons selector appears in the Leaderboard tab "
            "when GET /leaderboard/seasons returns at least one entry"
        )

    def test_profile_renders_past_placements(self):
        # frontend-only: past placement lines (e.g. "Season 15 — 3rd, 1240 pts")
        # are rendered by frontend/app-profile.js
        pytest.skip(
            "frontend-only: not testable via pytest — "
            "verify the Profile view renders a line per past_seasons entry"
        )


# ---------------------------------------------------------------------------
# Story: Manual Week Creation with Date-Only Inputs
# ---------------------------------------------------------------------------

class TestManualWeekCreationDateOnly:
    def test_create_week_derives_start_time_midnight_utc(self, db):
        from routers.admin import create_week, WeekCreateBody

        result = create_week(
            WeekCreateBody(label="Week X", start_date="2026-04-06", end_date="2026-04-12"),
            db=db, admin=_ADMIN,
        )

        expected_start = int(datetime.datetime(2026, 4, 6, 0, 0, 0,
                                                tzinfo=datetime.timezone.utc).timestamp())
        assert result["start_time"] == expected_start

    def test_create_week_derives_end_time_3am_day_after_end_date(self, db):
        from routers.admin import create_week, WeekCreateBody

        result = create_week(
            WeekCreateBody(label="Week Y", start_date="2026-04-06", end_date="2026-04-12"),
            db=db, admin=_ADMIN,
        )

        expected_end = int(datetime.datetime(2026, 4, 13, 3, 0, 0,
                                              tzinfo=datetime.timezone.utc).timestamp())
        assert result["end_time"] == expected_end

    def test_patch_week_accepts_date_only_inputs(self, db):
        from routers.admin import create_week, edit_week, WeekCreateBody, WeekEditBody

        created = create_week(
            WeekCreateBody(label="Week Z", start_date="2026-05-04", end_date="2026-05-10"),
            db=db, admin=_ADMIN,
        )

        result = edit_week(
            created["id"],
            WeekEditBody(start_date="2026-05-05", end_date="2026-05-11"),
            db=db, admin=_ADMIN,
        )

        expected_start = int(datetime.datetime(2026, 5, 5, 0, 0, 0,
                                                tzinfo=datetime.timezone.utc).timestamp())
        expected_end = int(datetime.datetime(2026, 5, 12, 3, 0, 0,
                                              tzinfo=datetime.timezone.utc).timestamp())
        assert result["start_time"] == expected_start
        assert result["end_time"] == expected_end

    def test_create_week_rejects_end_before_start(self, db):
        from routers.admin import create_week, WeekCreateBody

        with pytest.raises(HTTPException) as exc:
            create_week(
                WeekCreateBody(label="Bad Week", start_date="2026-06-08", end_date="2026-06-01"),
                db=db, admin=_ADMIN,
            )

        assert exc.value.status_code == 422

    def test_locked_week_edit_and_delete_stay_blocked(self, db):
        from routers.admin import edit_week, delete_week, WeekEditBody

        week = _make_week(db, is_locked=True)
        db.commit()

        with pytest.raises(HTTPException) as exc_edit:
            edit_week(week.id, WeekEditBody(start_date="2026-01-01", end_date="2026-01-07"),
                      db=db, admin=_ADMIN)
        assert exc_edit.value.status_code == 409

        with pytest.raises(HTTPException) as exc_delete:
            delete_week(week.id, db=db, admin=_ADMIN)
        assert exc_delete.value.status_code == 409

    def test_weeks_are_not_auto_generated_background_loop_only_locks(self, db):
        """The maintenance loop in main.py only calls auto_lock_weeks — no
        week-generation function exists to call."""
        main_path = os.path.join(_BACKEND_DIR, "main.py")
        with open(main_path) as f:
            source = f.read()
        assert "generate_weeks" not in source
        assert "auto_lock_weeks" in source

        import weeks
        assert not hasattr(weeks, "generate_weeks")

    def test_week_forms_use_date_inputs(self):
        # frontend-only: Week Management create/edit forms switch from
        # datetime-local to date inputs in frontend/index.html /
        # frontend/app-admin.js
        pytest.skip(
            "frontend-only: not testable via pytest — "
            "verify Week Management create/edit forms use <input type=date>"
        )


# ---------------------------------------------------------------------------
# Story: Retire Season Env Vars
# ---------------------------------------------------------------------------

class TestRetireSeasonEnvVars:
    def test_generate_weeks_removed_from_weeks_module(self):
        import weeks
        assert not hasattr(weeks, "generate_weeks")
        assert not hasattr(weeks, "_parse_season_lock_anchor")
        assert not hasattr(weeks, "_parse_season_end")

        main_path = os.path.join(_BACKEND_DIR, "main.py")
        with open(main_path) as f:
            source = f.read()
        assert "generate_weeks" not in source

    def test_app_imports_cleanly_without_retired_env_vars(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("SEASON_LOCK_START", "SEASON_END", "AUTO_INGEST_LEAGUES")}
        env["DEBUG"] = "true"
        result = subprocess.run(
            [sys.executable, "-c", "import main"],
            cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_app_imports_cleanly_with_retired_env_vars_still_set(self):
        env = dict(os.environ)
        env["DEBUG"] = "true"
        env["SEASON_LOCK_START"] = "2026-03-08"
        env["SEASON_END"] = "2026-06-01"
        env["AUTO_INGEST_LEAGUES"] = "19368,19369"
        result = subprocess.run(
            [sys.executable, "-c", "import main"],
            cwd=_BACKEND_DIR, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_schedule_default_url_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv("SCHEDULE_SHEET_URL", raising=False)
        import importlib
        import schedule
        importlib.reload(schedule)
        try:
            assert schedule.SCHEDULE_SHEET_URL == ""
        finally:
            importlib.reload(schedule)  # restore normal env-derived state

    def test_env_example_omits_retired_vars(self):
        env_example_path = os.path.join(_BACKEND_DIR, "..", ".env.example")
        with open(env_example_path) as f:
            content = f.read()
        assert "SEASON_LOCK_START" not in content
        assert "SEASON_END" not in content
        assert "AUTO_INGEST_LEAGUES" not in content
