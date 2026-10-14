"""
One-off backfill of bench substitutions for weeks locked before benches were saved
at lock (issue #189). See markdown/features/reference/retroactive-bench-substitution.md.

Take a backup first (bash scripts/backup-db.sh), then from backend/:

  python scripts/backfill_bench.py --weeks "Week 2,Week 3,Week 4" --dry-run
  python scripts/backfill_bench.py --weeks "Week 2,Week 3,Week 4"

Weeks are given by label or id. Exit code 1 when a named week doesn't exist (nothing
is processed then) or a week fails; 0 otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clock  # noqa: E402
import database  # noqa: E402
import weeks  # noqa: E402
from models import AuditLog, Week, WeeklyRosterEntry  # noqa: E402
from routers.leaderboard import weekly_leaderboard  # noqa: E402


def _resolve(db, names: list[str]) -> tuple[list[Week], list[str]]:
    found, missing = [], []
    for name in names:
        week = db.query(Week).filter(Week.label == name).first()
        if week is None and name.isdigit():
            week = db.get(Week, int(name))
        if week is None:
            missing.append(name)
        elif week not in found:
            found.append(week)
    return found, missing


def _skip_reason(db, week: Week) -> str | None:
    if not week.is_locked:
        return "not locked"
    if clock.now(db) < weeks.substitution_time(week):
        return "substitution time not reached"
    has_bench = (
        db.query(WeeklyRosterEntry.id)
        .filter(WeeklyRosterEntry.week_id == week.id,
                WeeklyRosterEntry.is_bench == True)  # noqa: E712
        .first()
    )
    if has_bench:
        return "bench already saved"
    return None


def _week_points(db, week_id: int) -> dict[int, tuple[str, float]]:
    """{user_id: (username, week_points)} exactly as the weekly leaderboard shows them."""
    return {r["id"]: (r["username"], r["week_points"])
            for r in weekly_leaderboard(week_id=week_id, db=db)}


def _report(week: Week, users: int, bench_cards: int, subs: int, before, after) -> list[str]:
    if bench_cards == 0:
        return [f"{week.label}: no bench cards to add"]
    lines = [f"{week.label}: {users} users get a bench, {bench_cards} bench cards, "
             f"{subs} substitutions"]
    changes = []
    for uid, (username, old) in before.items():
        new = after.get(uid, (username, old))[1]
        if new != old:
            changes.append((new - old, username, old, new))
    changes.sort(key=lambda c: (-abs(c[0]), c[1]))
    for delta, username, old, new in changes:
        lines.append(f"  {username}: {old:g} -> {new:g} ({delta:+.2f})")
    return lines


def _process_week(db, week: Week, dry_run: bool) -> list[str]:
    label, week_id = week.label, week.id
    before = _week_points(db, week_id)
    users, bench_cards, subs = weeks.backfill_bench(db, week)
    after = _week_points(db, week_id) if bench_cards else before
    lines = _report(week, users, bench_cards, subs, before, after)
    if dry_run or bench_cards == 0:
        db.rollback()
        return lines
    db.add(AuditLog(
        timestamp=int(clock.now(db)),
        actor_id=None,
        actor_username="script",
        action="admin_bench_backfill",
        detail=f"id={week_id} label={label} users={users} bench_cards={bench_cards} "
               f"substitutions={subs}",
    ))
    db.commit()
    return lines


def run(db, names: list[str], dry_run: bool) -> int:
    targets, missing = _resolve(db, names)
    if missing:
        for name in missing:
            print(f"Unknown week: {name}")
        return 1
    if dry_run:
        print("Dry run: nothing is written.")
    failed = False
    for week in targets:
        reason = _skip_reason(db, week)
        if reason:
            print(f"{week.label}: {reason}, skipped")
            continue
        label = week.label
        try:
            lines = _process_week(db, week, dry_run)
        except Exception as e:
            db.rollback()
            print(f"{label}: failed ({type(e).__name__}: {e}), rolled back")
            failed = True
            continue
        print("\n".join(lines))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill bench substitutions for weeks locked before benches were saved (#189).")
    parser.add_argument("--weeks", required=True,
                        help='Comma-separated week labels or ids, e.g. "Week 2,Week 3,4"')
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the report without writing anything")
    args = parser.parse_args(argv)
    names = [n.strip() for n in args.weeks.split(",") if n.strip()]
    db = database.SessionLocal()
    try:
        return run(db, names, args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
