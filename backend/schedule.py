import csv
import io
import os
import re
from datetime import datetime

import requests
from sqlalchemy import bindparam, text

SCHEDULE_SHEET_URL = os.getenv("SCHEDULE_SHEET_URL", "")
CACHE_TTL = 3600

_cache = {"data": None, "fetched_at": None}

# {hero_id: full icon URL}, fetched once per process lifetime — hero constants
# are effectively static within a patch, so there is no need to refresh this on
# the same 1-hour cadence as the schedule cache above.
_hero_icon_cache = None


# -----------------------
# FETCH
# -----------------------

def fetch_csv_text():
    if not SCHEDULE_SHEET_URL:
        print("[SCHEDULE] SCHEDULE_SHEET_URL is not set")
        return None
    try:
        res = requests.get(SCHEDULE_SHEET_URL, timeout=15, allow_redirects=True)
        print(f"[SCHEDULE] Fetch status={res.status_code} content-type={res.headers.get('content-type', '')}")
        if res.status_code != 200:
            return None
        return res.content.decode("utf-8")
    except Exception as e:
        print(f"[SCHEDULE] Fetch error: {e}")
        return None


# -----------------------
# PARSING HELPERS
# -----------------------

def parse_date_time(date_str, time_str):
    if not date_str:
        return None

    # Strip trailing text like "Monday", "Tuesday", etc.
    date_clean = re.split(r'\s+[A-Za-z]', date_str.strip())[0].strip()
    date_clean = date_clean.replace("-", ".").replace("/", ".")
    parts = [p.strip() for p in date_clean.split(".") if p.strip()]

    try:
        day = int(parts[0])
        month = int(parts[1])
        year = int(parts[2]) if len(parts) >= 3 else datetime.now().year
    except (IndexError, ValueError):
        return None

    time_clean = (time_str or "").strip().replace(".", ":")
    if ":" not in time_clean:
        time_clean = "00:00"
    try:
        h, m = int(time_clean.split(":")[0]), int(time_clean.split(":")[1])
        return datetime(year, month, day, h, m).isoformat()
    except (ValueError, IndexError):
        return None


def classify_row(cells):
    stripped = [c.strip() for c in cells]
    non_empty = [c for c in stripped if c]
    if not non_empty:
        return "empty"
    first = non_empty[0].lower()
    if "week" in first and any(ch.isdigit() for ch in first):
        return "week_header"
    if first in ("upper", "lower", "upper division", "lower division", "division 1", "division 2"):
        return "division_label"
    if first in ("team 1", "team"):
        return "column_header"
    return "data"


def parse_match_row(row, offset):
    padded = row + [""] * 12
    team1  = padded[offset + 0].strip()
    team2  = padded[offset + 1].strip()
    date   = padded[offset + 2].strip()
    time   = padded[offset + 3].strip()
    stream = padded[offset + 4].strip()

    if not team1 and not team2:
        return None

    stream_url   = stream if stream.startswith("http://") or stream.startswith("https://") else None
    stream_label = None if stream_url else (stream or None)

    dt_iso = parse_date_time(date, time)
    status = "unknown"
    if dt_iso:
        try:
            status = "past" if datetime.fromisoformat(dt_iso) < datetime.now() else "upcoming"
        except ValueError:
            pass

    return {
        "team1": team1 or None,
        "team2": team2 or None,
        "date": date or None,
        "time": time or None,
        "stream_label": stream_label,
        "stream_url": stream_url,
        "datetime_iso": dt_iso,
        "match_status": status,
    }


# -----------------------
# STATE MACHINE PARSER
# -----------------------

