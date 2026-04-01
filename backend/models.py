from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey
from database import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True)  # OpenDota account_id
    name = Column(String)
    avatar_url = Column(String)


class Match(Base):
    __tablename__ = "matches"

    match_id = Column(Integer, primary_key=True)
    radiant_team_id = Column(Integer)
    dire_team_id = Column(Integer)
    league_id = Column(Integer, ForeignKey("leagues.id"))
    start_time = Column(Integer)   # Unix timestamp from OpenDota
    radiant_win = Column(Boolean)  # from OpenDota


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


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)  # OpenDota team_id
    name = Column(String)


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    owner_id = Column(Integer, ForeignKey("users.id"))
    card_type = Column(String)  # "common", "rare", "epic", "legendary"
    league_id = Column(Integer, ForeignKey("leagues.id"))
    is_active = Column(Boolean, default=False)


class CardModifier(Base):
    __tablename__ = "card_modifiers"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    card_id   = Column(Integer, ForeignKey("cards.id"))
    stat_key  = Column(String)   # one of SCORING_STATS
    bonus_pct = Column(Float)    # e.g. 10.0 = +10% boost to this stat's contribution


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    email = Column(String, unique=True)
    password_hash = Column(String)
    is_admin = Column(Boolean, default=False)
    tokens = Column(Integer, default=0)
    created_at = Column(Integer, nullable=True)  # Unix timestamp of registration
    player_id = Column(Integer, nullable=True)   # linked OpenDota account_id
    must_change_password = Column(Boolean, default=False)  # True after a temp password is issued


class League(Base):
    __tablename__ = "leagues"

    id = Column(Integer, primary_key=True)  # OpenDota league_id
    name = Column(String)


class Weight(Base):
    __tablename__ = "weights"

    key = Column(String, primary_key=True)
    label = Column(String)
    value = Column(Float)


class Week(Base):
    __tablename__ = "weeks"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    label      = Column(String)   # "Week 1", "Week 2", ...
    start_time = Column(Integer)  # Unix timestamp — 0 for week 1, Monday 00:00 UTC thereafter
    end_time   = Column(Integer)  # Unix timestamp — Sunday 23:59:59 UTC
    is_locked  = Column(Boolean, default=False)


class WeeklyRosterEntry(Base):
    __tablename__ = "weekly_roster_entries"

    id      = Column(Integer, primary_key=True, autoincrement=True)
    week_id = Column(Integer, ForeignKey("weeks.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    card_id = Column(Integer, ForeignKey("cards.id"))


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
