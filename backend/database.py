from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import sqlite3
import time
from pathlib import Path


def _default_database_url() -> str:
    # Docker / Linux container: bind mount is usually ./data -> /app/data
    # (Do not gate on os.name — WSL/Linux hosts may look like "nt" in edge setups.)
    app_data = Path("/app/data")
    if app_data.is_dir():
        return "sqlite:////app/data/fantasy.db"

    # Local checkout: backend/database.py -> repo root is parent of backend/
    backend_dir = Path(__file__).resolve().parent
    repo_root = backend_dir.parent
    db_path = (repo_root / "data" / "fantasy.db").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = os.getenv("DATABASE_URL") or _default_database_url()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 10})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_db():
    """FastAPI dependency: yield a DB session and guarantee close even on exception."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def spend_tokens(db, user_id: int, amount: int) -> bool:
    """Atomically decrement a user's token balance if they have enough.

    Uses a single conditional UPDATE instead of read-check-write, so two
    concurrent requests from the same user (double-click, two tabs) cannot
    both pass a token check against a stale in-memory value and both spend
    the same tokens. Returns True if the balance was decremented, False if
    the user doesn't have enough tokens (or doesn't exist).

    Callers that already hold an ORM-loaded User object must db.refresh(user)
    afterward — this bypasses the ORM identity map via a raw UPDATE.
    """
    result = db.execute(
        text("UPDATE users SET tokens = tokens - :amt "
             "WHERE id = :uid AND COALESCE(tokens, 0) >= :amt"),
        {"amt": amount, "uid": user_id},
    )
    return result.rowcount > 0


def cleanup_old_backups(retention_days: int) -> int:
    """Delete local SQLite backup files (from backup_sqlite_db()) older than
    retention_days. Returns the number of files deleted. No-op for non-SQLite
    DATABASE_URLs or if the DB directory can't be found."""
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix):
        return 0
    db_path = Path(DATABASE_URL[len(prefix):])
    if not db_path.parent.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for f in db_path.parent.glob(f"{db_path.name}.backup-*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted


def backup_sqlite_db() -> str | None:
    """Online backup of the live SQLite database, mirroring scripts/backup-db.sh's
    naming convention ({db}.backup-{timestamp}) but callable from within a request.

    Uses sqlite3's backup API (not a raw file copy) so a backup taken while the
    engine holds a WAL-mode connection is always transactionally consistent.
    Returns the backup file path, or None if the database isn't a local SQLite
    file (e.g. a future non-SQLite DATABASE_URL).
    """
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix):
        return None
    db_path = DATABASE_URL[len(prefix):]
    if not os.path.isfile(db_path):
        return None
    backup_path = f"{db_path}.backup-{time.strftime('%Y%m%d-%H%M%S')}"
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return backup_path
