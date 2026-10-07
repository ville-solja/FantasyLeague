from sqlalchemy import Column, Integer, String, Text, Float, Boolean, ForeignKey, CheckConstraint, Index, UniqueConstraint
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
    vod_url = Column(String, nullable=True)  # admin-set caster VOD link, shown in the Weekly Report
    parse_status = Column(String, nullable=True)  # 'parsed' | 'unparsed' | 'unparseable' (see ingest.py parse retry)
    excluded_from_scoring = Column(Boolean, default=False, nullable=False, server_default="0")  # admin: match counts for no fantasy points


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
    session_version = Column(Integer, nullable=False, default=0)  # issue #119; no longer read since #117 (see UserSession)
    # Issue #157: "full" = website account, "twitch" = soft account created by the
    # extension's Join (no username, email or password; hidden from every ranking).
    account_type = Column(String, nullable=False, default="full", server_default="full")
    last_seen_at = Column(Integer, nullable=True)  # Unix timestamp of last panel activity (soft-account retention)
    twitch_account_id = Column(String, nullable=True, unique=True)  # real Twitch user id, after the extension's identity share
    # Issue #160: when this website account absorbed a soft account (one merge ever),
    # and the soft account waiting to be merged (its Twitch id moved here at connect).
    merged_soft_account_at = Column(Integer, nullable=True)
    pending_merge_user_id = Column(Integer, nullable=True)
    # Issue #150: verified Steam64 id from Steam sign-in (never returned by the API), and
    # the marker of throwaway demo accounts (POST /admin/demo/seed-accounts), which can
    # never become admins or link Steam.
    steam_id = Column(String(17), nullable=True, unique=True)
    is_demo = Column(Boolean, nullable=False, default=False, server_default="0")
    # When SEED_ADMIN_STEAM_IDS was first applied to this account (security review
    # after #150): the list promotes each account at most once, so a later in-app
    # demotion sticks even while the id is still listed.
    admin_seed_applied_at = Column(Integer, nullable=True)
    # Issue #169: Unix time of the last real rename (rename cooldown); NULL = never renamed.
    username_changed_at = Column(Integer, nullable=True)

    @property
    def is_soft(self) -> bool:
        return self.account_type == "twitch"

    @property
    def display_name(self) -> str:
        """Username, or the admin label of a soft account (which has none)."""
        return self.username or f"Twitch viewer #{self.id}"


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
    substitutions_at = Column(Integer, nullable=True)  # when bench substitutions last ran (issue #129)


