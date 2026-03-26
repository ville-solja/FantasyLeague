import requests
import time
from database import SessionLocal
from models import Match, Player, PlayerMatchStats, League, Team
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


# -----------------------
# INGESTION ENTRYPOINT
# -----------------------

def ingest_league(league_id: int):
    db = SessionLocal()

    league_data = get_league_info(league_id)
    league_name = league_data.get("name", "unknown")

    print(f"[LEAGUE] {league_name}")

    # Upsert league
    league = db.get(League, league_id)
    if not league:
        league = League(id=league_id, name=league_name)
        db.add(league)
    else:
        league.name = league_name

    db.commit()

    matches = get_league_matches(league_id)
    print(f"[LEAGUE] {len(matches)} matches")

    for match_id in matches:
        if db.get(Match, match_id):
            continue

        print(f"[MATCH] Ingesting {match_id}")
        ingest_match(db, match_id, league_id)

        time.sleep(0.5)

    db.close()


# -----------------------
# MATCH INGESTION
# -----------------------

def ingest_match(db, match_id: int, league_id: int):
    res = requests.get(f"{OPEN_DOTA_URL}/matches/{match_id}")
    res.raise_for_status()
    data = res.json()

    if data.get("duration", 0) < 900:
        print(f"[SKIP] Match {match_id} too short")
        return

    # Correct extraction
    radiant_team_id = data.get("radiant_team_id")
    dire_team_id = data.get("dire_team_id")

    print(f"[MATCH] {match_id} | {radiant_team_id} vs {dire_team_id}")

    if radiant_team_id:
        if not db.get(Team, radiant_team_id):
            db.add(Team(id=radiant_team_id))

    if dire_team_id:
        if not db.get(Team, dire_team_id):
            db.add(Team(id=dire_team_id))

    # Insert match
    match = Match(
        match_id=match_id,
        radiant_team_id=radiant_team_id,
        dire_team_id=dire_team_id,
        league_id=league_id
    )
    db.add(match)

    seen_players = set()

    # Process players
    for p in data.get("players", []):
        account_id = p.get("account_id")

        if account_id is None:
            continue

        if account_id not in seen_players:
            player = db.get(Player, account_id)

            if not player:
                db.add(Player(id=account_id, name=None))

            seen_players.add(account_id)
                    
        # Determine team
        is_radiant = p.get("isRadiant")
        if is_radiant is None:
            player_slot = p.get("player_slot")
            if player_slot is None:
                continue
            is_radiant = player_slot < 128

        team_id = radiant_team_id if is_radiant else dire_team_id

        print(f"[PLAYER] {account_id} -> {team_id}")

        # Insert stats
        score = fantasy_score(p)

        stat = PlayerMatchStats(
            player_id=account_id,
            match_id=match_id,
            team_id=team_id,
            fantasy_points=score
        )
        db.add(stat)

    db.commit()