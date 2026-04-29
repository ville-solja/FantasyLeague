import logging

from database import SessionLocal
from models import Match, Player, PlayerMatchStats, League, Team, Weight, MatchBan
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json
from scoring import fantasy_score
from dotabuff_league_logos import ensure_dotabuff_league_logos

logger = logging.getLogger(__name__)


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


# -----------------------
# INGESTION ENTRYPOINT
# -----------------------

def ingest_league(league_id: int):
    db = SessionLocal()
    try:
        league_data = get_league_info(league_id)
        league_name = league_data.get("name", "unknown")

        logger.info("League: %s", league_name)

        league = db.get(League, league_id)
        if not league:
            league = League(id=league_id, name=league_name)
            db.add(league)
        else:
            league.name = league_name

        db.commit()

        match_ids = get_league_matches(league_id)
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

    if data.get("duration", 0) < 900:
        logger.info("Skipping match %d — too short (%ds)", match_id, data.get("duration", 0))
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
    )
    db.add(match)

    # Pre-fetch which players are already in the DB to avoid N+1 lookups
    raw_players = data.get("players", [])
    match_account_ids = [p.get("account_id") for p in raw_players if p.get("account_id") is not None]
    name_by_id = {p["account_id"]: p.get("personaname") for p in raw_players if p.get("account_id") is not None}
    new_account_ids = [aid for aid in match_account_ids if aid not in seen_players]
    if new_account_ids:
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

    for p in raw_players:
        account_id = p.get("account_id")
        if account_id is None:
            continue

        is_radiant = p.get("isRadiant")
        if is_radiant is None:
            player_slot = p.get("player_slot")
            if player_slot is None:
                continue
            is_radiant = player_slot < 128

        team_id = radiant_team_id if is_radiant else dire_team_id

        logger.debug("Player %d -> team %s", account_id, team_id)

        stat = PlayerMatchStats(
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
        db.add(stat)

    existing_bans = db.query(MatchBan).filter(MatchBan.match_id == match_id).count()
    if not existing_bans:
        for pb in data.get("picks_bans", []):
            if not pb.get("is_pick"):
                db.add(MatchBan(match_id=match_id, hero_id=pb.get("hero_id")))

    db.commit()
