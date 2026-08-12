from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from card_utils import (
    _SCORED_STAT_COLS, _load_weights,
    _compute_card_points, _mvp_bonus_delta,
)
from database import get_db
from models import Match, SeasonArchive, Weight, UserTag, TagDefinition
from scoring import fantasy_score, stat_dict_from_row, SCORING_STATS

router = APIRouter()


class SimulateBody(BaseModel):
    kills: float | None = None
    last_hits: float | None = None
    denies: float | None = None
    gold_per_min: float | None = None
    obs_placed: float | None = None
    towers_killed: float | None = None
    roshan_kills: float | None = None
    teamfight_participation: float | None = None
    camps_stacked: float | None = None
    rune_pickups: float | None = None
    firstblood_claimed: float | None = None
    stuns: float | None = None
    death_pool: float | None = None
    death_deduction: float | None = None


def _fetch_tags_for_users(db, user_ids: list[int]) -> dict:
    """Return {user_id: [{"key": ..., "label": ...}, ...]} for the given user IDs."""
    if not user_ids:
        return {}
    rows = (
        db.query(UserTag, TagDefinition)
        .join(TagDefinition, TagDefinition.id == UserTag.tag_id)
        .filter(UserTag.user_id.in_(user_ids))
        .all()
    )
    result: dict = {}
    for ut, td in rows:
        result.setdefault(ut.user_id, []).append({"key": td.key, "label": td.label})
    return result


def _leaderboard_rows(db, rows, mvp_rows=None) -> list[dict]:
    """Compute leaderboard totals using per-stat card_fantasy_score().

    rows must have: user_id, username, card_id, card_type, player_name,
                    deaths, kills, last_hits, denies, gold_per_min, obs_placed,
                    towers_killed, roshan_kills, teamfight_participation,
                    camps_stacked, rune_pickups, firstblood_claimed, stuns

    mvp_rows — optional raw (un-aggregated) is_mvp=1 match rows, one per MVP
    match, each with card_id + the same per-stat columns as `rows`. Summed
    per card via _mvp_bonus_delta() and added to that card's total.
    """
    from card_utils import _card_modifiers_map
    weights, rarity = _load_weights(db)
    card_ids = list({r.card_id for r in rows if r.card_id})
    mods_map = _card_modifiers_map(db, card_ids)

    mvp_bonus_map: dict[int, float] = {}
    for r in (mvp_rows or []):
        mvp_bonus_map[r.card_id] = mvp_bonus_map.get(r.card_id, 0.0) + _mvp_bonus_delta(r, weights)

    totals: dict[int, float] = {}
    usernames: dict[int, str] = {}
    cards_by_user: dict[int, list] = {}

    for r in rows:
        uid = r.user_id
        usernames[uid] = r.username
        totals.setdefault(uid, 0.0)
        cards_by_user.setdefault(uid, [])
        if not r.card_id:
            continue
        if getattr(r, 'match_count', 1) == 0:
            continue
        stat_sums = stat_dict_from_row(r)
        mods = mods_map.get(r.card_id, {})
        card_pts = _compute_card_points(stat_sums, r.card_type, weights, rarity, mods,
                                         mvp_bonus_map.get(r.card_id, 0.0))
        totals[uid] += card_pts
        cards_by_user[uid].append({
            "card_id": r.card_id,
            "card_type": r.card_type,
            "player_name": getattr(r, "player_name", None) or "",
            "points": round(card_pts, 2),
        })

    tags_by_user = _fetch_tags_for_users(db, list(totals.keys()))
    return sorted(
        [{"id": uid, "username": usernames[uid], "points": round(totals[uid], 2),
          "tags": tags_by_user.get(uid, []),
          "cards": sorted(cards_by_user.get(uid, []), key=lambda c: c["points"], reverse=True)}
         for uid in totals],
        key=lambda x: x["points"], reverse=True,
    )


@router.get("/top")
def top_performances(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, s.fantasy_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        ORDER BY s.fantasy_points DESC
        LIMIT 10
    """)).fetchall()
    return [dict(r._mapping) for r in results]


@router.get("/leaderboard")
def leaderboard(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT p.id, p.name, p.avatar_url, COUNT(s.id) as matches, AVG(s.fantasy_points) as avg_points
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        GROUP BY p.id, p.name, p.avatar_url
        ORDER BY avg_points DESC
    """)).fetchall()
    return [dict(r._mapping) for r in results]


