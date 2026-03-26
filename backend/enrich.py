import requests
import time
from database import SessionLocal
from models import Player, Team

OPEN_DOTA_URL = "https://api.opendota.com/api"


# -----------------------
# PLAYER ENRICHMENT
# -----------------------

def enrich_players(batch_size=50):
    db = SessionLocal()

    players = (
        db.query(Player)
        .filter(
            Player.name.is_(None) | Player.avatar_url.is_(None)
        )
        .limit(batch_size)
        .all()
    )

    if not players:
        db.close()
        return 0

    print(f"[ENRICH] Players -> {len(players)}")

    for player in players:
        account_id = player.id

        try:
            res = requests.get(f"{OPEN_DOTA_URL}/players/{account_id}")

            if res.status_code == 429:
                print(f"[RATE LIMIT] Player {account_id}, skipping for retry")
                time.sleep(10)
                continue

            if res.status_code != 200:
                print(f"[WARN] Player {account_id} failed: {res.status_code}")
                player.name = str(account_id)
                continue

            data = res.json()
            profile = data.get("profile", {})

            name = (
                profile.get("personaname")
                or profile.get("name")
                or str(account_id)
            )

            avatar_url = profile.get("avatarfull")
            print(f"[PLAYER] {account_id} -> {name}")
            player.name = name
            player.avatar_url = avatar_url

        except Exception as e:
            print(f"[ERROR] Player {account_id}: {e}")
            player.name = str(account_id)

        time.sleep(0.2)

    db.commit()
    db.close()
    return len(players)


# -----------------------
# TEAM ENRICHMENT
# -----------------------

def enrich_teams(batch_size=50):
    db = SessionLocal()

    teams = (
        db.query(Team)
        .filter(Team.name.is_(None))
        .limit(batch_size)
        .all()
    )

    if not teams:
        db.close()
        return 0

    print(f"[ENRICH] Teams with missing name -> {len(teams)}")

    for team in teams:
        team.name = str(team.id)
        print(f"[WARN] Team {team.id} has no name, using ID as fallback")

    db.commit()
    db.close()
    return len(teams)


# -----------------------
# RUN
# -----------------------

def run_enrichment(max_rounds=20):
    for round in range(max_rounds):
        print(f"[ENRICH] Round {round + 1}")
        p = enrich_players()
        t = enrich_teams()

        if p == 0 and t == 0:
            print("[ENRICH] Done")
            return

    print(f"[ENRICH] Stopped after {max_rounds} rounds — some records may still have null names")


if __name__ == "__main__":
    run_enrichment()
