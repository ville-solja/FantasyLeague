"""Dota 2 rank medal from OpenDota's GET /players/{account_id} (issue #221).

`rank_tier` is two digits: the tens digit is the medal, the ones digit the stars
(1-5; 0 for Immortal). `leaderboard_rank` is the Immortal leaderboard place.
"""

MEDALS = {1: "Herald", 2: "Guardian", 3: "Crusader", 4: "Archon",
          5: "Legend", 6: "Ancient", 7: "Divine", 8: "Immortal"}


def parse_rank(data: dict) -> tuple[int | None, int | None]:
    """(rank_tier, leaderboard_rank) from a player response; invalid values are None."""
    data = data or {}
    tier = data.get("rank_tier")
    if (not isinstance(tier, int) or isinstance(tier, bool)
            or not (10 <= tier <= 80) or tier // 10 not in MEDALS):
        tier = None
    lb = data.get("leaderboard_rank")
    lb = lb if isinstance(lb, int) and not isinstance(lb, bool) and lb > 0 and tier == 80 else None
    return tier, lb


def medal_name(tier, lb=None) -> str | None:
    """"Legend 4", "Immortal" or "Immortal #123"; None for no rank."""
    if tier is None:
        return None
    medal, stars = MEDALS[tier // 10], tier % 10
    if medal == "Immortal":
        return f"Immortal #{lb}" if lb else "Immortal"
    return f"{medal} {stars}" if 1 <= stars <= 5 else medal


def apply_rank(player, data: dict, now: int) -> None:
    """Store the parsed rank on a Player row and stamp rank_fetched_at."""
    player.rank_tier, player.leaderboard_rank = parse_rank(data)
    player.rank_fetched_at = now
