import logging
import os
import threading
import time

from sqlalchemy import func

from database import SessionLocal
from models import Match, Player, PlayerMatchStats, League, Team, Weight, MatchBan, TwitchMVP
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json, post_json as opendota_post_json
from scoring import apply_mvp_bonus_to_row, fantasy_score
from dotabuff_league_logos import ensure_dotabuff_league_logos

logger = logging.getLogger(__name__)

# Shared between the background poll loop (main.py::_ingest_poll_loop) and the
# admin-triggered manual ingest endpoint (routers/admin_ingest.py) so the two
# can never run ingest_league()/run_enrichment() concurrently against the
# same league data.
INGEST_LOCK = threading.Lock()

# match_id -> unix time of the last successful POST /request/{id}. A parse job can fail
# on OpenDota's side (e.g. Valve's replay server returning 5xx), so a match is asked for
# again once INGEST_PARSE_REREQUEST_HOURS have passed rather than only once per process.
_parse_requested: dict[int, float] = {}


def _parse_rerequest_seconds() -> float:
    return float(os.getenv("INGEST_PARSE_REREQUEST_HOURS", "6")) * 3600


def _parse_request_due(match_id: int) -> bool:
    last = _parse_requested.get(match_id)
    return last is None or (time.time() - last) >= _parse_rerequest_seconds()

# OpenDota's parse request is billed as ten calls against the per-minute cap.
_PARSE_REQUEST_COST = 10


def _match_logo_url(val) -> str | None:
    if not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    if s.startswith("//"):
        s = "https:" + s
    if s.startswith("http://") or s.startswith("https://"):
        return s
    return None


# -----------------------
# API HELPERS
# -----------------------


def get_league_matches(league_id: int):
    url = f"{OPEN_DOTA_URL}/leagues/{league_id}/matchIds"
    return opendota_get_json(url, label=f"league {league_id} matchIds")


def get_league_info(league_id: int):
    url = f"{OPEN_DOTA_URL}/leagues/{league_id}"
    return opendota_get_json(url, label=f"league {league_id} info")


def get_live_match_league_ids() -> set[int]:
    """League IDs with a match currently in progress, per OpenDota's live endpoint.
    One request regardless of how many leagues are monitored."""
    data = opendota_get_json(f"{OPEN_DOTA_URL}/live", label="live matches") or []
    return {m.get("league_id") for m in data if m.get("league_id")}


# -----------------------
# INGESTION ENTRYPOINT
# -----------------------

def ingest_league(league_id: int):
    db = SessionLocal()
    try:
        league_data = get_league_info(league_id) or {}
        league_name = league_data.get("name", "unknown")

        logger.info("League: %s", league_name)

        league = db.get(League, league_id)
        if not league:
            league = League(id=league_id, name=league_name)
            db.add(league)
        else:
            league.name = league_name

        db.commit()

        match_ids = get_league_matches(league_id) or []
        logger.info("League %d: %d matches found", league_id, len(match_ids))

        # Pre-fetch already-ingested match IDs in one query
        existing = {
            row[0] for row in
            db.query(Match.match_id).filter(Match.match_id.in_(match_ids)).all()
        }

        weights = {w.key: w.value for w in db.query(Weight).all()}
        logger.info("Loaded %d weights", len(weights))

        seen_players = set()
        seen_teams = set()

        for match_id in match_ids:
            if match_id in existing:
                continue

            logger.info("Ingesting match %d", match_id)
            try:
                ingest_match(db, match_id, league_id, seen_players, seen_teams, weights)
            except Exception:
                logger.exception("Skipping match %d — ingestion failed", match_id)
    finally:
        db.close()

    try:
        ensure_dotabuff_league_logos()
    except Exception:
        logger.exception("Dotabuff league logo step failed")


# -----------------------
# MATCH INGESTION
# -----------------------

def ingest_match(db, match_id: int, league_id: int, seen_players: set, seen_teams: set, weights: dict):
    data = opendota_get_json(f"{OPEN_DOTA_URL}/matches/{match_id}", label=f"match {match_id}")
    if data is None:
        logger.warning("Skipping match %d — unavailable after retries", match_id)
        return

    duration = data.get("duration")
    if duration is not None and duration < 900:
        logger.info("Skipping match %d — too short (%ds)", match_id, duration)
        return

    radiant_team_id = data.get("radiant_team_id")
    dire_team_id = data.get("dire_team_id")
    radiant_name = data.get("radiant_name")
    dire_name = data.get("dire_name")
    radiant_logo = _match_logo_url(data.get("radiant_logo"))
    dire_logo = _match_logo_url(data.get("dire_logo"))

    logger.info("Match %d | %s vs %s", match_id, radiant_name, dire_name)

    for team_id, team_name, row_logo in (
        (radiant_team_id, radiant_name, radiant_logo),
        (dire_team_id, dire_name, dire_logo),
    ):
        if not team_id:
            continue
        team = db.get(Team, team_id)
        if not team:
            db.add(Team(id=team_id, name=team_name or str(team_id), logo_url=row_logo))
        else:
            if team_name and (not team.name or team.name == str(team_id)):
                team.name = team_name
            if row_logo and not team.logo_url:
                team.logo_url = row_logo
        seen_teams.add(team_id)

    match = Match(
        match_id=match_id,
        radiant_team_id=radiant_team_id,
        dire_team_id=dire_team_id,
        league_id=league_id,
        start_time=data.get("start_time"),
        radiant_win=data.get("radiant_win"),
        duration=duration,
    )
    db.add(match)

    raw_players = data.get("players", [])
    _ensure_players(db, raw_players, seen_players)

    for p in raw_players:
        stat = _build_stat_row(p, match_id, radiant_team_id, dire_team_id, weights)
        if stat is not None:
            db.add(stat)

    existing_bans = db.query(MatchBan).filter(MatchBan.match_id == match_id).count()
    if not existing_bans:
        for pb in data.get("picks_bans", []):
            if not pb.get("is_pick"):
                db.add(MatchBan(match_id=match_id, hero_id=pb.get("hero_id")))

    db.commit()

    _reapply_mvp_bonus(db, match_id)

    if _is_unparsed(data):
        request_parse(match_id)


