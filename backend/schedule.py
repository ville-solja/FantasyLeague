import csv
import io
import os
import re
from datetime import datetime

import requests
from sqlalchemy import text

SCHEDULE_SHEET_URL = os.getenv("SCHEDULE_SHEET_URL", "")
CACHE_TTL = 3600

_cache = {"data": None, "fetched_at": None}


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


def _norm(name):
    """Normalise a team name for fuzzy matching."""
    name = (name or "").lower().strip()
    name = re.sub(r'\(.*?\)', '', name)   # strip parentheticals: Meta(no)core → metacore
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _find_team_id(name, team_lookup):
    """Exact match first, then substring containment fallback."""
    n = _norm(name)
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
        return {_norm(row[1]): row[0] for row in rows if row[1]}
    except Exception:
        return {}


def resolve_series_result(db, team1_name, team2_name, team_lookup):
    """Return {team1_wins, team2_wins, game_count, start_time} or None if unresolvable."""
    team1_id = _find_team_id(team1_name, team_lookup)
    team2_id = _find_team_id(team2_name, team_lookup)
    if not team1_id or not team2_id:
        return None
    try:
        rows = db.execute(text("""
            SELECT radiant_team_id, radiant_win, start_time FROM matches
            WHERE (radiant_team_id = :a AND dire_team_id = :b)
               OR (radiant_team_id = :b AND dire_team_id = :a)
        """), {"a": team1_id, "b": team2_id}).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    team1_wins = 0
    team2_wins = 0
    start_times = [r[2] for r in rows if r[2] is not None]
    for radiant_id, radiant_win, _ in rows:
        if radiant_win is None:
            continue
        if radiant_id == team1_id:
            team1_wins += 1 if radiant_win else 0
            team2_wins += 0 if radiant_win else 1
        else:
            team2_wins += 1 if radiant_win else 0
            team1_wins += 0 if radiant_win else 1
    return {
        "team1_wins": team1_wins,
        "team2_wins": team2_wins,
        "game_count": len(rows),
        "start_time": min(start_times) if start_times else None,
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
        # Return stale cache if available, otherwise empty
        if _cache["data"] is not None:
            stale = dict(_cache["data"])
            stale["stale"] = True
            return stale
        return {"weeks": [], "cached_at": None, "stale": False, "error": "Schedule unavailable"}

    weeks = parse_schedule(csv_text)

    team_lookup = build_team_lookup(db)
    db_team_names = set(team_lookup.keys())

    for week in weeks:
        div1_teams = {_norm(t) for m in week["div1"] for t in (m["team1"] or "", m["team2"] or "") if t.strip()}
        div2_teams = {_norm(t) for m in week["div2"] for t in (m["team1"] or "", m["team2"] or "") if t.strip()}
        week["has_results_div1"] = bool(div1_teams & db_team_names)
        week["has_results_div2"] = bool(div2_teams & db_team_names)

        for series in week["div1"] + week["div2"]:
            series["series_result"] = resolve_series_result(
                db, series.get("team1"), series.get("team2"), team_lookup
            )

    data = {
        "weeks": weeks,
        "cached_at": now.isoformat(),
        "stale": False,
        "error": None,
    }

    _cache["data"] = data
    _cache["fetched_at"] = now

    return data
