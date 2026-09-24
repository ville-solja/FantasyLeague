import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from database import _sqlite_db_path, backup_retention_days, backup_sqlite_db, get_db, list_sqlite_backups
from deps import require_admin, _audit

router = APIRouter()

# Also keeps two backups from landing in the same one-second filename slot.
BACKUP_COOLDOWN_SECONDS = 60


# ---------------------------------------------------------------------------
# Database backups — on-demand backup, listing, and download
# ---------------------------------------------------------------------------

def _backup_info(path) -> dict:
    st = path.stat()
    return {"filename": path.name, "size_bytes": st.st_size, "created_at": int(st.st_mtime)}


@router.post("/admin/backups")
def create_backup(db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Take an online backup of the live SQLite DB via backup_sqlite_db()."""
    if _sqlite_db_path() is None:
        raise HTTPException(status_code=409,
                            detail="Backups are only available when the database is a local SQLite file")
    existing = list_sqlite_backups()
    if existing:
        age = time.time() - existing[0].stat().st_mtime
        if age < BACKUP_COOLDOWN_SECONDS:
            wait = max(1, int(BACKUP_COOLDOWN_SECONDS - age))
            raise HTTPException(status_code=429,
                                detail=f"A backup was created less than {BACKUP_COOLDOWN_SECONDS} seconds ago. Try again in {wait}s.")
    backup_path = backup_sqlite_db()
    if backup_path is None:
        raise HTTPException(status_code=409, detail="Live SQLite database file not found")
    backup = next((f for f in list_sqlite_backups() if str(f) == backup_path), None)
    if backup is None:
        raise HTTPException(status_code=500, detail="Backup was not written")
    info = _backup_info(backup)
    _audit(db, "admin_db_backup", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"filename={info['filename']}")
    db.commit()
    return info


@router.get("/admin/backups")
def list_backups(admin: dict = Depends(require_admin)):
    backups = []
    for f in list_sqlite_backups():
        try:
            backups.append(_backup_info(f))
        except OSError:
            pass
    return {"retention_days": backup_retention_days(), "backups": backups}


@router.get("/admin/backups/{filename}")
def download_backup(filename: str, db=Depends(get_db),
                    admin: dict = Depends(require_admin)):
    """Stream a backup as an attachment. The filename is only ever matched
    against the listing's basenames — never joined onto a path — so traversal
    attempts and the live DB's own name simply don't match and 404."""
    match = next((f for f in list_sqlite_backups() if f.name == filename), None)
    if match is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    _audit(db, "admin_db_backup_download", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"filename={match.name}")
    db.commit()
    return FileResponse(match, media_type="application/octet-stream", filename=match.name,
                        headers={"Cache-Control": "no-store"})
