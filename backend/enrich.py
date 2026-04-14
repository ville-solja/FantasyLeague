from database import SessionLocal
from models import Player
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json


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
            data = opendota_get_json(
                f"{OPEN_DOTA_URL}/players/{account_id}",
                label=f"player {account_id}",
            )
            if not data:
                player.name = str(account_id)
                continue
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

    db.commit()
    db.close()
    return len(players)


# -----------------------
# RUN
# -----------------------

def run_enrichment(max_rounds=20):
    for round in range(max_rounds):
        print(f"[ENRICH] Round {round + 1}")
        p = enrich_players()

        if p == 0:
            print("[ENRICH] Done")
            return

    print(f"[ENRICH] Stopped after {max_rounds} rounds — some records may still have null names")


if __name__ == "__main__":
    run_enrichment()
