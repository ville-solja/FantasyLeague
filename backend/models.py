from sqlalchemy import Column, BigInteger, String, Float, ForeignKey
from database import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(BigInteger, primary_key=True)  # OpenDota account_id
    name = Column(String)


class Match(Base):
    __tablename__ = "matches"

    match_id = Column(BigInteger, primary_key=True)  # use match_id directly
    radiant_team_id = Column(BigInteger)
    dire_team_id = Column(BigInteger)
    league_id = Column(BigInteger, ForeignKey("leagues.id"))


class PlayerMatchStats(Base):
    __tablename__ = "player_match_stats"

    id = Column(BigInteger, primary_key=True)
    player_id = Column(BigInteger, ForeignKey("players.id"))
    match_id = Column(BigInteger, ForeignKey("matches.match_id"))
    team_id = Column(BigInteger, ForeignKey("teams.id"))
    fantasy_points = Column(Float)


class Team(Base):
    __tablename__ = "teams"

    id = Column(BigInteger, primary_key=True)  # OpenDota team_id
    name = Column(String)


class Card(Base):
    __tablename__ = "cards"

    id = Column(BigInteger, primary_key=True)
    player_id = Column(BigInteger, ForeignKey("players.id"))
    owner_id = Column(BigInteger, ForeignKey("users.id"))  # user_id of the card owner
    card_type = Column(String)  # e.g., "common", "rare", "epic", "legendary"
    league_id = Column(BigInteger, ForeignKey("leagues.id"))


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String, unique=True)
    email = Column(String, unique=True)


class League(Base):
    __tablename__ = "leagues"

    id = Column(BigInteger, primary_key=True)  # OpenDota league_id
    name = Column(String)