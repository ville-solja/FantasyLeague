"""Season end checks on a database backup, read-only (issue 257).

Run it on a backup downloaded from Admin > Backups, never on the live database:

    python3 scripts/season_end_check.py <backup file> [--label "Season 16"]

The file is opened with SQLite's `mode=ro` (and `immutable`), so nothing is written,
no -wal/-shm files are created and a missing file is not created. The report lists:
  - the archived labels with their dates and user counts;
  - labels that match after normalising (trimmed, inner spaces collapsed, case ignored);
  - accolade counts per label, kind and source;
  - possible duplicates: the same player and kind under two matching labels, more
    than one champion team per label and division, and a season_end row next to an
    admin row for the same player and kind;
  - whether each archived label has a stored season summary;
  - what Reset Season would delete and keep (row counts).

Exit code: 0 when nothing needs attention, 1 when it finds a problem, 2 when the
file can't be read. --label limits the per-label parts to that label and the
labels that match it. See markdown/features/reference/season-lifecycle.md
("Season 16 -> 17 runbook").
"""

import argparse
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")


def normalise_label(label) -> str:
    """Copy of backend accolades.normalise_label (a test checks they agree)."""
    return " ".join((label or "").split()).casefold()


def connect(path) -> sqlite3.Connection:
    """Read-only connection to the file (a write raises OperationalError). `immutable`
    reads the main file only, so no -wal/-shm files appear next to a WAL-mode copy; a
    backup from Admin > Backups has everything in its main file."""
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def reset_groups() -> tuple[tuple, tuple]:
    """(cleared, kept) table names from backend season_reset. The backend's database
    module builds an engine at import; DATABASE_URL points it at an in-memory one, so
    importing it never opens or creates the app's database file."""
    os.environ["DATABASE_URL"] = "sqlite://"
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    import season_reset
    return (tuple(season_reset.CLEARED_TABLES),
            tuple(season_reset.KEPT_TABLES) + tuple(season_reset.UPDATED_TABLES))


def _day(ts) -> str:
    return datetime.fromtimestamp(int(ts or 0), tz=timezone.utc).strftime("%Y-%m-%d")


def _tables(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _who(row) -> str:
    if row["player_account_id"] is not None:
        return f"player {row['player_account_id']}" + (f" ({row['player_name']})" if row["player_name"] else "")
    return f"user {row['user_id']}" + (f" ({row['username']})" if row["username"] else "")


def check(con, label=None) -> tuple[list[str], list[str]]:
    """(report lines, problems)."""
    con.row_factory = sqlite3.Row
    tables = _tables(con)
    lines, problems = [], []
    want = normalise_label(label) if label else None

    def wanted(lb) -> bool:
        return want is None or normalise_label(lb) == want

    archives = [] if "season_archive" not in tables else con.execute(
        "SELECT season_label, MAX(archived_at) AS at, COUNT(*) AS users FROM season_archive "
        "GROUP BY season_label ORDER BY at DESC, season_label").fetchall()
    accolades = [] if "season_accolades" not in tables else con.execute(
        "SELECT * FROM season_accolades ORDER BY season_label, kind, id").fetchall()

    lines.append("Archived seasons:")
    shown = [a for a in archives if wanted(a["season_label"])]
    for a in shown:
        lines.append(f"  {a['season_label']}: archived {_day(a['at'])}, {a['users']} users")
    if not shown:
        lines.append("  none")

    # Labels from every table that names a season, grouped by their normalised form.
    labels = defaultdict(set)
    for a in archives:
        labels[normalise_label(a["season_label"])].add(a["season_label"])
    for r in accolades:
        labels[normalise_label(r["season_label"])].add(r["season_label"])
    lines.append("Labels that match after normalising:")
    found = False
    for key, group in sorted(labels.items()):
        if len(group) > 1 and (want is None or key == want):
            found = True
            text = ", ".join(repr(g) for g in sorted(group))
            lines.append(f"  {text}")
            problems.append(f"Labels {text} are one season under different spellings")
    if not found:
        lines.append("  none")

    lines.append("Accolades per label, kind and source:")
    counts = defaultdict(int)
    for r in accolades:
        if wanted(r["season_label"]):
            counts[(r["season_label"], r["kind"], r["source"])] += 1
    for (lb, kind, source), n in sorted(counts.items()):
        lines.append(f"  {lb} / {kind} / {source}: {n}")
    if not counts:
        lines.append("  none")

    lines.append("Possible duplicates:")
    before = len(problems)
    by_player = defaultdict(list)
    for r in accolades:
        if not wanted(r["season_label"]):
            continue
        who = (r["player_account_id"] if r["player_account_id"] is not None
               else ("user", r["user_id"]))
        by_player[(normalise_label(r["season_label"]), r["kind"], who)].append(r)
    for rows in by_player.values():
        first = rows[0]
        spellings = sorted({r["season_label"] for r in rows})
        if len(spellings) > 1:
            problems.append(f"{first['kind']} for {_who(first)} under matching labels "
                            + ", ".join(repr(s) for s in spellings))
        sources = {r["source"] for r in rows}
        if {"season_end", "admin"} <= sources:
            problems.append(f"{first['kind']} for {_who(first)} in {first['season_label']} "
                            "recorded by End Season (season_end) and by hand (admin)")
    champions = defaultdict(set)
    for r in accolades:
        if r["kind"] == "champion" and wanted(r["season_label"]):
            champions[(r["season_label"], r["division"])].add(r["team_name"] or "?")
    for (lb, division), teams in sorted(champions.items(), key=repr):
        if len(teams) > 1:
            problems.append(f"{lb} {division}: {len(teams)} champion teams ("
                            + ", ".join(sorted(teams)) + ")")
    for p in problems[before:]:
        lines.append(f"  {p}")
    if len(problems) == before:
        lines.append("  none")

    lines.append("Season summaries:")
    live = "matches" in tables and con.execute("SELECT 1 FROM matches LIMIT 1").fetchone() is not None
    newest = archives[0]["season_label"] if archives else None
    for a in shown:
        lb = a["season_label"]
        stored = sum(con.execute(f"SELECT COUNT(*) FROM {t} WHERE season_label = ?", (lb,)).fetchone()[0]
                     for t in ("season_player_stats", "season_team_results") if t in tables)
        if stored:
            lines.append(f"  {lb}: summary stored ({stored} rows)")
        else:
            lines.append(f"  {lb}: no stored summary")
            if lb == newest and live:
                problems.append(f"{lb} has no stored summary: press Save season summary "
                                "in the Reset Season dialog before Reset")

    cleared, kept = reset_groups()
    for title, names in (("Reset would delete:", cleared), ("Reset would keep:", kept)):
        lines.append(title)
        for name in names:
            if name in tables:
                n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                lines.append(f"  {name}: {n}")
    return lines, problems


def main(argv=None, out=print) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", help="a database backup file (Admin > Backups)")
    parser.add_argument("--label", help="limit the per-label report to this season label")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.path):
        print(f"No such file: {args.path}", file=sys.stderr)
        return 2
    try:
        con = connect(args.path)
        try:
            lines, problems = check(con, args.label)
        finally:
            con.close()
    except sqlite3.Error as e:
        print(f"Can't read the file as a database ({type(e).__name__})", file=sys.stderr)
        return 2
    for line in lines:
        out(line)
    out("")
    if problems:
        out(f"Problems found: {len(problems)}")
        for p in problems:
            out(f"  - {p}")
        return 1
    out("No problems found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
