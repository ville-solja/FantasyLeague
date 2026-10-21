"""Season insights for the player popup (issue 208).

Pure helpers behind GET /players/{id}: a match's points split by source, league
aggregates over scored matches, percentiles and hero rows. Every figure uses the
scoring code that produces match points (scoring.fantasy_score and the death pool),
so a match's parts add up to its fantasy points. No formula lives here.
"""

import re
import statistics
import threading
import time

from sqlalchemy import text

from match_scoring import scored_match_sql
from scoring import SCORING_STATS, STAT_LABELS, _death_contribution, display_points, fantasy_score

# (key, label, stats) in display order. "deaths" is the death pool (Survival);
# the MVP bonus has no stats of its own.
SOURCE_GROUPS = [
    ("kills",        "Kills",            ["kills"]),
    ("assists",      "Assists",          ["assists"]),
    ("farm",         "Farm",             ["last_hits", "denies"]),
    ("gpm",          "GPM",              ["gold_per_min"]),
    ("vision",       "Vision",           ["obs_placed"]),
    ("objectives",   "Objectives",       ["towers_killed", "roshan_kills"]),
    ("teamfight",    "Teamfight",        ["teamfight_participation"]),
    ("stuns",        "Stuns",            ["stuns"]),
    ("jungle_runes", "Jungle and runes", ["camps_stacked", "rune_pickups"]),
    ("first_blood",  "First blood",      ["firstblood_claimed"]),
    ("survival",     "Survival",         ["deaths"]),
    ("mvp_bonus",    "MVP bonus",        []),
]
SOURCE_KEYS = [key for key, _, _ in SOURCE_GROUPS]

# League comparison strips: (stat column, label, lower is better).
COMPARISON_STATS = [
    ("kills",                   "Kills",       False),
    ("deaths",                  "Deaths",      True),
    ("assists",                 "Assists",     False),
    ("gold_per_min",            "GPM",         False),
    ("last_hits",               "Last hits",   False),
    ("obs_placed",              "Wards",       False),
    ("stuns",                   "Stuns",       False),
    ("teamfight_participation", "Teamfight %", False),
]

# A player needs this many scored matches to be ranked against the league.
MIN_COMPARISON_MATCHES = 3

_STAT_COLS = SCORING_STATS + ["deaths"]


def _stats(row) -> dict:
    """{stat: value} for SCORING_STATS + deaths; a missing (partial) stat counts as 0."""
    get = row.get if isinstance(row, dict) else (lambda k: getattr(row, k, None))
    return {k: get(k) or 0 for k in _STAT_COLS}


def stat_points(stats: dict, weights: dict) -> dict:
    """Points each scoring stat earns in one match: weight × value, and the death pool
    for "deaths". They sum to scoring.fantasy_score(stats, weights)."""
    s = _stats(stats)
    out = {k: weights.get(k, 0) * s[k] for k in SCORING_STATS}
    out["deaths"] = _death_contribution(s["deaths"], weights)
    return out


def points_by_source(stats: dict, weights: dict, is_mvp: bool = False) -> dict:
    """{source key: exact points} for one match, in SOURCE_GROUPS order. The parts add
    up to the match's fantasy points: fantasy_score, plus mvp_bonus_pct of it for MVP."""
    per_stat = stat_points(stats, weights)
    out = {key: sum(per_stat[s] for s in group) for key, _, group in SOURCE_GROUPS if group}
    out["mvp_bonus"] = (fantasy_score(_stats(stats), weights) * weights.get("mvp_bonus_pct", 10.0) / 100
                        if is_mvp else 0.0)
    return out


def percentile(value, population, lower_is_better: bool = False) -> int:
    """Share of the population (0–100) the value beats, counting ties as half
    (mid-rank). With lower_is_better, a smaller value beats a larger one."""
    values = list(population)
    if not values:
        return 0
    if lower_is_better:
        beaten = sum(1 for v in values if v > value)
    else:
        beaten = sum(1 for v in values if v < value)
    ties = sum(1 for v in values if v == value)
    return int(round(100 * (beaten + 0.5 * ties) / len(values)))


# League aggregates are the same for every player, so GET /players/{id} reuses them
# until the data or the weights change (see _data_version), at most for the TTL.
LEAGUE_CACHE_TTL = 60.0
_league_lock = threading.Lock()
_league_cache: dict = {"key": None, "at": 0.0, "value": None}


def clear_league_cache() -> None:
    with _league_lock:
        _league_cache.update(key=None, at=0.0, value=None)


