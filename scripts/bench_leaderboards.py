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
import season_generator  # noqa: E402


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

    # Issue #145: the data comes from the pure generator (same draws as before the move).
    start0 = 1_700_000_000
    season = season_generator.generate(
        rng, weeks=weeks, teams=teams, players_per_team=players_per_team,
        games_per_team_week=games_per_team_week, users=users, cards_per_user=cards_per_user,
        roster_size=roster_size, start=start0)
    stat_cols = set(PlayerMatchStats.__table__.columns.keys())

    db = SessionLocal()
    try:
        db.add(League(id=1, name="Bench League", is_monitored=True))
        for t in season["teams"]:
            db.add(Team(id=t["id"], name=t["name"]))
        for p in season["players"]:
            db.add(Player(id=p["id"], name=p["name"], is_active=True))

        week_rows = []
        for w in season["weeks"]:
            wk = Week(label=w["label"], start_time=w["start_time"], end_time=w["end_time"],
                      is_locked=True)
            db.add(wk)
            week_rows.append(wk)
        db.flush()

        stat_count = 0
        for m in season["matches"]:
            db.add(Match(match_id=m["match_id"], radiant_team_id=m["radiant_team_id"],
                         dire_team_id=m["dire_team_id"], league_id=1, start_time=m["start_time"],
                         radiant_win=m["radiant_win"], duration=m["duration"],
                         parse_status=m["parse_status"]))
            for row in m["stats"]:
                db.add(PlayerMatchStats(match_id=m["match_id"], fantasy_points=0.0,
                                        **{k: v for k, v in row.items() if k in stat_cols}))
                stat_count += 1
        db.flush()

        card_total = 0
        roster_total = 0
        for gu in season["users"]:
            u = gu["index"]
            user = User(username=f"bench{u}", email=f"bench{u}@example.invalid",
                        password_hash="x", is_admin=False, is_tester=False, tokens=5,
                        created_at=start0)
            db.add(user)
            db.flush()
            cards = []
            for gc in gu["cards"]:
                c = Card(player_id=gc["player_id"], owner_id=user.id, card_type=gc["card_type"],
                         league_id=1, is_active=gc["is_active"], slot_index=gc["slot_index"])
                db.add(c)
                db.flush()
                for mod in gc["modifiers"]:
                    db.add(CardModifier(card_id=c.id, **mod))
                cards.append(c)
                card_total += 1
            for wk, picks in zip(week_rows, gu["weekly_rosters"]):
                for i in picks:
                    db.add(WeeklyRosterEntry(week_id=wk.id, user_id=user.id, card_id=cards[i].id))
                    roster_total += 1
        db.commit()
        # Build stored per-match card points (issue #141) the way ingest would have.
        import card_points
        card_points.rebuild_all(db)
        return {"weeks": [w.id for w in week_rows], "players": len(season["players"]),
                "matches": len(season["matches"]), "stat_rows": stat_count,
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