@router.get("/leaderboard/roster")
def roster_leaderboard(db=Depends(get_db)):
    results = db.execute(text("""
        SELECT u.username,
               COALESCE(owned.total, 0) as total_cards,
               COALESCE(SUM(pts.total), 0) as roster_value
        FROM users u
        LEFT JOIN (
            SELECT owner_id, COUNT(*) as total
            FROM cards
            GROUP BY owner_id
        ) owned ON owned.owner_id = u.id
        LEFT JOIN cards c ON c.owner_id = u.id AND c.is_active = true
        LEFT JOIN (
            SELECT player_id, SUM(fantasy_points) as total
            FROM player_match_stats
            GROUP BY player_id
        ) pts ON pts.player_id = c.player_id
        WHERE u.is_tester = 0
        GROUP BY u.id, u.username, owned.total
        ORDER BY roster_value DESC
    """)).fetchall()
    return [dict(r._mapping) for r in results]


def compute_season_standings(db) -> list[dict]:
    """Compute the live season standings (one dict per non-tester user).

    Returns [{"id", "username", "points", "tags", "cards"}, ...] sorted by
    points descending. Shared by GET /leaderboard/season and the End Season
    archive action (POST /admin/season/end).
    """
    rows = db.execute(text("""
        SELECT u.id as user_id, u.username,
               c.id as card_id, c.card_type,
               p.name as player_name,
               COUNT(DISTINCT m.match_id) as match_count,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.deaths                  ELSE 0 END), 0) as deaths,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.kills                   ELSE 0 END), 0) as kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.last_hits               ELSE 0 END), 0) as last_hits,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.denies                  ELSE 0 END), 0) as denies,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.gold_per_min            ELSE 0 END), 0) as gold_per_min,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.obs_placed              ELSE 0 END), 0) as obs_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.towers_killed           ELSE 0 END), 0) as towers_killed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.roshan_kills            ELSE 0 END), 0) as roshan_kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.teamfight_participation ELSE 0 END), 0) as teamfight_participation,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.camps_stacked           ELSE 0 END), 0) as camps_stacked,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.rune_pickups            ELSE 0 END), 0) as rune_pickups,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.firstblood_claimed      ELSE 0 END), 0) as firstblood_claimed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.stuns                   ELSE 0 END), 0) as stuns
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id
        LEFT JOIN weeks wk ON wk.id = wre.week_id AND wk.is_locked = 1
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN players p ON p.id = c.player_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND (m.week_override_id = wk.id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN wk.start_time AND wk.end_time))
        WHERE u.is_tester = 0
        GROUP BY u.id, u.username, c.id, c.card_type, p.name
    """)).fetchall()
    mvp_rows = db.execute(text("""
        SELECT c.id as card_id,
               s.deaths, s.kills, s.last_hits, s.denies, s.gold_per_min, s.obs_placed,
               s.towers_killed, s.roshan_kills, s.teamfight_participation, s.camps_stacked,
               s.rune_pickups, s.firstblood_claimed, s.stuns
        FROM weekly_roster_entries wre
        JOIN weeks wk ON wk.id = wre.week_id AND wk.is_locked = 1
        JOIN cards c ON c.id = wre.card_id
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id
            AND (m.week_override_id = wk.id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN wk.start_time AND wk.end_time))
        WHERE s.is_mvp = 1
    """)).fetchall()
    return _leaderboard_rows(db, rows, mvp_rows)


@router.get("/leaderboard/season")
def season_leaderboard(db=Depends(get_db)):
    result = compute_season_standings(db)
    return [{"id": r["id"], "username": r["username"], "season_points": r["points"],
             "tags": r["tags"], "cards": r["cards"]} for r in result]


# ---------------------------------------------------------------------------
# Past Seasons (archived standings)
#
# Addressing scheme: a "season" is a group of season_archive rows sharing one
# season_label. Its public season_id is MIN(id) within the group — stable, and
# any row id belonging to the group resolves to the same season (the detail
# endpoint looks up the row by id and serves that row's whole label group).
# ---------------------------------------------------------------------------

@router.get("/leaderboard/seasons")
def list_archived_seasons(db=Depends(get_db)):
    rows = db.execute(text("""
        SELECT MIN(id) as id, season_label, MAX(archived_at) as archived_at,
               COUNT(*) as user_count
        FROM season_archive
        GROUP BY season_label
        ORDER BY MAX(archived_at) DESC, season_label
    """)).fetchall()
    return [{"id": r.id, "season_label": r.season_label,
             "archived_at": r.archived_at, "user_count": r.user_count}
            for r in rows]


