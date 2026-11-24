import logging
import os
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, text

import accolades
import season_reset
import season_summary
from database import get_db, backup_sqlite_db, rename_to_season_backup
from deps import require_admin, require_recent_reauth, require_typed_confirmation, _audit
from models import OwnPlayerCardGrant, SeasonAccolade, SeasonArchive
from routers.leaderboard import compute_season_standings

logger = logging.getLogger(__name__)

router = APIRouter()

# An OpenDota account id as SQLite can bind it (a larger int would be a 500).
AccountId = Annotated[int, Field(ge=1, le=2**63 - 1)]

AUDIT_LOG_LIMIT_MAX = 1000


# ---------------------------------------------------------------------------
# Season lifecycle — End Season archive + Season Reset
# ---------------------------------------------------------------------------

class SeasonEndChampions(BaseModel):
    """One division's winning team at End Season (issue #50)."""
    division: Literal["div1", "div2"]
    team_name: str = Field(..., min_length=1, max_length=100)
    player_account_ids: list[AccountId] = Field(..., max_length=50)

    @field_validator("team_name")
    @classmethod
    def _team_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Team name cannot be empty")
        return v


class SeasonEndBody(BaseModel):
    season_label: str = Field(..., min_length=1, max_length=100)
    # Optional: the finals may not be played yet; Mark champions adds them later.
    champions: list[SeasonEndChampions] | None = Field(None, max_length=2)
    # Issue #133: the parts End Season applies (the standings archive always runs).
    record_awards: bool = True
    record_champions: bool = True
    record_played: bool = True
    store_summary: bool = True

    @field_validator("champions")
    @classmethod
    def _one_per_division(cls, v):
        if v and len({c.division for c in v}) != len(v):
            raise ValueError("One champion team per division")
        return v


class SeasonResetBody(BaseModel):
    force: bool = False
    # Names the season backup; default: the newest archived season (issue #133).
    season_label: str | None = Field(None, max_length=100)


class SeasonSummaryBody(BaseModel):
    season_label: str = Field(..., min_length=1, max_length=100)


@router.get("/admin/season/accolades-preview")
def accolades_preview(season_label: str | None = Query(None, max_length=100),
                      db=Depends(get_db), _: dict = Depends(require_admin)):
    """What End Season will record (issue #50): the five awards (ties included), how
    many players get a played row, and the season's teams with their players for the
    champion picker. season_label defaults to the live season's label; `recorded`
    counts the accolade rows that label already has, per End Season part (issue #133)."""
    label = (season_label or "").strip() or accolades.current_season_label(db)
    archived = accolades.archived_match(db, label)
    if archived:
        archived["has_summary"] = season_summary.has_summary(db, archived["label"])
    recorded = {d: db.query(SeasonAccolade).filter(
        SeasonAccolade.season_label == label, SeasonAccolade.kind == "champion",
        SeasonAccolade.division == d).count() for d in accolades.DIVISIONS}
    return {
        "season_label": label,
        "awards": accolades.compute_awards(db),
        "played_count": len(accolades.played_player_ids(db)),
        "teams": accolades.season_teams(db),
        "champions_recorded": recorded,
        "recorded": accolades.recorded_counts(db, label),
        # Issue 257: an archive under this label in any spelling; End Season refuses it.
        "archived": archived,
    }


@router.post("/admin/season/end", dependencies=[Depends(require_recent_reauth),
                                                Depends(require_typed_confirmation("season_end"))])
