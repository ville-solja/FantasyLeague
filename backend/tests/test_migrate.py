import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text

from database import Base
from migrate import run_migrations


@pytest.fixture
def fresh_engine():
    """In-memory SQLite engine with the current ORM schema (all columns present)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def legacy_engine():
    """
    In-memory SQLite engine whose player_match_stats table is missing the
    expanded scoring columns and is_mvp — simulates a DB created before
    those columns were added.
    """
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("CREATE TABLE leagues (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("CREATE TABLE teams (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("CREATE TABLE players (id INTEGER PRIMARY KEY, name TEXT, avatar_url TEXT)"))
        conn.execute(text("""
            CREATE TABLE matches (
                match_id INTEGER PRIMARY KEY,
                radiant_team_id INTEGER, dire_team_id INTEGER,
                league_id INTEGER, start_time INTEGER,
                radiant_win BOOLEAN, week_override_id INTEGER
            )
        """))
        # Stripped player_match_stats: has only original 7-stat columns, no expanded columns, no is_mvp
        conn.execute(text("""
            CREATE TABLE player_match_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER, match_id INTEGER,
                team_id INTEGER, fantasy_points FLOAT,
                kills INTEGER DEFAULT 0, assists INTEGER DEFAULT 0,
                deaths INTEGER DEFAULT 0, gold_per_min FLOAT DEFAULT 0,
                obs_placed INTEGER DEFAULT 0, sen_placed INTEGER DEFAULT 0,
                tower_damage INTEGER DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, username TEXT, email TEXT,
                password_hash TEXT, is_admin BOOLEAN, tokens INTEGER DEFAULT 5,
                created_at INTEGER, player_id INTEGER, must_change_password BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE weeks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT, start_time INTEGER, end_time INTEGER,
                is_locked BOOLEAN DEFAULT 0
            )
        """))
        conn.execute(text("""
            CREATE TABLE cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER, owner_id INTEGER, card_type TEXT,
                league_id INTEGER, is_active BOOLEAN, generation INTEGER DEFAULT 1
            )
        """))
        conn.execute(text("""
            CREATE TABLE card_modifiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER, stat_key VARCHAR, bonus_pct FLOAT
            )
        """))
        conn.execute(text("CREATE TABLE weights (key TEXT PRIMARY KEY, label TEXT, value FLOAT)"))
        conn.execute(text("""
            CREATE TABLE weekly_roster_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_id INTEGER, user_id INTEGER, card_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE, token_amount INTEGER, created_by_id INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE code_redemptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code_id INTEGER, user_id INTEGER, redeemed_at INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER, actor_id INTEGER,
                actor_username TEXT, action TEXT, detail TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE player_profiles (
                player_id INTEGER PRIMARY KEY,
                facts_json TEXT, bio_text TEXT,
                facts_fetched_at INTEGER, bio_generated_at INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE twitch_link_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, code TEXT, expires_at INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE twitch_presence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                twitch_user_id TEXT, channel_id TEXT, seen_at INTEGER
            )
        """))
        conn.execute(text("""
            CREATE TABLE twitch_mvp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER, player_id INTEGER, channel_id TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE twitch_token_drops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id INTEGER, channel_id TEXT, dropped_at INTEGER
            )
        """))
        conn.commit()
    return engine


# ---------------------------------------------------------------------------
# Idempotency on a fully-current schema
# ---------------------------------------------------------------------------

class TestMigrationsIdempotent:
    def test_first_run_does_not_raise(self, fresh_engine):
        run_migrations(fresh_engine)  # should not raise

    def test_second_run_does_not_raise(self, fresh_engine):
        run_migrations(fresh_engine)
        run_migrations(fresh_engine)  # must remain safe to call twice

    def test_indexes_created(self, fresh_engine):
        run_migrations(fresh_engine)
        with fresh_engine.connect() as conn:
            indexes = {
                r[0]
                for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='index'")
                ).fetchall()
            }
        assert "ix_cards_owner_id" in indexes
        assert "ix_pms_player_id" in indexes
        assert "ix_pms_match_id" in indexes


# ---------------------------------------------------------------------------
# Column additions on a legacy schema
# ---------------------------------------------------------------------------

class TestMigrationsAddColumns:
    def _pms_cols(self, engine) -> set:
        with engine.connect() as conn:
            return {
                r[1]
                for r in conn.execute(
                    text("PRAGMA table_info(player_match_stats)")
                ).fetchall()
            }

    def test_adds_is_mvp(self, legacy_engine):
        assert "is_mvp" not in self._pms_cols(legacy_engine)
        run_migrations(legacy_engine)
        assert "is_mvp" in self._pms_cols(legacy_engine)

    def test_adds_last_hits(self, legacy_engine):
        assert "last_hits" not in self._pms_cols(legacy_engine)
        run_migrations(legacy_engine)
        assert "last_hits" in self._pms_cols(legacy_engine)

    def test_adds_towers_killed(self, legacy_engine):
        run_migrations(legacy_engine)
        assert "towers_killed" in self._pms_cols(legacy_engine)

    def test_adds_teamfight_participation(self, legacy_engine):
        run_migrations(legacy_engine)
        assert "teamfight_participation" in self._pms_cols(legacy_engine)

    def test_adds_camps_stacked(self, legacy_engine):
        run_migrations(legacy_engine)
        assert "camps_stacked" in self._pms_cols(legacy_engine)

    def test_adds_firstblood_claimed(self, legacy_engine):
        run_migrations(legacy_engine)
        assert "firstblood_claimed" in self._pms_cols(legacy_engine)

    def test_adds_stuns(self, legacy_engine):
        run_migrations(legacy_engine)
        assert "stuns" in self._pms_cols(legacy_engine)

    def test_existing_rows_preserved_after_column_addition(self, legacy_engine):
        with legacy_engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO player_match_stats (player_id, match_id, kills, deaths)"
                " VALUES (1, 1, 5, 2)"
            ))
            conn.commit()

        run_migrations(legacy_engine)

        with legacy_engine.connect() as conn:
            row = conn.execute(
                text("SELECT kills, deaths FROM player_match_stats WHERE player_id = 1")
            ).first()
        assert row.kills == 5
        assert row.deaths == 2

    def test_idempotent_on_legacy_engine(self, legacy_engine):
        run_migrations(legacy_engine)
        run_migrations(legacy_engine)  # second call must not raise


# ---------------------------------------------------------------------------
# card_modifiers CHECK constraint migration
# ---------------------------------------------------------------------------

class TestCardModifiersConstraintMigration:
    def test_old_stat_keys_removed_after_migration(self, legacy_engine):
        with legacy_engine.connect() as conn:
            conn.execute(text(
                "INSERT INTO card_modifiers (card_id, stat_key, bonus_pct)"
                " VALUES (1, 'assists', 10.0), (1, 'kills', 10.0)"
            ))
            conn.commit()

        run_migrations(legacy_engine)

        with legacy_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT stat_key FROM card_modifiers")
            ).fetchall()
        stat_keys = {r[0] for r in rows}
        assert "assists" not in stat_keys
        assert "kills" in stat_keys  # valid stat should survive

    def test_check_constraint_applied_after_migration(self, legacy_engine):
        run_migrations(legacy_engine)
        with legacy_engine.connect() as conn:
            ddl = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='card_modifiers'"
            )).scalar() or ""
        assert "ck_card_modifiers_stat_key" in ddl
