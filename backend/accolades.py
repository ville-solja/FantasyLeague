"""Season champions, accolades and Holo eligibility (issues #50, #53, #105).

Every title lives in `season_accolades` (models.SeasonAccolade), which Season Reset
never touches. Names are stored on each row, so readers never depend on the season's
players, teams or users still existing. See
markdown/features/reference/season-winners-and-holo-cards.md.
"""
from __future__ import annotations

import logging
import math
import random
import re
import time

from sqlalchemy import text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from match_scoring import scored_stat_sql
from models import League, Player, SeasonAccolade, TagDefinition, User, UserTag, Weight
from scoring import display_points

logger = logging.getLogger(__name__)

# The symbol registry: order, name, Lucide icon, plate and colour token per kind.
# frontend/app-globals.js keeps the same list (ACCOLADE_KINDS); a test checks they agree.
ACCOLADE_KINDS = [
    {"key": "div1",           "kind": "champion",       "division": "div1", "name": "Div 1 Champion",    "icon": "crown",          "plate": "filled",   "token": "--accolade-div1"},
    {"key": "div2",           "kind": "champion",       "division": "div2", "name": "Div 2 Champion",    "icon": "trophy",         "plate": "filled",   "token": "--accolade-div2"},
    {"key": "most_points",    "kind": "most_points",    "division": None,   "name": "Most Points",       "icon": "flame",          "plate": "outlined", "token": "--accolade-points"},
    {"key": "best_average",   "kind": "best_average",   "division": None,   "name": "Best Average",      "icon": "gauge",          "plate": "outlined", "token": "--accolade-average"},
    {"key": "best_match",     "kind": "best_match",     "division": None,   "name": "Best Single Match", "icon": "zap",            "plate": "outlined", "token": "--accolade-match"},
    {"key": "fantasy_winner", "kind": "fantasy_winner", "division": None,   "name": "Fantasy Winner",    "icon": "medal",          "plate": "outlined", "token": "--accolade-fantasy"},
    {"key": "played",         "kind": "played",         "division": None,   "name": "Played",            "icon": "calendar-check", "plate": "muted",    "token": "--accolade-played"},
]

KINDS = ("champion", "most_points", "best_average", "best_match", "fantasy_winner", "played")
AWARD_KINDS = ("most_points", "best_average", "best_match")
PLAYER_AWARD_KINDS = AWARD_KINDS
DIVISIONS = ("div1", "div2")
SOURCE_SEASON_END = "season_end"
SOURCE_ADMIN = "admin"
DEFAULT_HOLO_CHANCE = 20.0
WINNER_TAG_KEY = "season_winner"

_SEASON_RE = re.compile(r"\s*(?:season|s)\s*(\d+)\s*", re.I)
# "Season N" anywhere in an OpenDota league name ("Kanaliiga Season 16 Lower").
# At most four digits: a longer number is ignored rather than parsed (OpenDota names are external data).
_LEAGUE_SEASON_RE = re.compile(r"\bseason\s*(\d{1,4})(?!\d)", re.I)


# ---------------------------------------------------------------------------
# Season labels
# ---------------------------------------------------------------------------

def season_number(label) -> int | None:
    """16 for "Season 16" or "S16"; None when the label has no season number."""
    m = _SEASON_RE.fullmatch(str(label or ""))
    return int(m.group(1)) if m else None


def short_season(label) -> str:
    """'Season 16' -> 'S16'; an unparseable label is returned unchanged."""
    n = season_number(label)
    return f"S{n}" if n is not None else str(label or "")


def season_sort_key(label) -> tuple:
    """Ascending key: numbered seasons by number, unnumbered ones before them."""
    n = season_number(label)
    return (n if n is not None else -1, str(label or ""))


def league_season_number(name) -> int | None:
    """16 for "Kanaliiga Season 16 Lower"; None for a name without "Season N"
    ("Kanaliiga", "(pending ingest)")."""
    m = _LEAGUE_SEASON_RE.search(str(name or ""))
    return int(m.group(1)) if m else None


