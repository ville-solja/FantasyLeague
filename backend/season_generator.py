"""Pure, seeded season generator (issue #145).

`generate()` returns a synthetic league as plain dicts: teams, players, weeks, matches
with per-player stats, and users with their cards. It touches no database, so the
season scenarios (`scenarios.py`), `scripts/bench_leaderboards.py` and the mock
OpenDota (#146) build the same league from the same seed. Only the scoring constants
are imported.

The random draws happen in the order `bench_leaderboards.seed()` used before the move,
so the benchmark keeps its counts and totals for the same arguments. Everything added
after that (hero ids, series times, MVP gaps, the sit-out, unparsed and excluded
matches) is derived without further draws.
"""

import random

from card_utils import _SCORED_STAT_COLS
from scoring import SCORING_STATS

DAY = 86400
WEEK = 7 * DAY
# Seconds between the games of one series: well inside schedule.SERIES_GAP_SECONDS (6 h).
GAME_GAP_SECONDS = 3000
GAME_DURATION = 2400
FIRST_PLAYER_ID = 1001
FIRST_MATCH_ID = 8_000_000_001

RARITIES = ["common"] * 60 + ["rare"] * 25 + ["epic"] * 10 + ["legendary"] * 5
MODIFIER_COUNT = {"common": 0, "rare": 1, "epic": 2, "legendary": 3}
MODIFIER_BONUS_PCT = 10.0
# Stats an unparsed match still has (OpenDota gives them without a replay parse).
UNPARSED_STATS = ("kills", "deaths", "assists", "last_hits", "denies", "gold_per_min")

_FIRST = ("Ash", "Bram", "Cael", "Dax", "Eko", "Fen", "Gry", "Hol", "Ivo", "Jun")
_LAST = ("vane", "mire", "lock", "ward", "fall", "rook", "spire", "thorn")


def team_name(index: int) -> str:
    return f"Scenario Team {chr(65 + index)}" if index < 26 else f"Scenario Team {index + 1}"


def player_name(n: int) -> str:
    """A synthetic handle for the n-th player (0-based); never a real player's name."""
    return f"{_FIRST[n % len(_FIRST)]}{_LAST[(n // len(_FIRST)) % len(_LAST)]}{n // 80 or ''}"


def _hero_id(match_id: int, player_id: int) -> int:
    return 1 + (match_id * 31 + player_id) % 120


