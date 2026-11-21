"""Mock OpenDota and Steam GetLiveLeagueGames for dev and test servers (issue #146).

Serves the OpenDota paths the app calls and Steam's live-league list from a scripted,
in-memory season built by `backend/season_generator.py`, so the app's real polling code
(ingest, live poll, parse retry) runs against it. Control endpoints under `/_control/`
release matches, make a game live and mark a match parsed. Dev only: never in the
production image, published on 127.0.0.1 only (docker-compose.mock.yml).

Run: uvicorn app:create_app --factory --port 8090 --no-access-log (see README.md).
"""

import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (os.getenv("MOCK_BACKEND_DIR"), "/backend",
                   os.path.join(_HERE, "..", "..", "backend")):
    if _candidate and os.path.isfile(os.path.join(_candidate, "season_generator.py")):
        if os.path.abspath(_candidate) not in map(os.path.abspath, sys.path):
            sys.path.insert(0, os.path.abspath(_candidate))
        break

# season_generator and scenarios import the backend's models, and so `database`: point
# it at an in-memory SQLite so the mock never creates or opens a database file.
if "database" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import JSONResponse, PlainTextResponse  # noqa: E402
from pydantic import BaseModel, Field, StrictBool, StrictInt  # noqa: E402

import scenarios  # noqa: E402
import season_generator  # noqa: E402
from scoring import SCORING_STATS  # noqa: E402

STEAM_LIVE_PATH = "/IDOTA2Match_570/GetLiveLeagueGames/v1/"
# MOCK_SEED leagues: their own ids, so they never collide with a loaded scenario.
SEEDED_LEAGUE_BASE = 990100
SEEDED_TEAM_OFFSET = 900
SEEDED_PLAYER_OFFSET = 900_000
SEEDED_MATCH_OFFSET = 1_000_000_000
# OpenDota's GET /matches/{id} has a non-null "version" once the replay is parsed.
PARSED_VERSION = 21
_STAT_KEYS = tuple(SCORING_STATS) + ("deaths",)
_MAX_LIVE_MINUTES = 24 * 60


def _env_seed():
    raw = os.getenv("MOCK_SEED")
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        raise ValueError("MOCK_SEED must be an integer (or unset for the mid-season scenario)") from None


def build_script(seed=None) -> dict:
    """The scripted league: {"league_id", "league_name", "teams", "players", "matches"}.
    Matches are sorted by start time. Without a seed: the mid-season scenario's unplayed
    weeks in scenarios.SCENARIO_LEAGUE_ID, with the scenario's ids."""
    if seed is None:
        spec = dict(scenarios.SCENARIOS["mid-season"])
        scenario_seed, locked = spec.pop("seed"), spec.pop("locked_weeks")
        season = season_generator.generate(scenario_seed, users=len(scenarios.ACCOUNT_NAMES),
                                           **scenarios._SEASON, **spec)
        matches = [m for m in season["matches"] if m["week"] > locked]
        teams = {t["id"]: t["name"] for t in season["teams"]}
        players = {p["id"]: p["name"] for p in season["players"]}
        league_id, league_name = scenarios.SCENARIO_LEAGUE_ID, scenarios.SCENARIO_LEAGUE_NAME
    else:
        season = season_generator.generate(
            seed, weeks=5, teams=8, players_per_team=5, games_per_team_week=2, users=0,
            cards_per_user=0, roster_size=5, start=scenarios.SCENARIO_START, window_days=5)
        t_off, p_off, m_off = SEEDED_TEAM_OFFSET, SEEDED_PLAYER_OFFSET, SEEDED_MATCH_OFFSET
        teams = {t["id"] + t_off: f"Mock Team {t['name'].rsplit(' ', 1)[-1]}" for t in season["teams"]}
        players = {p["id"] + p_off: f"mock_{p['name']}" for p in season["players"]}
        matches = []
        for m in season["matches"]:
            m = dict(m)
            m["match_id"] += m_off
            m["radiant_team_id"] += t_off
            m["dire_team_id"] += t_off
            m["radiant_name"] = teams[m["radiant_team_id"]]
            m["dire_name"] = teams[m["dire_team_id"]]
            m["stats"] = [{**s, "player_id": s["player_id"] + p_off, "team_id": s["team_id"] + t_off}
                          for s in m["stats"]]
            matches.append(m)
        league_id, league_name = SEEDED_LEAGUE_BASE + seed % 900, f"Mock League {seed}"
    matches.sort(key=lambda m: (m["start_time"], m["match_id"]))
    return {"league_id": league_id, "league_name": league_name, "teams": teams,
            "players": players, "matches": matches}


