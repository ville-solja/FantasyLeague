import json
import logging
import os
import time

from sqlalchemy import text, func

from database import SessionLocal
from models import Player, PlayerMatchStats, MatchBan, PlayerProfile
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json

logger = logging.getLogger(__name__)

_COOLDOWN_HOURS = float(os.getenv("PROFILE_ENRICHMENT_COOLDOWN_HOURS", "24"))
_BATCH_SIZE     = int(os.getenv("ENRICHMENT_BATCH_SIZE", "3"))


# -----------------------
# PLAYER ENRICHMENT (name/avatar)
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

    logger.info("Enrich: processing %d players", len(players))

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
            logger.info("Enrich: player %d -> %s", account_id, name)
            player.name = name
            player.avatar_url = avatar_url

        except Exception as e:
            logger.error("Enrich: player %d error: %s", account_id, e)
            player.name = str(account_id)

    db.commit()
    db.close()
    return len(players)


def run_enrichment(max_rounds=20):
    for round in range(max_rounds):
        logger.info("Enrich: round %d", round + 1)
        p = enrich_players()

        if p == 0:
            logger.info("Enrich: done")
            return

    logger.warning("Enrich: stopped after %d rounds — some records may still have null names", max_rounds)


# -----------------------
# PROFILE ENRICHMENT (hero stats, bans, bio)
# -----------------------

def _fetch_hero_name_map() -> dict:
    data = opendota_get_json(f"{OPEN_DOTA_URL}/constants/heroes", label="constants/heroes")
    if not data or not isinstance(data, dict):
        return {}
    result = {}
    for hero_id_str, info in data.items():
        if hero_id_str.lstrip("-").isdigit():
            result[int(hero_id_str)] = info.get("localized_name", hero_id_str)
    return result


def crawl_player_facts(player_id: int, hero_name_map: dict, db) -> dict | None:
    agg = db.execute(text("""
        SELECT
            COUNT(DISTINCT s.match_id)               as kanaliiga_matches,
            COUNT(DISTINCT m.league_id)              as kanaliiga_seasons,
            AVG(s.fantasy_points)                    as avg_fantasy_points,
            AVG(s.kills)                             as avg_kills,
            AVG(s.assists)                           as avg_assists,
            AVG(s.deaths)                            as avg_deaths,
            AVG(s.gold_per_min)                      as avg_gpm,
            AVG(s.obs_placed + s.sen_placed)         as avg_wards,
            MAX(s.fantasy_points)                    as best_match_points
        FROM player_match_stats s
        LEFT JOIN matches m ON m.match_id = s.match_id
        WHERE s.player_id = :pid
    """), {"pid": player_id}).first()

    if not agg or not agg.kanaliiga_matches:
        return None

    avg_wards = round(float(agg.avg_wards or 0), 2)
    avg_gpm   = round(float(agg.avg_gpm or 0), 2)
    role      = "support" if avg_wards >= 3 and avg_gpm < 450 else "core"
    total_matches = int(agg.kanaliiga_matches)

    t_hero_rows = db.execute(text("""
        SELECT hero_id, COUNT(*) as games
        FROM player_match_stats
        WHERE player_id = :pid AND hero_id IS NOT NULL
        GROUP BY hero_id ORDER BY games DESC
    """), {"pid": player_id}).fetchall()

    tournament_heroes = [
        {"hero_name": hero_name_map.get(r.hero_id, str(r.hero_id)), "games": r.games}
        for r in t_hero_rows
    ]

    match_id_rows = db.execute(text("""
        SELECT DISTINCT match_id FROM player_match_stats WHERE player_id = :pid
    """), {"pid": player_id}).fetchall()
    match_ids = [r.match_id for r in match_id_rows]

    ban_by_hero: dict[int, int] = {}
    if match_ids:
        ban_rows = (
            db.query(MatchBan.hero_id, func.count().label("cnt"))
            .filter(MatchBan.match_id.in_(match_ids))
            .group_by(MatchBan.hero_id)
            .all()
        )
        ban_by_hero = {r.hero_id: r.cnt for r in ban_rows}

    # Career hero pool from OpenDota
    career_data = opendota_get_json(
        f"{OPEN_DOTA_URL}/players/{player_id}/heroes",
        label=f"player {player_id} heroes",
    ) or []

    top_heroes_alltime = []
    if isinstance(career_data, list):
        for h in sorted(career_data, key=lambda x: x.get("games", 0), reverse=True):
            hero_id = h.get("hero_id")
            if not hero_id:
                continue
            games = h.get("games", 0)
            win   = h.get("win", 0)
            top_heroes_alltime.append({
                "hero_name": hero_name_map.get(int(hero_id), str(hero_id)),
                "games":     games,
                "win_rate":  round(win / games, 2) if games else 0.0,
            })

    # Recent pub heroes (last 100 matches)
    time.sleep(0.5)
    recent_data = opendota_get_json(
        f"{OPEN_DOTA_URL}/players/{player_id}/matches?limit=100&project=hero_id",
        label=f"player {player_id} recent matches",
    ) or []

    recent_hero_counts: dict[int, int] = {}
    if isinstance(recent_data, list):
        for m in recent_data:
            hid = m.get("hero_id")
            if hid:
                recent_hero_counts[int(hid)] = recent_hero_counts.get(int(hid), 0) + 1

    recent_pub_heroes = [
        {"hero_name": hero_name_map.get(hid, str(hid)), "games": cnt}
        for hid, cnt in sorted(recent_hero_counts.items(), key=lambda x: x[1], reverse=True)
    ]

    # Ban correlations: career heroes that also appear in tournament match bans
    ban_correlations = []
    for h in top_heroes_alltime:
        hero_name = h["hero_name"]
        # Find the hero_id for this hero via reverse lookup
        hero_id_int = None
        for hid, hname in hero_name_map.items():
            if hname == hero_name:
                hero_id_int = hid
                break
        if hero_id_int is None:
            continue
        banned_in = ban_by_hero.get(hero_id_int, 0)
        if banned_in == 0:
            continue
        ban_correlations.append({
            "hero_name":              hero_name,
            "pub_games":              h["games"],
            "tournament_match_count": total_matches,
            "banned_in":              banned_in,
            "ban_rate":               round(banned_in / total_matches, 2),
        })
    ban_correlations.sort(key=lambda x: x["ban_rate"], reverse=True)

    return {
        "kanaliiga_matches":   total_matches,
        "kanaliiga_seasons":   int(agg.kanaliiga_seasons),
        "avg_fantasy_points":  round(float(agg.avg_fantasy_points or 0), 2),
        "avg_kills":           round(float(agg.avg_kills or 0), 2),
        "avg_assists":         round(float(agg.avg_assists or 0), 2),
        "avg_deaths":          round(float(agg.avg_deaths or 0), 2),
        "avg_gpm":             avg_gpm,
        "avg_wards":           avg_wards,
        "best_match_points":   round(float(agg.best_match_points or 0), 2),
        "role_tendency":       role,
        "top_heroes_alltime":  top_heroes_alltime,
        "tournament_heroes":   tournament_heroes,
        "recent_pub_heroes":   recent_pub_heroes,
        "ban_correlations":    ban_correlations,
    }


