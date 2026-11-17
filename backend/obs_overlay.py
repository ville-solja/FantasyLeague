"""The OBS pause-screen overlay's data (issue 246): the current series between two
teams, its last game with raw points (schedule.game_players) and a game whose stats
are still on their way."""
import os

from sqlalchemy import and_, or_

import schedule
from models import LiveMatch, Match, PlayerMatchStats, Team

# The same setting, default and parsing main.py uses for post-match fast polling:
# after a game ends ingest keeps looking for its stats this long, so the overlay
# says "stats are on their way" for the same window. 0 or less: nothing is pending.
PENDING_WINDOW_MINUTES = int(os.getenv("INGEST_POST_MATCH_FAST_POLL_MINUTES", "20"))


def _pair_filter(model, team_a, team_b):
    # A match belongs to the pair only when its two sides are exactly the two teams
    # (as _build_unscheduled_results and resolve_series_result); a NULL side never does.
    return or_(and_(model.radiant_team_id == team_a, model.dire_team_id == team_b),
               and_(model.radiant_team_id == team_b, model.dire_team_id == team_a))


def _current_series(db, team_a, team_b, now):
    """The pair's games of the current series, oldest first: walk back from the
    newest game while start times are at most SERIES_GAP_SECONDS apart. Empty when
    the newest game started more than the gap before `now`."""
    rows = (db.query(Match)
              .filter(_pair_filter(Match, team_a, team_b), Match.start_time.isnot(None))
              .order_by(Match.start_time.desc(), Match.match_id.desc())
              .all())
    series = []
    for m in rows:
        anchor = now if not series else series[-1].start_time
        if anchor - m.start_time > schedule.SERIES_GAP_SECONDS:
            break
        series.append(m)
    series.reverse()
    return series


def _pending_count(db, team_a, team_b, now, known_ids):
    """Games between the pair that ended within the pending window and have no stats."""
    if PENDING_WINDOW_MINUTES <= 0:
        return 0
    cutoff = now - PENDING_WINDOW_MINUTES * 60
    ingested = db.query(PlayerMatchStats.id).filter(
        PlayerMatchStats.match_id == LiveMatch.match_id
    ).exists()
    rows = (db.query(LiveMatch.match_id)
              .filter(_pair_filter(LiveMatch, team_a, team_b),
                      LiveMatch.ended_at.isnot(None),
                      LiveMatch.ended_at >= cutoff,
                      ~ingested)
              .all())
    return sum(1 for (mid,) in rows if mid not in known_ids)


def last_game(db, team_a, team_b, now):
    """The overlay payload for two team ids, in the order given, or None when either
    team is unknown. `teams` and `series_score` follow the given order, and so do
    the game's team columns (not radiant/dire)."""
    names = {t.id: t.name for t in db.query(Team).filter(Team.id.in_([team_a, team_b]))}
    if team_a not in names or team_b not in names:
        return None

    series = _current_series(db, team_a, team_b, now)
    wins_a, wins_b = schedule._tally_wins(
        [(m.radiant_team_id, m.radiant_win) for m in series], team_a)
    pending = _pending_count(db, team_a, team_b, now, {m.match_id for m in series})

    game = None
    if series:
        newest = series[-1]
        players = schedule.game_players(db, newest.match_id) or {}
        by_team = {t["team_id"]: t for t in players.get("teams", [])}
        if newest.radiant_win is None:
            winner = None
        else:
            winner = newest.radiant_team_id if newest.radiant_win else newest.dire_team_id
        game = {
            "match_id": newest.match_id,
            "game_number": len(series),
            "winner_team_id": winner,
            "duration": newest.duration,
            "start_time": newest.start_time,
            "parse_status": players.get("parse_status", newest.parse_status),
            "excluded_from_scoring": players.get("excluded_from_scoring",
                                                 bool(newest.excluded_from_scoring)),
            "teams": [by_team.get(t) or {"team_id": t, "team_name": names[t], "players": []}
                      for t in (team_a, team_b)],
        }

    return {
        "teams": [{"team_id": t, "team_name": names[t]} for t in (team_a, team_b)],
        "series_score": {str(team_a): wins_a, str(team_b): wins_b},
        "pending_game": len(series) + pending if pending else None,
        "game": game,
    }