def league_division(name) -> str:
    """Each division is its own OpenDota league: "div2" when the name says "Lower"
    (any case), else "div1"."""
    return "div2" if "lower" in str(name or "").lower() else "div1"


def _monitored_league_season(db) -> int | None:
    """The season number the monitored leagues' names agree on (the highest, with a
    warning, when they disagree); None when no monitored league names one."""
    names = [r[0] for r in db.query(League.name).filter(League.is_monitored == True).all()]  # noqa: E712
    numbers = sorted({n for n in (league_season_number(x) for x in names) if n is not None})
    if not numbers:
        return None
    if len(numbers) > 1:
        logger.warning("Monitored leagues name different seasons %s; using Season %d",
                       numbers, numbers[-1])
    return numbers[-1]


def current_season_label(db) -> str:
    """The label the live season's data belongs to.

    First from the monitored leagues' OpenDota names ("Kanaliiga Season 16" and
    "Kanaliiga Season 16 Lower" give "Season 16"); End Season keeps them monitored, so
    the label stays until Reset unmonitors them. Fallback (no monitored league, a name
    still "(pending ingest)" or without a number): after End Season and before Reset
    the stats belong to the season just archived (its archive is newer than every
    match); otherwise the season after the highest one known from archives and
    non-champion accolades (champions of the running season may be entered early)."""
    from_leagues = _monitored_league_season(db)
    if from_leagues is not None:
        return f"Season {from_leagues}"
    newest_match = db.execute(text("SELECT MAX(start_time) FROM matches")).scalar()
    latest = db.execute(text(
        "SELECT season_label, MAX(archived_at) AS at FROM season_archive "
        "GROUP BY season_label ORDER BY at DESC LIMIT 1")).first()
    if latest is not None and newest_match is not None and latest.at >= newest_match:
        return latest.season_label
    labels = [r[0] for r in db.execute(text(
        "SELECT DISTINCT season_label FROM season_archive "
        "UNION SELECT DISTINCT season_label FROM season_accolades WHERE kind != 'champion'"))]
    numbers = [n for n in (season_number(lb) for lb in labels) if n is not None]
    return f"Season {max(numbers) + 1}" if numbers else "Season 1"


# ---------------------------------------------------------------------------
# The live season: awards, played players, teams
# ---------------------------------------------------------------------------

def _player_names(db, ids) -> dict[int, str]:
    ids = [i for i in ids if i is not None]
    if not ids:
        return {}
    return {p.id: p.name for p in db.query(Player.id, Player.name).filter(Player.id.in_(ids)).all()
            if p.name}


def _scored_rows(db):
    return db.execute(text(f"""
        SELECT s.player_id, s.match_id, COALESCE(s.fantasy_points, 0) AS pts
        FROM player_match_stats s
        WHERE s.player_id IS NOT NULL AND {scored_stat_sql()}
    """)).fetchall()


def _ties(items: list, key) -> list:
    if not items:
        return []
    best = max(round(key(i), 6) for i in items)
    return [i for i in items if round(key(i), 6) == best]