def generate(seed, *, weeks: int, teams: int, players_per_team: int,
             games_per_team_week: int, users: int, cards_per_user, roster_size: int,
             start: int, window_days: int = 7, mvp_skip_every: int | None = None,
             sit_out_week: int | None = None, special_week: int | None = None,
             unparsed: int = 0, excluded: int = 0) -> dict:
    """Generate a season.

    seed: an int, or a `random.Random` to draw from (the benchmark passes its own).
    weeks start every 7 days from `start`; each week's match window is `window_days`
    long (7 = back to back). cards_per_user: an int, or one count per user.
    mvp_skip_every: every n-th match (1-based) has no MVP. sit_out_week: in that week
    (1-based) the player of the first active card of users[1] plays no game (a bench
    substitution). Users are 0-based: in the scenarios, users[0] is scenario-admin and
    users[1] is scenario1. special_week: its last `unparsed + excluded` matches are unparsed
    (partial stats) and excluded from scoring, in that order.
    """
    rng = seed if isinstance(seed, random.Random) else random.Random(seed)
    window = window_days * DAY

    team_ids = list(range(1, teams + 1))
    team_rows = [{"id": t, "name": team_name(t - 1)} for t in team_ids]
    players_by_team: dict[int, list[int]] = {}
    player_rows = []
    pid = FIRST_PLAYER_ID - 1
    for t in team_ids:
        players_by_team[t] = []
        for _ in range(players_per_team):
            pid += 1
            player_rows.append({"id": pid, "name": player_name(pid - FIRST_PLAYER_ID), "team_id": t})
            players_by_team[t].append(pid)
    all_players = [p for ps in players_by_team.values() for p in ps]

    week_rows = [{"number": w + 1, "label": f"Week {w + 1}", "start_time": start + w * WEEK,
                  "end_time": start + w * WEEK + window - 1} for w in range(weeks)]

    match_rows = []
    match_id = FIRST_MATCH_ID - 1
    for wk in week_rows:
        # Pair teams up; each pair plays games_per_team_week games (one series) this week.
        order = team_ids[:]
        rng.shuffle(order)
        for a, b in zip(order[::2], order[1::2]):
            series_start = None
            for g in range(games_per_team_week):
                match_id += 1
                t0 = wk["start_time"] + rng.randint(3600, window - 7200)
                series_start = t0 if series_start is None else series_start
                radiant_win = rng.random() < 0.5
                mvp = rng.choice(players_by_team[a] + players_by_team[b])
                stats = []
                for team in (a, b):
                    for p in players_by_team[team]:
                        row = {s: 0 for s in SCORING_STATS}
                        row.update(
                            kills=rng.randint(0, 15), assists=rng.randint(0, 20),
                            deaths=rng.randint(0, 14), last_hits=rng.randint(10, 400),
                            denies=rng.randint(0, 25), gold_per_min=rng.randint(250, 750),
                            obs_placed=rng.randint(0, 20), towers_killed=rng.randint(0, 4),
                            roshan_kills=rng.randint(0, 2),
                            teamfight_participation=round(rng.random(), 2),
                            camps_stacked=rng.randint(0, 10), rune_pickups=rng.randint(0, 12),
                            firstblood_claimed=int(rng.random() < 0.1),
                            stuns=round(rng.random() * 60, 1),
                        )
                        row.update(player_id=p, team_id=team, hero_id=_hero_id(match_id, p),
                                   is_mvp=p == mvp)
                        stats.append(row)
                match_rows.append({
                    "match_id": match_id, "week": wk["number"],
                    "series_id": f"w{wk['number']}-{min(a, b)}-{max(a, b)}",
                    "radiant_team_id": a, "dire_team_id": b,
                    "radiant_name": team_name(a - 1), "dire_name": team_name(b - 1),
                    "start_time": series_start + g * GAME_GAP_SECONDS,
                    "radiant_win": radiant_win, "duration": GAME_DURATION,
                    "parse_status": "parsed", "excluded_from_scoring": False, "stats": stats,
                })

    stat_keys = list(_SCORED_STAT_COLS)  # the modifier pool: no courier_kills (issue 134)
    user_rows = []
    for u in range(users):
        n_cards = cards_per_user if isinstance(cards_per_user, int) else cards_per_user[u]
        owned = rng.sample(all_players, min(n_cards, len(all_players)))
        cards = []
        for i, p in enumerate(owned):
            ctype = rng.choice(RARITIES)
            mods = rng.sample(stat_keys, MODIFIER_COUNT[ctype])
            cards.append({"player_id": p, "card_type": ctype, "is_active": i < roster_size,
                          "slot_index": i if i < roster_size else None,
                          "modifiers": [{"stat_key": k, "bonus_pct": MODIFIER_BONUS_PCT} for k in mods]})
        # A random roster per week: the benchmark writes these as its roster snapshots.
        weekly_rosters = [rng.sample(range(len(cards)), min(roster_size, len(cards)))
                          for _ in week_rows]
        user_rows.append({"index": u, "cards": cards, "weekly_rosters": weekly_rosters})

    _shape(match_rows, user_rows, mvp_skip_every, sit_out_week, special_week, unparsed, excluded)
    return {"teams": team_rows, "players": player_rows, "weeks": week_rows,
            "matches": match_rows, "users": user_rows}


def _shape(matches, users, mvp_skip_every, sit_out_week, special_week, unparsed, excluded):
    """The scenario touches, applied after every draw so they never shift the stream."""
    if mvp_skip_every:
        for n, m in enumerate(matches, start=1):
            if n % mvp_skip_every == 0:
                for s in m["stats"]:
                    s["is_mvp"] = False
    if sit_out_week and len(users) > 1 and users[1]["cards"]:
        absent = users[1]["cards"][0]["player_id"]
        for m in matches:
            if m["week"] == sit_out_week:
                m["stats"] = [s for s in m["stats"] if s["player_id"] != absent]
    if special_week and (unparsed or excluded):
        in_week = [m for m in matches if m["week"] == special_week]
        chosen = in_week[len(in_week) - unparsed - excluded:]
        for m in chosen[:unparsed]:
            m["parse_status"] = "unparsed"
            for s in m["stats"]:
                for k in SCORING_STATS:
                    if k not in UNPARSED_STATS:
                        s[k] = 0
        for m in chosen[unparsed:]:
            m["excluded_from_scoring"] = True