def parse_schedule(csv_text):
    weeks = []
    current_week = None
    state = "SEEKING_WEEK"

    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        kind = classify_row(row)

        if kind == "week_header":
            if current_week is not None:
                weeks.append(current_week)
            label = next((c.strip() for c in row if c.strip()), "")
            current_week = {"label": label, "div1": [], "div2": []}
            state = "IN_WEEK"

        elif state == "IN_WEEK":
            if kind in ("division_label", "column_header"):
                continue
            elif kind == "empty":
                state = "SEEKING_WEEK"
            elif kind == "data":
                m1 = parse_match_row(row, offset=0)
                m2 = parse_match_row(row, offset=6)
                if m1:
                    current_week["div1"].append(m1)
                if m2:
                    current_week["div2"].append(m2)

    if current_week is not None:
        weeks.append(current_week)

    return weeks


# -----------------------
# CROSS-REFERENCE & CACHE
# -----------------------

def bust_cache():
    _cache["data"] = None
    _cache["fetched_at"] = None


def norm_team_name(name):
    """Normalise a team name for fuzzy matching."""
    name = (name or "").lower().strip()
    name = re.sub(r'\(.*?\)', '', name)   # strip parentheticals: Meta(no)core → metacore
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def find_team_id(name, team_lookup):
    """Exact match first, then substring containment fallback."""
    n = norm_team_name(name)
    if n in team_lookup:
        return team_lookup[n]
    for key, tid in team_lookup.items():
        if n and key and (n in key or key in n):
            return tid
    return None


def build_team_lookup(db):
    """Return {normalised_name: team_id} for all teams in DB."""
    try:
        rows = db.execute(text("SELECT id, name FROM teams")).fetchall()
        return {norm_team_name(row[1]): row[0] for row in rows if row[1]}
    except Exception:
        return {}


