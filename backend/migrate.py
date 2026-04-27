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

        # player_match_stats: hero_id
        pms_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(player_match_stats)")).fetchall()]
        if "hero_id" not in pms_cols:
            conn.execute(text("ALTER TABLE player_match_stats ADD COLUMN hero_id INTEGER"))
            conn.commit()
            logger.info("Migration: player_match_stats — added hero_id column")

        # teams: logo_url
        team_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(teams)")).fetchall()]
        if "logo_url" not in team_cols:
            conn.execute(text("ALTER TABLE teams ADD COLUMN logo_url TEXT"))
            conn.commit()

        # card_modifiers: add CHECK constraint via table rebuild
        _cm_ddl = (conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='card_modifiers'"
        )).scalar() or "")
        if "ck_card_modifiers_stat_key" not in _cm_ddl:
            conn.execute(text("""
                CREATE TABLE card_modifiers_new (
                    id        INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    card_id   INTEGER REFERENCES cards(id),
                    stat_key  VARCHAR,
                    bonus_pct FLOAT,
                    CONSTRAINT ck_card_modifiers_stat_key
                        CHECK (stat_key IN ('kills','assists','deaths','gold_per_min',
                                            'obs_placed','sen_placed','tower_damage'))
                )
            """))
            conn.execute(text(
                "INSERT INTO card_modifiers_new SELECT id, card_id, stat_key, bonus_pct FROM card_modifiers"
            ))
            conn.execute(text("DROP TABLE card_modifiers"))
            conn.execute(text("ALTER TABLE card_modifiers_new RENAME TO card_modifiers"))
            conn.commit()
            logger.info("Migration: card_modifiers — added stat_key CHECK constraint")

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
