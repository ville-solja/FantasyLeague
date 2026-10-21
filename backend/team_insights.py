"""Season insights for the team popup and the Teams tab (issue 211).

Pure helpers behind GET /teams and GET /teams/{id}: a team's record (series from
the schedule feed, games from matches), its season's series with upcoming
fixtures, the roster with games, share of points and ownership, points by source
against the average team, top heroes, and champion titles matched by team name.

Points come from the scoring code through player_insights (points_by_source,
modifier_values, hero_rows), so no formula lives here. Matches an admin excluded
from scoring count in no figure; partial-stat matches count. Ownership is an
aggregate percentage only: no user ids or usernames leave this module.
"""

import logging
import threading
import time

from sqlalchemy import text

import accolades
import player_insights
import schedule
from logo_hosts import safe_logo_url
from match_scoring import scored_match_sql
from models import SeasonAccolade, Team
from scoring import display_points

logger = logging.getLogger(__name__)

# Below this many managers, ownership percentages are withheld: with a handful of
# managers a percentage could reveal one manager's active roster.
OWNERSHIP_MIN_MANAGERS = 10
# Players with fewer than this share of the team's games are listed under "Also played".
ALSO_PLAYED_SHARE = 0.30
TOP_HEROES = 6

_ROW_STATS = ", ".join("s." + c for c in player_insights._STAT_COLS)


# ---------------------------------------------------------------------------
# League numbers (cached): the average team's sources and ownership counts
# ---------------------------------------------------------------------------

# The same versioned in-process cache as player_insights (issue 208): reused until the
# stats, the exclusions, the weights or the active cards change, at most for the TTL.
LEAGUE_CACHE_TTL = 60.0
_league_lock = threading.Lock()
_league_cache: dict = {"key": None, "at": 0.0, "value": None}


_list_cache: dict = {"key": None, "at": 0.0, "value": None}


def clear_league_cache() -> None:
    """Empty the league numbers cache and the GET /teams list cache."""
    with _league_lock:
        _league_cache.update(key=None, at=0.0, value=None)
        _list_cache.update(key=None, at=0.0, value=None)


def _ownership_version(db) -> tuple:
    """A cheap fingerprint of what the ownership counts read: active cards and the
    accounts that qualify as managers."""
    row = db.execute(text("""
        SELECT (SELECT COUNT(*) FROM cards WHERE is_active = 1),
               (SELECT COALESCE(SUM(id), 0) FROM cards WHERE is_active = 1),
               (SELECT COALESCE(SUM(owner_id), 0) FROM cards WHERE is_active = 1),
               (SELECT COALESCE(SUM(player_id), 0) FROM cards WHERE is_active = 1),
               (SELECT COUNT(*) FROM users),
               (SELECT COALESCE(SUM(id), 0) FROM users
                WHERE account_type = 'full' AND COALESCE(is_tester, 0) = 0
                  AND COALESCE(is_demo, 0) = 0)
    """)).fetchone()
    return tuple(row)


def _manager_filter_sql(user_alias: str = "u") -> str:
    """Managers: full (website) accounts that are neither testers nor demo accounts."""
    return (f"{user_alias}.account_type = 'full' AND COALESCE({user_alias}.is_tester, 0) = 0 "
            f"AND COALESCE({user_alias}.is_demo, 0) = 0")


def ownership_counts(db) -> tuple[int, dict]:
    """(managers, {player_id: managers holding an active card of the player}). A
    manager is a full, non-tester, non-demo account with at least one active card."""
    where = f"c.is_active = 1 AND {_manager_filter_sql()}"
    managers = db.execute(text(f"""
        SELECT COUNT(DISTINCT c.owner_id) FROM cards c JOIN users u ON u.id = c.owner_id
        WHERE {where}
    """)).scalar() or 0
    rows = db.execute(text(f"""
        SELECT c.player_id, COUNT(DISTINCT c.owner_id) AS holders
        FROM cards c JOIN users u ON u.id = c.owner_id
        WHERE {where}
        GROUP BY c.player_id
    """)).fetchall()
    return managers, {r.player_id: r.holders for r in rows}


