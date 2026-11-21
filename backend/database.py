from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import re
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


def credit_tokens(db, user_id: int, amount: int) -> None:
    """Atomically add `amount` tokens to a user's balance (issue #185).

    A relative UPDATE, never `user.tokens = (user.tokens or 0) + n`: writing back a
    value read earlier overwrites a spend_tokens() that ran in between. Like
    spend_tokens, this bypasses the ORM identity map — db.refresh(user) afterwards
    when the ORM object's balance is used. An unknown user_id changes nothing.
    """
    db.execute(
        text("UPDATE users SET tokens = COALESCE(tokens, 0) + :amt WHERE id = :uid"),
        {"amt": amount, "uid": user_id},
    )


DEFAULT_BACKUP_RETENTION_DAYS = 14


def backup_retention_days() -> int:
    """DB_BACKUP_RETENTION_DAYS, shared by the background pruning loop in main.py
    and the admin backups panel so the default can't drift between them."""
    return int(os.getenv("DB_BACKUP_RETENTION_DAYS", str(DEFAULT_BACKUP_RETENTION_DAYS)))


def _sqlite_db_path() -> Path | None:
    """Path of the live SQLite DB file, or None for a non-SQLite DATABASE_URL."""
    prefix = "sqlite:///"
    if not DATABASE_URL.startswith(prefix):
        return None
    return Path(DATABASE_URL[len(prefix):])


SEASON_LABEL_MAX = 60


def season_label_slug(label) -> str:
    """A season label as a file-name part (issue #133): only [A-Za-z0-9-], runs of
    anything else become one "-", trimmed and capped; "season" when nothing is left."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(label or "")).strip("-")[:SEASON_LABEL_MAX].strip("-")
    return slug or "season"


def _backups_matching(pattern: str) -> list[Path]:
    db_path = _sqlite_db_path()
    if db_path is None or not db_path.parent.is_dir():
        return []
    files = []
    for f in db_path.parent.glob(f"{db_path.name}.{pattern}"):
        try:
            if f.is_file():
                files.append((f.stat().st_mtime, f))
        except OSError:
            pass
    return [f for _, f in sorted(files, key=lambda t: t[0], reverse=True)]


def list_sqlite_backups() -> list[Path]:
    """Backup files (from backup_sqlite_db()) next to the live SQLite DB, newest
    first. Empty for non-SQLite URLs or if the DB directory can't be found. Season
    backups (fantasy.db.season-*) are not in this list, so the daily cleanup never
    deletes them."""
    return _backups_matching("backup-*")


def list_season_backups() -> list[Path]:
    """Permanent season backups (fantasy.db.season-<label>-<timestamp>, issue #133),
    newest first. Nothing deletes them automatically."""
    return _backups_matching("season-*")


def cleanup_old_backups(retention_days: int) -> int:
    """Delete local SQLite backup files (from backup_sqlite_db()) older than
    retention_days. Returns the number of files deleted. No-op for non-SQLite
    DATABASE_URLs or if the DB directory can't be found."""
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    for f in list_sqlite_backups():
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass
    return deleted


def backup_sqlite_db(kind: str = "daily", label: str | None = None) -> str | None:
    """Online backup of the live SQLite database, mirroring scripts/backup-db.sh's
    naming convention ({db}.backup-{timestamp}) but callable from within a request.
    kind="season" names it {db}.season-{label slug}-{timestamp} instead (issue #133),
    a file the daily cleanup never deletes.

    Uses sqlite3's backup API (not a raw file copy) so a backup taken while the
    engine holds a WAL-mode connection is always transactionally consistent.
    Returns the backup file path, or None if the database isn't a local SQLite
    file (e.g. a future non-SQLite DATABASE_URL).
    """
    sqlite_path = _sqlite_db_path()
    if sqlite_path is None:
        return None
    db_path = str(sqlite_path)
    if not os.path.isfile(db_path):
        return None
    stamp = time.strftime('%Y%m%d-%H%M%S')
    if kind == "season":
        backup_path = f"{db_path}.season-{season_label_slug(label)}-{stamp}"
    else:
        backup_path = f"{db_path}.backup-{stamp}"
    # Create the file owner-only up front so it is never world-readable, even
    # briefly: backups hold password hashes and emails.
    os.close(os.open(backup_path, os.O_CREAT | os.O_WRONLY, 0o600))
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(backup_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.chmod(backup_path, 0o600)
    return backup_path


_BACKUP_SUFFIX_RE = re.compile(r"\.backup-(\d{8}-\d{6})$")


def rename_to_season_backup(path: str | None, label: str | None) -> str | None:
    """Rename a backup written by backup_sqlite_db() to its permanent season name
    ({db}.season-{label slug}-{timestamp}, issue #133), in the same directory.
    A path that is not an existing file (None, or a test stub) is returned as is."""
    if not path or not os.path.isfile(path):
        return path
    db_path = _sqlite_db_path()
    if db_path is None:
        return path
    # Source and target must both sit directly in the live DB's directory.
    db_dir = os.path.realpath(db_path.parent)
    src = os.path.realpath(path)
    if not src.startswith(db_dir + os.sep) or os.path.dirname(src) != db_dir:
        raise ValueError("Backup is not in the database directory")
    name = os.path.basename(src)
    m = _BACKUP_SUFFIX_RE.search(name)
    stamp = m.group(1) if m else time.strftime('%Y%m%d-%H%M%S')
    base = name[:m.start()] if m else name
    stem = f"{base}.season-{season_label_slug(label)}-{stamp}"
    # Two resets with the same label in the same second must not overwrite each other.
    n = 1
    while True:
        target = os.path.normpath(os.path.join(db_dir, stem if n == 1 else f"{stem}-{n}"))
        if not target.startswith(db_dir + os.sep) or os.path.dirname(target) != db_dir:
            raise ValueError("Season backup name escapes the database directory")
        if not os.path.exists(target):
            break
        n += 1
    os.replace(src, target)
    return os.path.join(os.path.dirname(path), os.path.basename(target))
