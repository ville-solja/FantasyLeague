"""
One-time migration: add expanded scoring stat columns to player_match_stats.

Run once against an existing database before restarting the server:
    python backend/migrate_scoring_stats.py

Safe to run multiple times — each ALTER TABLE is skipped if the column already exists.
A full re-ingest is required after this migration to populate the new columns for
existing match rows (they default to 0 until re-ingested).
"""
import sqlite3
import os

DB_PATH = os.getenv("DATABASE_URL", "fantasy.db").replace("sqlite:///", "")

NEW_COLUMNS = [
    ("last_hits",               "INTEGER DEFAULT 0"),
    ("denies",                  "INTEGER DEFAULT 0"),
    ("towers_killed",           "INTEGER DEFAULT 0"),
    ("roshan_kills",            "INTEGER DEFAULT 0"),
    ("teamfight_participation", "REAL    DEFAULT 0.0"),
    ("camps_stacked",           "INTEGER DEFAULT 0"),
    ("rune_pickups",            "INTEGER DEFAULT 0"),
    ("firstblood_claimed",      "INTEGER DEFAULT 0"),
    ("stuns",                   "REAL    DEFAULT 0.0"),
]


def migrate():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(player_match_stats)")
    existing = {row[1] for row in cur.fetchall()}

    added = []
    for col, col_type in NEW_COLUMNS:
        if col not in existing:
            cur.execute(f"ALTER TABLE player_match_stats ADD COLUMN {col} {col_type}")
            added.append(col)
            print(f"  Added column: {col}")
        else:
            print(f"  Skipped (exists): {col}")

    conn.commit()
    conn.close()

    if added:
        print(f"\nMigration complete — {len(added)} column(s) added.")
        print("Run a full re-ingest to populate new columns for existing match rows.")
    else:
        print("\nNo changes — all columns already present.")


if __name__ == "__main__":
    migrate()
