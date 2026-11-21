"""Demo Mode database snapshots (issue #147).

An admin on a Demo Mode server saves the live SQLite database under a name and
restores it later while the app keeps running. Snapshots live in
`demo-snapshots/` next to the live database file (`data/demo-snapshots/` in a
normal deployment): the folder is 0700 and every file 0600, since snapshots hold
password hashes and emails.

Names are `[A-Za-z0-9-]{1,40}`; `path_for` builds the file path from a validated
name only and checks it resolves inside the folder.
"""

import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import delete

import database
import models  # noqa: F401  (registers every table for create_all)
from deps import _audit
from models import UserSession

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,40}$")
FOLDER_NAME = "demo-snapshots"

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

# One save or restore at a time: a restore replaces the whole file underneath the app.
_lock = threading.Lock()


def _live_path() -> Path:
    path = database._sqlite_db_path()
    if path is None:
        raise HTTPException(status_code=409, detail="Snapshots need a local SQLite database")
    return path


def folder() -> Path:
    """The snapshot folder, next to the live database file."""
    return _live_path().parent / FOLDER_NAME


def path_for(name: str) -> Path:
    """The snapshot file for a valid name; ValueError for anything else."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("invalid snapshot name")
    base = folder().resolve()
    unresolved = base / f"{name}.db"
    # A symlink in the folder (even to another snapshot there) never stands in for a name.
    if unresolved.is_symlink():
        raise ValueError("invalid snapshot name")
    p = unresolved.resolve()
    if p.parent != base:
        raise ValueError("invalid snapshot name")
    return p


def _ensure_folder() -> Path:
    d = folder()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _info(path: Path) -> dict:
    st = path.stat()
    return {"name": path.stem, "size_bytes": st.st_size, "saved_at": int(st.st_mtime)}


def _open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)


def save(name: str) -> dict:
    """Copy the live database to `{folder}/{name}.db` with SQLite's online backup.
    409 when the name is taken; the existing file is left as it is."""
    path = path_for(name)
    live = _live_path()
    if not live.is_file():
        raise HTTPException(status_code=409, detail="The live database file was not found")
    _ensure_folder()
    with _lock:
        try:
            # Owner-only from the start, and O_EXCL never follows or replaces a file.
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW, 0o600))
        except FileExistsError:
            raise HTTPException(status_code=409, detail=f"Snapshot {name} already exists")
        try:
            src = sqlite3.connect(str(live), timeout=10)
            try:
                dst = sqlite3.connect(str(path))
                try:
                    src.backup(dst)
                    # A rollback-journal file can be opened read-only for a restore.
                    dst.execute("PRAGMA journal_mode=DELETE")
                finally:
                    dst.close()
            finally:
                src.close()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        os.chmod(path, 0o600)
        return _info(path)


def list_all() -> list[dict]:
    """Saved snapshots as {name, size_bytes, saved_at}, newest first."""
    d = folder()
    if not d.is_dir():
        return []
    found = []
    for f in d.glob("*.db"):
        if not NAME_RE.fullmatch(f.stem):
            continue
        try:
            if f.is_file() and not f.is_symlink():
                found.append((f.stat().st_mtime_ns, _info(f)))
        except OSError:
            pass
    found.sort(key=lambda t: (t[0], t[1]["name"]), reverse=True)
    return [info for _, info in found]


def _caller_is_admin_in(src: sqlite3.Connection, user_id: int) -> bool:
    try:
        row = src.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.Error:
        return False
    return bool(row and row[0])


def _rewrite_sessions(conn: sqlite3.Connection, kept: list[dict]) -> None:
    """Delete every user_sessions row in the just-restored file and write the caller's
    saved rows back (only the columns the snapshot's table has)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(user_sessions)")}
    if not have:
        return  # created by create_all below; the ORM step inserts the rows
    conn.execute("DELETE FROM user_sessions")
    for row in kept:
        cols = [c for c in row if c in have]
        conn.execute(f"INSERT INTO user_sessions ({', '.join(cols)}) "
                     f"VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols])
    conn.commit()


def _end_all_sessions(live: Path) -> None:
    try:
        conn = sqlite3.connect(str(live), timeout=10)
        try:
            conn.execute("DELETE FROM user_sessions")
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        logger.exception("Demo snapshot restore: ending every session failed")


def restore(name: str, keep_user_id: int, actor_username: str | None = None) -> dict:
    """Replace the live database with snapshot `name` while the app runs.

    The caller (`keep_user_id`) stays logged in: their user_sessions rows are read
    first and written back afterwards, and every other session ends. 404 when the
    file is missing; 409 (nothing changed) when the snapshot has no admin account
    with the caller's id. Afterwards the schema is migrated, stored card points are
    rebuilt, the restore is audited (after the swap, so the entry survives) and the
    in-memory caches are emptied."""
    import card_points
    import season_reset
    from migrate import run_migrations

    path = path_for(name)
    live = _live_path()
    with _lock:
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Snapshot not found")
        try:
            src = _open_read_only(path)
        except sqlite3.Error:
            logger.exception("Snapshot restore: opening %s failed", path)
            raise HTTPException(status_code=409, detail="The snapshot can't be read")
        try:
            if not _caller_is_admin_in(src, keep_user_id):
                raise HTTPException(
                    status_code=409,
                    detail="The snapshot has no admin account with your id, so restoring it "
                           "would log you out. Nothing was changed.")
            cols = [c.name for c in UserSession.__table__.columns]
            with database.SessionLocal() as s:
                kept = [{c: getattr(r, c) for c in cols}
                        for r in s.query(UserSession).filter(UserSession.user_id == keep_user_id)]
            replaced_state_at = int(time.time())
            logger.warning("Demo snapshot restore: replacing all data with snapshot %s "
                           "(by %s, user id %s)", name, actor_username, keep_user_id)
            engine = database.engine
            engine.dispose()
            dst = sqlite3.connect(str(live), timeout=10)
            try:
                src.backup(dst)
                # Before anything else can fail: only the caller's sessions stay valid.
                try:
                    _rewrite_sessions(dst, kept)
                except Exception:
                    dst.close()
                    logger.exception("Demo snapshot restore of %s: rewriting sessions after "
                                     "the data swap failed; ending every session", name)
                    _end_all_sessions(live)
                    raise
            finally:
                dst.close()
        finally:
            src.close()

        try:
            # Drop every pooled connection that could still hold pages of the old file,
            # then bring an older snapshot up to the current schema before the ORM runs.
            engine.dispose()
            database.Base.metadata.create_all(bind=engine)
            run_migrations(engine)

            db = database.SessionLocal()
            try:
                db.execute(delete(UserSession))
                if kept:
                    db.execute(UserSession.__table__.insert(), kept)
                db.commit()
                rows = card_points.rebuild_all(db)
                _audit(db, "demo_snapshot_restored", actor_id=keep_user_id,
                       actor_username=actor_username,
                       detail=f"name={name} replaced_state_at={replaced_state_at}")
                db.commit()
            finally:
                db.close()
        except Exception:
            logger.exception("Demo snapshot restore of %s failed after the data swap; "
                             "ending every session", name)
            _end_all_sessions(live)
            raise
    season_reset.bust_caches()
    return {"restored": name, "card_points_rows": rows}
