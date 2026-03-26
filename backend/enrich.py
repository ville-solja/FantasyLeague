import requests
import time
from sqlalchemy import text
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
        .filter(Player.name.is_(None))
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

            print(f"[PLAYER] {account_id} -> {name}")

            player.name = name

        except Exception as e:
            print(f"[ERROR] Player {account_id}: {e}")
            player.name = str(account_id)

        time.sleep(0.2)  # rate limit

    db.commit()
    db.close()


# -----------------------
# TEAM ENRICHMENT
# -----------------------

def enrich_teams(batch_size=50):
    db = SessionLocal()

    team_ids = db.execute(text("""
        SELECT DISTINCT pms.team_id
        FROM player_match_stats pms
        LEFT JOIN teams t ON t.id = pms.team_id
        WHERE pms.team_id IS NOT NULL
        AND t.id IS NULL
        LIMIT :limit
    """), {"limit": batch_size}).fetchall()

    if not team_ids:
        db.close()
        return 0

    team_ids = [row[0] for row in team_ids]

    print(f"[ENRICH] Teams -> {len(team_ids)}")

    for team_id in team_ids:
        try:
            res = requests.get(f"{OPEN_DOTA_URL}/teams/{team_id}")

            if res.status_code != 200:
                print(f"[WARN] Team {team_id} failed: {res.status_code}")
                continue

            data = res.json()
            name = data.get("name", "unknown")

            print(f"[TEAM] {team_id} -> {name}")

            team = Team(id=team_id, name=name)
            db.add(team)

        except Exception as e:
            print(f"[ERROR] Team {team_id}: {e}")

        time.sleep(0.3)

    db.commit()
    db.close()


# -----------------------
# RUN
# -----------------------

def run_enrichment():
    while True:
        p = enrich_players()
        t = enrich_teams()

        if p == 0 and t == 0:
            print("[ENRICH] Done")
            break


if __name__ == "__main__":
    run_enrichment()