def _data_version(db) -> tuple:
    """A cheap fingerprint of everything league_aggregates reads: stat rows added,
    replaced or removed (count, ids), recalculated points and MVP flags, edited stats,
    and which matches are excluded. One aggregate pass, no per-row work."""
    row = db.execute(text("""
        SELECT COUNT(*), COALESCE(MAX(id), 0), COALESCE(SUM(id), 0), COALESCE(SUM(player_id), 0),
               COALESCE(SUM(fantasy_points), 0), COALESCE(SUM(is_mvp), 0),
               COALESCE(SUM(kills), 0), COALESCE(SUM(deaths), 0), COALESCE(SUM(assists), 0),
               COALESCE(SUM(gold_per_min), 0), COALESCE(SUM(last_hits), 0),
               (SELECT COUNT(*) FROM matches WHERE excluded_from_scoring = 1),
               (SELECT COALESCE(SUM(match_id), 0) FROM matches WHERE excluded_from_scoring = 1)
        FROM player_match_stats
    """)).fetchone()
    bind = db.get_bind()
    return (id(bind), str(bind.url)) + tuple(row)


def cached_league_aggregates(db, weights: dict) -> dict:
    """league_aggregates(db, weights), cached in-process: keyed on the weights
    fingerprint and _data_version, recomputed after LEAGUE_CACHE_TTL seconds anyway.
    Thread-safe; callers must not mutate the result."""
    from card_points import weights_fingerprint
    key = (weights_fingerprint(weights), _data_version(db))
    now = time.monotonic()
    with _league_lock:
        if _league_cache["key"] == key and now - _league_cache["at"] < LEAGUE_CACHE_TTL:
            return _league_cache["value"]
        value = league_aggregates(db, weights)
        _league_cache.update(key=key, at=now, value=value)
        return value


def league_aggregates(db, weights: dict) -> dict:
    """League figures over scored matches, in one query.

    Returns:
      population       {player_id: {"matches", "avg_points", "stats": {stat: avg}}} for
                       players with at least MIN_COMPARISON_MATCHES scored matches
      avg_points       league average fantasy points per scored match (all players)
      sources          league average points per scored match, per source
    """
    rows = db.execute(text(f"""
        SELECT s.player_id, s.fantasy_points, s.is_mvp,
               {", ".join("s." + c for c in _STAT_COLS)}
        FROM player_match_stats s
        LEFT JOIN matches m ON m.match_id = s.match_id
        WHERE {scored_match_sql()}
    """)).fetchall()

    per_player: dict[int, dict] = {}
    source_sums = {k: 0.0 for k in SOURCE_KEYS}
    points_sum = 0.0
    for r in rows:
        m = r._mapping
        stats = _stats(dict(m))
        points_sum += m["fantasy_points"] or 0
        for k, v in points_by_source(stats, weights, bool(m["is_mvp"])).items():
            source_sums[k] += v
        agg = per_player.setdefault(m["player_id"], {"matches": 0, "points": 0.0,
                                                     "sums": {c: 0.0 for c in _STAT_COLS}})
        agg["matches"] += 1
        agg["points"] += m["fantasy_points"] or 0
        for c in _STAT_COLS:
            agg["sums"][c] += stats[c]

    n = len(rows)
    population = {
        pid: {"matches": a["matches"],
              "avg_points": a["points"] / a["matches"],
              "stats": {c: a["sums"][c] / a["matches"] for c in _STAT_COLS}}
        for pid, a in per_player.items() if a["matches"] >= MIN_COMPARISON_MATCHES
    }
    return {
        "population": population,
        "avg_points": points_sum / n if n else 0.0,
        "sources": {k: (v / n if n else 0.0) for k, v in source_sums.items()},
    }


def avg_rank(player_id, population: dict):
    """{rank, of} of the player's average points in the population, or None when the
    player is not in it. Ties share the better rank."""
    me = population.get(player_id)
    if me is None:
        return None
    better = sum(1 for a in population.values() if a["avg_points"] > me["avg_points"])
    return {"rank": better + 1, "of": len(population)}


def league_comparison(player_id, population: dict):
    """Percentile strips for COMPARISON_STATS, or None when the player has fewer than
    MIN_COMPARISON_MATCHES scored matches (and so is not in the population)."""
    me = population.get(player_id)
    if me is None:
        return None
    stats = {}
    for col, label, lower in COMPARISON_STATS:
        values = [a["stats"][col] for a in population.values()]
        stats[col] = {
            "label": label,
            "value": display_points(me["stats"][col], 2),
            "percentile": percentile(me["stats"][col], values, lower),
            "median": display_points(statistics.median(values), 2),
            "lower_is_better": lower,
        }
    return {"population": len(population), "stats": stats}


