import os
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from database import get_db
from deps import get_current_user
from dotabuff_league_logos import resolve_local_team_logo_path
from image import _ASSETS_DIR
from models import (
    Card, Player, PlayerMatchStats, Team, Week, WeeklyRosterEntry,
    WeeklySummary, WeeklySummaryReveal, WeeklySummarySeen,
)

router = APIRouter()

_SERIES_GAP = 6 * 3600  # seconds — matches the clustering window backend/schedule.py uses
_LOGO_DIR = os.path.join(_ASSETS_DIR, "dotabuff_league_logos")


def _group_into_series(matches: list[dict]) -> list[dict]:
    """Cluster same-two-team matches (already sorted by start_time) into series:
    consecutive matches between the same unordered team pair belong together as
    long as the gap to the previous match in that pair is <= _SERIES_GAP.
    Scoped-down version of the same pair/gap rule backend/schedule.py uses for
    the season-wide schedule view, applied here to a single week's matches."""
    open_clusters = {}
    clusters = []
    for m in matches:
        if m["radiant_team_id"] and m["dire_team_id"]:
            pair = tuple(sorted((m["radiant_team_id"], m["dire_team_id"])))
        else:
            pair = ("unknown", m["match_id"])  # standalone series of one
        current = open_clusters.get(pair)
        if current is not None and (m["start_time"] - current[-1]["start_time"]) <= _SERIES_GAP:
            current.append(m)
        else:
            if current is not None:
                clusters.append(current)
            open_clusters[pair] = [m]
    clusters.extend(open_clusters.values())
    return [{"matches": cluster} for cluster in clusters]


def _team_logo_url(team) -> str | None:
    """Prefer the locally-scraped Dotabuff PNG already used for card image generation
    (served under /assets/) — Team.logo_url is an OpenDota HTTP field that's rarely
    populated for lower-tier leagues, so reading it alone left most teams with no
    logo at all in the Weekly Report despite having a working one elsewhere in the
    app (see backend/image.py::_load_team_logo_for_card, the same preference order)."""
    if team and team.name:
        local_path = resolve_local_team_logo_path(_LOGO_DIR, team.name)
        if local_path:
            return f"/assets/dotabuff_league_logos/{os.path.basename(local_path)}"
    return team.logo_url if team else None


def _team_dict(team):
    if not team:
        return None
    return {"id": team.id, "name": team.name, "logo_url": _team_logo_url(team)}


def _build_week_summary(db, week: Week, revealed: bool, user_id: int) -> dict:
    match_rows = db.execute(text("""
        SELECT m.match_id, m.radiant_team_id, m.dire_team_id, m.radiant_win,
               m.start_time, m.vod_url
        FROM matches m
        WHERE m.week_override_id = :week_id
           OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we)
        ORDER BY m.start_time ASC
    """), {"week_id": week.id, "ws": week.start_time, "we": week.end_time}).fetchall()

    team_ids = {r.radiant_team_id for r in match_rows if r.radiant_team_id} | \
               {r.dire_team_id for r in match_rows if r.dire_team_id}
    teams_by_id = {
        t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()
    } if team_ids else {}

    roster_player_ids = set()
    if revealed:
        roster_player_ids = {
            row[0] for row in
            db.query(Card.player_id)
              .join(WeeklyRosterEntry, WeeklyRosterEntry.card_id == Card.id)
              .filter(WeeklyRosterEntry.week_id == week.id,
                      WeeklyRosterEntry.user_id == user_id)
              .all()
        }

    match_ids = [r.match_id for r in match_rows]
    players_by_match = {}
    if revealed and match_ids:
        stat_rows = (
            db.query(PlayerMatchStats, Player)
              .join(Player, Player.id == PlayerMatchStats.player_id)
              .filter(PlayerMatchStats.match_id.in_(match_ids))
              .all()
        )
        for stats, player in stat_rows:
            players_by_match.setdefault(stats.match_id, []).append({
                "player_id": player.id,
                "name": player.name,
                "avatar_url": player.avatar_url,
                "team_id": stats.team_id,
                "points": round(stats.fantasy_points or 0.0, 1),
                "is_mvp": bool(stats.is_mvp),
                "on_roster": player.id in roster_player_ids,
            })

    matches = []
    for r in match_rows:
        winner_team_id = None
        if r.radiant_win is not None and r.radiant_team_id and r.dire_team_id:
            winner_team_id = r.radiant_team_id if r.radiant_win else r.dire_team_id
        match = {
            "match_id": r.match_id,
            "radiant_team_id": r.radiant_team_id,
            "dire_team_id": r.dire_team_id,
            "radiant_team": _team_dict(teams_by_id.get(r.radiant_team_id)),
            "dire_team": _team_dict(teams_by_id.get(r.dire_team_id)),
            "winner_team_id": winner_team_id,
            "vod_url": r.vod_url,
            "start_time": r.start_time,
        }
        if revealed:
            match["players"] = players_by_match.get(r.match_id, [])
        matches.append(match)

    return {
        "week_id": week.id,
        "label": week.label,
        "revealed": revealed,
        "series": _group_into_series(matches),
    }