def compute_awards(db) -> dict:
    """The season's four awards from raw fantasy_points of scored matches; every tied
    winner is listed. best_average needs at least half as many scored matches as the
    most-played player (rounded up)."""
    rows = _scored_rows(db)
    per: dict[int, dict] = {}
    for r in rows:
        p = per.setdefault(r.player_id, {"total": 0.0, "count": 0, "best": None, "best_match": None})
        p["total"] += r.pts
        p["count"] += 1
        if p["best"] is None or r.pts > p["best"]:
            p["best"], p["best_match"] = r.pts, r.match_id
    names = _player_names(db, per.keys())

    def entry(pid, value, match_id=None):
        e = {"player_account_id": pid, "player_name": names.get(pid) or f"Player {pid}",
             "value": display_points(value)}
        if match_id is not None:
            e["match_id"] = match_id
        return e

    items = list(per.items())
    most = _ties(items, lambda i: i[1]["total"])
    max_count = max((p["count"] for p in per.values()), default=0)
    min_count = math.ceil(max_count / 2)
    qualified = [i for i in items if i[1]["count"] >= min_count and i[1]["count"] > 0]
    avg = _ties(qualified, lambda i: i[1]["total"] / i[1]["count"])
    best = _ties(items, lambda i: i[1]["best"])

    awards = {
        "most_points": [entry(pid, p["total"]) for pid, p in most],
        "best_average": [entry(pid, p["total"] / p["count"]) for pid, p in avg],
        "best_match": [entry(pid, p["best"], p["best_match"]) for pid, p in best],
        "fantasy_winner": [],
    }
    for key in AWARD_KINDS:
        awards[key].sort(key=lambda e: (e["player_name"].lower(), e["player_account_id"]))

    if rows:
        from routers.leaderboard import compute_season_standings
        standings = [s for s in compute_season_standings(db) if (s.get("points") or 0) > 0]
        top = _ties(standings, lambda s: float(s["points"]))
        awards["fantasy_winner"] = sorted(
            ({"user_id": s["id"], "username": s["username"], "value": display_points(s["points"])}
             for s in top), key=lambda e: (str(e["username"]).lower(), e["user_id"]))
    return awards


def played_player_ids(db) -> list[int]:
    """Every player with at least one scored match this season."""
    return sorted({r.player_id for r in _scored_rows(db)})


def played_match_counts(db) -> dict[int, int]:
    """{player_id: scored matches this season}."""
    counts: dict[int, int] = {}
    for r in _scored_rows(db):
        counts[r.player_id] = counts.get(r.player_id, 0) + 1
    return counts


def _team_divisions(db) -> dict[int, dict[str, int]]:
    """{team_id: {division: matches}} from the leagues of the team's matches."""
    rows = db.execute(text("""
        SELECT s.team_id, l.name AS league_name, COUNT(DISTINCT s.match_id) AS n
        FROM player_match_stats s
        JOIN matches m ON m.match_id = s.match_id
        JOIN leagues l ON l.id = m.league_id
        WHERE s.team_id IS NOT NULL
        GROUP BY s.team_id, l.name
    """)).fetchall()
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        d = out.setdefault(r.team_id, {})
        div = league_division(r.league_name)
        d[div] = d.get(div, 0) + r.n
    return out


def season_teams(db) -> list[dict]:
    """The season's teams, each with the players who played for it
    (player_match_stats.team_id), for the champion picker. `division` comes from the
    league of the team's matches (div2 for a "Lower" league): the division of most of
    them, None when unknown; `divisions` lists every division it played in."""
    divisions = _team_divisions(db)
    rows = db.execute(text("""
        SELECT t.id AS team_id, t.name AS team_name, s.player_id, p.name AS player_name,
               COUNT(s.id) AS matches
        FROM player_match_stats s
        JOIN teams t ON t.id = s.team_id
        LEFT JOIN players p ON p.id = s.player_id
        WHERE s.player_id IS NOT NULL
        GROUP BY t.id, t.name, s.player_id, p.name
    """)).fetchall()
    teams: dict[int, dict] = {}
    for r in rows:
        if r.team_id not in teams:
            divs = divisions.get(r.team_id, {})
            main = max(sorted(divs), key=lambda d: divs[d]) if divs else None
            teams[r.team_id] = {"team_id": r.team_id, "team_name": r.team_name or f"Team {r.team_id}",
                                "division": main, "divisions": sorted(divs), "players": []}
        t = teams[r.team_id]
        t["players"].append({"account_id": r.player_id,
                             "name": r.player_name or f"Player {r.player_id}",
                             "matches": r.matches})
    for t in teams.values():
        t["players"].sort(key=lambda p: (-p["matches"], p["name"].lower()))
    return sorted(teams.values(), key=lambda t: t["team_name"].lower())


# ---------------------------------------------------------------------------
# Writing rows
# ---------------------------------------------------------------------------

