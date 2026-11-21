"""Reset Season's clean slate (issue #133): which tables it clears, updates and keeps,
a preview of the counts, the clear itself and the in-memory caches it empties.

Every model table is in exactly one group of TABLE_GROUPS (a test checks it), so a
table added later fails that test until someone decides what Reset does with it.
The raw `schema_migrations` table (migrate.py) has no model and is outside the lists.
"""

import os

from sqlalchemy import func, select

import clock
from database import Base
from models import League, SeasonArchive, SeasonPlayerStats, SeasonTeamResult, User, Week

TABLE_GROUPS = {
    # Deleted outright: the season's data.
    "cleared": (
        "card_match_points", "player_match_stats", "match_bans", "matches",
        "weekly_roster_entries", "weeks", "twitch_mvp", "twitch_token_drops", "players",
        "teams", "card_modifiers", "cards", "own_player_card_grants", "weekly_summaries",
        "weekly_summary_reveals", "weekly_summary_seen", "live_matches", "match_timings",
        "twitch_presence",
    ),
    # Rows kept, one field reset.
    "updated": {
        "users": "tokens reset to INITIAL_TOKENS",
        "leagues": "unmonitored",
        "demo_clock": "override cleared",
    },
    # Untouched: history, accounts, settings and records that span seasons.
    "kept": (
        "season_archive", "season_accolades", "season_player_stats", "season_team_results",
        "tag_definitions", "user_tags", "audit_logs", "finals_brackets", "finals_predictions",
        "team_signup_periods", "team_signups", "team_signup_players", "promo_codes",
        "code_redemptions", "token_grant_events", "token_grant_claims", "notifications",
        "notification_dismissals", "weights", "player_profiles", "twitch_mvp_polls",
        "twitch_mvp_votes", "twitch_pending_tokens", "twitch_link_codes",
        "twitch_oauth_states", "twitch_merge_log", "twitch_starter_grants",
        "twitch_channel_approvals", "steam_login_states", "steam_openid_nonces",
        "steam_pending_signups", "password_reset_tokens", "user_sessions",
        "toornament_sync_log", "scoring_state",
    ),
}
CLEARED_TABLES = TABLE_GROUPS["cleared"]
UPDATED_TABLES = tuple(TABLE_GROUPS["updated"])
KEPT_TABLES = TABLE_GROUPS["kept"]

UNARCHIVED_LABEL = "unarchived"
END_SEASON_MISSING = ("Locked weeks exist but no season archive was created "
                      "after the newest locked week. Run End Season first "
                      "or pass force=true.")


def initial_tokens() -> int:
    return int(os.getenv("INITIAL_TOKENS", "5"))


def end_season_missing(db) -> bool:
    """True when locked weeks exist and no season archive is newer than the newest one."""
    newest_lock = db.query(func.max(func.coalesce(Week.start_time, 0))).filter(
        Week.is_locked == True).scalar()  # noqa: E712
    if newest_lock is None:
        return False
    return db.query(SeasonArchive.id).filter(SeasonArchive.archived_at >= newest_lock).first() is None


def backup_label(db) -> str:
    """The label the season backup is named after: the newest archived season."""
    row = (db.query(SeasonArchive.season_label)
           .order_by(SeasonArchive.archived_at.desc(), SeasonArchive.id.desc()).first())
    return row[0] if row else UNARCHIVED_LABEL


def summary_counts(db, label: str) -> tuple[int, int]:
    """(season_player_stats rows, season_team_results rows) stored for label."""
    return (db.query(SeasonPlayerStats).filter(SeasonPlayerStats.season_label == label).count(),
            db.query(SeasonTeamResult).filter(SeasonTeamResult.season_label == label).count())


def _count(db, name: str) -> int:
    return db.execute(select(func.count()).select_from(Base.metadata.tables[name])).scalar() or 0


def kept_counts(db) -> dict:
    return {name: _count(db, name) for name in KEPT_TABLES}


def preview(db) -> dict:
    """What Reset Season would delete, update and keep, with row counts. Changes nothing."""
    tokens = initial_tokens()
    delete = {name: _count(db, name) for name in CLEARED_TABLES}
    delete["users_tokens_reset"] = db.query(User).count()
    delete["leagues_unmonitored"] = db.query(League).filter(League.is_monitored == True).count()  # noqa: E712
    delete["demo_clock_override"] = 1 if clock.get_override(db) is not None else 0
    missing = end_season_missing(db)
    label = backup_label(db)
    players, teams = summary_counts(db, label)
    return {
        "season_label": label,
        "archived": label != UNARCHIVED_LABEL,
        # Issue #133: a season ended before the summary existed can save it before Reset.
        "has_summary": bool(players or teams),
        "summary_players": players,
        "summary_teams": teams,
        "initial_tokens": tokens,
        "delete": delete,
        "keep": kept_counts(db),
        "end_season_missing": missing,
        "warning": END_SEASON_MISSING if missing else None,
    }


def clear(db, skip=()) -> dict:
    """Delete every cleared table except `skip`, reset tokens, unmonitor leagues and
    clear the demo clock override. Returns {table or action: rows}. Does not commit."""
    counts = {name: db.execute(Base.metadata.tables[name].delete()).rowcount
              for name in CLEARED_TABLES if name not in skip}
    counts["users_tokens_reset"] = db.query(User).update({User.tokens: initial_tokens()},
                                                         synchronize_session=False)
    counts["leagues_unmonitored"] = (
        db.query(League).filter(League.is_monitored == True)  # noqa: E712
        .update({League.is_monitored: False}, synchronize_session=False))
    counts["demo_clock_override"] = 1 if clock.get_override(db) is not None else 0
    clock.clear_override(db)
    return counts


def bust_caches() -> None:
    """Empty the in-memory caches that hold season data. Call after the commit, so a
    request in between can't refill them with the old season."""
    import finals
    import player_insights
    import schedule
    import team_insights
    import twitch
    schedule.bust_cache()
    twitch.bust_panel_cache()
    finals.clear_caches()
    team_insights.clear_league_cache()
    player_insights.clear_league_cache()
