import logging
import os
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

import accolades
import card_points
from database import get_db, backup_sqlite_db
from deps import require_admin, require_recent_reauth, require_typed_confirmation, _audit
from models import Card, CardModifier, League, Match, MatchBan, OwnPlayerCardGrant, Player, PlayerMatchStats, SeasonAccolade, SeasonArchive, Team, TwitchMVP, TwitchTokenDrop, User, Week, WeeklyRosterEntry
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

    @field_validator("champions")
    @classmethod
    def _one_per_division(cls, v):
        if v and len({c.division for c in v}) != len(v):
            raise ValueError("One champion team per division")
        return v


class SeasonResetBody(BaseModel):
    force: bool = False


@router.get("/admin/season/accolades-preview")
def accolades_preview(db=Depends(get_db), _: dict = Depends(require_admin)):
    """What End Season will record (issue #50): the four awards (ties included), how
    many players get a played row, and the season's teams with their players for the
    champion picker. season_label is the live season's label."""
    label = accolades.current_season_label(db)
    recorded = {d: db.query(SeasonAccolade).filter(
        SeasonAccolade.season_label == label, SeasonAccolade.kind == "champion",
        SeasonAccolade.division == d).count() for d in accolades.DIVISIONS}
    return {
        "season_label": label,
        "awards": accolades.compute_awards(db),
        "played_count": len(accolades.played_player_ids(db)),
        "teams": accolades.season_teams(db),
        "champions_recorded": recorded,
    }


@router.post("/admin/season/end", dependencies=[Depends(require_recent_reauth),
                                                Depends(require_typed_confirmation("season_end"))])
def end_season(body: SeasonEndBody, db=Depends(get_db),
               admin: dict = Depends(require_admin)):
    """Snapshot the current season leaderboard into season_archive.

    Run this BEFORE a season reset — standings are computed live from match
    stats and are destroyed by the reset.

    In the same transaction it records the season's accolades (issue #50): the four
    awards, the optional champions and one played row per player with a scored match.
    If recording fails nothing is committed.
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
    champions = [c.model_dump() for c in body.champions] if body.champions else None
    try:
        recorded = accolades.record_season(db, season_label, champions, admin["user_id"])
    except Exception:
        db.rollback()
        logger.exception("End Season: recording accolades failed for %s", season_label)
        raise HTTPException(status_code=500,
                            detail="Recording accolades failed; nothing was archived")
    _audit(db, "admin_season_archived", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"season_label={season_label} users={len(standings)} "
                  f"accolades={recorded['accolades']} champions={recorded['champions']}")
    db.commit()
    result = {"season_label": season_label, "archived_users": len(standings),
              "accolades": recorded["accolades"], "awards": recorded["awards"],
              "champions": recorded["champions"], "played": recorded["played"]}
    if recorded["played"] == 0 and recorded["awards"] == 0:
        result["note"] = "No scored matches: no awards or played rows recorded"
    if not champions:
        result["warning"] = "No champions recorded; add them in Player management"
    return result


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
    if backup_path is None:
        raise HTTPException(
            status_code=500,
            detail="Season reset aborted — no pre-reset backup could be taken")

    counts = {
        "card_match_points":     card_points.delete_card_points(db),
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
        # Issue #188: next season's league players get their own card again.
        "own_player_card_grants": db.query(OwnPlayerCardGrant).delete(synchronize_session=False),
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
    kept = {"season_accolades": db.query(SeasonAccolade).count()}
    detail = (f"backup={backup_path} " + " ".join(f"{k}={v}" for k, v in counts.items())
              + f" kept_season_accolades={kept['season_accolades']}")
    _audit(db, "admin_season_reset", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=detail)
    db.commit()
    return {"status": "ok", "initial_tokens": initial_tokens, "counts": counts,
            "kept": kept, "backup_path": backup_path}


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