@router.get("/weekly-summary")
def list_weekly_summaries(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    rows = (
        db.query(WeeklySummary, Week)
          .join(Week, Week.id == WeeklySummary.week_id)
          .order_by(Week.start_time.desc())
          .all()
    )
    revealed_ids = {
        row[0] for row in
        db.query(WeeklySummaryReveal.week_id)
          .filter(WeeklySummaryReveal.user_id == current_user["user_id"]).all()
    }
    seen = db.get(WeeklySummarySeen, current_user["user_id"])
    latest_week_id = rows[0][1].id if rows else None
    has_unseen = latest_week_id is not None and (
        seen is None or seen.last_seen_week_id != latest_week_id
    )
    weeks = [
        {"week_id": w.id, "label": w.label, "revealed": w.id in revealed_ids}
        for _, w in rows
    ]
    return {"weeks": weeks, "has_unseen": has_unseen}


@router.get("/weekly-summary/{week_id}")
def get_weekly_summary(week_id: int, db=Depends(get_db),
                       current_user: dict = Depends(get_current_user)):
    summary = db.get(WeeklySummary, week_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Weekly summary not available")
    week = db.get(Week, week_id)
    revealed = db.query(WeeklySummaryReveal).filter_by(
        week_id=week_id, user_id=current_user["user_id"]).first() is not None
    return _build_week_summary(db, week, revealed, current_user["user_id"])


@router.post("/weekly-summary/{week_id}/reveal")
def reveal_weekly_summary(week_id: int, db=Depends(get_db),
                          current_user: dict = Depends(get_current_user)):
    summary = db.get(WeeklySummary, week_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Weekly summary not available")
    week = db.get(Week, week_id)
    existing = db.query(WeeklySummaryReveal).filter_by(
        week_id=week_id, user_id=current_user["user_id"]).first()
    if not existing:
        db.add(WeeklySummaryReveal(week_id=week_id, user_id=current_user["user_id"],
                                   revealed_at=int(time.time())))
        db.commit()
    return _build_week_summary(db, week, True, current_user["user_id"])


@router.post("/weekly-summary/seen")
def mark_weekly_summary_seen(db=Depends(get_db),
                             current_user: dict = Depends(get_current_user)):
    latest = (
        db.query(Week)
          .join(WeeklySummary, WeeklySummary.week_id == Week.id)
          .order_by(Week.start_time.desc())
          .first()
    )
    if not latest:
        return {"ok": True}
    seen = db.get(WeeklySummarySeen, current_user["user_id"])
    if seen:
        seen.last_seen_week_id = latest.id
    else:
        db.add(WeeklySummarySeen(user_id=current_user["user_id"], last_seen_week_id=latest.id))
    db.commit()
    return {"ok": True}
