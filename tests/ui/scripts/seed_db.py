"""
Inserts minimal test data into the SQLite database before UI tests run.
Creates one test league, one team, one player, and a set of unowned cards.
The app's startup migration (create_all) will add any missing tables without
touching this data.

Run from the repo root:
  python tests/ui/scripts/seed_db.py
"""
import os
import sqlite3
import sys
import time

DB_PATH = os.getenv("DB_PATH", "data/fantasy.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH)
conn.execute("PRAGMA journal_mode=WAL")
cur = conn.cursor()

# --- Minimal schema bootstrap (app will fill in the rest at startup) ---
cur.executescript("""
CREATE TABLE IF NOT EXISTS leagues (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    id   INTEGER PRIMARY KEY,
    name TEXT
);
CREATE TABLE IF NOT EXISTS players (
    id         INTEGER PRIMARY KEY,
    name       TEXT,
    avatar_url TEXT
);
CREATE TABLE IF NOT EXISTS cards (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    card_type TEXT    NOT NULL,
    league_id INTEGER NOT NULL,
    owner_id  INTEGER,
    is_active INTEGER NOT NULL DEFAULT 0
);
""")

TEST_LEAGUE_ID = 99901
TEST_TEAM_ID   = 99901
TEST_PLAYER_ID = 99901

# League
cur.execute(
    "INSERT OR IGNORE INTO leagues (id, name) VALUES (?, ?)",
    (TEST_LEAGUE_ID, "CI Test League"),
)
# Team
cur.execute(
    "INSERT OR IGNORE INTO teams (id, name) VALUES (?, ?)",
    (TEST_TEAM_ID, "CI Test Team"),
)
# Player
cur.execute(
    "INSERT OR IGNORE INTO players (id, name) VALUES (?, ?)",
    (TEST_PLAYER_ID, "CI Test Player"),
)

# Cards (1 legendary, 2 epic, 4 rare, 8 common) — all unowned
cards = (
    [("legendary", TEST_PLAYER_ID, TEST_LEAGUE_ID)] * 1
    + [("epic",      TEST_PLAYER_ID, TEST_LEAGUE_ID)] * 2
    + [("rare",      TEST_PLAYER_ID, TEST_LEAGUE_ID)] * 4
    + [("common",    TEST_PLAYER_ID, TEST_LEAGUE_ID)] * 8
)
for card_type, player_id, league_id in cards:
    cur.execute(
        "INSERT OR IGNORE INTO cards (player_id, card_type, league_id, owner_id, is_active) "
        "SELECT ?, ?, ?, NULL, 0 WHERE NOT EXISTS ("
        "  SELECT 1 FROM cards WHERE player_id=? AND card_type=? AND owner_id IS NULL"
        ")",
        (player_id, card_type, league_id, player_id, card_type),
    )

conn.commit()
conn.close()

print(f"Seed complete: {DB_PATH}")
print(f"  League {TEST_LEAGUE_ID}, Team {TEST_TEAM_ID}, Player {TEST_PLAYER_ID}")
print(f"  {len(cards)} unowned cards inserted (skipped if already present)")