def known_name(db, account_id: int) -> str | None:
    """A player's name from the pool, else from their newest earlier accolade row."""
    p = db.get(Player, account_id)
    if p is not None and p.name:
        return p.name
    row = (db.query(SeasonAccolade.player_name)
           .filter(SeasonAccolade.player_account_id == account_id,
                   SeasonAccolade.player_name.isnot(None))
           .order_by(SeasonAccolade.id.desc()).first())
    return row[0] if row else None


def insert_ignore(db, rows: list[dict]) -> int:
    """INSERT … ON CONFLICT DO NOTHING on the unique key; returns how many were new."""
    added = 0
    for row in rows:
        res = db.execute(sqlite_insert(SeasonAccolade).values(**row).on_conflict_do_nothing())
        added += res.rowcount or 0
    return added


def grant_winner_tag(db, user_id: int, granted_by: int | None) -> bool:
    """The existing season_winner user tag for a fantasy winner (created when missing)."""
    if db.get(User, user_id) is None:
        return False
    tag = db.query(TagDefinition).filter_by(key=WINNER_TAG_KEY).first()
    if tag is None:
        tag = TagDefinition(key=WINNER_TAG_KEY, label="Season Winner", created_at=int(time.time()))
        db.add(tag)
        db.flush()
    if db.query(UserTag).filter_by(user_id=user_id, tag_id=tag.id).first():
        return False
    db.add(UserTag(user_id=user_id, tag_id=tag.id, granted_by=granted_by,
                   granted_at=int(time.time()), source="admin"))
    return True


def record_season(db, label: str, champions: list[dict] | None, actor_id: int | None) -> dict:
    """End Season: insert the awards, the champions and one played row per player with
    a scored match, all with source season_end, and give each fantasy winner the
    season_winner tag. Rows that already exist (entered by hand earlier) are kept.
    Does not commit. champions: [{division, team_name, player_account_ids}]."""
    now = int(time.time())
    base = {"season_label": label, "source": SOURCE_SEASON_END, "created_at": now,
            "created_by": actor_id}
    awards = compute_awards(db)
    played = played_player_ids(db)
    names = _player_names(db, played)
    rows: list[dict] = []
    for kind in AWARD_KINDS:
        for a in awards[kind]:
            rows.append({**base, "kind": kind, "player_account_id": a["player_account_id"],
                         "player_name": a["player_name"], "value": a["value"],
                         "match_id": a.get("match_id")})
    for a in awards["fantasy_winner"]:
        rows.append({**base, "kind": "fantasy_winner", "user_id": a["user_id"],
                     "username": a["username"], "value": a["value"]})
    award_count = insert_ignore(db, rows)

    champ_rows = []
    for c in champions or []:
        for pid in dict.fromkeys(c["player_account_ids"]):
            champ_rows.append({**base, "kind": "champion", "division": c["division"],
                               "team_name": c["team_name"], "player_account_id": pid,
                               "player_name": known_name(db, pid) or f"Player {pid}"})
    champion_count = insert_ignore(db, champ_rows)

    played_count = insert_ignore(db, [
        {**base, "kind": "played", "player_account_id": pid,
         "player_name": names.get(pid) or f"Player {pid}"} for pid in played])

    for a in awards["fantasy_winner"]:
        grant_winner_tag(db, a["user_id"], actor_id)
    return {"awards": award_count, "champions": champion_count, "played": played_count,
            "accolades": award_count + champion_count + played_count}


