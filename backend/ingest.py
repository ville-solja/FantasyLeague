import requests
import time
from database import SessionLocal
from models import Match, Player, PlayerMatchStats
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


def get_player_name(account_id: int):
    """Fetch player name once (fallback safe)"""
    try:
        res = requests.get(f"{OPEN_DOTA_URL}/players/{account_id}")

        if res.status_code != 200:
            print(f"[WARN] Player API failed for {account_id}: {res.status_code}")
            name = str(account_id)
        else:
            player_data = res.json()
            profile = player_data.get("profile", {})
            return profile.get("personaname")
    except Exception:
        return str(account_id)


# -----------------------
# INGESTION ENTRYPOINT
# -----------------------

def ingest_league(league_id: int):
    db = SessionLocal()

    league = get_league_info(league_id)
    league_name = league.get("name", "unknown")

    matches = get_league_matches(league_id)
    print(f"[LEAGUE] {league_name} -> {len(matches)} matches")

    for match_id in matches:
        if db.get(Match, match_id):
            continue

        print(f"[MATCH] Ingesting {match_id}")
        ingest_match(db, match_id, league_name)

        time.sleep(0.5)  # rate limiting

    db.close()


# -----------------------
# MATCH INGESTION
# -----------------------

def ingest_match(db, match_id: int, league_name: str):
    res = requests.get(f"{OPEN_DOTA_URL}/matches/{match_id}")
    res.raise_for_status()
    data = res.json()

    # Skip short / invalid matches
    if data.get("duration", 0) < 900:
        print(f"[SKIP] Match {match_id} too short")
        return

    radiant_name = (
        (data.get("radiant_team") or {}).get("name")
        or data.get("radiant_name")
        or "unknown"
    )

    dire_name = (
        (data.get("dire_team") or {}).get("name")
        or data.get("dire_name")
        or "unknown"
    )

    print(f"[MATCH] {match_id} | {radiant_name} vs {dire_name}")

    # Insert match
    match = Match(
        match_id=match_id,
        radiant_team_name=radiant_name,
        dire_team_name=dire_name,
        league_name=league_name
    )
    db.add(match)
    db.commit()

    # Process players
    for p in data.get("players", []):
        account_id = p.get("account_id")
        if account_id is None:
            continue

        # Determine side
        is_radiant = p.get("isRadiant")
        if is_radiant is None:
            player_slot = p.get("player_slot")
            if player_slot is None:
                continue
            is_radiant = player_slot < 128

        team_name = radiant_name if is_radiant else dire_name

        print(f"[PLAYER] {account_id} -> {team_name}")

        # Upsert player
        player = db.get(Player, account_id)

        if not player:
            name = get_player_name(account_id)

            player = Player(
                id=account_id,
                name=name,
                team_name=team_name,
                division=league_name
            )
            db.add(player)
        else:
            # Update missing data only (no destructive overwrites)
            if not player.team_name:
                player.team_name = team_name

            if player.division == "unknown":
                player.division = league_name

            # Insert stats
            score = fantasy_score(p)

            stat = PlayerMatchStats(
                player_id=account_id,
                match_id=match_id,
                fantasy_points=score
            )
            db.add(stat)

    db.commit()


# -----------------------
# RUN
# -----------------------

if __name__ == "__main__":
    ingest_league(19369)