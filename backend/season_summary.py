"""Season summary (issue #133): what is worth keeping of a season once Reset Season
has cleared the live tables. One season_player_stats row per player with a scored
match and one season_team_results row per team, built from the live data and stored
by End Season (or POST /admin/season/summary for a season archived earlier).

Raw points are scoring.fantasy_score of the stored stats with the weights in force
now (no MVP bonus, no rarity, no modifiers: issue #244's definition), exact sums.
The Best Single Match award uses stored fantasy_points, which include the MVP bonus,
so a player's best game here can differ from that award.

Team results come from stored matches only (never the schedule feed): each team
pair's scored games are clustered into series by schedule.SERIES_GAP_SECONDS.
"""

import time

from sqlalchemy import text

import schedule
from match_scoring import scored_match_sql, scored_stat_sql
from models import Match, Player, PlayerMatchStats, SeasonPlayerStats, SeasonTeamResult, Team, Weight
from player_insights import won
from scoring import fantasy_score, stat_dict_from_row


def _names(db, model, ids) -> dict:
    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    return {r.id: r.name for r in db.query(model.id, model.name).filter(model.id.in_(ids)) if r.name}


def player_rows(db) -> list[dict]:
    """One dict per player with a scored match (scored_stat_sql, as the awards)."""
    weights = {w.key: w.value for w in db.query(Weight)}
    rows = db.execute(text(f"""
        SELECT s.*, m.radiant_team_id AS m_radiant, m.dire_team_id AS m_dire,
               m.radiant_win AS m_radiant_win
        FROM player_match_stats s
        LEFT JOIN matches m ON m.match_id = s.match_id
        WHERE s.player_id IS NOT NULL AND {scored_stat_sql()}
        ORDER BY s.match_id, s.id
    """)).fetchall()
    per: dict[int, dict] = {}
    for r in rows:
        raw = fantasy_score(stat_dict_from_row(r), weights)
        p = per.setdefault(r.player_id, {"games": 0, "wins": 0, "total": 0.0, "best": None,
                                         "best_match": None, "kills": 0, "deaths": 0,
                                         "assists": 0, "mvps": 0, "teams": {}})
        p["games"] += 1
        p["wins"] += 1 if won(r.team_id, r.m_radiant, r.m_dire, r.m_radiant_win) else 0
        p["total"] += raw
        if p["best"] is None or raw > p["best"]:
            p["best"], p["best_match"] = raw, r.match_id
        p["kills"] += r.kills or 0
        p["deaths"] += r.deaths or 0
        p["assists"] += r.assists or 0
        p["mvps"] += 1 if r.is_mvp else 0
        if r.team_id is not None:
            p["teams"][r.team_id] = p["teams"].get(r.team_id, 0) + 1
    players = _names(db, Player, per)
    teams = _names(db, Team, {t for p in per.values() for t in p["teams"]})
    out = []
    for pid, p in sorted(per.items()):
        team_name = None
        if p["teams"]:
            # The team of most of the player's games; ties by name.
            team_id = min(p["teams"], key=lambda t: (-p["teams"][t], (teams.get(t) or f"Team {t}").lower()))
            team_name = teams.get(team_id) or f"Team {team_id}"
        out.append({"player_id": pid, "player_name": players.get(pid) or f"Player {pid}",
                    "team_name": team_name, "games": p["games"], "wins": p["wins"],
                    "raw_points_total": p["total"], "raw_points_avg": p["total"] / p["games"],
                    "best_raw_points": p["best"], "best_match_id": p["best_match"],
                    "kills": p["kills"], "deaths": p["deaths"], "assists": p["assists"],
                    "mvps": p["mvps"]})
    return out


def team_rows(db) -> list[dict]:
    """One dict per team in a scored match with both sides known."""
    rows = db.execute(text(f"""
        SELECT m.match_id, m.radiant_team_id, m.dire_team_id, m.radiant_win,
               COALESCE(m.start_time, 0) AS start_time
        FROM matches m
        WHERE m.radiant_team_id IS NOT NULL AND m.dire_team_id IS NOT NULL
          AND m.radiant_team_id != m.dire_team_id AND {scored_match_sql("m")}
        ORDER BY start_time, m.match_id
    """)).fetchall()
    per: dict[int, dict] = {}

    def team(tid):
        return per.setdefault(tid, {"series_won": 0, "series_lost": 0, "series_drawn": 0,
                                    "games_won": 0, "games_lost": 0})
    clusters: list[list] = []
    open_series: dict[tuple, list] = {}
    for r in rows:
        team(r.radiant_team_id), team(r.dire_team_id)
        if r.radiant_win is not None:
            winner, loser = ((r.radiant_team_id, r.dire_team_id) if r.radiant_win
                             else (r.dire_team_id, r.radiant_team_id))
            team(winner)["games_won"] += 1
            team(loser)["games_lost"] += 1
        pair = tuple(sorted((r.radiant_team_id, r.dire_team_id)))
        current = open_series.get(pair)
        if current is not None and r.start_time - current[-1].start_time <= schedule.SERIES_GAP_SECONDS:
            current.append(r)
        else:
            current = open_series[pair] = [r]
            clusters.append(current)
    for cluster in clusters:
        a, b = sorted((cluster[0].radiant_team_id, cluster[0].dire_team_id))
        a_wins = sum(1 for r in cluster if r.radiant_win is not None
                     and (r.radiant_team_id == a) == bool(r.radiant_win))
        b_wins = sum(1 for r in cluster if r.radiant_win is not None) - a_wins
        if a_wins == b_wins == 0:
            continue  # no known result
        if a_wins == b_wins:
            team(a)["series_drawn"] += 1
            team(b)["series_drawn"] += 1
        else:
            winner, loser = (a, b) if a_wins > b_wins else (b, a)
            team(winner)["series_won"] += 1
            team(loser)["series_lost"] += 1
    names = _names(db, Team, per)
    divisions = schedule.cached_team_divisions()
    return [{"team_id": tid, "team_name": names.get(tid) or f"Team {tid}",
             "division": divisions.get(tid), **t} for tid, t in sorted(per.items())]


def has_summary(db, label: str) -> bool:
    return (db.query(SeasonPlayerStats.id).filter(SeasonPlayerStats.season_label == label).first()
            is not None or
            db.query(SeasonTeamResult.id).filter(SeasonTeamResult.season_label == label).first()
            is not None)


def has_live_data(db) -> bool:
    """True while the season's matches and stats are still in the live tables."""
    return (db.query(Match.match_id).first() is not None
            and db.query(PlayerMatchStats.id).first() is not None)


def store(db, label: str) -> dict:
    """Write the summary rows for label. Does not commit. Returns the row counts."""
    now = int(time.time())
    players = player_rows(db)
    teams = team_rows(db)
    db.add_all(SeasonPlayerStats(season_label=label, created_at=now, **p) for p in players)
    db.add_all(SeasonTeamResult(season_label=label, created_at=now, **t) for t in teams)
    db.flush()
    return {"players": len(players), "teams": len(teams)}