def _picks_bans(match: dict) -> list[dict]:
    picked = [s["hero_id"] for s in match["stats"]]
    out = [{"is_pick": True, "hero_id": h, "team": 0 if s["team_id"] == match["radiant_team_id"] else 1,
            "order": i} for i, (h, s) in enumerate(zip(picked, match["stats"]))]
    bans, k = [], 0
    while len(bans) < 4:
        hero = 1 + (match["match_id"] * 7 + k * 13) % 120
        k += 1
        if hero not in picked and hero not in bans:
            bans.append(hero)
    out += [{"is_pick": False, "hero_id": h, "team": i % 2, "order": len(out) + i}
            for i, h in enumerate(bans)]
    return out


def match_json(match: dict, players: dict, parsed: bool, league_id: int) -> dict:
    """GET /matches/{id} in OpenDota's shape, as ingest.py reads it. Unparsed: no
    "version" and only season_generator.UNPARSED_STATS per player, as OpenDota does
    before the replay is parsed."""
    keep = _STAT_KEYS if parsed else season_generator.UNPARSED_STATS
    out_players = []
    side_slot = {True: 0, False: 128}
    for s in match["stats"]:
        radiant = s["team_id"] == match["radiant_team_id"]
        row = {"account_id": s["player_id"], "isRadiant": radiant,
               "player_slot": side_slot[radiant], "hero_id": s["hero_id"],
               "personaname": players.get(s["player_id"])}
        side_slot[radiant] += 1
        row.update({k: s[k] for k in keep})
        out_players.append(row)
    data = {
        "match_id": match["match_id"], "leagueid": league_id,
        "start_time": match["start_time"], "duration": match["duration"],
        "radiant_win": match["radiant_win"],
        "radiant_team_id": match["radiant_team_id"], "dire_team_id": match["dire_team_id"],
        "radiant_name": match["radiant_name"], "dire_name": match["dire_name"],
        "picks_bans": _picks_bans(match), "players": out_players,
    }
    if parsed:
        data["version"] = PARSED_VERSION
    return data


def steam_game_json(match: dict, players: dict, league_id: int) -> dict:
    """One game of Steam's GetLiveLeagueGames, as steam_live.parse_live_league_games reads
    it. Every other player has no name, as Steam often sends."""
    out_players = []
    for i, s in enumerate(match["stats"]):
        p = {"account_id": s["player_id"], "hero_id": s["hero_id"],
             "team": 0 if s["team_id"] == match["radiant_team_id"] else 1}
        if i % 2 == 0:
            p["name"] = players.get(s["player_id"])
        out_players.append(p)
    return {
        "match_id": match["match_id"], "league_id": league_id, "lobby_id": match["match_id"],
        "radiant_team": {"team_id": match["radiant_team_id"], "team_name": match["radiant_name"]},
        "dire_team": {"team_id": match["dire_team_id"], "team_name": match["dire_name"]},
        "players": out_players,
    }


class NextMatchBody(BaseModel):
    unparsed: StrictBool = False


class LiveBody(BaseModel):
    minutes: StrictInt = Field(gt=0, le=_MAX_LIVE_MINUTES)


class MockState:
    """The script and what has been released, made live and parsed. One lock: uvicorn
    runs these handlers on a thread pool."""

    def __init__(self, script: dict, now):
        self.script = script
        self.now = now
        self.by_id = {m["match_id"]: m for m in script["matches"]}
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.released: dict[int, bool] = {}  # match_id -> parsed
        self.live: dict[int, float] = {}     # match_id -> ends_at
        self.parse_requests: list[int] = []
        self._job = 0

    def live_now(self) -> dict[int, float]:
        now = self.now()
        self.live = {m: end for m, end in self.live.items() if end > now}
        return self.live

    def remaining(self) -> list[dict]:
        return [m for m in self.script["matches"] if m["match_id"] not in self.released]


