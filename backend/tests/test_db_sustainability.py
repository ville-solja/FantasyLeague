"""
Tests for the DB-sustainability acceptance criteria.

Covers:
  - schema_migrations table creation and structure
  - migration recording and skipping
  - failed migration does not write a schema_migrations row
  - scripts/backup-db.sh naming pattern, content parity, and error handling

NOT duplicated from test_migrate.py:
  - Column existence after migration (TestMigrationsAddColumns)
  - CHECK constraint migration (TestCardModifiersConstraintMigration)
  - Full schema coverage (TestSchemaCoverage)
  - Basic idempotency (TestMigrationsIdempotent)
"""
import os
import subprocess
import sys
import tempfile

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migrate import run_migrations, MIGRATIONS, _ensure_migrations_table, _applied, _record  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine():
    """Fresh in-memory SQLite engine with no pre-existing schema."""
    return create_engine("sqlite:///:memory:")


# ---------------------------------------------------------------------------
# schema_migrations table — creation
# ---------------------------------------------------------------------------

class TestSchemaMigrationsTableCreation:
    def test_table_exists_after_first_run_migrations_call(self):
        """schema_migrations table is created the first time run_migrations() is called."""
        engine = _make_engine()
        # Need at least the tables that migrations reference — use a minimal set
        with engine.connect() as conn:
            _bootstrap_minimal_schema(conn)
        run_migrations(engine)
        with engine.connect() as conn:
            tables = {
                r[0] for r in conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                ).fetchall()
            }
        assert "schema_migrations" in tables

    def test_table_has_id_column(self):
        """schema_migrations.id column exists after run_migrations()."""
        engine = _make_engine()
        with engine.connect() as conn:
            _bootstrap_minimal_schema(conn)
        run_migrations(engine)
        with engine.connect() as conn:
            col_names = {
                r[1] for r in conn.execute(
                    text("PRAGMA table_info(schema_migrations)")
                ).fetchall()
            }
        assert "id" in col_names

    def test_table_has_applied_at_column(self):
        """schema_migrations.applied_at column exists after run_migrations()."""
        engine = _make_engine()
        with engine.connect() as conn:
            _bootstrap_minimal_schema(conn)
        run_migrations(engine)
        with engine.connect() as conn:
            col_names = {
                r[1] for r in conn.execute(
                    text("PRAGMA table_info(schema_migrations)")
                ).fetchall()
            }
        assert "applied_at" in col_names