def end_season(body: SeasonEndBody, db=Depends(get_db),
               admin: dict = Depends(require_admin)):
    """Snapshot the current season leaderboard into season_archive.

    Run this BEFORE a season reset — standings are computed live from match
    stats and are destroyed by the reset.

    In the same transaction it records the season's accolades (issue #50): the five
    awards, the optional champions and one played row per player with a scored match.
    If recording fails nothing is committed.
    """
    season_label = body.season_label.strip()
    if not season_label:
        raise HTTPException(status_code=422, detail="Season label cannot be empty")
    # Issue 257: "season 16" or "Season  16" would be a second copy of "Season 16".
    existing = accolades.archived_match(db, season_label)
    if existing:
        raise HTTPException(status_code=409, detail=accolades.archived_text(existing))
    standings = compute_season_standings(db)
    now = int(time.time())
    for rank, row in enumerate(standings, start=1):
        db.add(SeasonArchive(
            season_label=season_label,
            user_id=row["id"],
            username=row["username"],
            points=row["points"],
            rank=rank,
            archived_at=now,
        ))
    champions = ([c.model_dump() for c in body.champions]
                 if body.champions and body.record_champions else None)
    parts = {"archive": True, "awards": body.record_awards, "champions": body.record_champions,
             "played": body.record_played, "summary": body.store_summary}
    try:
        recorded = accolades.record_season(db, season_label, champions, admin["user_id"],
                                           awards=body.record_awards,
                                           champions_on=body.record_champions,
                                           played=body.record_played)
    except Exception:
        db.rollback()
        logger.exception("End Season: recording accolades failed for %s", season_label)
        raise HTTPException(status_code=500,
                            detail="Recording accolades failed; nothing was archived")
    try:
        summary = season_summary.store(db, season_label) if body.store_summary else None
    except Exception:
        db.rollback()
        logger.exception("End Season: storing the summary failed for %s", season_label)
        raise HTTPException(status_code=500,
                            detail="Storing the season summary failed; nothing was archived")
    ran = ",".join(k for k, v in parts.items() if v)
    _audit(db, "admin_season_archived", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"season_label={season_label} users={len(standings)} "
                  f"accolades={recorded['accolades']} champions={recorded['champions']} "
                  f"parts={ran}" + (f" summary_players={summary['players']} "
                                    f"summary_teams={summary['teams']}" if summary else ""))
    db.commit()
    result = {"season_label": season_label, "archived_users": len(standings),
              "accolades": recorded["accolades"], "awards": recorded["awards"],
              "champions": recorded["champions"], "played": recorded["played"],
              "parts": parts, "summary": summary}
    if not accolades.played_player_ids(db):
        result["note"] = "No scored matches: no awards or played rows recorded"
    if body.record_champions and not champions:
        result["warning"] = "No champions recorded; add them in Player management"
    return result


@router.post("/admin/season/summary", dependencies=[Depends(require_recent_reauth),
                                                    Depends(require_typed_confirmation("season_summary"))])
def store_season_summary(body: SeasonSummaryBody, db=Depends(get_db),
                         admin: dict = Depends(require_admin)):
    """Store the season summary (issue #133) for a season archived without one, from
    the live data: only before Reset Season has cleared it."""
    label = body.season_label.strip()
    if not db.query(SeasonArchive.id).filter(SeasonArchive.season_label == label).first():
        raise HTTPException(status_code=404, detail=f"Season '{label}' is not archived")
    if season_summary.has_summary(db, label):
        raise HTTPException(status_code=409, detail=f"Season '{label}' already has a summary")
    if not season_summary.has_live_data(db):
        raise HTTPException(status_code=409,
                            detail="No live matches: the season's data has already been reset")
    stored = season_summary.store(db, label)
    _audit(db, "admin_season_summary", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"season_label={label} players={stored['players']} teams={stored['teams']}")
    db.commit()
    return {"season_label": label, **stored}


@router.get("/admin/season/archives")
def list_season_archives(db=Depends(get_db), _: dict = Depends(require_admin)):
    """The archived seasons, newest first, with whether each has a stored summary (issue 257)."""
    return [{**a, "has_summary": season_summary.has_summary(db, a["season_label"])}
            for a in accolades.archives(db)]


@router.delete("/admin/season/archive", dependencies=[Depends(require_recent_reauth),
                                                     Depends(require_typed_confirmation("season_archive_remove"))])