@router.get("/leaderboard/seasons/{season_id}")
def archived_season_detail(season_id: int, db=Depends(get_db)):
    anchor = db.get(SeasonArchive, season_id)
    if not anchor:
        raise HTTPException(status_code=404, detail="Archived season not found")
    rows = (
        db.query(SeasonArchive)
        .filter(SeasonArchive.season_label == anchor.season_label)
        .order_by(SeasonArchive.rank)
        .all()
    )
    return {
        "id": season_id,
        "season_label": anchor.season_label,
        "archived_at": anchor.archived_at,
        "standings": [{"user_id": r.user_id, "username": r.username,
                       "points": r.points, "rank": r.rank} for r in rows],
    }


@router.get("/leaderboard/weekly")
def weekly_leaderboard(week_id: int, db=Depends(get_db)):
    from models import Week
    week = db.get(Week, week_id)
    if not week:
        raise HTTPException(status_code=404, detail="Week not found")
    rows = db.execute(text("""
        SELECT u.id as user_id, u.username,
               c.id as card_id, c.card_type,
               p.name as player_name,
               COUNT(DISTINCT m.match_id) as match_count,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.deaths                  ELSE 0 END), 0) as deaths,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.kills                   ELSE 0 END), 0) as kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.last_hits               ELSE 0 END), 0) as last_hits,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.denies                  ELSE 0 END), 0) as denies,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.gold_per_min            ELSE 0 END), 0) as gold_per_min,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.obs_placed              ELSE 0 END), 0) as obs_placed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.towers_killed           ELSE 0 END), 0) as towers_killed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.roshan_kills            ELSE 0 END), 0) as roshan_kills,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.teamfight_participation ELSE 0 END), 0) as teamfight_participation,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.camps_stacked           ELSE 0 END), 0) as camps_stacked,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.rune_pickups            ELSE 0 END), 0) as rune_pickups,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.firstblood_claimed      ELSE 0 END), 0) as firstblood_claimed,
               COALESCE(SUM(CASE WHEN m.match_id IS NOT NULL THEN s.stuns                   ELSE 0 END), 0) as stuns
        FROM users u
        LEFT JOIN weekly_roster_entries wre ON wre.user_id = u.id AND wre.week_id = :week_id
        LEFT JOIN cards c ON c.id = wre.card_id
        LEFT JOIN players p ON p.id = c.player_id
        LEFT JOIN player_match_stats s ON s.player_id = c.player_id
        LEFT JOIN matches m ON m.match_id = s.match_id
            AND (m.week_override_id = :week_id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
        WHERE u.is_tester = 0
        GROUP BY u.id, u.username, c.id, c.card_type, p.name
    """), {"week_id": week_id, "ws": week.start_time, "we": week.end_time}).fetchall()
    mvp_rows = db.execute(text("""
        SELECT c.id as card_id,
               s.deaths, s.kills, s.last_hits, s.denies, s.gold_per_min, s.obs_placed,
               s.towers_killed, s.roshan_kills, s.teamfight_participation, s.camps_stacked,
               s.rune_pickups, s.firstblood_claimed, s.stuns
        FROM weekly_roster_entries wre
        JOIN cards c ON c.id = wre.card_id
        JOIN player_match_stats s ON s.player_id = c.player_id
        JOIN matches m ON m.match_id = s.match_id
            AND (m.week_override_id = :week_id
                 OR (m.week_override_id IS NULL AND m.start_time BETWEEN :ws AND :we))
        WHERE wre.week_id = :week_id AND s.is_mvp = 1
    """), {"week_id": week_id, "ws": week.start_time, "we": week.end_time}).fetchall()
    result = _leaderboard_rows(db, rows, mvp_rows)
    return [{"id": r["id"], "username": r["username"], "week_points": r["points"],
             "tags": r["tags"], "cards": r["cards"]} for r in result]


@router.get("/weights")
def get_weights(db=Depends(get_db)):
    weights = db.query(Weight).order_by(Weight.key).all()
    return [{"key": w.key, "label": w.label, "value": w.value} for w in weights]