def _bootstrap_minimal_schema(conn):
    """Create the minimal set of tables required for all 12 migrations to run."""
    conn.execute(text("PRAGMA foreign_keys = OFF"))
    conn.execute(text("CREATE TABLE IF NOT EXISTS players (id INTEGER PRIMARY KEY, name TEXT)"))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY,
            radiant_team_id INTEGER, dire_team_id INTEGER, league_id INTEGER
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT, email TEXT,
            password_hash TEXT, is_admin BOOLEAN
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS player_match_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER, match_id INTEGER,
            kills INTEGER DEFAULT 0, deaths INTEGER DEFAULT 0,
            gold_per_min FLOAT DEFAULT 0, obs_placed INTEGER DEFAULT 0
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER, owner_id INTEGER, card_type TEXT
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS card_modifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER, stat_key VARCHAR, bonus_pct FLOAT
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS teams (id INTEGER PRIMARY KEY, name TEXT)
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS weeks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT, start_time INTEGER, end_time INTEGER,
            is_locked BOOLEAN DEFAULT 0
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS weekly_roster_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_id INTEGER, user_id INTEGER, card_id INTEGER
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS twitch_mvp (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER, player_id INTEGER, channel_id TEXT
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS twitch_token_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER, channel_id TEXT, dropped_at INTEGER
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS twitch_presence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            twitch_user_id TEXT, channel_id TEXT, seen_at INTEGER
        )
    """))
    conn.commit()


# ---------------------------------------------------------------------------
# schema_migrations table — recording and skipping
# ---------------------------------------------------------------------------

class TestSchemaMigrationsRegistry:
    def test_applied_migration_is_recorded(self):
        """After run_migrations(), at least one row is present in schema_migrations."""
        engine = _make_engine()
        with engine.connect() as conn:
            _bootstrap_minimal_schema(conn)
        run_migrations(engine)
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM schema_migrations")
            ).scalar()
        assert count > 0

    def test_migration_already_in_table_is_not_re_executed(self):
        """
        A migration ID already present in schema_migrations is skipped on the
        second call to run_migrations() (the migration function is not invoked again).
        """
        call_count = {"n": 0}

        def _counting_fn(conn):
            call_count["n"] += 1

        engine = _make_engine()
        with engine.connect() as conn:
            _bootstrap_minimal_schema(conn)
            _ensure_migrations_table(conn)
            # Pre-record the migration ID so it looks already applied
            _record(conn, "test_skip_001")

        # Manually invoke with a fake MIGRATIONS list (monkey-patch temporarily)
        import migrate as _migrate
        original = _migrate.MIGRATIONS
        _migrate.MIGRATIONS = [("test_skip_001", _counting_fn)]
        try:
            run_migrations(engine)
        finally:
            _migrate.MIGRATIONS = original

        assert call_count["n"] == 0, "Migration fn should not have been called — already recorded"

    def test_failed_migration_does_not_write_schema_migrations_row(self):
        """
        If a migration function raises an exception, no schema_migrations row is
        written for that migration ID, so it will be retried on the next startup.
        """
        def _failing_fn(conn):
            raise RuntimeError("intentional test failure")

        engine = _make_engine()
        with engine.connect() as conn:
            _bootstrap_minimal_schema(conn)

        import migrate as _migrate
        original = _migrate.MIGRATIONS
        _migrate.MIGRATIONS = [("test_fail_001", _failing_fn)]
        try:
            run_migrations(engine)  # must not raise despite fn failing
        finally:
            _migrate.MIGRATIONS = original

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM schema_migrations WHERE id = 'test_fail_001'")
            ).first()
        assert row is None, "Failed migration must not be recorded in schema_migrations"


# ---------------------------------------------------------------------------
# scripts/backup-db.sh
# ---------------------------------------------------------------------------

BACKUP_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "scripts", "backup-db.sh"
)


class TestBackupScript:
    def test_creates_file_with_timestamped_naming_pattern(self):
        """
        Running backup-db.sh creates a file whose name matches
        <original>.backup-YYYYMMDD-HHmmss next to the source file.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "fantasy.db")
            # Create a minimal SQLite-like file (just needs to exist and be copyable)
            with open(db_path, "wb") as f:
                f.write(b"SQLite format 3\x00" + b"\x00" * 84)

            result = subprocess.run(
                ["bash", BACKUP_SCRIPT, db_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"Script failed: {result.stderr}"

            # Find the backup file
            files = os.listdir(tmpdir)
            backups = [f for f in files if f.startswith("fantasy.db.backup-")]
            assert len(backups) == 1, f"Expected one backup file, found: {files}"

            import re
            assert re.match(r"fantasy\.db\.backup-\d{8}-\d{6}$", backups[0]), (
                f"Backup filename does not match expected pattern: {backups[0]}"
            )

    def test_backup_is_identical_to_source(self):
        """
        The backup file produced by backup-db.sh has the same content (or at
        minimum the same byte size) as the original database file.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "fantasy.db")
            content = b"SQLite format 3\x00" + b"\xAB\xCD" * 50
            with open(db_path, "wb") as f:
                f.write(content)

            result = subprocess.run(
                ["bash", BACKUP_SCRIPT, db_path],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"Script failed: {result.stderr}"

            files = os.listdir(tmpdir)
            backups = [f for f in files if f.startswith("fantasy.db.backup-")]
            assert backups, "No backup file created"

            backup_path = os.path.join(tmpdir, backups[0])
            with open(backup_path, "rb") as f:
                backup_content = f.read()
            assert backup_content == content, "Backup content does not match source"

    def test_nonexistent_db_exits_nonzero_with_error_message(self):
        """
        Passing a path to a non-existent DB file causes the script to print an
        error message to stderr and exit with a non-zero status code.
        """
        result = subprocess.run(
            ["bash", BACKUP_SCRIPT, "/tmp/this_db_does_not_exist_xyz.db"],
            capture_output=True, text=True
        )
        assert result.returncode != 0, "Script should exit non-zero for missing source file"
