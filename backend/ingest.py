import requests
import time
from database import SessionLocal
from models import Match, Player, PlayerMatchStats, League, Team, Weight
from scoring import fantasy_score

OPEN_DOTA_URL = "https://api.opendota.com/api"


# -----------------------
# API HELPERS
# -----------------------

def get_league_matches(league_id: int):
    url = f"{OPEN_DOTA_URL}/leagues/{league_id}/matchIds"
    res = requests.get(url)
    res.raise_for_status()
    return res.json()


def get_league_info(league_id: int):
    url = f"{OPEN_DOTA_URL}/leagues/{league_id}"
    res = requests.get(url)
    res.raise_for_status()
    return res.json()


def fetch_match_with_retry(match_id: int, retries=3, backoff=5):
    for attempt in range(retries):
        res = requests.get(f"{OPEN_DOTA_URL}/matches/{match_id}")
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

        time.sleep(0.5)

    db.close()


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

    print(f"[MATCH] {match_id} | {radiant_name} vs {dire_name}")

    for team_id, team_name in ((radiant_team_id, radiant_name), (dire_team_id, dire_name)):
        if team_id and team_id not in seen_teams:
            if not db.get(Team, team_id):
                db.add(Team(id=team_id, name=team_name))
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