def create_app(seed: int | None = None, now=None) -> FastAPI:
    """A fresh mock with its own in-memory state. seed: MOCK_SEED when None (unset or
    empty: the mid-season scenario). now: the clock for live games (time.time)."""
    if seed is None:
        seed = _env_seed()
    state = MockState(build_script(seed), now or time.time)
    script = state.script
    league_id = script["league_id"]
    app = FastAPI(title="Mock OpenDota", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.mock = state

    def _not_found():
        return JSONResponse({"error": "Not Found"}, status_code=404)

    # --- OpenDota ------------------------------------------------------------------

    @app.get("/leagues/{lid}")
    def league_info(lid: int):
        if lid != league_id:
            return _not_found()
        return {"leagueid": league_id, "name": script["league_name"], "tier": "amateur"}

    @app.get("/leagues/{lid}/matchIds")
    def league_match_ids(lid: int):
        if lid != league_id:
            return []
        with state.lock:
            return [m["match_id"] for m in script["matches"] if m["match_id"] in state.released]

    @app.get("/matches/{match_id}")
    def match_detail(match_id: int):
        with state.lock:
            if match_id not in state.released:
                return _not_found()
            parsed = state.released[match_id]
        return match_json(state.by_id[match_id], script["players"], parsed, league_id)

    @app.post("/request/{match_id}")
    def request_parse(match_id: int):
        with state.lock:
            state._job += 1
            state.parse_requests.append(match_id)
            return {"job": {"jobId": state._job}}

    @app.get("/constants/heroes")
    def heroes():
        return {str(h): {"id": h, "name": f"npc_dota_hero_mock_{h}", "localized_name": f"Mock Hero {h}"}
                for h in range(1, 121)}

    @app.get("/players/{pid}")
    def player(pid: int):
        name = script["players"].get(pid)
        if name is None:
            return _not_found()
        return {"profile": {"account_id": pid, "personaname": name, "name": None, "avatarfull": ""},
                "rank_tier": None, "leaderboard_rank": None}

    @app.get("/players/{pid}/heroes")
    def player_heroes(pid: int):
        return [] if pid in script["players"] else _not_found()

    @app.get("/players/{pid}/matches")
    def player_matches(pid: int):
        return [] if pid in script["players"] else _not_found()

    # --- Steam ---------------------------------------------------------------------

    @app.get(STEAM_LIVE_PATH)
    def steam_live_games(key: str | None = Query(default=None)):
        # Like Steam: 403 without a key. The key is never echoed in a response; the
        # handler doesn't log it, and the mock runs with --no-access-log (query strings).
        if not key:
            return PlainTextResponse("Forbidden", status_code=403)
        with state.lock:
            live = sorted(state.live_now())
            games = [steam_game_json(state.by_id[m], script["players"], league_id) for m in live]
        return {"result": {"games": games, "status": 200}}

    # --- Control -------------------------------------------------------------------

    @app.post("/_control/next-match")
    def next_match(body: NextMatchBody | None = None):
        body = body or NextMatchBody()
        with state.lock:
            remaining = state.remaining()
            if not remaining:
                raise HTTPException(status_code=409, detail="No scripted match left; POST /_control/reset")
            match = remaining[0]
            state.released[match["match_id"]] = not body.unparsed
            state.live.pop(match["match_id"], None)
            return {"match_id": match["match_id"], "parsed": not body.unparsed,
                    "start_time": match["start_time"], "remaining": len(remaining) - 1}

    @app.post("/_control/live")
    def make_live(body: LiveBody):
        with state.lock:
            live = state.live_now()
            candidates = [m for m in state.remaining() if m["match_id"] not in live]
            if not candidates:
                raise HTTPException(status_code=409, detail="No scripted match left to make live")
            match = candidates[0]
            ends_at = state.now() + body.minutes * 60
            live[match["match_id"]] = ends_at
            return {"match_id": match["match_id"], "ends_at": int(ends_at)}

    @app.post("/_control/parse/{match_id}")
    def parse(match_id: int):
        with state.lock:
            if match_id not in state.released:
                raise HTTPException(status_code=404, detail="Match not released")
            if state.released[match_id]:
                raise HTTPException(status_code=409, detail="Match already parsed")
            state.released[match_id] = True
            return {"match_id": match_id, "parsed": True}

    @app.post("/_control/reset")
    def reset():
        with state.lock:
            state.reset()
            return {"reset": True, "remaining": len(script["matches"])}

    @app.get("/_control/state")
    def control_state():
        with state.lock:
            live = state.live_now()
            return {
                "league_id": league_id,
                "league_name": script["league_name"],
                "released": [m for m in state.released],
                "live": [{"match_id": m, "ends_at": int(end)} for m, end in sorted(live.items())],
                "unparsed": [m for m, parsed in state.released.items() if not parsed],
                "parse_requests": list(state.parse_requests),
                "remaining": len(state.remaining()),
                "scripted": len(script["matches"]),
            }

    return app