class WeeklyRosterEntry(Base):
    """Lock-time roster snapshot. Active cards have is_bench=0 and are inserted in
    roster slot order; bench cards have is_bench=1 and bench_order 0..n. An entry
    counts for points when (is_bench=0 AND subbed_out=0) OR subbed_in=1 — see
    match_scoring.counted_roster_entry_sql() (issue #129)."""
    __tablename__ = "weekly_roster_entries"

    id      = Column(Integer, primary_key=True, autoincrement=True)
    week_id = Column(Integer, ForeignKey("weeks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(Integer, ForeignKey("cards.id"))
    is_bench    = Column(Boolean, default=False, nullable=False, server_default="0")
    bench_order = Column(Integer, nullable=True)
    subbed_in   = Column(Boolean, default=False, nullable=False, server_default="0")
    subbed_out  = Column(Boolean, default=False, nullable=False, server_default="0")
    subbed_for_entry_id = Column(Integer, nullable=True)  # on a subbed_in entry: the subbed_out entry it replaced


class WeeklySummary(Base):
    """Marks a week as available in the Weekly Report. Content itself is
    computed live from Match/PlayerMatchStats/Team, the same way the weekly
    leaderboard and card scoring already do — this table only gates tab
    visibility and drives the "new report" highlight badge."""
    __tablename__ = "weekly_summaries"

    week_id      = Column(Integer, ForeignKey("weeks.id"), primary_key=True)
    generated_at = Column(Integer)  # Unix timestamp


class WeeklySummaryReveal(Base):
    __tablename__ = "weekly_summary_reveals"
    __table_args__ = (UniqueConstraint("week_id", "user_id",
                                       name="uq_weekly_summary_reveal_week_user"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    week_id     = Column(Integer, ForeignKey("weeks.id"))
    user_id     = Column(Integer, ForeignKey("users.id"))
    revealed_at = Column(Integer)  # Unix timestamp


class WeeklySummarySeen(Base):
    """One row per user: the most recent week_id they've opened the report
    popup for (gates the highlight badge on the report button), and the most
    recent week_id the "recap is ready" popup announced (issue #151)."""
    __tablename__ = "weekly_summary_seen"

    user_id               = Column(Integer, ForeignKey("users.id"), primary_key=True)
    last_seen_week_id     = Column(Integer, ForeignKey("weeks.id"), nullable=True)
    last_prompted_week_id = Column(Integer, ForeignKey("weeks.id"), nullable=True)


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
    __table_args__ = (UniqueConstraint("code_id", "user_id", name="uq_code_redemption_code_user"),)

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


class TwitchOAuthState(Base):
    """One Twitch sign-in attempt started by GET /auth/twitch/start (issue #160).
    Only sha256(state) is stored; the row is consumed by the first callback that
    presents it and expires after 10 minutes."""
    __tablename__ = "twitch_oauth_states"

    state_hash    = Column(String(64), primary_key=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    nonce         = Column(String, nullable=False)
    code_verifier = Column(String, nullable=True)   # PKCE verifier (NULL when PKCE is off)
    expires_at    = Column(Integer, nullable=False)
    used_at       = Column(Integer, nullable=True)


class SteamLoginState(Base):
    """One Steam sign-in attempt started by GET /auth/steam/start (issue #150). Only
    sha256(state) is stored; the first callback that presents it uses it up, and it
    expires after 10 minutes. `user_id` is set for link and re-auth attempts."""
    __tablename__ = "steam_login_states"

    state_hash = Column(String(64), primary_key=True)
    purpose    = Column(String(16), nullable=False)    # login | link | reauth
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    return_tab = Column(String(16), nullable=True)     # reauth: profile | admin
    expires_at = Column(Integer, nullable=False)
    used_at    = Column(Integer, nullable=True)


class SteamOpenIdNonce(Base):
    """sha256 of each accepted openid.response_nonce (issue #150), so an assertion
    cannot be replayed. Pruned after a day by the daily clean-up."""
    __tablename__ = "steam_openid_nonces"

    nonce_hash = Column(String(64), primary_key=True)
    created_at = Column(Integer, nullable=False)


class SteamPendingSignup(Base):
    """A verified Steam id waiting for the player to choose a display name (issue
    #150). Only sha256 of the cookie token is stored; valid for 15 minutes, single use."""
    __tablename__ = "steam_pending_signups"

    token_hash = Column(String(64), primary_key=True)
    steam_id   = Column(String(17), nullable=False)
    expires_at = Column(Integer, nullable=False)
    used_at    = Column(Integer, nullable=True)


class TwitchMergeLog(Base):
    """Undo log of one soft-account merge (issue #160), kept 30 days so an admin can
    reverse a bad merge. JSON columns are stored as text."""
    __tablename__ = "twitch_merge_log"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    full_user_id   = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    merged_at      = Column(Integer, nullable=False)
    soft_snapshot  = Column(Text, nullable=False)   # twitch_user_id, twitch_account_id, created_at, last_seen_at, tokens
    card_ids       = Column(Text, nullable=False)   # JSON list of the moved card ids
    tokens_moved   = Column(Integer, nullable=False, default=0)
    roster_entries = Column(Text, nullable=False)   # JSON list of the deleted locked-week roster rows
    reversed_at    = Column(Integer, nullable=True)


class PasswordResetToken(Base):
    """Single-use, expiring token for POST /reset-password (issue #123). Created by
    POST /forgot-password, which never touches user.password_hash itself — only a
    valid, unexpired token consumed via POST /reset-password can change the real
    password. Same shape/precedent as TwitchLinkCode above."""
    __tablename__ = "password_reset_tokens"

    token      = Column(String, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"))
    expires_at = Column(Integer)                         # Unix timestamp


class UserSession(Base):
    """One server-side login session (issue #117). The cookie carries only a random
    session ID; this row stores its SHA-256 hash, so a database leak exposes no live
    session IDs. Deleting the row ends the session. `id` is the opaque handle that
    GET/DELETE /sessions use."""
    __tablename__ = "user_sessions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    sid_hash     = Column(String(64), unique=True, nullable=False)
    user_id      = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    created_at   = Column(Integer, nullable=False)   # Unix timestamp of login (absolute limit)
    last_seen_at = Column(Integer, nullable=False)   # Unix timestamp of last touch (idle limit)
    reauth_at    = Column(Integer, nullable=True)    # Unix timestamp of last POST /reauth


class CardMatchPoints(Base):
    """A card's final points for one match (issue #141): stats with card modifiers, plus
    the MVP bonus when the player was that match's MVP, times the rarity multiplier.
    Written by card_points.py whenever an input changes; every points view sums these
    rows. Match exclusion and week assignment are applied when reading."""
    __tablename__ = "card_match_points"
    __table_args__ = (UniqueConstraint("card_id", "match_id", name="uq_card_match_points"),)

    id        = Column(Integer, primary_key=True, autoincrement=True)
    card_id   = Column(Integer, ForeignKey("cards.id"))
    match_id  = Column(Integer, ForeignKey("matches.match_id"), index=True)
    player_id = Column(Integer, index=True)
    points    = Column(Float, nullable=False)


class ScoringState(Base):
    """Small key/value store for scoring bookkeeping, e.g. the fingerprint of the
    weights the stored card points were built with (card_points.FINGERPRINT_KEY)."""
    __tablename__ = "scoring_state"

    key   = Column(String, primary_key=True)
    value = Column(String, nullable=True)


class TwitchPresence(Base):
    __tablename__ = "twitch_presence"

    twitch_user_id = Column(String, primary_key=True)
    channel_id     = Column(String)
    seen_at        = Column(Integer)  # Unix timestamp — updated on each heartbeat


class TwitchMVP(Base):
    __tablename__ = "twitch_mvp"
    # One MVP per match. Concurrent confirmations upsert on this key instead of
    # inserting a second row (see twitch.upsert_mvp).
    __table_args__ = (UniqueConstraint("match_id", name="uq_twitch_mvp_match"),)

    id          = Column(Integer, primary_key=True, autoincrement=True)
    match_id    = Column(Integer, ForeignKey("matches.match_id"))
    player_id   = Column(Integer, ForeignKey("players.id"))
    channel_id  = Column(String)
    selected_at = Column(Integer)  # Unix timestamp


class TwitchTokenDrop(Base):
    __tablename__ = "twitch_token_drops"
    # One drop per channel and match. The drop is claimed by inserting this row
    # first, so a concurrent confirmation cannot pay out twice (see twitch._claim_drop).
    __table_args__ = (UniqueConstraint("channel_id", "series_id", name="uq_twitch_token_drop_channel_series"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String)
    series_id  = Column(String)   # broadcaster-supplied series identifier
    dropped_at = Column(Integer)  # Unix timestamp
    count      = Column(Integer)  # number of tokens actually distributed


class LiveMatch(Base):
    """A monitored-league game seen in Steam's live league list (steam_live), kept until
    its stats are ingested so the Twitch MVP panel can offer it early (see
    ingest.store_live_matches)."""
    __tablename__ = "live_matches"

    match_id        = Column(Integer, primary_key=True)
    league_id       = Column(Integer)
    radiant_team_id = Column(Integer, nullable=True)
    dire_team_id    = Column(Integer, nullable=True)
    radiant_name    = Column(String, nullable=True)
    dire_name       = Column(String, nullable=True)
    players_json    = Column(Text)  # [{"account_id", "name", "side": "radiant"|"dire"}]
    first_seen_at   = Column(Integer)
    last_seen_at    = Column(Integer)
    ended_at        = Column(Integer, nullable=True)  # set when a poll no longer sees it


class MatchTiming(Base):
    """When a match was first seen live, ingested and given an MVP (issue #161), so admins
    can see where MVP-selection delays come from. Each field is set once, while empty
    (see ingest.record_timing). No foreign key: a match is seen live before its
    matches row exists."""
    __tablename__ = "match_timings"

    match_id           = Column(Integer, primary_key=True)
    live_first_seen_at = Column(Integer, nullable=True)
    ingested_at        = Column(Integer, nullable=True)
    mvp_confirmed_at   = Column(Integer, nullable=True)
    mvp_provisional    = Column(Boolean, nullable=True)  # MVP confirmed before ingest


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
# Covering index for the readers' card_id -> (match_id, points) lookups.
Index('ix_card_match_points_card_cover', CardMatchPoints.card_id, CardMatchPoints.match_id, CardMatchPoints.points)
