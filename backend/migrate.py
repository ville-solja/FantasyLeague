"""Schema migrations run once per startup (all idempotent)."""
import logging
import os

from sqlalchemy import text

logger = logging.getLogger(__name__)

_INITIAL_TOKENS = int(os.getenv("INITIAL_TOKENS", "5"))


def run_migrations(engine) -> None:
    """Apply column additions, constraint migrations, and index creation."""
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA busy_timeout=30000"))
        conn.commit()

        # players: avatar_url
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(players)")).fetchall()]
        if "avatar_url" not in cols:
            conn.execute(text("ALTER TABLE players ADD COLUMN avatar_url TEXT"))
            conn.commit()

        # matches: start_time, radiant_win, week_override_id
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

        # users: tokens, created_at, player_id, must_change_password
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

        # player_match_stats: hero_id + expanded scoring columns
        pms_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(player_match_stats)")).fetchall()]
        if "hero_id" not in pms_cols:
            conn.execute(text("ALTER TABLE player_match_stats ADD COLUMN hero_id INTEGER"))
            conn.commit()
            logger.info("Migration: player_match_stats — added hero_id column")
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

        # cards: generation
        card_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(cards)")).fetchall()]
        if "generation" not in card_cols:
            conn.execute(text(
                "ALTER TABLE cards ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"
            ))
            conn.commit()
            logger.info("Migration: cards — added generation column")

        # teams: logo_url
        team_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(teams)")).fetchall()]
        if "logo_url" not in team_cols:
            conn.execute(text("ALTER TABLE teams ADD COLUMN logo_url TEXT"))
            conn.commit()

        # card_modifiers: CHECK constraint — rebuild if missing or contains old stat keys
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

    # Indexes (all IF NOT EXISTS — safe to repeat)
    with engine.connect() as conn:
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

    # Data migration: bad epoch-0 Week 1 structure
    with engine.connect() as conn:
        old = conn.execute(text("SELECT id FROM weeks WHERE start_time = 0 LIMIT 1")).first()
        if old:
            conn.execute(text("DELETE FROM weekly_roster_entries"))
            conn.execute(text("DELETE FROM weeks"))
            conn.commit()
            logger.info("Migration: reset weeks — removed invalid epoch-0 Week 1")
