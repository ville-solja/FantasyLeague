from sqlalchemy import create_engine, event
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