def set_champions(db, label: str, division: str, team_name: str, players: list[dict],
                  actor_id: int | None) -> tuple[int, int]:
    """Make one season and division's champions exactly `players` ([{account_id, name}]):
    add new players, delete removed ones, update names and the team name. Does not
    commit. Returns (added, removed)."""
    existing = {r.player_account_id: r for r in db.query(SeasonAccolade).filter(
        SeasonAccolade.season_label == label, SeasonAccolade.kind == "champion",
        SeasonAccolade.division == division).all()}
    wanted = {p["account_id"]: p["name"] for p in players}
    removed = 0
    for pid, row in existing.items():
        if pid not in wanted:
            db.delete(row)
            removed += 1
    added = 0
    now = int(time.time())
    for pid, name in wanted.items():
        row = existing.get(pid)
        if row is not None:
            row.player_name = name
            row.team_name = team_name
        else:
            db.add(SeasonAccolade(season_label=label, kind="champion", division=division,
                                  team_name=team_name, player_account_id=pid, player_name=name,
                                  source=SOURCE_ADMIN, created_at=now, created_by=actor_id))
            added += 1
    db.flush()
    return added, removed


# ---------------------------------------------------------------------------
# Holo
# ---------------------------------------------------------------------------

def holo_eligible(db, player_id: int, current: str | None = None) -> bool:
    """True when the player has a champion accolade in a season other than the live one."""
    current = current if current is not None else current_season_label(db)
    return db.query(SeasonAccolade.id).filter(
        SeasonAccolade.kind == "champion",
        SeasonAccolade.player_account_id == player_id,
        SeasonAccolade.season_label != current).first() is not None


def holo_chance(db, weights: dict | None = None) -> float:
    if weights is None:
        weights = {w.key: w.value for w in db.query(Weight).filter(Weight.key == "holo_chance").all()}
    value = weights.get("holo_chance", DEFAULT_HOLO_CHANCE)
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return DEFAULT_HOLO_CHANCE


def roll_holo(db, player_id: int, rarity: str, weights: dict | None = None) -> bool:
    """A drawn Legendary of a past champion becomes Holo with holo_chance %."""
    if rarity != "legendary":
        return False
    chance = holo_chance(db, weights)
    if chance <= 0 or not holo_eligible(db, player_id):
        return False
    return random.random() * 100 < chance


# ---------------------------------------------------------------------------
# Reading: per-player accolades (pips and chips), seasons played
# ---------------------------------------------------------------------------

def _entry(row) -> dict:
    return {"kind": row.kind, "division": row.division, "season": row.season_label,
            "season_short": short_season(row.season_label), "team_name": row.team_name,
            "value": row.value, "match_id": row.match_id}


def _linked_users(db) -> dict[int, int]:
    """{user_id: player_id} for every Steam-verified link: a full, non-demo account with
    a steam_id and a player_id (the own_card.is_candidate rule). A self-reported id
    (PUT /profile/player-id, no steam_id) never counts, so nobody can put their fantasy
    win on someone else's player or publish a username-player link by typing an id."""
    return {r.id: r.player_id for r in db.query(User.id, User.player_id).filter(
        User.player_id.isnot(None), User.steam_id.isnot(None),
        User.account_type == "full", User.is_demo == False).all()}  # noqa: E712


def accolades_for(db, player_ids=None, include_live: bool = True,
                  current: str | None = None) -> dict[int, list[dict]]:
    """{player_id: [accolade, ...]} with champion and award titles, fantasy_winner
    seasons resolved through the winning user's current link (users.player_id), and
    played seasons, including the live season for players with a scored match. No
    user ids or usernames. Each accolade: kind, division, season, season_short,
    team_name, value, match_id."""
    current = current if current is not None else current_season_label(db)
    q = db.query(SeasonAccolade)
    wanted = set(player_ids) if player_ids is not None else None
    result: dict[int, list[dict]] = {}
    links = _linked_users(db)
    for row in q.all():
        if row.kind == "fantasy_winner":
            pid = links.get(row.user_id) if row.user_id is not None else None
        else:
            pid = row.player_account_id
        if pid is None or (wanted is not None and pid not in wanted):
            continue
        result.setdefault(pid, []).append(_entry(row))
    if include_live:
        for pid in played_player_ids(db):
            if wanted is not None and pid not in wanted:
                continue
            lst = result.setdefault(pid, [])
            if not any(a["kind"] == "played" and a["season"] == current for a in lst):
                lst.append({"kind": "played", "division": None, "season": current,
                            "season_short": short_season(current), "team_name": None,
                            "value": None, "match_id": None, "live": True})
    for lst in result.values():
        lst.sort(key=_newest_first_key)
    return result


