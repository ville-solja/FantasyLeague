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


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    email = Column(String, unique=True)
    password_hash = Column(String)
    is_admin = Column(Boolean, default=False)
    draw_limit = Column(Integer, default=7)


class League(Base):
    __tablename__ = "leagues"

    id = Column(Integer, primary_key=True)  # OpenDota league_id
    name = Column(String)


class Weight(Base):
    __tablename__ = "weights"

    key = Column(String, primary_key=True)
    label = Column(String)
    value = Column(Float)
