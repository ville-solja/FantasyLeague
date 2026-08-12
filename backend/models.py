from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, CheckConstraint, Index, UniqueConstraint
from database import Base
from scoring import SCORING_STATS


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)  # OpenDota account_id
    name = Column(String)
    avatar_url = Column(String)
    is_active = Column(Boolean, default=True, nullable=False)


class Match(Base):
    __tablename__ = "matches"

    match_id = Column(Integer, primary_key=True)
    radiant_team_id = Column(Integer)
    dire_team_id = Column(Integer)
    league_id = Column(Integer, ForeignKey("leagues.id"))
    start_time = Column(Integer)   # Unix timestamp from OpenDota
    radiant_win = Column(Boolean)  # from OpenDota
    week_override_id = Column(Integer, ForeignKey("weeks.id"), nullable=True)  # admin override: which week this match counts for
    duration = Column(Integer, nullable=True)  # seconds, from OpenDota match JSON


class PlayerMatchStats(Base):
    __tablename__ = "player_match_stats"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    match_id = Column(Integer, ForeignKey("matches.match_id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    fantasy_points = Column(Float)

    # Raw stats stored so fantasy points can be recalculated without re-fetching
    kills = Column(Integer, default=0)
    assists = Column(Integer, default=0)
    deaths = Column(Integer, default=0)
    gold_per_min = Column(Float, default=0)
    obs_placed = Column(Integer, default=0)
    sen_placed = Column(Integer, default=0)
    tower_damage = Column(Integer, default=0)
    hero_id      = Column(Integer, nullable=True)

    # Expanded scoring stats
    last_hits               = Column(Integer, default=0)
    denies                  = Column(Integer, default=0)
    towers_killed           = Column(Integer, default=0)
    roshan_kills            = Column(Integer, default=0)
    teamfight_participation = Column(Float,   default=0.0)
    camps_stacked           = Column(Integer, default=0)
    rune_pickups            = Column(Integer, default=0)
    firstblood_claimed      = Column(Integer, default=0)
    stuns                   = Column(Float,   default=0.0)
    is_mvp                  = Column(Boolean, default=False)

class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)  # OpenDota team_id
    name = Column(String)
    logo_url = Column(String, nullable=True)  # OpenDota team logo URL


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    owner_id = Column(Integer, ForeignKey("users.id"))
    card_type = Column(String)  # "common", "rare", "epic", "legendary"
    league_id = Column(Integer, ForeignKey("leagues.id"))
    is_active = Column(Boolean, default=False)
    generation = Column(Integer, default=1, nullable=False)
    slot_index = Column(Integer, nullable=True)


_VALID_STAT_KEYS_LIST = list(SCORING_STATS) + ["deaths"]
_VALID_STAT_KEYS = "(" + ",".join(f"'{k}'" for k in _VALID_STAT_KEYS_LIST) + ")"


class CardModifier(Base):
    __tablename__ = "card_modifiers"
    __table_args__ = (
        CheckConstraint(f"stat_key IN {_VALID_STAT_KEYS}", name="ck_card_modifiers_stat_key"),
    )

    id        = Column(Integer, primary_key=True, autoincrement=True)
    card_id   = Column(Integer, ForeignKey("cards.id"))
    stat_key  = Column(String)
    bonus_pct = Column(Float)    # e.g. 10.0 = +10% boost to this stat's contribution


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    email = Column(String, unique=True)
    password_hash = Column(String)
    is_admin = Column(Boolean, default=False)
    is_tester = Column(Boolean, default=False)
    tokens = Column(Integer, default=0)
    created_at = Column(Integer, nullable=True)  # Unix timestamp of registration
    player_id = Column(Integer, nullable=True)   # linked OpenDota account_id
    must_change_password = Column(Boolean, default=False)  # True after a temp password is issued
    temp_password_expires_at = Column(Integer, nullable=True)  # Unix timestamp; NULL when no temp password is active
    twitch_user_id = Column(String, nullable=True, unique=True)  # opaque Twitch user ID from extension JWT


class League(Base):
    __tablename__ = "leagues"

    id           = Column(Integer, primary_key=True)  # OpenDota league_id
    name         = Column(String)
    is_monitored = Column(Boolean, default=False, nullable=False)


class Weight(Base):
    __tablename__ = "weights"

    key = Column(String, primary_key=True)
    label = Column(String)
    value = Column(Float)


class Week(Base):
    __tablename__ = "weeks"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    label      = Column(String)   # "Week 1", "Week 2", ...
    start_time = Column(Integer)  # Unix timestamp — admin-defined, no fixed weekly cadence
    end_time   = Column(Integer)  # Unix timestamp — admin-defined
    is_locked  = Column(Boolean, default=False)


class WeeklyRosterEntry(Base):
    __tablename__ = "weekly_roster_entries"

    id      = Column(Integer, primary_key=True, autoincrement=True)
    week_id = Column(Integer, ForeignKey("weeks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(Integer, ForeignKey("cards.id"))


class SeasonArchive(Base):
    """Final standings snapshot taken by POST /admin/season/end.

    One row per (season_label, user). username is denormalised so the archive
    survives later renames or account deletion.
    """
    __tablename__ = "season_archive"
    __table_args__ = (UniqueConstraint("season_label", "user_id",
                                       name="uq_season_archive_label_user"),)

    id           = Column(Integer, primary_key=True, autoincrement=True)
    season_label = Column(String, nullable=False)
    user_id      = Column(Integer, ForeignKey("users.id"))
    username     = Column(String, nullable=False)   # denormalised: survives renames
    points       = Column(Float, nullable=False)
    rank         = Column(Integer, nullable=False)
    archived_at  = Column(Integer, nullable=False)  # Unix timestamp


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    code          = Column(String, unique=True)
    token_amount  = Column(Integer)
    created_by_id = Column(Integer, ForeignKey("users.id"))


class CodeRedemption(Base):
    __tablename__ = "code_redemptions"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    code_id     = Column(Integer, ForeignKey("promo_codes.id"))
    user_id     = Column(Integer, ForeignKey("users.id"))
    redeemed_at = Column(Integer)  # Unix timestamp


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    timestamp      = Column(Integer)           # Unix timestamp
    actor_id       = Column(Integer, nullable=True)   # user_id; None = system
    actor_username = Column(String, nullable=True)
    action         = Column(String)            # e.g. "user_register", "token_draw", "admin_ingest"
    detail         = Column(String, nullable=True)


class TwitchLinkCode(Base):
    __tablename__ = "twitch_link_codes"

    code       = Column(String, primary_key=True)        # 6-char alphanumeric
    user_id    = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(Integer)                         # Unix timestamp


class TwitchPresence(Base):
    __tablename__ = "twitch_presence"

    twitch_user_id = Column(String, primary_key=True)
    channel_id     = Column(String)
    seen_at        = Column(Integer)  # Unix timestamp — updated on each heartbeat


class TwitchMVP(Base):
    __tablename__ = "twitch_mvp"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    match_id    = Column(Integer, ForeignKey("matches.match_id"))
    player_id   = Column(Integer, ForeignKey("players.id"))
    channel_id  = Column(String)
    selected_at = Column(Integer)  # Unix timestamp


class TwitchTokenDrop(Base):
    __tablename__ = "twitch_token_drops"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String)
    series_id  = Column(String)   # broadcaster-supplied series identifier
    dropped_at = Column(Integer)  # Unix timestamp
    count      = Column(Integer)  # number of tokens actually distributed


class MatchBan(Base):
    __tablename__ = "match_bans"

    id       = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.match_id"))
    hero_id  = Column(Integer)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"

    player_id        = Column(Integer, ForeignKey("players.id"), primary_key=True)
    facts_json       = Column(String, nullable=True)
    bio_text         = Column(String, nullable=True)
    facts_fetched_at = Column(Integer, nullable=True)
    bio_generated_at = Column(Integer, nullable=True)


class ToornamentSyncLog(Base):
    __tablename__ = "toornament_sync_log"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    toornament_match_id = Column(String, unique=True, index=True)
    team1_name          = Column(String)   # as seen in toornament
    team2_name          = Column(String)
    team1_score         = Column(Integer)
    team2_score         = Column(Integer)
    pushed_at           = Column(Integer)  # Unix timestamp


class TokenGrantEvent(Base):
    __tablename__ = "token_grant_events"
    __table_args__ = (
        Index('ix_token_grant_events_time', 'start_time', 'end_time'),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    amount     = Column(Integer)
    start_time = Column(Integer)   # Unix timestamp
    end_time   = Column(Integer)   # Unix timestamp
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Integer)   # Unix timestamp


class TokenGrantClaim(Base):
    __tablename__ = "token_grant_claims"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_claim_event_user"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    event_id   = Column(Integer, ForeignKey("token_grant_events.id"))
    user_id    = Column(Integer, ForeignKey("users.id"))
    claimed_at = Column(Integer)   # Unix timestamp


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index('ix_notifications_time', 'start_time', 'end_time'),
    )

    id         = Column(Integer, primary_key=True, autoincrement=True)
    message    = Column(String)
    start_time = Column(Integer)
    end_time   = Column(Integer)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Integer)