def league_numbers(db, weights: dict) -> dict:
    """League figures shared by every team, in two queries:
      sources    the average team's points per team game, per source
      managers   the ownership denominator
      holders    {player_id: managers holding an active card of the player}
    """
    rows = db.execute(text(f"""
        SELECT s.team_id, s.match_id, s.is_mvp, {_ROW_STATS}
        FROM player_match_stats s
        LEFT JOIN matches m ON m.match_id = s.match_id
        WHERE {scored_match_sql()} AND s.team_id IS NOT NULL
    """)).fetchall()
    sums = {k: 0.0 for k in player_insights.SOURCE_KEYS}
    team_games = set()
    for r in rows:
        m = dict(r._mapping)
        team_games.add((m["team_id"], m["match_id"]))
        for k, v in player_insights.points_by_source(m, weights, bool(m["is_mvp"])).items():
            sums[k] += v
    n = len(team_games)
    managers, holders = ownership_counts(db)
    return {
        "sources": {k: (v / n if n else 0.0) for k, v in sums.items()},
        "managers": managers,
        "holders": holders,
    }


def cached_league_numbers(db, weights: dict) -> dict:
    """league_numbers(db, weights), cached in-process: keyed on the weights
    fingerprint, player_insights._data_version and the ownership fingerprint,
    recomputed after LEAGUE_CACHE_TTL seconds anyway. Callers must not mutate it."""
    from card_points import weights_fingerprint
    key = (weights_fingerprint(weights), player_insights._data_version(db), _ownership_version(db))
    now = time.monotonic()
    with _league_lock:
        if _league_cache["key"] == key and now - _league_cache["at"] < LEAGUE_CACHE_TTL:
            return _league_cache["value"]
        value = league_numbers(db, weights)
        _league_cache.update(key=key, at=now, value=value)
        return value


def ownership_hidden(league: dict) -> bool:
    """True while fewer than OWNERSHIP_MIN_MANAGERS managers have active cards."""
    return (league.get("managers") or 0) < OWNERSHIP_MIN_MANAGERS


def owned_pct(league: dict, player_id):
    """Whole percent of managers holding an active card of the player; None while
    ownership is hidden (too few managers), 0 without managers."""
    if ownership_hidden(league):
        return None
    managers = league.get("managers") or 0
    if not managers:
        return 0
    return int(round(100 * league["holders"].get(player_id, 0) / managers))


# ---------------------------------------------------------------------------
# Header: logo, division, titles
# ---------------------------------------------------------------------------

def team_logo(url):
    """The team logo only from an allowlisted host (issue #171), else None."""
    return safe_logo_url(url)


def team_divisions(db) -> dict:
    """{team_id: "div1" | "div2"} from the leagues of the team's matches (the division
    of most of them; "Lower" leagues are Div 2). Teams without a known league are left out."""
    rows = db.execute(text("""
        SELECT t.team_id, l.name AS league_name, COUNT(*) AS n
        FROM (SELECT match_id, league_id, radiant_team_id AS team_id FROM matches
              UNION ALL
              SELECT match_id, league_id, dire_team_id AS team_id FROM matches) t
        JOIN leagues l ON l.id = t.league_id
        WHERE t.team_id IS NOT NULL
        GROUP BY t.team_id, l.name
    """)).fetchall()
    counts: dict[int, dict[str, int]] = {}
    for r in rows:
        d = counts.setdefault(r.team_id, {})
        div = accolades.league_division(r.league_name)
        d[div] = d.get(div, 0) + r.n
    return {tid: max(sorted(d), key=lambda k: d[k]) for tid, d in counts.items() if d}


def norm_name(name) -> str:
    """Team names compare ignoring case and extra whitespace."""
    return " ".join(str(name or "").split()).lower()


_KIND_NAMES = {k["key"]: k["name"] for k in accolades.ACCOLADE_KINDS}


