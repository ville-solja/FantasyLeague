import json
import logging
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

import accolades
import player_insights
import schedule
import team_insights
from card_points import _current_weights
from database import get_db
from deps import require_admin
from enrich import run_profile_enrichment
from match_scoring import scored_match_sql, scored_stat_sql
from models import Player, PlayerProfile, Team, Week
from scoring import display_points
from weeks import scoring_week_for

logger = logging.getLogger(__name__)

router = APIRouter()


def _rounded_points(row) -> dict:
    """Row dict with avg_points/total_points rounded once for display (issue #149)."""
    d = dict(row)
    d["avg_points"] = display_points(d["avg_points"])
    d["total_points"] = display_points(d["total_points"])
    return d


@router.get("/players")
def list_players(db=Depends(get_db)):
    scored_pts = f"CASE WHEN {scored_stat_sql()} THEN s.fantasy_points END"
    results = db.execute(text(f"""
        SELECT p.id, p.name, p.avatar_url,
               t.name as team_name, t.id as team_id,
               COUNT(s.id) as matches,
               COALESCE(AVG({scored_pts}), 0) as avg_points,
               COALESCE(SUM({scored_pts}), 0) as total_points,
               COALESCE(SUM(CASE WHEN s.is_mvp THEN 1 ELSE 0 END), 0) as mvp_count
        FROM players p
        LEFT JOIN player_match_stats s ON s.player_id = p.id
        LEFT JOIN (
            SELECT s2.player_id, s2.team_id
            FROM player_match_stats s2
            INNER JOIN (
                SELECT player_id, MAX(match_id) as max_match
                FROM player_match_stats
                GROUP BY player_id
            ) mx ON mx.player_id = s2.player_id AND mx.max_match = s2.match_id
        ) latest ON latest.player_id = p.id
        LEFT JOIN teams t ON t.id = latest.team_id
        GROUP BY p.id, p.name, p.avatar_url, t.name, t.id
        ORDER BY total_points DESC
    """)).fetchall()
    rows = [_rounded_points(r._mapping) for r in results]
    # Issue #50: seasons played (with the live season) and titles, newest first.
    current = accolades.current_season_label(db)
    per_player = accolades.accolades_for(db, [r["id"] for r in rows], current=current)
    for r in rows:
        r.update(accolades.player_seasons(per_player.get(r["id"], [])))
        r["seasons_counted_from"] = accolades.FIRST_COUNTED_SEASON  # issue 212
    return rows