class NotificationDismissal(Base):
    __tablename__ = "notification_dismissals"
    __table_args__ = (UniqueConstraint("notification_id", "user_id",
                                       name="uq_dismissal_notif_user"),)

    id              = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(Integer, ForeignKey("notifications.id"))
    user_id         = Column(Integer, ForeignKey("users.id"))
    dismissed_at    = Column(Integer)


class DemoClock(Base):
    """Singleton row (id=1) holding the operator-set simulated 'now' override for
    DEMO_MODE deployments. See backend/clock.py."""
    __tablename__ = "demo_clock"

    id                  = Column(Integer, primary_key=True)  # always 1
    override_timestamp  = Column(Integer, nullable=True)
    updated_at          = Column(Integer, nullable=True)


class TagDefinition(Base):
    __tablename__ = "tag_definitions"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    key        = Column(String, unique=True, nullable=False)   # e.g. "caster"
    label      = Column(String, nullable=False)                # e.g. "Caster"
    created_at = Column(Integer)                               # Unix timestamp


class UserTag(Base):
    __tablename__ = "user_tags"
    __table_args__ = (UniqueConstraint("user_id", "tag_id", name="uq_user_tag"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    tag_id     = Column(Integer, ForeignKey("tag_definitions.id"), nullable=False)
    granted_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    granted_at = Column(Integer)


Index('ix_pms_player_id',    PlayerMatchStats.player_id)
Index('ix_pms_match_id',     PlayerMatchStats.match_id)
Index('ix_cards_owner_id',   Card.owner_id)
Index('ix_cards_player_id',  Card.player_id)
Index('ix_wre_user_week',    WeeklyRosterEntry.user_id, WeeklyRosterEntry.week_id)
Index('ix_presence_channel_seen', TwitchPresence.channel_id, TwitchPresence.seen_at)
Index('ix_matches_week_override_id', Match.week_override_id)
Index('ix_matches_start_time',       Match.start_time)
Index('ix_match_bans_match_id',      MatchBan.match_id)
Index('ix_matches_league_id',        Match.league_id)