_KIND_ORDER = {k["key"]: i for i, k in enumerate(ACCOLADE_KINDS)}


def kind_key(a: dict) -> str:
    return a["division"] if a["kind"] == "champion" else a["kind"]


def _newest_first_key(a: dict):
    n, label = season_sort_key(a["season"])
    return (-n, label, _KIND_ORDER.get(kind_key(a), 99))


def player_seasons(accolades: list[dict]) -> dict:
    """seasons_played, seasons (newest first) and titles (champion and award
    accolades, newest first) from one player's accolades_for list."""
    seasons = []
    for a in accolades:
        if a["kind"] == "played" and a["season"] not in seasons:
            seasons.append(a["season"])
    titles = [a for a in accolades if a["kind"] != "played"]
    return {"seasons_played": len(seasons), "seasons": seasons, "titles": titles}


def history(db, current: str | None = None) -> dict:
    """GET /history/seasons: the live season's label, one entry per season newest first
    with the champion teams and the four awards (ties included), plus the hall of fame.
    No user ids."""
    rows = db.query(SeasonAccolade).all()
    by_season: dict[str, list] = {}
    for r in rows:
        by_season.setdefault(r.season_label, []).append(r)
    seasons = []
    for label in sorted(by_season, key=season_sort_key, reverse=True):
        rs = by_season[label]
        champions = {}
        for div in DIVISIONS:
            members = sorted((r for r in rs if r.kind == "champion" and r.division == div),
                             key=lambda r: (str(r.player_name or "").lower(), r.player_account_id or 0))
            champions[div] = {
                "team_name": members[0].team_name,
                "players": [{"account_id": r.player_account_id, "name": r.player_name} for r in members],
            } if members else None
        awards = {}
        for kind in AWARD_KINDS:
            awards[kind] = [{"player_account_id": r.player_account_id, "player_name": r.player_name,
                             "value": r.value, "match_id": r.match_id}
                            for r in sorted((r for r in rs if r.kind == kind),
                                            key=lambda r: str(r.player_name or "").lower())]
        awards["fantasy_winner"] = [{"username": r.username, "value": r.value}
                                    for r in sorted((r for r in rs if r.kind == "fantasy_winner"),
                                                    key=lambda r: str(r.username or "").lower())]
        seasons.append({
            "season_label": label, "season_short": short_season(label),
            "champions": champions, "awards": awards,
            "played_count": sum(1 for r in rs if r.kind == "played"),
        })

    current = current if current is not None else current_season_label(db)
    per_player = accolades_for(db, include_live=False, current=current)
    names: dict[int, str] = {}  # the newest name stored on the player's rows
    for r in sorted(rows, key=lambda r: r.id):
        if r.player_account_id is not None and r.player_name:
            names[r.player_account_id] = r.player_name
    fame = []
    for pid, lst in per_player.items():
        titles = [a for a in lst if a["kind"] != "played"]
        if not titles:
            continue
        champ = sum(1 for a in titles if a["kind"] == "champion")
        fame.append({"player_account_id": pid, "player_name": names.get(pid) or f"Player {pid}",
                     "titles": len(titles), "champion_titles": champ,
                     "award_titles": len(titles) - champ, "accolades": titles})
    fame.sort(key=lambda f: (-f["titles"], -f["champion_titles"], f["player_name"].lower()))
    return {"current_season": current, "seasons": seasons, "hall_of_fame": fame}


def row_dict(r: SeasonAccolade) -> dict:
    return {"id": r.id, "season_label": r.season_label, "season_short": short_season(r.season_label),
            "kind": r.kind, "division": r.division, "team_name": r.team_name,
            "player_account_id": r.player_account_id, "player_name": r.player_name,
            "user_id": r.user_id, "username": r.username, "value": r.value,
            "match_id": r.match_id, "source": r.source, "created_at": r.created_at}