def points_sources(scored_breakdowns: list[dict], league_sources: dict, per=None) -> list[dict]:
    """Per source: average points per scored match, share of the player's average
    (percent) and the league average. Every source is listed, zero when unused.
    `per` divides the sums instead of the row count (issue 211: a team's rows are
    summed per team game)."""
    n = len(scored_breakdowns) if per is None else per
    avgs = {k: (sum(b[k] for b in scored_breakdowns) / n if n else 0.0) for k in SOURCE_KEYS}
    total = sum(avgs.values())
    return [{
        "key": key,
        "label": label,
        "avg": display_points(avgs[key], 2),
        "share": display_points(100 * avgs[key] / total if total else 0.0),
        "league_avg": display_points(league_sources.get(key, 0.0), 2),
    } for key, label, _ in SOURCE_GROUPS]


def modifier_values(scored_stats: list[dict], weights: dict, per=None) -> dict:
    """What a card modifier on each stat is worth per scored match:
    modifier_bonus_pct % of that stat's average points. Per stat, highest first.
    `base` is the stat's average points, so a card modifier with its own bonus_pct
    is worth base × bonus_pct / 100. `per` divides the sums instead of the row count
    (issue 211: per team game)."""
    pct = weights.get("modifier_bonus_pct", 10.0)
    n = len(scored_stats) if per is None else per
    sums = {k: 0.0 for k in _STAT_COLS}
    for s in scored_stats:
        for k, v in stat_points(s, weights).items():
            sums[k] += v
    rows = []
    for k in _STAT_COLS:
        base = sums[k] / n if n else 0.0
        rows.append({"stat": k, "label": STAT_LABELS.get(k, k),
                     "base": display_points(base, 3),
                     "value": display_points(base * pct / 100, 2)})
    rows.sort(key=lambda r: r["value"], reverse=True)
    return {"bonus_pct": pct, "stats": rows if n and scored_stats else []}


# The popup's Core / Support chip (the same rule as app-player-popup.js).
SUPPORT_MIN_WARDS = 3
SUPPORT_MAX_GPM = 450


def role(scored_stats: list[dict]):
    """"Support" when the average observer wards are SUPPORT_MIN_WARDS or more and the
    average GPM is under SUPPORT_MAX_GPM, else "Core"; None without scored matches."""
    n = len(scored_stats)
    if not n:
        return None
    wards = sum(_stats(s)["obs_placed"] for s in scored_stats) / n
    gpm = sum(_stats(s)["gold_per_min"] for s in scored_stats) / n
    return "Support" if wards >= SUPPORT_MIN_WARDS and gpm < SUPPORT_MAX_GPM else "Core"


def hero_rows(history: list[dict], icons: dict, names: dict | None = None) -> list[dict]:
    """This season's heroes from the match history: games, wins, losses and average
    points per hero, most played first. Excluded matches and matches without a
    hero_id count in no row. `fantasy_points` should be the exact value."""
    names = names or {}
    rows: dict[int, dict] = {}
    for m in history:
        if m.get("excluded_from_scoring") or m.get("hero_id") is None:
            continue
        h = rows.setdefault(m["hero_id"], {"hero_id": m["hero_id"], "games": 0, "wins": 0,
                                           "losses": 0, "_points": 0.0})
        h["games"] += 1
        if m.get("won") is True:
            h["wins"] += 1
        elif m.get("won") is False:
            h["losses"] += 1
        h["_points"] += m.get("fantasy_points") or 0
    out = []
    for h in rows.values():
        avg = h.pop("_points") / h["games"]
        out.append({**h, "hero_name": names.get(h["hero_id"]),
                    "icon_url": icons.get(h["hero_id"]),
                    "avg_points": display_points(avg)})
    out.sort(key=lambda h: (-h["games"], -h["avg_points"], h["hero_id"]))
    return out


def won(team_id, radiant_team_id, dire_team_id, radiant_win):
    """True/False when the player's side won/lost, None when the result or side is unknown."""
    if radiant_win is None or team_id is None:
        return None
    if team_id == radiant_team_id:
        return bool(radiant_win)
    if team_id == dire_team_id:
        return not bool(radiant_win)
    return None


def week_short(label):
    """"Week 3" -> "W3"; any other label is returned as it is."""
    if not label:
        return None
    m = re.fullmatch(r"\s*week\s*(\d+)\s*", label, re.I)
    return f"W{m.group(1)}" if m else label