def generate_player_bio(player_name: str, facts: dict) -> str | None:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — skipping bio generation")
        return None

    top_heroes = facts.get("top_heroes_alltime", [])[:5]
    t_heroes   = facts.get("tournament_heroes", [])[:3]
    r_heroes   = facts.get("recent_pub_heroes", [])[:3]
    bans       = facts.get("ban_correlations", [])[:3]

    top_hero_str = ", ".join(
        f"{h['hero_name']} ({h['games']}g, {int(h['win_rate']*100)}%wr)" for h in top_heroes
    ) or "none recorded"
    t_hero_str = ", ".join(f"{h['hero_name']} ({h['games']}g)" for h in t_heroes) or "none recorded"
    r_hero_str = ", ".join(f"{h['hero_name']} ({h['games']}g)" for h in r_heroes) or "none recorded"
    ban_str    = ", ".join(
        f"{b['hero_name']} (banned in {int(b['ban_rate']*100)}% of tournament games)" for b in bans
    ) or "none notable"

    prompt = (
        f"Write a 2–4 sentence player bio for {player_name}, a Dota 2 player in the Kanaliiga tournament. "
        f"Stats: {facts['kanaliiga_matches']} tournament matches across {facts['kanaliiga_seasons']} seasons, "
        f"avg {facts['avg_fantasy_points']} fantasy points, "
        f"{facts['avg_kills']:.1f}/{facts['avg_deaths']:.1f}/{facts['avg_assists']:.1f} K/D/A, "
        f"{facts['avg_gpm']} GPM, {facts['avg_wards']} wards/match. Role tendency: {facts['role_tendency']}. "
        f"Top career heroes: {top_hero_str}. "
        f"Tournament heroes: {t_hero_str}. "
        f"Recent pub heroes: {r_hero_str}. "
        f"Ban correlations (heroes targeted by opponents in tournament): {ban_str}. "
        f"Be analytical and specific. Do not use markdown or bullet points."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.warning("Bio generation failed for %s: %s", player_name, e)
        return None


def run_profile_enrichment(batch_size: int | None = None) -> dict:
    if batch_size is None:
        batch_size = _BATCH_SIZE

    db = SessionLocal()
    enriched = skipped = errors = 0

    try:
        hero_name_map = _fetch_hero_name_map()

        cooldown_secs = int(_COOLDOWN_HOURS * 3600)
        cutoff = int(time.time()) - cooldown_secs

        rows = db.execute(text("""
            SELECT DISTINCT p.id FROM players p
            JOIN player_match_stats s ON s.player_id = p.id
            LEFT JOIN player_profiles pp ON pp.player_id = p.id
            WHERE pp.player_id IS NULL
               OR pp.facts_fetched_at IS NULL
               OR pp.facts_fetched_at < :cutoff
            LIMIT :limit
        """), {"cutoff": cutoff, "limit": batch_size}).fetchall()

        player_ids = [r.id for r in rows]

        if not player_ids:
            return {"enriched": 0, "skipped": 0, "errors": 0}

        for player_id in player_ids:
            player = db.get(Player, player_id)
            if not player:
                skipped += 1
                continue

            try:
                facts = crawl_player_facts(player_id, hero_name_map, db)
                if facts is None:
                    skipped += 1
                    continue

                now = int(time.time())
                profile = db.get(PlayerProfile, player_id)
                if not profile:
                    profile = PlayerProfile(player_id=player_id)
                    db.add(profile)

                profile.facts_json       = json.dumps(facts)
                profile.facts_fetched_at = now

                bio = generate_player_bio(player.name or str(player_id), facts)
                if bio is not None:
                    profile.bio_text         = bio
                    profile.bio_generated_at = now

                db.commit()
                enriched += 1
                logger.info("Enriched player %d (%s)", player_id, player.name)

                time.sleep(0.5)

            except Exception:
                logger.exception("Profile enrichment failed for player %d", player_id)
                db.rollback()
                errors += 1
    finally:
        db.close()

    return {"enriched": enriched, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    run_enrichment()