def _fetch_hero_icon_map() -> dict:
    """{hero_id: full icon URL}, fetched once per process lifetime — hero constants
    are effectively static within a patch."""
    global _hero_icon_cache
    if _hero_icon_cache is not None:
        return _hero_icon_cache
    from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json
    try:
        data = opendota_get_json(f"{OPEN_DOTA_URL}/constants/heroes", label="constants/heroes") or {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    _hero_icon_cache = {
        h["id"]: f"https://cdn.cloudflare.steamstatic.com{h['icon']}"
        for h in data.values() if h.get("id") and h.get("icon")
    }
    return _hero_icon_cache


def _pad5(icons):
    """Pad (or truncate) a hero-icon list to exactly 5 slots, filling gaps with None."""
    icons = list(icons)[:5]
    return icons + [None] * (5 - len(icons))


def _build_games(db, match_ids, team1_id, team2_id):
    """Per-game duration/kills/hero-icons for the given match_ids, one entry per
    match_id (same order as match_ids), mapped to team1/team2 via the already
    resolved team ids."""
    if not match_ids:
        return []

    ids = list(match_ids)
    hero_icon_map = _fetch_hero_icon_map()

    duration_rows = db.execute(
        text("SELECT match_id, duration FROM matches WHERE match_id IN :ids")
            .bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).fetchall()
    duration_by_match = {r[0]: r[1] for r in duration_rows}

    kills_rows = db.execute(
        text("""
            SELECT match_id, team_id, SUM(kills) AS kills
            FROM player_match_stats
            WHERE match_id IN :ids AND team_id IS NOT NULL
            GROUP BY match_id, team_id
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).fetchall()
    kills_by_match_team = {(r[0], r[1]): (r[2] or 0) for r in kills_rows}

    hero_rows = db.execute(
        text("""
            SELECT match_id, team_id, hero_id
            FROM player_match_stats
            WHERE match_id IN :ids AND hero_id IS NOT NULL
            ORDER BY hero_id ASC
        """).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).fetchall()
    heroes_by_match_team: dict = {}
    for match_id, team_id, hero_id in hero_rows:
        heroes_by_match_team.setdefault((match_id, team_id), []).append(
            hero_icon_map.get(hero_id)
        )

    games = []
    for match_id in ids:
        games.append({
            "match_id": match_id,
            "duration": duration_by_match.get(match_id),
            "team1_kills": kills_by_match_team.get((match_id, team1_id), 0),
            "team2_kills": kills_by_match_team.get((match_id, team2_id), 0),
            "team1_heroes": _pad5(heroes_by_match_team.get((match_id, team1_id), [])),
            "team2_heroes": _pad5(heroes_by_match_team.get((match_id, team2_id), [])),
        })
    return games


def _tally_wins(rows, team1_id):
    """rows: iterable of (radiant_team_id, radiant_win) for one series.
    Returns (team1_wins, team2_wins)."""
    team1_wins = team2_wins = 0
    for radiant_id, radiant_win in rows:
        if radiant_win is None:
            continue
        if radiant_id == team1_id:
            team1_wins += 1 if radiant_win else 0
            team2_wins += 0 if radiant_win else 1
        else:
            team2_wins += 1 if radiant_win else 0
            team1_wins += 0 if radiant_win else 1
    return team1_wins, team2_wins


def _build_unscheduled_results(db, claimed_match_ids, div1_team_ids, div2_team_ids):
    """Derive series from completed matches no sheet row has already claimed.

    Consecutive matches (sorted by start_time) between the same unordered team
    pair belong to the same series as long as the gap to the previous match in
    that pair is <= 6 hours; a bigger gap starts a fresh series for that pair.
    """
    rows = db.execute(text("""
        SELECT match_id, radiant_team_id, dire_team_id, radiant_win, start_time
        FROM matches
        WHERE radiant_team_id IS NOT NULL AND dire_team_id IS NOT NULL
        ORDER BY start_time ASC
    """)).fetchall()

    GAP = 6 * 3600  # seconds — see plan Assumptions
    open_clusters = {}  # pair -> list of rows (currently-open series for that pair)
    clusters = []       # finished clusters, plus the still-open ones appended at the end

    for r in rows:
        match_id, radiant_id, dire_id, radiant_win, start_time = r
        if match_id in claimed_match_ids:
            continue
        pair = tuple(sorted((radiant_id, dire_id)))
        current = open_clusters.get(pair)
        if current is not None and (start_time - current[-1][4]) <= GAP:
            current.append(r)
        else:
            if current is not None:
                clusters.append(current)
            open_clusters[pair] = [r]

    clusters.extend(open_clusters.values())

    team_names = {t[0]: t[1] for t in db.execute(text("SELECT id, name FROM teams")).fetchall()}

    results = []
    for cluster in clusters:
        team1_id, team2_id = tuple(sorted((cluster[0][1], cluster[0][2])))
        team1_wins, team2_wins = _tally_wins(
            [(r[1], r[3]) for r in cluster], team1_id
        )
        match_ids = [r[0] for r in cluster]
        division = (
            "div1" if team1_id in div1_team_ids or team2_id in div1_team_ids else
            "div2" if team1_id in div2_team_ids or team2_id in div2_team_ids else
            None
        )
        results.append({
            "team1": team_names.get(team1_id, str(team1_id)), "team1_id": team1_id,
            "team2": team_names.get(team2_id, str(team2_id)), "team2_id": team2_id,
            "division": division,
            "datetime_iso": datetime.fromtimestamp(cluster[0][4]).isoformat(),
            "match_status": "past",
            "series_result": {
                "team1_wins": team1_wins, "team2_wins": team2_wins,
                "game_count": len(cluster), "start_time": cluster[0][4],
                "match_ids": match_ids,
                "games": _build_games(db, match_ids, team1_id, team2_id),
            },
        })
    return results


def resolve_series_result(db, team1_name, team2_name, team_lookup, scheduled_dt_iso=None):
    """Return {team1_wins, team2_wins, game_count, start_time} or None if unresolvable.

    When scheduled_dt_iso is supplied, only matches within ±4 days of that date
    are counted.  This prevents LAN-finals games from inflating regular-season
    series results when the same two teams met again later in the season.
    """
    team1_id = find_team_id(team1_name, team_lookup)
    team2_id = find_team_id(team2_name, team_lookup)
    if not team1_id or not team2_id:
        return None

    WINDOW = 4 * 86400  # 4 days in seconds
    params = {"a": team1_id, "b": team2_id}
    time_clause = ""
    if scheduled_dt_iso:
        try:
            anchor = int(datetime.fromisoformat(scheduled_dt_iso).timestamp())
            params["t0"] = anchor - WINDOW
            params["t1"] = anchor + WINDOW
            time_clause = "AND start_time BETWEEN :t0 AND :t1"
        except (ValueError, TypeError):
            pass  # malformed date — fall back to all-time

    try:
        rows = db.execute(text(f"""
            SELECT match_id, radiant_team_id, radiant_win, start_time FROM matches
            WHERE ((radiant_team_id = :a AND dire_team_id = :b)
               OR  (radiant_team_id = :b AND dire_team_id = :a))
            {time_clause}
            ORDER BY start_time ASC
        """), params).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    start_times = [r[3] for r in rows if r[3] is not None]
    match_ids = [r[0] for r in rows if r[0] is not None]
    team1_wins, team2_wins = _tally_wins(
        [(r[1], r[2]) for r in rows], team1_id
    )
    return {
        "team1_wins": team1_wins,
        "team2_wins": team2_wins,
        "game_count": len(rows),
        "start_time": min(start_times) if start_times else None,
        "match_ids": match_ids,
        "games": _build_games(db, match_ids, team1_id, team2_id),
    }


def get_schedule(db):
    now = datetime.now()

    # Return cache if still fresh
    if _cache["data"] is not None and _cache["fetched_at"] is not None:
        age = (now - _cache["fetched_at"]).total_seconds()
        if age < CACHE_TTL:
            return _cache["data"]

    csv_text = fetch_csv_text()

    if csv_text is None:
        # Return stale cache if available; otherwise fall through so Results
        # still populate from the DB below — only Upcoming has no fallback
        # when the sheet is unset/unreachable.
        if _cache["data"] is not None:
            stale = dict(_cache["data"])
            stale["stale"] = True
            return stale
        weeks = []
        error = "Schedule unavailable"
    else:
        weeks = parse_schedule(csv_text)
        error = None

    team_lookup = build_team_lookup(db)
    db_team_names = set(team_lookup.keys())

    claimed_match_ids = set()
    div1_names = set()
    div2_names = set()

    for week in weeks:
        div1_teams = {norm_team_name(t) for m in week["div1"] for t in (m["team1"] or "", m["team2"] or "") if t.strip()}
        div2_teams = {norm_team_name(t) for m in week["div2"] for t in (m["team1"] or "", m["team2"] or "") if t.strip()}
        week["has_results_div1"] = bool(div1_teams & db_team_names)
        week["has_results_div2"] = bool(div2_teams & db_team_names)
        div1_names |= div1_teams
        div2_names |= div2_teams

        for series in week["div1"] + week["div2"]:
            series["team1_id"] = find_team_id(series.get("team1"), team_lookup)
            series["team2_id"] = find_team_id(series.get("team2"), team_lookup)
            series["series_result"] = resolve_series_result(
                db, series.get("team1"), series.get("team2"), team_lookup,
                scheduled_dt_iso=series.get("datetime_iso"),
            )
            if series["series_result"] is not None:
                claimed_match_ids.update(series["series_result"]["match_ids"])

    div1_team_ids = set()
    for name in div1_names:
        tid = find_team_id(name, team_lookup)
        if tid is not None:
            div1_team_ids.add(tid)
    div2_team_ids = set()
    for name in div2_names:
        tid = find_team_id(name, team_lookup)
        if tid is not None:
            div2_team_ids.add(tid)

    extra_results = _build_unscheduled_results(db, claimed_match_ids, div1_team_ids, div2_team_ids)

    data = {
        "weeks": weeks,
        "cached_at": now.isoformat(),
        "stale": False,
        "error": error,
        "extra_results": extra_results,
    }

    _cache["data"] = data
    _cache["fetched_at"] = now

    return data
