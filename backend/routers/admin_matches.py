
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func

import card_points
import schedule
from accolades import league_division
from database import get_db
from deps import require_admin, _audit
import ingest
from models import League, Match, MatchTiming, Player, PlayerMatchStats, Team, TwitchMVP, Week, Weight
from schedule import bust_cache, out_of_week_series
from weeks import scoring_week_for, week_containing
from twitch import _apply_mvp_bonus, bust_panel_cache, upsert_mvp

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Match table + Admin MVP selection
# ---------------------------------------------------------------------------

class AdminMVPRequest(BaseModel):
    player_id: int


class MatchVodBody(BaseModel):
    vod_url: str | None = Field(None, max_length=500)


class MatchScoringBody(BaseModel):
    unparseable: bool | None = None
    excluded_from_scoring: bool | None = None


def _feed_series_by_match(db) -> dict:
    """match_id -> {series_key, team1_id, team2_id, division, stream_url} for every game
    the schedule feed's series have claimed, from one get_schedule pass (issue 214).
    Empty when the feed can't be read, so the Matches table still loads."""
    try:
        data = schedule.get_schedule(db) or {}
    except Exception:
        logger.exception("Schedule lookup for the admin Matches table failed")
        return {}
    by_match = {}
    for w_idx, week in enumerate(data.get("weeks") or []):
        for division in ("div1", "div2"):
            for s_idx, series in enumerate(week.get(division) or []):
                result = series.get("series_result") or {}
                info = {
                    "series_key": f"w{w_idx}-{division}-{s_idx}",
                    "team1_id": series.get("team1_id"),
                    "team2_id": series.get("team2_id"),
                    "division": division,
                    "stream_url": series.get("stream_url"),
                }
                for mid in result.get("match_ids") or []:
                    by_match.setdefault(mid, info)
    return by_match


@router.get("/admin/matches")
def list_matches(db=Depends(get_db), _: dict = Depends(require_admin)):
    matches = db.query(Match).order_by(Match.start_time.desc()).all()
    match_ids = [m.match_id for m in matches]

    series_by_match = _feed_series_by_match(db)
    league_ids = {m.league_id for m in matches if m.league_id}
    league_names = {
        lg.id: lg.name for lg in db.query(League).filter(League.id.in_(league_ids)).all()
    } if league_ids else {}

    mvps_by_match = {
        mv.match_id: mv
        for mv in db.query(TwitchMVP).filter(TwitchMVP.match_id.in_(match_ids)).all()
    } if match_ids else {}

    mvp_player_ids = {mv.player_id for mv in mvps_by_match.values()}
    players_by_id = {
        p.id: p for p in db.query(Player).filter(Player.id.in_(mvp_player_ids)).all()
    } if mvp_player_ids else {}

    timings_by_match = {
        t.match_id: t
        for t in db.query(MatchTiming).filter(MatchTiming.match_id.in_(match_ids)).all()
    } if match_ids else {}

    team_ids = {tid for m in matches for tid in (m.radiant_team_id, m.dire_team_id) if tid}
    teams_by_id = {
        t.id: t for t in db.query(Team).filter(Team.id.in_(team_ids)).all()
    } if team_ids else {}

    all_weeks = db.query(Week).all()

    result = []
    for m in matches:
        mvp = mvps_by_match.get(m.match_id)
        mvp_player = players_by_id.get(mvp.player_id) if mvp else None
        radiant = teams_by_id.get(m.radiant_team_id) if m.radiant_team_id else None
        dire = teams_by_id.get(m.dire_team_id) if m.dire_team_id else None
        timing = timings_by_match.get(m.match_id)
        scoring_week, scoring_source = scoring_week_for(db, m, all_weeks)
        time_week = week_containing(db, m.start_time, all_weeks)
        series = series_by_match.get(m.match_id)
        league_name = league_names.get(m.league_id)
        result.append({
            "match_id": m.match_id,
            "league_id": m.league_id,
            "radiant_team_id": m.radiant_team_id,
            "dire_team_id": m.dire_team_id,
            "team1": radiant.name if radiant else None,
            "team2": dire.name if dire else None,
            "start_time": m.start_time,
            "mvp_player_name": mvp_player.name if mvp_player else None,
            "mvp_player_id": mvp.player_id if mvp else None,
            "vod_url": m.vod_url,
            "parse_status": m.parse_status,
            "excluded_from_scoring": bool(m.excluded_from_scoring),
            "live_first_seen_at": timing.live_first_seen_at if timing else None,
            "ingested_at": timing.ingested_at if timing else None,
            "mvp_confirmed_at": timing.mvp_confirmed_at if timing else None,
            "week_override_id": m.week_override_id,
            "scoring_week_id": scoring_week.id if scoring_week else None,
            "scoring_week_label": scoring_week.label if scoring_week else None,
            "scoring_week_source": scoring_source,
            "time_week_id": time_week.id if time_week else None,
            "time_week_label": time_week.label if time_week else None,
            "series_key": series["series_key"] if series else None,
            "series_team1_id": series["team1_id"] if series else None,
            "series_team2_id": series["team2_id"] if series else None,
            "division": series["division"] if series else (
                league_division(league_name) if league_name is not None else None),
            "league_name": league_name,
            "stream_url": series["stream_url"] if series else None,
        })
    return result


@router.get("/admin/matches/out-of-week")
def list_out_of_week_series(db=Depends(get_db), _: dict = Depends(require_admin)):
    """Feed series counted for a different fantasy week than their league week's
    (issue #193); see schedule.out_of_week_series."""
    return out_of_week_series(db)