def remove_season_archive(season_label: str = Query(..., min_length=1, max_length=100),
                          db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Delete one season's archived standings (issue 257) so End Season can run again.
    Accolades, the season summary and season backups stay. Refused once the season's
    data is gone (Reset ran, or a newer season is archived): End Season couldn't rebuild it."""
    label = season_label.strip()
    rows = db.query(SeasonArchive).filter(SeasonArchive.season_label == label)
    newest = db.query(func.max(SeasonArchive.archived_at)).filter(
        SeasonArchive.season_label == label).scalar()
    if newest is None:
        raise HTTPException(status_code=404, detail=f"Season '{label}' is not archived")
    if not season_summary.has_live_data(db):
        raise HTTPException(status_code=409,
                            detail="No live matches: the season's data has already been reset")
    if db.query(SeasonArchive.id).filter(SeasonArchive.archived_at > newest).first():
        raise HTTPException(status_code=409,
                            detail="A newer season is archived: this archive can no longer be redone")
    removed = rows.delete(synchronize_session=False)
    _audit(db, "admin_season_archive_removed", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"season_label={label} users={removed}")
    db.commit()
    return {"season_label": label, "removed": removed,
            "kept": "Accolades, the season summary and season backups are unchanged"}


@router.get("/admin/season/reset-preview")
def reset_preview(db=Depends(get_db), _: dict = Depends(require_admin)):
    """What Reset Season would delete and keep, with row counts (issue #133). Read-only."""
    return season_reset.preview(db)


@router.post("/admin/season/reset", dependencies=[Depends(require_recent_reauth),
                                                  Depends(require_typed_confirmation("season_reset"))])
def reset_season(body: SeasonResetBody, db=Depends(get_db),
                 admin: dict = Depends(require_admin)):
    """Clear all per-season data so the next season starts from a clean slate.

    Deletes matches, stats, stored card points, bans, weeks, roster snapshots, Twitch season
    records, all known players and teams, and every user's cards and own-card grants; resets
    user tokens to INITIAL_TOKENS; unmonitors all leagues. User accounts,
    tags, audit logs, season archives and season accolades (issue #50) are retained.

    Players and teams are wiped along with match data — this also clears the
    admin-curated Player Pool, so a new season (or a new league entirely)
    starts with an empty draft pool that the admin repopulates via Player
    Management. Cards are deleted outright rather than deactivated: player
    rosters fluctuate season to season, so keeping cards for players who no
    longer play would be dead weight, and a "clean slate" season should mean
    users draw a fresh collection with their reset tokens rather than keep
    holding cards tied to a season that no longer exists.

    Takes an automatic online backup of the SQLite database immediately
    before deleting anything, since this single call is the most destructive
    operation in the app and has no undo path otherwise. The backup is renamed to a
    permanent season backup (fantasy.db.season-<label>-<timestamp>, issue #133) that
    the daily cleanup never deletes. Aborts with a 500 (no deletes performed) if the
    backup cannot be taken, rather than proceeding uninsured.

    Issue #133: also clears the Weekly Report tables, live_matches, match_timings,
    Twitch presence and the demo clock override (season_reset.TABLE_GROUPS lists
    every table), then empties the in-memory season caches after the commit. Issue 257:
    also finals brackets and predictions, promo codes and redemptions, token grant
    events and claims, and notifications with their dismissals.
    """
    if season_reset.end_season_missing(db) and not body.force:
        raise HTTPException(status_code=409, detail=season_reset.END_SEASON_MISSING)

    label = (body.season_label or "").strip() or season_reset.backup_label(db)
    try:
        backup_path = backup_sqlite_db()
        backup_path = rename_to_season_backup(backup_path, label)
    except Exception as e:
        # The error text can hold absolute server paths: log it, return only its type.
        logger.exception("Season reset aborted: pre-reset backup failed")
        raise HTTPException(
            status_code=500,
            detail=f"Season reset aborted — pre-reset backup failed ({type(e).__name__})")
    if backup_path is None:
        raise HTTPException(
            status_code=500,
            detail="Season reset aborted — no pre-reset backup could be taken")

    counts = {
        # Issue #188: next season's league players get their own card again.
        "own_player_card_grants": db.query(OwnPlayerCardGrant).delete(synchronize_session=False),
        **season_reset.clear(db, skip=("own_player_card_grants",)),
    }
    kept = season_reset.kept_counts(db)
    backup_file = os.path.basename(backup_path)
    detail = (f"backup={backup_path} " + " ".join(f"{k}={v}" for k, v in counts.items())
              + f" kept_season_accolades={kept['season_accolades']}")
    _audit(db, "admin_season_reset", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=detail)
    db.commit()
    season_reset.bust_caches()
    return {"status": "ok", "initial_tokens": season_reset.initial_tokens(), "counts": counts,
            "kept": kept, "season_label": label, "backup_path": backup_path,
            "backup_file": backup_file}


@router.get("/audit-logs")
def get_audit_logs(db=Depends(get_db), limit: int = Query(200, ge=1, le=AUDIT_LOG_LIMIT_MAX),
                   _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT id, timestamp, actor_username, action, detail
        FROM audit_logs
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]
