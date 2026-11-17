"""Season usage numbers from a database file, read-only (issue #251).

Opens the file with SQLite's `mode=ro`, so nothing is written, and prints counts
only: no usernames, emails or ids. Point it at a backup, not at a database a
running server is writing to.

Usage (from the repo root):
    python3 scripts/usage_report.py --db data/fantasy.db.backup-20261116-133709
    python3 scripts/usage_report.py --db /path/to/backup.db --json

What the numbers are:
  Accounts  website (`account_type` "full") and Twitch soft ("twitch") accounts,
            accounts owning a card, accounts with a roster snapshot per week.
  Activity  per week (by `weeks.start_time`/`end_time`), draws (`token_draw`,
            `token_booster_draw`) and logins (`user_login`) from `audit_logs`, and the
            busiest clock hour and minute over all audit rows. Roster saves write no
            audit row, so they are reported as not recorded.
  Twitch    channels, MVPs set, token drops, and the largest presence pool (the
            highest `pool_size=` in the `twitch_token_drop` audit details;
            `twitch_presence` only holds the current heartbeats).
  Data      rows per table, file size, and growth per week.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DRAW_ACTIONS = ("token_draw", "token_booster_draw")
LOGIN_ACTIONS = ("user_login",)
DROP_ACTION = "twitch_token_drop"
ROSTER_SAVES_NOTE = "not recorded (roster saves write no audit row)"
TOP_TABLES = 12
# Tables whose rows carry a Unix time, for "rows added per week".
TIMESTAMPED = (
    ("audit_logs", "SELECT timestamp FROM audit_logs"),
    ("matches", "SELECT start_time FROM matches"),
    ("player_match_stats",
     "SELECT m.start_time FROM player_match_stats s JOIN matches m ON m.match_id = s.match_id"),
    ("users", "SELECT created_at FROM users"),
    ("twitch_mvp", "SELECT selected_at FROM twitch_mvp"),
    ("twitch_token_drops", "SELECT dropped_at FROM twitch_token_drops"),
)
_POOL_SIZE = re.compile(r"(?:^|\s)pool_size=(\d+)(?:\s|$)")


def connect(path) -> sqlite3.Connection:
    """Read-only connection to the database file (a write raises OperationalError)."""
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)


def _tables(con) -> set:
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}


def _scalar(con, tables, table, sql, default=0):
    """One number, or `default` when the table is missing (an older backup)."""
    if table not in tables:
        return default
    row = con.execute(sql).fetchone()
    return row[0] if row and row[0] is not None else default


def _utc(ts) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _weeks(con, tables) -> list:
    if "weeks" not in tables:
        return []
    rows = con.execute("SELECT id, start_time, end_time FROM weeks "
                       "WHERE start_time IS NOT NULL AND end_time IS NOT NULL "
                       "ORDER BY start_time, id").fetchall()
    return [{"week": n, "id": r[0], "start": r[1], "end": r[2]} for n, r in enumerate(rows, 1)]


def _week_of(weeks, ts):
    for w in weeks:
        if w["start"] <= ts <= w["end"]:
            return w["week"]
    return None


def _accounts(con, tables, weeks) -> dict:
    per_week = {w["id"]: 0 for w in weeks}
    if "weekly_roster_entries" in tables:
        for week_id, users in con.execute(
                "SELECT week_id, COUNT(DISTINCT user_id) FROM weekly_roster_entries GROUP BY week_id"):
            if week_id in per_week:
                per_week[week_id] = users
    return {
        "website": _scalar(con, tables, "users",
                           "SELECT COUNT(*) FROM users WHERE account_type = 'full'"),
        "soft": _scalar(con, tables, "users",
                        "SELECT COUNT(*) FROM users WHERE account_type = 'twitch'"),
        "with_card": _scalar(con, tables, "cards",
                             "SELECT COUNT(DISTINCT owner_id) FROM cards WHERE owner_id IS NOT NULL"),
        "rosters_per_week": [{"week": w["week"], "accounts": per_week[w["id"]]} for w in weeks],
    }


def _peak(counts: dict, seconds: int):
    if not counts:
        return None
    # Highest count; the earliest bucket wins a tie.
    bucket, count = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {"start_utc": _utc(bucket * seconds), "count": count}


def _activity(con, tables, weeks) -> dict:
    per_week = {w["week"]: {"week": w["week"], "draws": 0, "logins": 0} for w in weeks}
    outside = {"draws": 0, "logins": 0}
    hours, minutes = {}, {}
    total = 0
    if "audit_logs" in tables:
        for ts, action in con.execute(
                "SELECT timestamp, action FROM audit_logs WHERE timestamp IS NOT NULL"):
            total += 1
            hours[ts // 3600] = hours.get(ts // 3600, 0) + 1
            minutes[ts // 60] = minutes.get(ts // 60, 0) + 1
            kind = ("draws" if action in DRAW_ACTIONS
                    else "logins" if action in LOGIN_ACTIONS else None)
            if kind is None:
                continue
            week = _week_of(weeks, ts)
            (per_week[week] if week is not None else outside)[kind] += 1
    return {
        "audit_rows": total,
        "weeks": list(per_week.values()),
        "outside_weeks": outside,
        "roster_saves": ROSTER_SAVES_NOTE,
        "busiest_hour": _peak(hours, 3600),
        "busiest_minute": _peak(minutes, 60),
    }


def _twitch(con, tables) -> dict:
    channels = set()
    for table in ("twitch_mvp", "twitch_token_drops"):
        if table in tables:
            channels.update(r[0] for r in con.execute(
                f"SELECT DISTINCT channel_id FROM {table} WHERE channel_id IS NOT NULL"))
    pools = []
    if "audit_logs" in tables:
        for (detail,) in con.execute(
                "SELECT detail FROM audit_logs WHERE action = ? AND detail IS NOT NULL",
                (DROP_ACTION,)):
            found = _POOL_SIZE.search(detail)
            if found:
                pools.append(int(found.group(1)))
    return {
        "channels": len(channels),
        "mvps_set": _scalar(con, tables, "twitch_mvp", "SELECT COUNT(*) FROM twitch_mvp"),
        "token_drops": _scalar(con, tables, "twitch_token_drops",
                               "SELECT COUNT(*) FROM twitch_token_drops"),
        "largest_presence_pool": max(pools) if pools else None,
    }


def _data(con, tables, weeks, path) -> dict:
    rows = sorted(((con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0], t) for t in tables),
                  key=lambda r: (-r[0], r[1]))
    size = os.path.getsize(path)
    added = {w["week"]: {"week": w["week"], "rows": 0} for w in weeks}
    for table, sql in TIMESTAMPED:
        if table not in tables or (table == "player_match_stats" and "matches" not in tables):
            continue
        for (ts,) in con.execute(sql):
            week = _week_of(weeks, ts) if ts is not None else None
            if week is not None:
                added[week]["rows"] += 1
    return {
        "file_size_bytes": size,
        "total_rows": sum(r[0] for r in rows),
        "tables": [{"table": t, "rows": n} for n, t in rows],
        "weeks": len(weeks),
        "size_per_week_bytes": round(size / len(weeks)) if weeks else None,
        "rows_added_per_week": list(added.values()),
        "rows_added_tables": [t for t, _ in TIMESTAMPED if t in tables],
    }


def build_report(path) -> dict:
    """Every number of the report, from a read-only connection."""
    con = connect(path)
    try:
        tables = _tables(con)
        weeks = _weeks(con, tables)
        return {
            "accounts": _accounts(con, tables, weeks),
            "activity": _activity(con, tables, weeks),
            "twitch": _twitch(con, tables),
            "data": _data(con, tables, weeks, path),
        }
    finally:
        con.close()


def _peak_text(peak) -> str:
    return "n/a" if peak is None else f"{peak['count']} actions, starting {peak['start_utc']}"


def format_report(report: dict) -> str:
    acc, act, tw, data = (report[k] for k in ("accounts", "activity", "twitch", "data"))
    lines = ["Accounts",
             f"  Website accounts:           {acc['website']}",
             f"  Twitch soft accounts:       {acc['soft']}",
             f"  Accounts with a card:       {acc['with_card']}",
             "  Accounts with a roster, per week:"]
    lines += [f"    Week {w['week']}: {w['accounts']}" for w in acc["rosters_per_week"]] or ["    (no weeks)"]
    lines += ["", "Activity (from audit_logs)",
              f"  Audit rows:                 {act['audit_rows']}",
              "  Per week:"]
    lines += [f"    Week {w['week']}: draws {w['draws']}, logins {w['logins']}"
              for w in act["weeks"]] or ["    (no weeks)"]
    lines += [f"    Outside any week: draws {act['outside_weeks']['draws']}, "
              f"logins {act['outside_weeks']['logins']}",
              f"  Roster saves:               {act['roster_saves']}",
              f"  Busiest hour:               {_peak_text(act['busiest_hour'])}",
              f"  Busiest minute:             {_peak_text(act['busiest_minute'])}",
              "", "Twitch",
              f"  Channels:                   {tw['channels']}",
              f"  MVPs set:                   {tw['mvps_set']}",
              f"  Token drops:                {tw['token_drops']}",
              "  Largest presence pool:      "
              + ("n/a" if tw["largest_presence_pool"] is None else str(tw["largest_presence_pool"])),
              "", "Data",
              f"  File size:                  {data['file_size_bytes']} bytes",
              f"  Rows in all tables:         {data['total_rows']}",
              f"  Weeks:                      {data['weeks']}",
              "  Size per week:              "
              + ("n/a" if data["size_per_week_bytes"] is None else f"{data['size_per_week_bytes']} bytes"),
              f"  Largest tables (top {TOP_TABLES} by rows):"]
    lines += [f"    {t['table']}: {t['rows']}" for t in data["tables"][:TOP_TABLES]]
    lines.append("  Rows added per week (" + ", ".join(data["rows_added_tables"]) + "):")
    lines += [f"    Week {w['week']}: {w['rows']}" for w in data["rows_added_per_week"]] or ["    (no weeks)"]
    return "\n".join(lines)


def main(argv=None, out=print, err=None) -> int:
    err = err or (lambda message: print(message, file=sys.stderr))
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", required=True, help="database file to read (a backup works)")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.db):
        err(f"Database file not found: {args.db}")
        return 2
    try:
        report = build_report(args.db)
    except sqlite3.Error as exc:
        err(f"Could not read {args.db}: {type(exc).__name__}")
        return 1
    out(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
