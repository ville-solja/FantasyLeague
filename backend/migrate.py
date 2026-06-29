"""Schema migrations run once per startup (all idempotent)."""
import logging
import os

from sqlalchemy import text

logger = logging.getLogger(__name__)

_INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))


# ---------------------------------------------------------------------------
# Migration registry helpers
# ---------------------------------------------------------------------------

def _ensure_migrations_table(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id         TEXT PRIMARY KEY,
            applied_at INTEGER NOT NULL
        )
    """))
    conn.commit()


def _applied(conn, migration_id: str) -> bool:
    row = conn.execute(
        text("SELECT 1 FROM schema_migrations WHERE id = :id"),
        {"id": migration_id}
    ).first()
    return row is not None


def _record(conn, migration_id: str):
    conn.execute(
        text("INSERT INTO schema_migrations (id, applied_at) VALUES (:id, :ts)"),
        {"id": migration_id, "ts": int(__import__("time").time())}
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Individual migration functions
# ---------------------------------------------------------------------------

def _m001_players_avatar_url(conn):
    cols = [r[1] for r in conn.execute(text("PRAGMA table_info(players)")).fetchall()]
    if "avatar_url" not in cols:
        conn.execute(text("ALTER TABLE players ADD COLUMN avatar_url TEXT"))
        conn.commit()


def _m002_matches_columns(conn):
    match_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(matches)")).fetchall()]
    if "start_time" not in match_cols:
        conn.execute(text("ALTER TABLE matches ADD COLUMN start_time INTEGER"))
        conn.commit()
    if "radiant_win" not in match_cols:
        conn.execute(text("ALTER TABLE matches ADD COLUMN radiant_win BOOLEAN"))
        conn.commit()
    if "week_override_id" not in match_cols:
        conn.execute(text(
            "ALTER TABLE matches ADD COLUMN week_override_id INTEGER REFERENCES weeks(id)"
        ))
        conn.commit()


def _m003_users_columns(conn):
    user_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
    if "tokens" not in user_cols:
        conn.execute(text(
            f"ALTER TABLE users ADD COLUMN tokens INTEGER DEFAULT {_INITIAL_TOKENS}"
        ))
        if "draw_limit" in user_cols:
            conn.execute(text("UPDATE users SET tokens = COALESCE(draw_limit, 7)"))
        conn.commit()
    if "created_at" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN created_at INTEGER"))
        conn.commit()
    if "player_id" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN player_id INTEGER"))
        conn.commit()
    if "must_change_password" not in user_cols:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 0"
        ))
        conn.commit()
    if "is_tester" not in user_cols:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN is_tester BOOLEAN DEFAULT 0"
        ))
        conn.commit()
        logger.info("Migration: users — added is_tester column")
    if "twitch_user_id" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN twitch_user_id TEXT"))
        conn.commit()
        logger.info("Migration: users — added twitch_user_id column")


def _m004_pms_hero_id(conn):
    pms_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(player_match_stats)")).fetchall()]
    if "hero_id" not in pms_cols:
        conn.execute(text("ALTER TABLE player_match_stats ADD COLUMN hero_id INTEGER"))
        conn.commit()
        logger.info("Migration: player_match_stats — added hero_id column")


def _m005_pms_expanded_stats(conn):
    pms_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(player_match_stats)")).fetchall()]
    for _col, _col_type in [
        ("last_hits",               "INTEGER DEFAULT 0"),
        ("denies",                  "INTEGER DEFAULT 0"),
        ("towers_killed",           "INTEGER DEFAULT 0"),
        ("roshan_kills",            "INTEGER DEFAULT 0"),
        ("teamfight_participation", "REAL DEFAULT 0.0"),
        ("camps_stacked",           "INTEGER DEFAULT 0"),
        ("rune_pickups",            "INTEGER DEFAULT 0"),
        ("firstblood_claimed",      "INTEGER DEFAULT 0"),
        ("stuns",                   "REAL DEFAULT 0.0"),
    ]:
        if _col not in pms_cols:
            conn.execute(text(f"ALTER TABLE player_match_stats ADD COLUMN {_col} {_col_type}"))
            conn.commit()
            logger.info("Migration: player_match_stats — added %s column", _col)

    if "is_mvp" not in pms_cols:
        conn.execute(text("ALTER TABLE player_match_stats ADD COLUMN is_mvp BOOLEAN DEFAULT 0"))
        conn.commit()
        logger.info("Migration: player_match_stats — added is_mvp column")


def _m006_cards_generation(conn):
    card_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(cards)")).fetchall()]
    if "generation" not in card_cols:
        conn.execute(text(
            "ALTER TABLE cards ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"
        ))
        conn.commit()
        logger.info("Migration: cards — added generation column")


def _m007_teams_logo_url(conn):
    team_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(teams)")).fetchall()]
    if "logo_url" not in team_cols:
        conn.execute(text("ALTER TABLE teams ADD COLUMN logo_url TEXT"))
        conn.commit()


def _m008_card_modifiers_constraint(conn):
    _cm_ddl = (conn.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='card_modifiers'"
    )).scalar() or "")
    _needs_cm_rebuild = (
        "ck_card_modifiers_stat_key" not in _cm_ddl
        or "assists" in _cm_ddl
        or "sen_placed" in _cm_ddl
    )
    if _needs_cm_rebuild:
        conn.execute(text("DROP TABLE IF EXISTS card_modifiers_new"))
        conn.execute(text("""
            CREATE TABLE card_modifiers_new (
                id        INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                card_id   INTEGER REFERENCES cards(id),
                stat_key  VARCHAR,
                bonus_pct FLOAT,
                CONSTRAINT ck_card_modifiers_stat_key
                    CHECK (stat_key IN (
                        'kills','deaths','gold_per_min','obs_placed',
                        'last_hits','denies','towers_killed','roshan_kills',
                        'teamfight_participation','camps_stacked','rune_pickups',
                        'firstblood_claimed','stuns'
                    ))
            )
        """))
        conn.execute(text("""
            INSERT INTO card_modifiers_new
            SELECT id, card_id, stat_key, bonus_pct FROM card_modifiers
            WHERE stat_key IN (
                'kills','deaths','gold_per_min','obs_placed',
                'last_hits','denies','towers_killed','roshan_kills',
                'teamfight_participation','camps_stacked','rune_pickups',
                'firstblood_claimed','stuns'
            )
        """))
        conn.execute(text("DROP TABLE card_modifiers"))
        conn.execute(text("ALTER TABLE card_modifiers_new RENAME TO card_modifiers"))
        conn.commit()
        logger.info("Migration: card_modifiers — updated stat_key CHECK constraint")


def _m009_indexes(conn):
    for stmt in [
        "CREATE INDEX IF NOT EXISTS ix_cards_owner_id ON cards(owner_id)",
        "CREATE INDEX IF NOT EXISTS ix_cards_player_id ON cards(player_id)",
        "CREATE INDEX IF NOT EXISTS ix_pms_player_id ON player_match_stats(player_id)",
        "CREATE INDEX IF NOT EXISTS ix_pms_match_id ON player_match_stats(match_id)",
        "CREATE INDEX IF NOT EXISTS ix_matches_start_time ON matches(start_time)",
        "CREATE INDEX IF NOT EXISTS ix_wre_week_user ON weekly_roster_entries(week_id, user_id)",
        "CREATE INDEX IF NOT EXISTS ix_twitch_presence_pool ON twitch_presence(channel_id, seen_at)",
        "CREATE INDEX IF NOT EXISTS ix_card_modifiers_card_id ON card_modifiers(card_id)",
    ]:
        conn.execute(text(stmt))
    conn.commit()


def _m010_weeks_epoch0_reset(conn):
    old = conn.execute(text("SELECT id FROM weeks WHERE start_time = 0 LIMIT 1")).first()
    if old:
        conn.execute(text("DELETE FROM weekly_roster_entries"))
        conn.execute(text("DELETE FROM weeks"))
        conn.commit()
        logger.info("Migration: reset weeks — removed invalid epoch-0 Week 1")


def _m011_twitch_mvp_selected_at(conn):
    tmvp_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(twitch_mvp)")).fetchall()]
    if "selected_at" not in tmvp_cols:
        conn.execute(text("ALTER TABLE twitch_mvp ADD COLUMN selected_at INTEGER"))
        conn.commit()
        logger.info("Migration: twitch_mvp — added selected_at column")


def _m012_twitch_token_drops_columns(conn):
    ttd_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(twitch_token_drops)")).fetchall()]
    if "series_id" not in ttd_cols:
        conn.execute(text("ALTER TABLE twitch_token_drops ADD COLUMN series_id TEXT"))
        conn.commit()
        logger.info("Migration: twitch_token_drops — added series_id column")
    if "count" not in ttd_cols:
        conn.execute(text("ALTER TABLE twitch_token_drops ADD COLUMN count INTEGER"))
        conn.commit()
        logger.info("Migration: twitch_token_drops — added count column")


def _m013_user_tag_system(conn):
    tables = {r[0] for r in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )).fetchall()}
    if "tag_definitions" not in tables:
        conn.execute(text("""
            CREATE TABLE tag_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                created_at INTEGER
            )
        """))
        logger.info("Migration: created tag_definitions table")
    if "user_tags" not in tables:
        conn.execute(text("""
            CREATE TABLE user_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                tag_id INTEGER NOT NULL REFERENCES tag_definitions(id),
                granted_by INTEGER REFERENCES users(id),
                granted_at INTEGER,
                UNIQUE(user_id, tag_id)
            )
        """))
        logger.info("Migration: created user_tags table")
    conn.commit()


def _m014_cards_league_id_nullable(conn):
    col_info = conn.execute(text("PRAGMA table_info(cards)")).fetchall()
    league_col = next((r for r in col_info if r[1] == "league_id"), None)
    if league_col is None or league_col[3] == 0:
        return  # already nullable or absent — nothing to do
    conn.execute(text("PRAGMA foreign_keys = OFF"))
    conn.execute(text("""
        CREATE TABLE cards_new (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            card_type TEXT    NOT NULL,
            league_id INTEGER,
            owner_id  INTEGER,
            is_active INTEGER NOT NULL DEFAULT 0,
            generation INTEGER NOT NULL DEFAULT 1
        )
    """))
    conn.execute(text("""
        INSERT INTO cards_new (id, player_id, card_type, league_id, owner_id, is_active, generation)
        SELECT id, player_id, card_type, league_id, owner_id, is_active, COALESCE(generation, 1)
        FROM cards
    """))
    conn.execute(text("DROP TABLE cards"))
    conn.execute(text("ALTER TABLE cards_new RENAME TO cards"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cards_owner_id  ON cards(owner_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cards_player_id ON cards(player_id)"))
    conn.execute(text("PRAGMA foreign_keys = ON"))
    conn.commit()
    logger.info("Migration: cards — made league_id nullable for dynamic card creation")


def _m015_missing_indexes(conn):
    for stmt in [
        "CREATE INDEX IF NOT EXISTS ix_matches_week_override_id ON matches(week_override_id)",
        "CREATE INDEX IF NOT EXISTS ix_match_bans_match_id ON match_bans(match_id)",
    ]:
        conn.execute(text(stmt))
    conn.commit()


def _m016_players_is_active(conn):
    cols = [r[1] for r in conn.execute(text("PRAGMA table_info(players)")).fetchall()]
    if "is_active" not in cols:
        conn.execute(text("ALTER TABLE players ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"))
        conn.commit()
        logger.info("Migration: players — added is_active column")


def _m017_leagues_is_monitored(conn):
    cols = {r[1] for r in conn.execute(text("PRAGMA table_info(leagues)"))}
    if "is_monitored" not in cols:
        conn.execute(text("ALTER TABLE leagues ADD COLUMN is_monitored INTEGER NOT NULL DEFAULT 0"))
        conn.commit()
        logger.info("Migration: leagues — added is_monitored column")


# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------

MIGRATIONS = [
    ("001_players_avatar_url",       _m001_players_avatar_url),
    ("002_matches_columns",          _m002_matches_columns),
    ("003_users_columns",            _m003_users_columns),
    ("004_pms_hero_id",              _m004_pms_hero_id),
    ("005_pms_expanded_stats",       _m005_pms_expanded_stats),
    ("006_cards_generation",         _m006_cards_generation),
    ("007_teams_logo_url",           _m007_teams_logo_url),
    ("008_card_modifiers_constraint", _m008_card_modifiers_constraint),
    ("009_indexes",                  _m009_indexes),
    ("010_weeks_epoch0_reset",       _m010_weeks_epoch0_reset),
    ("011_twitch_mvp_selected_at",   _m011_twitch_mvp_selected_at),
    ("012_twitch_token_drops_columns", _m012_twitch_token_drops_columns),
    ("013_user_tag_system",          _m013_user_tag_system),
    ("014_cards_league_id_nullable", _m014_cards_league_id_nullable),
    ("015_missing_indexes",          _m015_missing_indexes),
    ("016_players_is_active",        _m016_players_is_active),
    ("017_leagues_is_monitored",     _m017_leagues_is_monitored),
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_migrations(engine) -> None:
    """Apply all registered migrations exactly once each."""
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))
        conn.commit()
        _ensure_migrations_table(conn)
        for migration_id, fn in MIGRATIONS:
            if _applied(conn, migration_id):
                continue
            try:
                fn(conn)
                _record(conn, migration_id)
                logger.info("Migration applied: %s", migration_id)
            except Exception:
                logger.exception(
                    "Migration FAILED: %s — startup will continue but "
                    "this migration will be retried next start",
                    migration_id
                )