def titles_by_name(db) -> dict[str, list[dict]]:
    """{normalised team name: [title, ...]}: one champion title per season and division
    from every season's accolades, newest first. Each title is accolade-shaped (kind,
    division, season, season_short, team_name) plus its full `label`."""
    seen = set()
    out: dict[str, list[dict]] = {}
    for r in db.query(SeasonAccolade).filter(SeasonAccolade.kind == "champion").all():
        key = norm_name(r.team_name)
        if not key or (key, r.season_label, r.division) in seen:
            continue
        seen.add((key, r.season_label, r.division))
        short = accolades.short_season(r.season_label)
        out.setdefault(key, []).append({
            "kind": "champion", "division": r.division, "season": r.season_label,
            "season_short": short, "team_name": r.team_name,
            "label": f"{short} {_KIND_NAMES.get(r.division, 'Champion')}",
        })
    for lst in out.values():
        lst.sort(key=lambda t: (accolades.season_sort_key(t["season"]), t["division"] == "div1"),
                 reverse=True)
    return out


# ---------------------------------------------------------------------------
# Records: series from the schedule feed, games from matches
# ---------------------------------------------------------------------------

def feed_data(db) -> dict:
    """The schedule feed payload, or {} when the feed is down or malformed: the team
    views never fail because of it."""
    try:
        data = schedule.get_schedule(db)
    except Exception:
        logger.warning("Schedule feed unavailable for the team views", exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def feed_weeks(db, data: dict | None = None) -> list:
    """The feed's weeks ([] when unavailable); `data` reuses a payload already read."""
    weeks = (feed_data(db) if data is None else data).get("weeks")
    return weeks if isinstance(weeks, list) else []


def _series_result(team_wins: int, opp_wins: int) -> str:
    return "W" if team_wins > opp_wins else "L" if team_wins < opp_wins else "D"


def feed_series(db, teams: dict, data: dict | None = None) -> dict[int, dict]:
    """{team_id: {"series": [...], "upcoming": [...]}} from the feed for the given
    {team_id: Team}. A series counts as played when the feed resolved a result; an
    unplayed one is upcoming unless its time has passed. Rows are oldest first."""
    out = {tid: {"series": [], "upcoming": []} for tid in teams}
    weeks = feed_weeks(db, data)
    if not weeks:
        return out
    lookup = None
    for week in weeks:
        if not isinstance(week, dict):
            continue
        label = week.get("label")
        for division in ("div1", "div2"):
            for s in week.get(division) or []:
                ids = []
                for side in ("team1", "team2"):
                    tid = s.get(f"{side}_id")
                    if tid is None and s.get(side):
                        if lookup is None:
                            lookup = schedule.build_team_lookup(db)
                        tid = schedule.find_team_id(s.get(side), lookup)
                    ids.append(tid)
                for me, other in ((0, 1), (1, 0)):
                    tid = ids[me]
                    if tid not in out:
                        continue
                    opp_id = ids[other]
                    opp_team = teams.get(opp_id) if opp_id is not None else None
                    opp_name = s.get("team2" if me == 0 else "team1")
                    if opp_team is None and opp_id is not None:
                        opp_team = db.get(Team, opp_id)
                    opponent = {
                        "id": opp_id if opp_team is not None else None,
                        "name": (opp_team.name if opp_team is not None and opp_team.name else opp_name),
                        "logo_url": team_logo(opp_team.logo_url) if opp_team is not None else None,
                    }
                    base = {"week": label, "week_short": player_insights.week_short(label),
                            "division": division, "opponent": opponent,
                            "datetime_iso": s.get("datetime_iso")}
                    result = s.get("series_result")
                    if result:
                        wins = [int(result.get("team1_wins") or 0), int(result.get("team2_wins") or 0)]
                        mine, theirs = wins[me], wins[other]
                        out[tid]["series"].append({
                            **base, "wins": mine, "losses": theirs,
                            "result": _series_result(mine, theirs),
                            "start_time": result.get("start_time"),
                            "match_ids": list(result.get("match_ids") or []),
                        })
                    elif s.get("match_status") != "past":
                        out[tid]["upcoming"].append({
                            **base, "date": s.get("date"), "time": s.get("time"),
                            "scheduled": bool(s.get("scheduled", True)),
                            "stream_url": s.get("stream_url") or None,
                            "stream_label": s.get("stream_label") or None,
                        })
    for v in out.values():
        v["series"].sort(key=lambda r: (r["start_time"] is None, r["start_time"] or 0, r["datetime_iso"] or ""))
        v["upcoming"].sort(key=lambda r: r["datetime_iso"] or "")
    return out


def series_record(series: list[dict]) -> dict:
    return {"series_wins": sum(1 for s in series if s["result"] == "W"),
            "series_losses": sum(1 for s in series if s["result"] == "L"),
            "series_draws": sum(1 for s in series if s["result"] == "D")}


def scored_matches(db, team_id=None) -> list[dict]:
    """Matches that count for scoring, with both team ids, the result and duration;
    only the team's when team_id is given."""
    where = scored_match_sql()
    params = {}
    if team_id is not None:
        where += " AND (m.radiant_team_id = :t OR m.dire_team_id = :t)"
        params["t"] = team_id
    rows = db.execute(text(f"""
        SELECT m.match_id, m.radiant_team_id, m.dire_team_id, m.radiant_win, m.duration, m.start_time
        FROM matches m WHERE {where}
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


def games_record(team_id, matches: list[dict]) -> dict:
    """Games, wins, losses and the average duration (seconds) of the team's matches."""
    mine = [m for m in matches if team_id in (m["radiant_team_id"], m["dire_team_id"])]
    results = [player_insights.won(team_id, m["radiant_team_id"], m["dire_team_id"], m["radiant_win"])
               for m in mine]
    durations = [m["duration"] for m in mine if m["duration"]]
    return {"games": len(mine),
            "wins": sum(1 for r in results if r is True),
            "losses": sum(1 for r in results if r is False),
            "avg_game_length": int(round(sum(durations) / len(durations))) if durations else None}


def games_records(matches: list[dict]) -> dict[int, dict]:
    """{team_id: games_record} for every team, in one pass over the matches."""
    acc: dict[int, dict] = {}
    for m in matches:
        for tid in {m["radiant_team_id"], m["dire_team_id"]} - {None}:
            a = acc.setdefault(tid, {"games": 0, "wins": 0, "losses": 0, "_dur": []})
            a["games"] += 1
            r = player_insights.won(tid, m["radiant_team_id"], m["dire_team_id"], m["radiant_win"])
            if r is True:
                a["wins"] += 1
            elif r is False:
                a["losses"] += 1
            if m["duration"]:
                a["_dur"].append(m["duration"])
    for a in acc.values():
        d = a.pop("_dur")
        a["avg_game_length"] = int(round(sum(d) / len(d))) if d else None
    return acc


_EMPTY_RECORD = {"games": 0, "wins": 0, "losses": 0, "avg_game_length": None}


def _list_version(db) -> tuple:
    """A cheap fingerprint of what team_list reads beyond the stats (_data_version):
    matches (results, durations, leagues, exclusions), teams (names, logos), league
    names and champion accolades."""
    row = db.execute(text("""
        SELECT (SELECT COUNT(*) FROM matches),
               (SELECT COALESCE(SUM(match_id), 0) FROM matches),
               (SELECT COALESCE(SUM(radiant_win), 0) FROM matches),
               (SELECT COALESCE(SUM(duration), 0) FROM matches),
               (SELECT COALESCE(SUM(league_id), 0) FROM matches),
               (SELECT COALESCE(SUM(radiant_team_id), 0) + COALESCE(SUM(dire_team_id), 0) FROM matches),
               (SELECT group_concat(id || ':' || COALESCE(name, '') || ':' || COALESCE(logo_url, ''), '|')
                FROM teams),
               (SELECT group_concat(id || ':' || COALESCE(name, ''), '|') FROM leagues),
               (SELECT COUNT(*) FROM season_accolades WHERE kind = 'champion'),
               (SELECT COALESCE(MAX(id), 0) + COALESCE(SUM(id), 0) FROM season_accolades
                WHERE kind = 'champion')
    """)).fetchone()
    return tuple(row)


def cached_team_list(db, weights: dict) -> list[dict]:
    """team_list(db), cached in-process like cached_league_numbers: keyed on the weights
    fingerprint, the stats and match/team fingerprints and the feed's `cached_at`, at
    most for LEAGUE_CACHE_TTL. Callers must not mutate the result."""
    from card_points import weights_fingerprint
    data = feed_data(db)
    key = (weights_fingerprint(weights), player_insights._data_version(db), _list_version(db),
           data.get("cached_at"), bool(data.get("stale")))
    now = time.monotonic()
    with _league_lock:
        if _list_cache["key"] == key and now - _list_cache["at"] < LEAGUE_CACHE_TTL:
            return _list_cache["value"]
    value = team_list(db, data)
    with _league_lock:
        _list_cache.update(key=key, at=now, value=value)
    return value


def scored_stat_rows(db, team_id=None) -> list[dict]:
    """The team's stat rows in scored matches, with the match result and player name."""
    where = f"{scored_match_sql()} AND s.team_id IS NOT NULL"
    params = {}
    if team_id is not None:
        where += " AND s.team_id = :t"
        params["t"] = team_id
    rows = db.execute(text(f"""
        SELECT s.player_id, s.match_id, s.team_id, s.hero_id, s.fantasy_points, s.is_mvp,
               {_ROW_STATS},
               m.radiant_team_id, m.dire_team_id, m.radiant_win,
               p.name AS player_name, p.avatar_url
        FROM player_match_stats s
        JOIN matches m ON m.match_id = s.match_id
        LEFT JOIN players p ON p.id = s.player_id
        WHERE {where}
    """), params).fetchall()
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# Roster and heroes
# ---------------------------------------------------------------------------

def roster(rows: list[dict], team_games: int, league: dict, per_player_accolades: dict,
           tags: dict) -> list[dict]:
    """One row per player who played for the team in a scored match, by total points."""
    by_player: dict[int, list[dict]] = {}
    for r in rows:
        by_player.setdefault(r["player_id"], []).append(r)
    team_total = sum(r["fantasy_points"] or 0 for r in rows)
    out = []
    for pid, prs in by_player.items():
        total = sum(r["fantasy_points"] or 0 for r in prs)
        games = len(prs)
        out.append({
            "id": pid,
            "name": prs[0]["player_name"] or f"Player {pid}",
            "avatar_url": prs[0]["avatar_url"],
            "role": player_insights.role(prs),
            "games": games,
            "matches": games,
            "team_games": team_games,
            "avg_points": display_points(total / games),
            "total_points": display_points(total),
            "mvps": sum(1 for r in prs if r["is_mvp"]),
            "share": display_points(100 * total / team_total) if team_total else 0.0,
            "owned_pct": owned_pct(league, pid),
            "also_played": bool(team_games) and games < ALSO_PLAYED_SHARE * team_games,
            "accolades": per_player_accolades.get(pid, []),
            "tags": tags.get(pid, []),
            "_total": total,
        })
    out.sort(key=lambda p: (-p["_total"], str(p["name"]).lower()))
    for p in out:
        p.pop("_total")
    return out


def heroes(rows: list[dict], team_id) -> list[dict]:
    """The team's most picked heroes (TOP_HEROES), with W–L and the players who played them."""
    if not any(r["hero_id"] is not None for r in rows):
        return []
    icons, names = {}, {}
    try:
        icons, names = schedule.cached_hero_maps()
    except Exception:
        logger.warning("Hero icon map unavailable for the team popup", exc_info=True)
    history = [{"hero_id": r["hero_id"], "fantasy_points": r["fantasy_points"],
                "won": player_insights.won(team_id, r["radiant_team_id"], r["dire_team_id"], r["radiant_win"])}
               for r in rows]
    top = player_insights.hero_rows(history, icons, names)[:TOP_HEROES]
    for h in top:
        players: dict[int, dict] = {}
        for r in rows:
            if r["hero_id"] != h["hero_id"]:
                continue
            p = players.setdefault(r["player_id"], {"id": r["player_id"],
                                                   "name": r["player_name"] or f"Player {r['player_id']}",
                                                   "games": 0})
            p["games"] += 1
        h["players"] = sorted(players.values(), key=lambda p: (-p["games"], str(p["name"]).lower()))
    return top


# ---------------------------------------------------------------------------
# Endpoint bodies
# ---------------------------------------------------------------------------

def team_list(db, data: dict | None = None) -> list[dict]:
    """GET /teams rows: logo, division, series and games records, points per game,
    players and titles. Default order: division, then series wins. `data` reuses a
    schedule feed payload already read."""
    teams = {t.id: t for t in db.query(Team).all()}
    if not teams:
        return []
    divisions = team_divisions(db)
    titles = titles_by_name(db)
    feed = feed_series(db, teams, data)
    records = games_records(scored_matches(db))
    points: dict[int, float] = {}
    players: dict[int, set] = {}
    for r in db.execute(text(f"""
        SELECT s.team_id, s.player_id, s.fantasy_points
        FROM player_match_stats s JOIN matches m ON m.match_id = s.match_id
        WHERE {scored_match_sql()} AND s.team_id IS NOT NULL
    """)).fetchall():
        points[r.team_id] = points.get(r.team_id, 0.0) + (r.fantasy_points or 0)
        players.setdefault(r.team_id, set()).add(r.player_id)
    out = []
    for tid, t in teams.items():
        rec = records.get(tid, _EMPTY_RECORD)
        series = series_record(feed[tid]["series"])
        out.append({
            "id": tid,
            "name": t.name,
            "logo_url": team_logo(t.logo_url),
            "division": divisions.get(tid),
            **series,
            "wins": rec["wins"],
            "losses": rec["losses"],
            "matches": rec["games"],
            "points_per_game": display_points(points.get(tid, 0.0) / rec["games"]) if rec["games"] else 0.0,
            "player_count": len(players.get(tid, ())),
            "titles": titles.get(norm_name(t.name), []),
        })
    div_order = {"div1": 0, "div2": 1}
    out.sort(key=lambda r: (div_order.get(r["division"], 2), -r["series_wins"], -r["wins"],
                            str(r["name"] or "").lower()))
    return out


def team_detail(db, team: Team, weights: dict) -> dict:
    """GET /teams/{id}: header, summary tiles, series, roster, sources and heroes."""
    tid = team.id
    feed = feed_series(db, {tid: team})[tid]
    record = games_record(tid, scored_matches(db, tid))
    rows = scored_stat_rows(db, tid)
    team_games = record["games"]
    total = sum(r["fantasy_points"] or 0 for r in rows)
    league = cached_league_numbers(db, weights)

    current = accolades.current_season_label(db)
    pids = sorted({r["player_id"] for r in rows})
    per_player = accolades.accolades_for(db, pids, current=current) if pids else {}
    tags = accolades.tags_by_player(db) if pids else {}

    breakdowns = [player_insights.points_by_source(r, weights, bool(r["is_mvp"])) for r in rows]
    summary = {
        **series_record(feed["series"]),
        "games": team_games,
        "wins": record["wins"],
        "losses": record["losses"],
        "points_per_game": display_points(total / team_games) if team_games else 0.0,
        "avg_game_length": record["avg_game_length"],
        "mvps": sum(1 for r in rows if r["is_mvp"]),
    }
    return {
        "id": tid,
        "name": team.name,
        "logo_url": team_logo(team.logo_url),
        "division": team_divisions(db).get(tid),
        "season": current,
        "titles": titles_by_name(db).get(norm_name(team.name), []),
        "matches": team_games,
        "summary": summary,
        "series": feed["series"],
        "upcoming": feed["upcoming"],
        "players": roster(rows, team_games, league, per_player, tags),
        # Too few managers: owned_pct is null for every player (OWNERSHIP_MIN_MANAGERS).
        "ownership_hidden": ownership_hidden(league),
        "points_sources": player_insights.points_sources(breakdowns, league["sources"], per=team_games),
        "modifier_values": player_insights.modifier_values(rows, weights, per=team_games),
        "heroes": heroes(rows, tid),
    }