_SIMULATE_DOCS = {
    "endpoint": "POST /simulate/{match_id}",
    "description": (
        "per-stat weights. Any weight not provided falls back to the current season "
        "default stored in the database. No authentication required."
    ),
    "path_parameters": {
        "match_id": "integer — OpenDota match ID that has been ingested into the system",
    },
    "request_body": {
        "content_type": "application/json",
        "fields": {
            "kills":                    "float | omit — points per kill (default from DB)",
            "last_hits":                "float | omit — points per last hit (default from DB)",
            "denies":                   "float | omit — points per deny (default from DB)",
            "gold_per_min":             "float | omit — points per GPM (default from DB)",
            "obs_placed":               "float | omit — points per observer ward placed (default from DB)",
            "towers_killed":            "float | omit — points per tower destroyed (default from DB)",
            "roshan_kills":             "float | omit — points per Roshan kill (default from DB)",
            "teamfight_participation":  "float | omit — points for 100% teamfight participation (default from DB)",
            "camps_stacked":            "float | omit — points per camp stacked (default from DB)",
            "rune_pickups":             "float | omit — points per rune picked up (default from DB)",
            "firstblood_claimed":       "float | omit — points for claiming first blood (default from DB)",
            "stuns":                    "float | omit — points per second of stuns applied (default from DB)",
            "death_pool":               "float | omit — base points awarded for 0 deaths (default from DB)",
            "death_deduction":          "float | omit — points deducted per death (default from DB)",
        },
        "example": {
            "kills": 0.5,
            "death_pool": 5.0,
            "death_deduction": 0.5,
        },
    },
    "response": {
        "match_id": "integer — the queried match ID",
        "weights_used": "object — the full weight map applied (merged DB defaults + overrides)",
        "players": [
            {
                "player_id": "integer",
                "player_name": "string",
                "team_name": "string | null",
                "fantasy_points": "float — score under the provided weights",
                "stats": {
                    "kills": "integer",
                    "deaths": "integer",
                    "last_hits": "integer",
                    "denies": "integer",
                    "gold_per_min": "float",
                    "obs_placed": "integer",
                    "towers_killed": "integer",
                    "roshan_kills": "integer",
                    "teamfight_participation": "float",
                    "camps_stacked": "integer",
                    "rune_pickups": "integer",
                    "firstblood_claimed": "integer",
                    "stuns": "float",
                },
            }
        ],
    },
    "errors": {
        "404": "Match not found — match_id has not been ingested",
        "422": "Validation error — non-numeric weight value supplied",
    },
}


@router.get("/simulate")
def simulate_docs():
    """Human- and machine-readable documentation for the weight simulation endpoint."""
    return _SIMULATE_DOCS


@router.post("/simulate/{match_id}")
def simulate_match(match_id: int, db=Depends(get_db), body: SimulateBody = None):
    """Return fantasy scores for every player in a match under custom weights.

    Any weight not supplied in the request body falls back to the current DB default.
    No authentication required so statisticians can call this without an account.
    """
    if body is None:
        body = SimulateBody()

    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    db_weights = {w.key: w.value for w in db.query(Weight).all()}
    overrides = {k: v for k, v in body.model_dump().items() if v is not None}
    all_weight_keys = list(SCORING_STATS) + ["death_pool", "death_deduction"]
    weights_used = {k: overrides.get(k, db_weights.get(k, 0.0)) for k in all_weight_keys}

    rows = db.execute(text("""
        SELECT s.player_id, p.name as player_name,
               t.name as team_name,
               s.kills, s.deaths, s.gold_per_min, s.obs_placed,
               s.last_hits, s.denies, s.towers_killed, s.roshan_kills,
               s.teamfight_participation, s.camps_stacked, s.rune_pickups,
               s.firstblood_claimed, s.stuns
        FROM player_match_stats s
        JOIN players p ON p.id = s.player_id
        LEFT JOIN teams t ON t.id = s.team_id
        WHERE s.match_id = :match_id
    """), {"match_id": match_id}).fetchall()

    players = []
    for r in rows:
        stats = {
            "kills": r.kills or 0,
            "deaths": r.deaths or 0,
            "gold_per_min": r.gold_per_min or 0,
            "obs_placed": r.obs_placed or 0,
            "last_hits": r.last_hits or 0,
            "denies": r.denies or 0,
            "towers_killed": r.towers_killed or 0,
            "roshan_kills": r.roshan_kills or 0,
            "teamfight_participation": r.teamfight_participation or 0.0,
            "camps_stacked": r.camps_stacked or 0,
            "rune_pickups": r.rune_pickups or 0,
            "firstblood_claimed": r.firstblood_claimed or 0,
            "stuns": r.stuns or 0.0,
        }
        players.append({
            "player_id": r.player_id,
            "player_name": r.player_name,
            "team_name": r.team_name,
            "fantasy_points": round(fantasy_score(stats, weights_used), 2),
            "stats": stats,
        })

    players.sort(key=lambda p: p["fantasy_points"], reverse=True)

    return {
        "match_id": match_id,
        "weights_used": weights_used,
        "players": players,
    }
