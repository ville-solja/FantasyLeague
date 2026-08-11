import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import get_db, backup_sqlite_db
from deps import require_admin, _audit
from models import Card, CardModifier, League, Match, MatchBan, Player, PlayerMatchStats, SeasonArchive, Team, TwitchMVP, TwitchTokenDrop, User, Week, WeeklyRosterEntry
from routers.leaderboard import compute_season_standings

router = APIRouter()


# ---------------------------------------------------------------------------
# Season lifecycle — End Season archive + Season Reset
# ---------------------------------------------------------------------------

class SeasonEndBody(BaseModel):
    season_label: str = Field(..., min_length=1, max_length=100)


class SeasonResetBody(BaseModel):
    force: bool = False


@router.post("/admin/season/end")
def end_season(body: SeasonEndBody, db=Depends(get_db),
               admin: dict = Depends(require_admin)):
    """Snapshot the current season leaderboard into season_archive.

    Run this BEFORE a season reset — standings are computed live from match
    stats and are destroyed by the reset.
    """
    season_label = body.season_label.strip()
    if not season_label:
        raise HTTPException(status_code=422, detail="Season label cannot be empty")
    existing = (db.query(SeasonArchive)
                .filter(SeasonArchive.season_label == season_label).first())
    if existing:
        raise HTTPException(status_code=409,
                            detail=f"Season '{season_label}' is already archived")
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
    _audit(db, "admin_season_archived", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"season_label={season_label} users={len(standings)}")
    db.commit()
    return {"season_label": season_label, "archived_users": len(standings)}


@router.post("/admin/season/reset")
def reset_season(body: SeasonResetBody, db=Depends(get_db),
                 admin: dict = Depends(require_admin)):
    """Clear all per-season data so the next season starts from a clean slate.

    Deletes matches, stats, bans, weeks, roster snapshots, Twitch season
    records, all known players and teams, and every user's cards; resets
    user tokens to INITIAL_TOKENS; unmonitors all leagues. User accounts,
    tags, audit logs, and season archives are retained.

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
    operation in the app and has no undo path otherwise. Aborts with a 500
    (no deletes performed) if the backup cannot be taken, rather than
    proceeding uninsured.
    """
    locked_weeks = db.query(Week).filter(Week.is_locked == True).all()  # noqa: E712
    if locked_weeks and not body.force:
        newest_lock = max(w.start_time or 0 for w in locked_weeks)
        newer_archive = (db.query(SeasonArchive)
                         .filter(SeasonArchive.archived_at >= newest_lock).first())
        if not newer_archive:
            raise HTTPException(
                status_code=409,
                detail="Locked weeks exist but no season archive was created "
                       "after the newest locked week. Run End Season first "
                       "or pass force=true.")

    try:
        backup_path = backup_sqlite_db()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Season reset aborted — pre-reset backup failed: {e}")

    counts = {
        "player_match_stats":    db.query(PlayerMatchStats).delete(synchronize_session=False),
        "match_bans":            db.query(MatchBan).delete(synchronize_session=False),
        "matches":               db.query(Match).delete(synchronize_session=False),
        "weekly_roster_entries": db.query(WeeklyRosterEntry).delete(synchronize_session=False),
        "weeks":                 db.query(Week).delete(synchronize_session=False),
        "twitch_mvp":            db.query(TwitchMVP).delete(synchronize_session=False),
        "twitch_token_drops":    db.query(TwitchTokenDrop).delete(synchronize_session=False),
        "players":               db.query(Player).delete(synchronize_session=False),
        "teams":                 db.query(Team).delete(synchronize_session=False),
        "card_modifiers":        db.query(CardModifier).delete(synchronize_session=False),
        "cards":                 db.query(Card).delete(synchronize_session=False),
    }
    initial_tokens = int(os.getenv("INITIAL_TOKENS", "5"))
    counts["users_tokens_reset"] = (
        db.query(User).update({User.tokens: initial_tokens},
                              synchronize_session=False)
    )
    counts["leagues_unmonitored"] = (
        db.query(League).filter(League.is_monitored == True)  # noqa: E712
        .update({League.is_monitored: False}, synchronize_session=False)
    )
    detail = f"backup={backup_path} " + " ".join(f"{k}={v}" for k, v in counts.items())
    _audit(db, "admin_season_reset", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=detail)
    db.commit()
    return {"status": "ok", "initial_tokens": initial_tokens, "counts": counts,
            "backup_path": backup_path}


@router.get("/audit-logs")
def get_audit_logs(db=Depends(get_db), limit: int = 200, _: dict = Depends(require_admin)):
    rows = db.execute(text("""
        SELECT id, timestamp, actor_username, action, detail
        FROM audit_logs
        ORDER BY id DESC
        LIMIT :limit
    """), {"limit": limit}).fetchall()
    return [dict(r._mapping) for r in rows]