def _ensure_players(db, raw_players: list, seen_players: set) -> None:
    """Insert Player rows missing for this match's account_ids (and backfill blank names).
    Pre-fetches which players already exist in one query to avoid N+1 lookups."""
    match_account_ids = [p.get("account_id") for p in raw_players if p.get("account_id") is not None]
    name_by_id = {p["account_id"]: p.get("personaname") for p in raw_players if p.get("account_id") is not None}
    new_account_ids = [aid for aid in match_account_ids if aid not in seen_players]
    if not new_account_ids:
        return
    existing_players = {
        row[0]: row[1] for row in
        db.query(Player.id, Player.name).filter(Player.id.in_(new_account_ids)).all()
    }
    for aid in new_account_ids:
        if aid not in existing_players:
            db.add(Player(id=aid, name=name_by_id.get(aid)))
        elif not existing_players[aid] and name_by_id.get(aid):
            db.query(Player).filter(Player.id == aid).update({"name": name_by_id[aid]})
        seen_players.add(aid)


def _build_stat_row(p: dict, match_id: int, radiant_team_id, dire_team_id, weights: dict):
    """Build one PlayerMatchStats row from an OpenDota player entry, or None if the entry
    has no account_id / side. Shared by first-pass ingest and the parse-retry refresh so
    both store identical rows."""
    account_id = p.get("account_id")
    if account_id is None:
        return None

    is_radiant = p.get("isRadiant")
    if is_radiant is None:
        player_slot = p.get("player_slot")
        if player_slot is None:
            return None
        is_radiant = player_slot < 128

    team_id = radiant_team_id if is_radiant else dire_team_id

    logger.debug("Player %d -> team %s", account_id, team_id)

    return PlayerMatchStats(
        player_id=account_id,
        match_id=match_id,
        team_id=team_id,
        kills=p.get("kills", 0),
        assists=p.get("assists", 0),
        deaths=p.get("deaths", 0),
        gold_per_min=p.get("gold_per_min", 0),
        obs_placed=p.get("obs_placed", 0),
        sen_placed=p.get("sen_placed", 0),
        tower_damage=p.get("tower_damage", 0),
        hero_id=p.get("hero_id"),
        last_hits=p.get("last_hits", 0),
        denies=p.get("denies", 0),
        towers_killed=p.get("towers_killed", 0),
        roshan_kills=p.get("roshan_kills", 0),
        teamfight_participation=float(p.get("teamfight_participation") or 0),
        camps_stacked=p.get("camps_stacked", 0),
        rune_pickups=p.get("rune_pickups", 0),
        firstblood_claimed=int(bool(p.get("firstblood_claimed"))),
        stuns=float(p.get("stuns") or 0),
        fantasy_points=fantasy_score(p, weights)
    )


def _reapply_mvp_bonus(db, match_id: int) -> None:
    """Re-apply the Twitch MVP flag + bonus to the freshly written stat row, if one was
    confirmed for this match. Commits on its own."""
    mvp = db.query(TwitchMVP).filter_by(match_id=match_id).first()
    if not mvp:
        return
    pms_row = db.query(PlayerMatchStats).filter_by(
        player_id=mvp.player_id, match_id=match_id
    ).first()
    if pms_row:
        mvp_weights = {w.key: w.value for w in db.query(Weight).all()}
        apply_mvp_bonus_to_row(pms_row, mvp_weights, apply=True)
        db.commit()
        logger.info("Ingest: applied MVP bonus to player %d match %d", mvp.player_id, match_id)


# -----------------------
# PARSE RETRY
# -----------------------
#
# OpenDota only fills teamfight_participation / stuns / obs_placed / camps_stacked /
# rune_pickups / towers_killed / roshan_kills / firstblood_claimed once it has parsed
# the replay, and reports "version": null on GET /matches/{id} until then. First-pass
# ingest stores whatever it gets so results show up immediately; the functions below
# re-check recent matches that still look unparsed and replace their rows once the
# parsed payload exists.

