from sqlalchemy import Column, BigInteger, String, Float, ForeignKey
from database import Base


class Player(Base):
    __tablename__ = "players"

    id = Column(BigInteger, primary_key=True)  # OpenDota account_id
    name = Column(String)
    team_name = Column(String)
    division = Column(String)


class Match(Base):
    __tablename__ = "matches"

    match_id = Column(BigInteger, primary_key=True)  # use match_id directly
    radiant_team_name = Column(String)
    dire_team_name = Column(String)
    league_name = Column(String)


class PlayerMatchStats(Base):
    __tablename__ = "player_match_stats"

    id = Column(BigInteger, primary_key=True)
    player_id = Column(BigInteger, ForeignKey("players.id"))
    match_id = Column(BigInteger, ForeignKey("matches.match_id"))
    fantasy_points = Column(Float)