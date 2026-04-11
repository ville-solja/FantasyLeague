import time

import requests
from database import SessionLocal
from models import Match, Player, PlayerMatchStats, League, Team, Weight
from opendota_client import OPEN_DOTA_URL, get as opendota_get
from scoring import fantasy_score
from dotabuff_league_logos import ensure_dotabuff_league_logos


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


def _get_json_with_retry(url: str, *, label: str, retries: int = 5, backoff: int = 15):
    """OpenDota league/list endpoints 429 often without api_key; retry with backoff."""
    for attempt in range(retries):
        res = opendota_get(url, timeout=30)
        if res.status_code == 429:
            wait = backoff * (attempt + 1)
            print(f"[RATE LIMIT] {label}, waiting {wait}s (set OPENDOTA_API_KEY to raise limits)")
            time.sleep(wait)
            continue
        if res.status_code >= 500:
            wait = backoff * (attempt + 1)
            print(f"[ERROR] {label} HTTP {res.status_code}, retry in {wait}s")
            time.sleep(wait)
            continue
        res.raise_for_status()
        return res.json()
    raise requests.HTTPError(f"429/5xx after {retries} retries: {label}")


def get_league_matches(league_id: int):
    url = f"{OPEN_DOTA_URL}/leagues/{league_id}/matchIds"
    return _get_json_with_retry(url, label=f"league {league_id} matchIds")


def get_league_info(league_id: int):
    url = f"{OPEN_DOTA_URL}/leagues/{league_id}"
    return _get_json_with_retry(url, label=f"league {league_id} info")


def fetch_match_with_retry(match_id: int, retries=3, backoff=5):
    for attempt in range(retries):
        res = opendota_get(f"{OPEN_DOTA_URL}/matches/{match_id}", timeout=30)
        if res.status_code == 429:
            wait = backoff * (attempt + 1)
            print(f"[RATE LIMIT] Match {match_id}, waiting {wait}s")
            time.sleep(wait)
            continue
        if res.status_code >= 500:
            wait = backoff * (attempt + 1)
            print(f"[ERROR] Match {match_id} got {res.status_code}, retrying in {wait}s")
            time.sleep(wait)
            continue
        res.raise_for_status()
        return res.json()
    return None


# -----------------------
# INGESTION ENTRYPOINT
# -----------------------

def ingest_league(league_id: int):
    db = SessionLocal()

    league_data = get_league_info(league_id)
    league_name = league_data.get("name", "unknown")

    print(f"[LEAGUE] {league_name}")

    league = db.get(League, league_id)
    if not league:
        league = League(id=league_id, name=league_name)
        db.add(league)
    else:
        league.name = league_name

    db.commit()

    match_ids = get_league_matches(league_id)
    print(f"[LEAGUE] {len(match_ids)} matches")

    # Pre-fetch already-ingested match IDs in one query
    existing = {
        row[0] for row in
        db.query(Match.match_id).filter(Match.match_id.in_(match_ids)).all()
    }

    weights = {w.key: w.value for w in db.query(Weight).all()}
    print(f"[INGEST] Loaded {len(weights)} weights")

    seen_players = set()
    seen_teams = set()

    for match_id in match_ids:
        if match_id in existing:
            continue

        print(f"[MATCH] Ingesting {match_id}")
        try:
            ingest_match(db, match_id, league_id, seen_players, seen_teams, weights)
        except Exception as e:
            print(f"[SKIP] Match {match_id} failed: {e}")

    db.close()
    try:
        ensure_dotabuff_league_logos()
    except Exception as e:
        print(f"[DOTABUFF] League logo step failed: {e}")


# -----------------------
# MATCH INGESTION
# -----------------------

def ingest_match(db, match_id: int, league_id: int, seen_players: set, seen_teams: set, weights: dict):
    data = fetch_match_with_retry(match_id)
    if data is None:
        print(f"[SKIP] Match {match_id} unavailable after retries")
        return

    if data.get("duration", 0) < 900:
        print(f"[SKIP] Match {match_id} too short")
        return

    radiant_team_id = data.get("radiant_team_id")
    dire_team_id = data.get("dire_team_id")
    radiant_name = data.get("radiant_name")
    dire_name = data.get("dire_name")
    radiant_logo = _match_logo_url(data.get("radiant_logo"))
    dire_logo = _match_logo_url(data.get("dire_logo"))

    print(f"[MATCH] {match_id} | {radiant_name} vs {dire_name}")

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

    for p in data.get("players", []):
        account_id = p.get("account_id")

        if account_id is None:
            continue

        if account_id not in seen_players:
            if not db.get(Player, account_id):
                db.add(Player(id=account_id, name=None))
            seen_players.add(account_id)

        is_radiant = p.get("isRadiant")
        if is_radiant is None:
            player_slot = p.get("player_slot")
            if player_slot is None:
                continue
            is_radiant = player_slot < 128

        team_id = radiant_team_id if is_radiant else dire_team_id

        print(f"[PLAYER] {account_id} -> {team_id}")

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
            fantasy_points=fantasy_score(p, weights)
        )
        db.add(stat)

    db.commit()
