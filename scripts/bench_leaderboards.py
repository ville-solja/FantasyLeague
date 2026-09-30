"""Benchmark the leaderboard and roster scoring paths on a synthetic season.

Seeds a throwaway SQLite database (never the real data/fantasy.db) with a
deterministic league, then times the server functions behind:

  GET /leaderboard/weekly   -> routers.leaderboard.weekly_leaderboard
  GET /leaderboard/season   -> routers.leaderboard.compute_season_standings
  GET /roster/{user_id}     -> routers.cards._build_roster_response

Usage (from the repo root):
    python3 scripts/bench_leaderboards.py                    # default size, print results
    python3 scripts/bench_leaderboards.py --save baseline.json
    python3 scripts/bench_leaderboards.py --compare scripts/bench-leaderboards-baseline.json

The committed baseline (scripts/bench-leaderboards-baseline.json) was taken
before issue #141 (stored per-match card points); compare against it after
that change lands. Totals are expected to differ slightly after #141 because
the death bonus becomes per match; timings and query counts are the check.
"""

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

_TMP = tempfile.mkdtemp(prefix="bench-lb-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/bench.db"
os.environ.setdefault("BACKGROUND_TASKS_ENABLED", "false")

from sqlalchemy import event  # noqa: E402

import database  # noqa: E402
import models  # noqa: E402,F401  (registers tables)
from database import Base, SessionLocal, engine  # noqa: E402
from models import (Card, CardModifier, League, Match, Player, PlayerMatchStats,  # noqa: E402
                    Team, User, Week, WeeklyRosterEntry)
from scoring import SCORING_STATS  # noqa: E402


def seed(users: int, weeks: int, teams: int, players_per_team: int, games_per_team_week: int,
         cards_per_user: int, roster_size: int, rng: random.Random) -> dict:
    from seed import seed_weights
    Base.metadata.create_all(engine)
    try:
        from migrate import run_migrations
        run_migrations(engine)
    except Exception:
        pass
    seed_weights()

    db = SessionLocal()
    try:
        db.add(League(id=1, name="Bench League", is_monitored=True))
        team_ids = list(range(1, teams + 1))
        for t in team_ids:
            db.add(Team(id=t, name=f"Team {t}"))
        players_by_team = {}
        pid = 1000
        for t in team_ids:
            players_by_team[t] = []
            for _ in range(players_per_team):
                pid += 1
                db.add(Player(id=pid, name=f"Player {pid}", is_active=True))
                players_by_team[t].append(pid)
        all_players = [p for ps in players_by_team.values() for p in ps]

        week_len = 7 * 86400
        start0 = 1_700_000_000
        week_rows = []
        for w in range(weeks):
            wk = Week(label=f"Week {w + 1}", start_time=start0 + w * week_len,
                      end_time=start0 + (w + 1) * week_len - 1, is_locked=True)
            db.add(wk)
            week_rows.append(wk)
        db.flush()

        match_id = 8_000_000_000
        stat_count = 0
        for wk in week_rows:
            # Pair teams up; each pair plays games_per_team_week games this week.
            order = team_ids[:]
            rng.shuffle(order)
            for a, b in zip(order[::2], order[1::2]):
                for g in range(games_per_team_week):
                    match_id += 1
                    t0 = wk.start_time + rng.randint(3600, week_len - 7200)
                    db.add(Match(match_id=match_id, radiant_team_id=a, dire_team_id=b, league_id=1,
                                 start_time=t0, radiant_win=rng.random() < 0.5, duration=2400,
                                 parse_status="parsed"))
                    mvp = rng.choice(players_by_team[a] + players_by_team[b])
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
                            db.add(PlayerMatchStats(player_id=p, match_id=match_id, team_id=team,
                                                    fantasy_points=0.0, is_mvp=(p == mvp),
                                                    **{k: v for k, v in row.items()
                                                       if hasattr(PlayerMatchStats, k)}))
                            stat_count += 1
        db.flush()

        rarities = ["common"] * 60 + ["rare"] * 25 + ["epic"] * 10 + ["legendary"] * 5
        mod_count = {"common": 0, "rare": 1, "epic": 2, "legendary": 3}
        stat_keys = list(SCORING_STATS) + ["deaths"]
        card_total = 0
        roster_total = 0
        for u in range(users):
            user = User(username=f"bench{u}", email=f"bench{u}@example.invalid",
                        password_hash="x", is_admin=False, is_tester=False, tokens=5,
                        created_at=start0)
            db.add(user)
            db.flush()
            owned = rng.sample(all_players, min(cards_per_user, len(all_players)))
            cards = []
            for i, p in enumerate(owned):
                ctype = rng.choice(rarities)
                c = Card(player_id=p, owner_id=user.id, card_type=ctype, league_id=1,
                         is_active=i < roster_size, slot_index=i if i < roster_size else None)
                db.add(c)
                db.flush()
                for sk in rng.sample(stat_keys, mod_count[ctype]):
                    db.add(CardModifier(card_id=c.id, stat_key=sk, bonus_pct=10.0))
                cards.append(c)
                card_total += 1
            for wk in week_rows:
                for c in rng.sample(cards, min(roster_size, len(cards))):
                    db.add(WeeklyRosterEntry(week_id=wk.id, user_id=user.id, card_id=c.id))
                    roster_total += 1
        db.commit()
        # Build stored per-match card points (issue #141) the way ingest would have.
        import card_points
        card_points.rebuild_all(db)
        return {"weeks": [w.id for w in week_rows], "players": len(all_players),
                "matches": match_id - 8_000_000_000, "stat_rows": stat_count,
                "cards": card_total, "roster_entries": roster_total,
                "first_user_id": db.query(User.id).order_by(User.id).first()[0]}
    finally:
        db.close()


_query_count = 0


def _count(*_a, **_k):
    global _query_count
    _query_count += 1


def timed(fn, runs: int) -> dict:
    global _query_count
    fn()  # warm-up
    times, queries = [], []
    for _ in range(runs):
        _query_count = 0
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
        queries.append(_query_count)
    times.sort()
    return {"median_ms": round(statistics.median(times), 2),
            "p95_ms": round(times[max(0, int(len(times) * 0.95) - 1)], 2),
            "queries": max(queries)}


def run(args) -> dict:
    rng = random.Random(args.seed)
    info = seed(args.users, args.weeks, args.teams, args.players_per_team, args.games,
                args.cards, args.roster, rng)
    event.listen(engine, "before_cursor_execute", _count)

    from routers.leaderboard import compute_season_standings, weekly_leaderboard
    from routers.cards import _build_roster_response

    last_week = info["weeks"][-1]
    uid = info["first_user_id"]

    def weekly():
        db = SessionLocal()
        try:
            return weekly_leaderboard(last_week, db=db)
        finally:
            db.close()

    def season():
        db = SessionLocal()
        try:
            return compute_season_standings(db)
        finally:
            db.close()

    def roster():
        db = SessionLocal()
        try:
            return _build_roster_response(db, uid, last_week)
        finally:
            db.close()

    results = {
        "weekly_leaderboard": timed(weekly, args.runs),
        "season_leaderboard": timed(season, args.runs),
        "roster_one_user": timed(roster, args.runs),
    }
    # Value checks (expected to shift slightly after #141's per-match death floor).
    w, s, r = weekly(), season(), roster()
    totals = {
        "weekly_points_sum": round(sum(x["week_points"] for x in w), 2),
        "season_points_sum": round(sum(x["points"] for x in s), 2),
        "roster_week_points": round(r["combined_value"], 2),
        "roster_season_points": round(r["season_points"], 2),
    }
    return {"size": {"users": args.users, "weeks": args.weeks, **{k: v for k, v in info.items()
                                                                  if k not in ("weeks", "first_user_id")}},
            "timings": results, "totals": totals,
            "python": sys.version.split()[0]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--users", type=int, default=60)
    ap.add_argument("--weeks", type=int, default=10)
    ap.add_argument("--teams", type=int, default=8)
    ap.add_argument("--players-per-team", type=int, default=5)
    ap.add_argument("--games", type=int, default=2, help="games per team per week")
    ap.add_argument("--cards", type=int, default=15, help="cards owned per user")
    ap.add_argument("--roster", type=int, default=5)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--seed", type=int, default=141)
    ap.add_argument("--save", help="write results JSON to this path")
    ap.add_argument("--compare", help="baseline JSON to compare timings against")
    args = ap.parse_args()

    out = run(args)
    print(json.dumps(out, indent=2))
    if args.save:
        Path(args.save).write_text(json.dumps(out, indent=2) + "\n")
    if args.compare:
        base = json.loads(Path(args.compare).read_text())
        print("\nvs baseline (median ms, queries):")
        for k, cur in out["timings"].items():
            b = base["timings"].get(k)
            if not b:
                continue
            ratio = cur["median_ms"] / b["median_ms"] if b["median_ms"] else float("nan")
            print(f"  {k:22s} {b['median_ms']:>9.2f} -> {cur['median_ms']:>9.2f} ms "
                  f"({ratio:.2f}x)   queries {b['queries']} -> {cur['queries']}")
        for k, cur in out["totals"].items():
            print(f"  {k:22s} {base['totals'].get(k)} -> {cur}")


if __name__ == "__main__":
    main()