@router.get("/players/{player_id}")
def get_player(player_id: int, db=Depends(get_db)):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    stats = db.execute(text(f"""
        SELECT s.match_id, m.start_time, s.fantasy_points, s.is_mvp,
               m.parse_status,
               CASE WHEN {scored_match_sql()} THEN 0 ELSE 1 END as excluded_from_scoring,
               s.kills, s.assists, s.deaths, s.gold_per_min, s.obs_placed,
               s.sen_placed, s.tower_damage, s.hero_id,
               s.last_hits, s.denies, s.towers_killed, s.roshan_kills,
               s.teamfight_participation, s.camps_stacked, s.rune_pickups,
               s.firstblood_claimed, s.stuns,
               m.duration, m.radiant_team_id, m.dire_team_id, m.radiant_win,
               m.week_override_id,
               t.id as team_id, t.name as team_name,
               ot.id as opponent_team_id,
               ot.name as opponent_team_name
        FROM player_match_stats s
        LEFT JOIN matches m ON m.match_id = s.match_id
        LEFT JOIN teams t ON t.id = s.team_id
        LEFT JOIN teams ot ON ot.id = CASE WHEN s.team_id = m.radiant_team_id THEN m.dire_team_id
                                           ELSE m.radiant_team_id END
        WHERE s.player_id = :player_id
        ORDER BY COALESCE(m.start_time, 0) DESC
    """), {"player_id": player_id}).fetchall()

    weights = _current_weights(db)
    history = [dict(r._mapping) for r in stats]
    # Issue 208: hero icons are best effort and never block: only the cached map is
    # used (a cold cache warms in the background), and a failure never breaks the popup.
    icons, hero_names = {}, {}
    if any(r["hero_id"] is not None for r in history):
        try:
            icons, hero_names = schedule.cached_hero_maps()
        except Exception:
            logger.warning("Hero icon map unavailable for the player popup", exc_info=True)
    week_list = db.query(Week).all() if history else []
    for r in history:
        r["excluded_from_scoring"] = bool(r["excluded_from_scoring"])
        r["is_mvp"] = bool(r["is_mvp"])
        r["won"] = player_insights.won(r["team_id"], r.pop("radiant_team_id"),
                                       r.pop("dire_team_id"), r.pop("radiant_win"))
        week, _ = scoring_week_for(db, SimpleNamespace(week_override_id=r.pop("week_override_id"),
                                                       start_time=r["start_time"]), week_list)
        r["week_label"] = player_insights.week_short(week.label) if week else None
        r["hero_icon_url"] = icons.get(r["hero_id"]) if r["hero_id"] is not None else None
        r["hero_name"] = hero_names.get(r["hero_id"]) if r["hero_id"] is not None else None
        r["_breakdown"] = player_insights.points_by_source(r, weights, r["is_mvp"])

    matches = len(history)
    scored = [r for r in history if not r["excluded_from_scoring"]]
    total_points = sum(r["fantasy_points"] or 0 for r in scored)
    avg_points = total_points / len(scored) if scored else 0
    best = max(scored, key=lambda r: r["fantasy_points"] or 0, default=None)

    league = player_insights.cached_league_aggregates(db, weights)
    heroes = player_insights.hero_rows(history, icons, hero_names)
    sources = player_insights.points_sources([r["_breakdown"] for r in scored], league["sources"])
    modifiers = player_insights.modifier_values(scored, weights)
    summary = {
        "wins": sum(1 for r in scored if r["won"] is True),
        "losses": sum(1 for r in scored if r["won"] is False),
        "mvps": sum(1 for r in scored if r["is_mvp"]),
        "avg_rank": player_insights.avg_rank(player_id, league["population"]),
    }

    # Totals above use exact values; each displayed value is rounded once (issue #149).
    for r in history:
        r["points_breakdown"] = {k: display_points(v, 2) for k, v in r.pop("_breakdown").items()}
        if r["fantasy_points"] is not None:
            r["fantasy_points"] = display_points(r["fantasy_points"])

    team_name = history[0]["team_name"] if history else None
    team_id = history[0]["team_id"] if history else None
    current = accolades.current_season_label(db)
    player_accolades = accolades.accolades_for(db, [player_id], current=current).get(player_id, [])

    return {
        "id": player.id,
        "name": player.name,
        "avatar_url": player.avatar_url,
        "rank_tier": player.rank_tier,
        "leaderboard_rank": player.leaderboard_rank,
        "rank_fetched_at": player.rank_fetched_at,
        "team_name": team_name,
        "team_id": team_id,
        "matches": matches,
        "avg_points": display_points(avg_points),
        "total_points": display_points(total_points),
        "best_match": {
            "match_id": best["match_id"],
            "fantasy_points": best["fantasy_points"],
            "start_time": best["start_time"],
            "opponent_team_name": best["opponent_team_name"],
        } if best else None,
        "match_history": history,
        # Issue 208: the popup's form chart, points by source, comparison and heroes.
        "summary": summary,
        "league_avg_points": display_points(league["avg_points"]),
        "points_sources": sources,
        "modifier_values": modifiers,
        "league_comparison": player_insights.league_comparison(player_id, league["population"]),
        "heroes": heroes,
        # Issue #50: the popup's Accolades section.
        **accolades.player_seasons(player_accolades),
        "accolades": player_accolades,
        "current_season": current,
        "current_season_matches": len(scored),
        "holo_unlocked": accolades.holo_eligible(db, player_id, current),
    }


@router.get("/players/{player_id}/profile")
def get_player_profile(player_id: int, db=Depends(get_db)):
    profile = db.get(PlayerProfile, player_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    facts = json.loads(profile.facts_json) if profile.facts_json else None
    return {
        "player_id":        player_id,
        "facts":            facts,
        "bio_text":         profile.bio_text,
        "facts_fetched_at": profile.facts_fetched_at,
        "bio_generated_at": profile.bio_generated_at,
    }


@router.get("/teams")
def list_teams(db=Depends(get_db)):
    # Issue 211: logo (allowlisted hosts only), division, series and games records,
    # points per game and titles. Excluded matches count in no figure.
    # Cached in-process until the data, the weights or the feed change (60 s at most).
    return team_insights.cached_team_list(db, _current_weights(db))


@router.get("/teams/{team_id}")
def get_team(team_id: int, db=Depends(get_db)):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    # Issue 211: the team popup's header, tiles, series, roster, sources and heroes.
    return team_insights.team_detail(db, team, _current_weights(db))
