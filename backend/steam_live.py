"""Live games of monitored leagues, from Steam's IDOTA2Match_570/GetLiveLeagueGames (issue #161).

OpenDota's /live mirrors Steam's top-live-games list and so misses amateur-league games;
Steam's league list has every live league game. Checked by main._live_poll_loop.

The response shape is built from Steam's documentation and has not yet been checked
against a real capture (see markdown/features/reference/mvp-selection-delays.md).
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "").strip()
_URL = "https://api.steampowered.com/IDOTA2Match_570/GetLiveLeagueGames/v1/"
_TIMEOUT = 10

# Unix time of the last successful live check (set by main._live_poll_once); None
# until one succeeds. Read by GET /twitch/matches/current.
live_checked_at: int | None = None


def _int_or_none(val) -> int | None:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return None
    return n or None


def _normalise_game(game: dict) -> dict:
    """One Steam game as the entry shape ingest.store_live_matches() reads."""
    radiant = game.get("radiant_team") if isinstance(game.get("radiant_team"), dict) else {}
    dire = game.get("dire_team") if isinstance(game.get("dire_team"), dict) else {}
    players = []
    for p in game.get("players") or []:
        if not isinstance(p, dict) or p.get("team") not in (0, 1):
            continue  # 2 or more: casters and spectators
        account_id = _int_or_none(p.get("account_id"))
        if account_id is None:
            continue
        players.append({"account_id": account_id, "name": p.get("name") or None, "team": p["team"]})
    return {
        "match_id": _int_or_none(game.get("match_id")),
        "league_id": _int_or_none(game.get("league_id")),
        "team_id_radiant": _int_or_none(radiant.get("team_id")),
        "team_id_dire": _int_or_none(dire.get("team_id")),
        "team_name_radiant": radiant.get("team_name") or None,
        "team_name_dire": dire.get("team_name") or None,
        "players": players,
    }


def parse_live_league_games(data, league_ids) -> list[dict] | None:
    """Normalised games of `league_ids` from a GetLiveLeagueGames response; None if malformed."""
    result = data.get("result") if isinstance(data, dict) else None
    games = result.get("games") if isinstance(result, dict) else None
    if not isinstance(games, list):
        return None
    wanted = set(league_ids or ())
    entries = []
    for game in games:
        if not isinstance(game, dict):
            continue
        entry = _normalise_game(game)
        if entry["match_id"] is None or entry["league_id"] not in wanted:
            continue
        entries.append(entry)
    return entries


def get_live_league_games(league_ids) -> list[dict] | None:
    """Live games of the given leagues, normalised to the store_live_matches() entry
    shape; None when the request fails (never raises, never logs the key).

    One request with no league filter (the list is filtered here), one attempt,
    a 10 s timeout and no retries."""
    if not STEAM_API_KEY:
        return None
    try:
        resp = requests.get(_URL, params={"key": STEAM_API_KEY}, timeout=_TIMEOUT)
    except Exception as exc:
        # The exception text can contain the request URL, and so the key.
        logger.warning("Steam live check failed: %s", type(exc).__name__)
        return None
    if resp.status_code != 200:
        logger.warning("Steam live check failed: HTTP %s", resp.status_code)
        return None
    try:
        data = resp.json()
    except Exception as exc:
        logger.warning("Steam live check failed: invalid JSON (%s)", type(exc).__name__)
        return None
    entries = parse_live_league_games(data, league_ids)
    if entries is None:
        logger.warning("Steam live check failed: unexpected response shape")
    return entries