def _is_unparsed(data: dict) -> bool:
    return data.get("version") is None


def find_unparsed_match_ids(db, max_age_hours: int) -> list[int]:
    """Match IDs from the last `max_age_hours` whose stat rows sum to 0 on the three
    parse-only signature stats (teamfight_participation, stuns, obs_placed)."""
    if max_age_hours <= 0:
        return []
    cutoff = int(time.time()) - max_age_hours * 3600
    rows = (
        db.query(Match.match_id)
        .join(PlayerMatchStats, PlayerMatchStats.match_id == Match.match_id)
        .filter(Match.start_time >= cutoff)
        .group_by(Match.match_id)
        .having(func.coalesce(func.sum(PlayerMatchStats.teamfight_participation), 0) == 0)
        .having(func.coalesce(func.sum(PlayerMatchStats.stuns), 0) == 0)
        .having(func.coalesce(func.sum(PlayerMatchStats.obs_placed), 0) == 0)
        .order_by(Match.match_id)
        .all()
    )
    return [row[0] for row in rows]


def refresh_match_stats(db, match_id: int, weights: dict) -> str:
    """Re-fetch one match from OpenDota. Returns "refreshed" | "unparsed" | "unavailable".

    On "refreshed" the match's PlayerMatchStats rows are deleted and re-inserted from the
    fresh payload (fantasy_points recomputed with `weights`), duration / radiant_win are
    updated, and a confirmed Twitch MVP keeps its flag and bonus.
    """
    data = opendota_get_json(f"{OPEN_DOTA_URL}/matches/{match_id}", label=f"match {match_id} re-check")
    if data is None:
        return "unavailable"
    if _is_unparsed(data):
        return "unparsed"

    match = db.get(Match, match_id)
    if match is None:
        return "unavailable"

    radiant_team_id = data.get("radiant_team_id") or match.radiant_team_id
    dire_team_id = data.get("dire_team_id") or match.dire_team_id
    raw_players = data.get("players", [])
    _ensure_players(db, raw_players, set())

    # ORM-level delete + flush so the session drops the old rows from its identity map
    # before the replacements are inserted (SQLite reuses freed rowids).
    for old in db.query(PlayerMatchStats).filter(PlayerMatchStats.match_id == match_id).all():
        db.delete(old)
    db.flush()
    for p in raw_players:
        stat = _build_stat_row(p, match_id, radiant_team_id, dire_team_id, weights)
        if stat is not None:
            db.add(stat)

    if data.get("duration") is not None:
        match.duration = data["duration"]
    if data.get("radiant_win") is not None:
        match.radiant_win = data["radiant_win"]
    db.commit()

    _reapply_mvp_bonus(db, match_id)
    logger.info("Parse retry: refreshed match %d with parsed stats", match_id)
    return "refreshed"


def request_parse(match_id: int) -> bool:
    """Ask OpenDota to parse a match's replay (POST /request/{match_id}), at most once
    per INGEST_PARSE_REREQUEST_HOURS per match. Returns True when a request was submitted
    this call; a failed POST is logged and leaves the match eligible again next cycle."""
    if not _parse_request_due(match_id):
        return False
    result = opendota_post_json(
        f"{OPEN_DOTA_URL}/request/{match_id}",
        label=f"parse request {match_id}",
        cost=_PARSE_REQUEST_COST,
    )
    if result is None:
        logger.warning("Parse request for match %d failed — will retry next cycle", match_id)
        return False
    _parse_requested[match_id] = time.time()
    job = result.get("job") if isinstance(result.get("job"), dict) else {}
    logger.info("Parse requested for match %d (jobId=%s)", match_id, job.get("jobId"))
    return True


def retry_unparsed_matches(max_age_hours: int) -> dict:
    """Run one re-check pass over recent unparsed matches.

    Returns {"checked", "refreshed", "requested", "still_unparsed"}. A match that could
    not be re-fetched ("unavailable") counts as still unparsed — from the app's point of
    view it is — and is requested like any other unparsed match. A failure on one match
    is logged and does not stop the others. Caller holds INGEST_LOCK.
    """
    summary = {"checked": 0, "refreshed": 0, "requested": 0, "still_unparsed": 0}
    if max_age_hours <= 0:
        return summary
    db = SessionLocal()
    try:
        match_ids = find_unparsed_match_ids(db, max_age_hours)
        if not match_ids:
            return summary
        weights = {w.key: w.value for w in db.query(Weight).all()}
        for match_id in match_ids:
            summary["checked"] += 1
            try:
                outcome = refresh_match_stats(db, match_id, weights)
            except Exception:
                logger.exception("Parse retry: match %d re-check failed", match_id)
                db.rollback()
                continue
            if outcome == "refreshed":
                summary["refreshed"] += 1
                continue
            summary["still_unparsed"] += 1
            if _parse_request_due(match_id) and request_parse(match_id):
                summary["requested"] += 1
    finally:
        db.close()
    return summary