@router.get("/admin/matches/{match_id}/players")
def match_players(match_id: int, db=Depends(get_db), _: dict = Depends(require_admin)):
    rows = (
        db.query(Player, PlayerMatchStats.team_id, Team.name)
        .join(PlayerMatchStats, PlayerMatchStats.player_id == Player.id)
        .outerjoin(Team, Team.id == PlayerMatchStats.team_id)
        .filter(PlayerMatchStats.match_id == match_id)
        .all()
    )
    return [
        {"id": p.id, "name": p.name, "team_id": team_id, "team_name": team_name}
        for p, team_id, team_name in rows
    ]


@router.post("/admin/matches/{match_id}/mvp")
def admin_set_mvp(
    match_id: int,
    body: AdminMVPRequest,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    match = db.query(Match).filter(Match.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    player = db.query(Player).filter(Player.id == body.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    old_player_id = upsert_mvp(db, match_id, body.player_id, "admin")

    weights = {w.key: w.value for w in db.query(Weight).all()}
    if old_player_id and old_player_id != body.player_id:
        _apply_mvp_bonus(db, old_player_id, match_id, apply=False, weights=weights)
    _apply_mvp_bonus(db, body.player_id, match_id, apply=True, weights=weights)
    card_points.refresh_card_points(db, match_ids=[match_id])

    _audit(db, "admin_set_mvp", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match {match_id} → player {body.player_id} ({player.name})")
    db.commit()
    bust_cache()
    bust_panel_cache()
    return {"match_id": match_id, "player_id": body.player_id, "player_name": player.name}


@router.patch("/admin/matches/{match_id}/vod")
def set_match_vod(
    match_id: int,
    body: MatchVodBody,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    match = db.query(Match).filter(Match.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    vod_url = body.vod_url.strip() if body.vod_url else None
    if vod_url and not (vod_url.startswith("http://") or vod_url.startswith("https://")):
        raise HTTPException(status_code=422, detail="vod_url must be a valid http(s) URL")

    match.vod_url = vod_url
    _audit(db, "admin_match_vod_set", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=f"match {match_id} vod_url={vod_url}")
    db.commit()
    return {"match_id": match_id, "vod_url": match.vod_url}


# ---------------------------------------------------------------------------
# Parse status: manual retry + scoring flags
# ---------------------------------------------------------------------------

@router.post("/admin/matches/{match_id}/retry-parse")
def retry_match_parse(match_id: int, db=Depends(get_db), admin: dict = Depends(require_admin)):
    """Re-fetch one match from OpenDota now. If OpenDota has parsed it, its stat rows
    and fantasy points are replaced (outcome "refreshed"); otherwise a parse is
    requested, subject to the INGEST_PARSE_REREQUEST_HOURS cooldown (outcome
    "requested"; "cooldown" when one was sent too recently; "request_failed" when
    OpenDota rejected the request).
    Shares INGEST_LOCK with the poll loop and manual ingests (409 while held)."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if not ingest.INGEST_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="An ingest is already in progress — try again shortly")
    try:
        weights = {w.key: w.value for w in db.query(Weight).all()}
        fetched = ingest.refresh_match_stats(db, match_id, weights)
        if fetched == "refreshed":
            outcome = "refreshed"
        elif not ingest._parse_request_due(match_id):
            outcome = "cooldown"
        else:
            outcome = "requested" if ingest.request_parse(match_id) else "request_failed"
        db.refresh(match)
        _audit(db, "admin_match_retry_parse", actor_id=admin["user_id"], actor_username=admin["username"],
               detail=f"match {match_id} fetch={fetched} outcome={outcome}")
        db.commit()
    finally:
        ingest.INGEST_LOCK.release()
    if outcome == "refreshed":
        bust_cache()
    return {"match_id": match_id, "outcome": outcome, "parse_status": match.parse_status}


def _signature_unparsed(db, match_id: int) -> bool:
    """True when the match's stat rows sum to 0 on the parse-only signature stats
    (same rule as ingest.find_unparsed_match_ids)."""
    tf, stuns, obs = db.query(
        func.coalesce(func.sum(PlayerMatchStats.teamfight_participation), 0),
        func.coalesce(func.sum(PlayerMatchStats.stuns), 0),
        func.coalesce(func.sum(PlayerMatchStats.obs_placed), 0),
    ).filter(PlayerMatchStats.match_id == match_id).one()
    return not tf and not stuns and not obs


@router.patch("/admin/matches/{match_id}/scoring")
def set_match_scoring(
    match_id: int,
    body: MatchScoringBody,
    db=Depends(get_db),
    admin: dict = Depends(require_admin),
):
    """Mark a match unparseable (skipped by the parse retry pass) and/or exclude it from
    every fantasy-points aggregation. Omitted fields are left unchanged. Clearing
    `unparseable` restores the status the stat rows imply (unparsed or parsed)."""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    old_status = match.parse_status
    old_excluded = bool(match.excluded_from_scoring)
    if body.unparseable is True:
        match.parse_status = "unparseable"
    elif body.unparseable is False and match.parse_status == "unparseable":
        match.parse_status = "unparsed" if _signature_unparsed(db, match_id) else "parsed"
    if body.excluded_from_scoring is not None:
        match.excluded_from_scoring = body.excluded_from_scoring

    _audit(db, "admin_match_scoring", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=(f"match {match_id} parse_status {old_status}->{match.parse_status} "
                   f"excluded_from_scoring {old_excluded}->{bool(match.excluded_from_scoring)}"))
    db.commit()
    bust_cache()
    bust_panel_cache()
    return {
        "match_id": match_id,
        "parse_status": match.parse_status,
        "excluded_from_scoring": bool(match.excluded_from_scoring),
    }
