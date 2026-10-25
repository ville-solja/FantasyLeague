"""Matches added outside the league (issue 224): replay JSON validation, the preview
shown before storing, the replace rule, and the request handling behind
POST /admin/matches/manual/preview and POST /admin/matches/manual (the routes are in
routers/admin_matches.py). Storing goes through ingest.store_manual_match. See markdown/features/reference/matches-outside-the-league.md."""

import json
import logging
import math
import re
from typing import Annotated

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

import ingest
from accolades import league_division
from deps import _audit
from ingest import MIN_MATCH_SECONDS
from models import AuditLog, League, Match, Player, PlayerMatchStats, Team

logger = logging.getLogger(__name__)

REPLAY_MAX_BYTES = 56 * 1024  # under main.py's MAX_REQUEST_BODY_BYTES (64 KB) with the envelope; a real summary is 5-10 KB
_MAX_ID = 2**63 - 1

# Every stat ingest._build_stat_row reads, with its type and sane range. A replay
# summary must carry each one (0 for a stat the parser couldn't give, listed under
# missing_stats).
STAT_FIELDS = {
    "kills": (int, 0, 200),
    "deaths": (int, 0, 200),
    "assists": (int, 0, 200),
    "last_hits": (int, 0, 5000),
    "denies": (int, 0, 1000),
    "gold_per_min": (int, 0, 3000),
    "obs_placed": (int, 0, 200),
    "sen_placed": (int, 0, 300),
    "tower_damage": (int, 0, 100000),
    "towers_killed": (int, 0, 11),
    "roshan_kills": (int, 0, 10),
    "teamfight_participation": (float, 0, 1),
    "camps_stacked": (int, 0, 300),
    "rune_pickups": (int, 0, 500),
    "firstblood_claimed": (int, 0, 1),
    "stuns": (float, 0, 7200),
}

_REQUIRED_TOP = ("match_id", "start_time", "duration", "radiant_win", "players")
_OPTIONAL_TOP = ("radiant_name", "dire_name", "picks_bans", "missing_stats")
_REQUIRED_PLAYER = ("account_id", "side", "hero_id") + tuple(STAT_FIELDS)
_OPTIONAL_PLAYER = ("personaname",)
_PICK_BAN_KEYS = ("hero_id", "is_pick", "team", "order")

# Dota 2 hero ids up to Largo (155). The server also accepts any id in the cached
# OpenDota hero constants (schedule.hero_name_map), so a hero released later works
# once the cache is warm.
KNOWN_HERO_IDS = frozenset(
    list(range(1, 24)) + list(range(25, 115))
    + [119, 120, 121, 123, 126, 128, 129, 131, 135, 136, 137, 138, 145, 155]
)

_START_TIME_MIN = 1_262_304_000   # 2010-01-01
_START_TIME_MAX = 4_102_444_800   # 2100-01-01
_DURATION_MAX = 4 * 3600


class ManualMatchError(Exception):
    """A refusal with the field that failed (None when it is about the whole match)
    and the HTTP status the router answers with."""

    def __init__(self, message: str, field: str | None = None, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.field = field
        self.status_code = status_code

    @property
    def detail(self) -> str:
        return f"{self.field}: {self.message}" if self.field else self.message


def _known_hero_ids() -> set:
    try:
        import schedule
        return set(KNOWN_HERO_IDS) | set(schedule.hero_name_map())
    except Exception:
        return set(KNOWN_HERO_IDS)


def _int(value, field, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManualMatchError("must be an integer", field)
    if value < lo or value > hi:
        raise ManualMatchError(f"must be between {lo} and {hi}", field)
    return value


def _number(value, field, kind, lo, hi):
    if kind is int:
        return _int(value, field, lo, hi)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ManualMatchError("must be a number", field)
    if value < lo or value > hi:
        raise ManualMatchError(f"must be between {lo} and {hi}", field)
    return float(value)


def _name(value, field):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 100:
        raise ManualMatchError("must be text of at most 100 characters", field)
    return value.strip() or None


def _check_keys(obj, required, optional, prefix):
    for key in obj:
        if key not in required and key not in optional:
            raise ManualMatchError("unknown key", f"{prefix}{key}")
    for key in required:
        if key not in obj:
            raise ManualMatchError("is required", f"{prefix}{key}")


def validate_replay(payload, known_hero_ids=None) -> dict:
    """Validate a replay summary (the JSON scripts/replay_to_match.py writes) against
    the strict schema and return it normalised. Raises ManualMatchError naming the
    field that failed."""
    if not isinstance(payload, dict):
        raise ManualMatchError("must be a JSON object", "replay")
    heroes = _known_hero_ids() if known_hero_ids is None else set(known_hero_ids)
    _check_keys(payload, _REQUIRED_TOP, _OPTIONAL_TOP, "")

    out = {
        "match_id": _int(payload["match_id"], "match_id", 1, _MAX_ID),
        "start_time": _int(payload["start_time"], "start_time", _START_TIME_MIN, _START_TIME_MAX),
        "duration": _int(payload["duration"], "duration", 1, _DURATION_MAX),
        "radiant_name": _name(payload.get("radiant_name"), "radiant_name"),
        "dire_name": _name(payload.get("dire_name"), "dire_name"),
    }
    if not isinstance(payload["radiant_win"], bool):
        raise ManualMatchError("must be true or false", "radiant_win")
    out["radiant_win"] = payload["radiant_win"]

    missing = payload.get("missing_stats", [])
    if not isinstance(missing, list):
        raise ManualMatchError("must be a list", "missing_stats")
    for i, name in enumerate(missing):
        if name not in STAT_FIELDS:
            raise ManualMatchError(f"unknown stat {name!r}", f"missing_stats[{i}]")
    out["missing_stats"] = sorted(set(missing), key=list(STAT_FIELDS).index)

    picks_bans = payload.get("picks_bans", [])
    if not isinstance(picks_bans, list) or len(picks_bans) > 48:
        raise ManualMatchError("must be a list of at most 48 entries", "picks_bans")
    out["picks_bans"] = []
    for i, pb in enumerate(picks_bans):
        prefix = f"picks_bans[{i}]."
        if not isinstance(pb, dict):
            raise ManualMatchError("must be an object", f"picks_bans[{i}]")
        _check_keys(pb, ("hero_id", "is_pick", "team"), ("order",), prefix)
        if pb["hero_id"] not in heroes or isinstance(pb["hero_id"], bool):
            raise ManualMatchError("unknown hero id", prefix + "hero_id")
        if not isinstance(pb["is_pick"], bool):
            raise ManualMatchError("must be true or false", prefix + "is_pick")
        entry = {"hero_id": pb["hero_id"], "is_pick": pb["is_pick"],
                 "team": _int(pb["team"], prefix + "team", 0, 1)}
        if "order" in pb:
            entry["order"] = _int(pb["order"], prefix + "order", 0, 100)
        out["picks_bans"].append(entry)

    players = payload["players"]
    if not isinstance(players, list) or len(players) != 10:
        raise ManualMatchError("must list exactly ten players", "players")
    seen_accounts = set()
    normalised = []
    for i, p in enumerate(players):
        prefix = f"players[{i}]."
        if not isinstance(p, dict):
            raise ManualMatchError("must be an object", f"players[{i}]")
        _check_keys(p, _REQUIRED_PLAYER, _OPTIONAL_PLAYER, prefix)
        account_id = _int(p["account_id"], prefix + "account_id", 1, _MAX_ID)
        if account_id in seen_accounts:
            raise ManualMatchError("appears twice", prefix + "account_id")
        seen_accounts.add(account_id)
        if p["side"] not in ("radiant", "dire"):
            raise ManualMatchError('must be "radiant" or "dire"', prefix + "side")
        if isinstance(p["hero_id"], bool) or p["hero_id"] not in heroes:
            raise ManualMatchError("unknown hero id", prefix + "hero_id")
        row = {"account_id": account_id, "side": p["side"], "hero_id": p["hero_id"],
               "personaname": _name(p.get("personaname"), prefix + "personaname")}
        for stat, (kind, lo, hi) in STAT_FIELDS.items():
            row[stat] = _number(p[stat], prefix + stat, kind, lo, hi)
        normalised.append(row)
    radiant = sum(1 for p in normalised if p["side"] == "radiant")
    if radiant != 5:
        raise ManualMatchError(f"needs five players per side (radiant {radiant}, dire {10 - radiant})",
                               "players[].side")
    out["players"] = normalised
    return out


def replay_to_store_payload(replay: dict) -> dict:
    """A validated replay summary in the OpenDota /matches/{id} shape that
    ingest._build_stat_row and fantasy_score read."""
    missing = set(replay.get("missing_stats") or [])
    players, slots = [], {"radiant": 0, "dire": 128}
    for p in replay["players"]:
        slot = slots[p["side"]]
        slots[p["side"]] += 1
        row = {k: v for k, v in p.items() if k != "side"}
        for stat in missing:  # a stat the parser couldn't give always counts as 0
            row[stat] = 0.0 if STAT_FIELDS[stat][0] is float else 0
        row["isRadiant"] = p["side"] == "radiant"
        row["player_slot"] = slot
        players.append(row)
    return {
        "match_id": replay["match_id"],
        "start_time": replay["start_time"],
        "duration": replay["duration"],
        "radiant_win": replay["radiant_win"],
        "radiant_name": replay.get("radiant_name"),
        "dire_name": replay.get("dire_name"),
        "picks_bans": list(replay.get("picks_bans") or []),
        "players": players,
        "missing_stats": list(replay.get("missing_stats") or []),
    }


def check_opendota_data(data, match_id: int) -> dict:
    """Refusals for an OpenDota /matches/{id} answer: unavailable or without player
    data, or shorter than 15 minutes."""
    players = data.get("players") if isinstance(data, dict) else None
    if not players or not any(isinstance(p, dict) and p.get("account_id") for p in players):
        raise ManualMatchError(
            f"OpenDota has no player data for match {match_id}. Use a replay import instead.")
    check_short(data.get("duration"), match_id)
    return data


def check_short(duration, match_id: int) -> None:
    if duration is not None and duration < MIN_MATCH_SECONDS:
        raise ManualMatchError(
            f"Match {match_id} is shorter than 15 minutes ({duration // 60} min {duration % 60} s)")


def existing_match(db, match_id: int, confirm: bool | None = None):
    """The replace rule. A league-ingested match is refused (409) whatever `confirm`
    says. An earlier manual or replay match is returned; with confirm=False it is
    refused (409) until the admin confirms the replacement. None when not stored."""
    match = db.get(Match, match_id)
    if match is None:
        return None
    if (match.source or "league") == "league":
        raise ManualMatchError(
            f"Match {match_id} is already stored as a league match and is never replaced",
            status_code=409)
    if confirm is False:
        raise ManualMatchError(
            f"Match {match_id} was already added ({match.source}). Confirm to replace its stats.",
            status_code=409)
    return match


def monitored_leagues(db) -> list[dict]:
    rows = db.query(League).filter(League.is_monitored == True).order_by(League.id).all()  # noqa: E712
    out = []
    for lg in rows:
        div = league_division(lg.name)
        out.append({"id": lg.id, "name": lg.name, "division": div,
                    "division_label": "Div 2" if div == "div2" else "Div 1"})
    return out


def check_league(db, league_id) -> None:
    if league_id is None:
        raise ManualMatchError("choose a league", "league_id")
    if not any(lg["id"] == league_id for lg in monitored_leagues(db)):
        raise ManualMatchError("is not a monitored league", "league_id")


def check_teams(db, radiant_team_id, dire_team_id) -> None:
    for field, tid in (("radiant_team_id", radiant_team_id), ("dire_team_id", dire_team_id)):
        side = "Radiant" if field.startswith("radiant") else "Dire"
        if not tid:
            raise ManualMatchError(f"choose the {side} team", field)
        if db.get(Team, tid) is None:
            raise ManualMatchError(f"unknown {side} team", field)
    if radiant_team_id == dire_team_id:
        raise ManualMatchError("Radiant and Dire must be different teams", "dire_team_id")


def _norm(name) -> str:
    return " ".join(str(name or "").split()).lower()


def suggest_team_id(name, teams) -> int | None:
    key = _norm(name)
    if not key:
        return None
    hits = [t.id for t in teams if _norm(t.name) == key]
    return hits[0] if len(hits) == 1 else None


def build_preview(db, data: dict, source: str, missing_stats=None) -> dict:
    """The preview both Add match paths show before storing. `data` is OpenDota-shaped."""
    import schedule

    match_id = int(data["match_id"])
    teams = db.query(Team).order_by(Team.name).all()
    hero_names = {}
    try:
        hero_names = schedule.hero_name_map()
    except Exception:
        pass

    raw = [p for p in data.get("players") or [] if isinstance(p, dict)]
    ids = [p.get("account_id") for p in raw if p.get("account_id")]
    known = {pl.id: pl for pl in db.query(Player).filter(Player.id.in_(ids)).all()} if ids else {}
    players = []
    for p in raw:
        aid = p.get("account_id")
        is_radiant = p.get("isRadiant")
        if is_radiant is None and p.get("player_slot") is not None:
            is_radiant = p["player_slot"] < 128
        db_player = known.get(aid)
        players.append({
            "account_id": aid,
            "name": p.get("personaname") or (db_player.name if db_player else None),
            "side": "radiant" if is_radiant else "dire",
            "hero_id": p.get("hero_id"),
            "hero_name": hero_names.get(p.get("hero_id")),
            "kills": p.get("kills", 0),
            "deaths": p.get("deaths", 0),
            "assists": p.get("assists", 0),
            "in_pool": bool(db_player and db_player.is_active),
        })
    players.sort(key=lambda r: (r["side"] != "radiant"))
    missing = list(missing_stats or [])
    existing = db.get(Match, match_id)
    radiant_win = data.get("radiant_win")
    return {
        "source": source,
        "match_id": match_id,
        "start_time": data.get("start_time"),
        "duration": data.get("duration"),
        "radiant_win": radiant_win,
        "winner": None if radiant_win is None else ("radiant" if radiant_win else "dire"),
        "radiant_name": data.get("radiant_name"),
        "dire_name": data.get("dire_name"),
        "suggested_radiant_team_id": suggest_team_id(data.get("radiant_name"), teams),
        "suggested_dire_team_id": suggest_team_id(data.get("dire_name"), teams),
        "players": players,
        "not_in_pool": [p["account_id"] for p in players if not p["in_pool"]],
        "missing_stats": missing,
        "partial_note": f"Partial stats: {', '.join(missing)}" if missing else None,
        "existing_source": existing.source if existing is not None else None,
        "leagues": monitored_leagues(db),
        "teams": [{"id": t.id, "name": t.name} for t in teams],
    }


# ---------------------------------------------------------------------------
# Request handling for POST /admin/matches/manual/preview and /admin/matches/manual
# (routers/admin_matches.py)
# ---------------------------------------------------------------------------

_ADDED_MATCH_ID = re.compile(r"\bmatch_id=(\d+)")


def added_by_match(db) -> dict:
    """match_id -> (actor_username, timestamp) of its latest admin_match_added audit row."""
    out = {}
    rows = (db.query(AuditLog.detail, AuditLog.actor_username, AuditLog.timestamp)
            .filter(AuditLog.action == "admin_match_added")
            .order_by(AuditLog.timestamp, AuditLog.id).all())
    for detail, actor, ts in rows:
        found = _ADDED_MATCH_ID.search(detail or "")
        if found:
            out[int(found.group(1))] = (actor, ts)
    return out


_Id = Annotated[int, Field(ge=1, le=2**63 - 1)]
# The replay summary may be up to REPLAY_MAX_BYTES; the rest of the body is a few ids.
_BODY_MAX_BYTES = REPLAY_MAX_BYTES + 4096


class ManualMatchBody(BaseModel):
    """Either `match_id` (from OpenDota) or `replay` (a replay summary), plus, for
    storing, the league, the two teams and `confirm` to replace an earlier manual match."""
    model_config = ConfigDict(extra="forbid")

    match_id: _Id | None = None
    replay: dict | None = None
    league_id: _Id | None = None
    radiant_team_id: _Id | None = None
    dire_team_id: _Id | None = None
    confirm: bool = False


async def read_body(request: Request) -> ManualMatchBody:
    """The request body, size-checked before it is parsed: 413 above the limit, 422 for
    anything that isn't the expected JSON object."""
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > _BODY_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"The replay file is larger than {REPLAY_MAX_BYTES // 1024} KB")
    raw = await request.body()
    if len(raw) > _BODY_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"The replay file is larger than {REPLAY_MAX_BYTES // 1024} KB")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(status_code=422, detail="The request is not valid JSON")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="The request must be a JSON object")
    try:
        body = ManualMatchBody.model_validate(data)
    except ValidationError as e:
        err = e.errors()[0]
        field = ".".join(str(x) for x in err.get("loc", ())) or "body"
        raise HTTPException(status_code=422, detail=f"{field}: {err.get('msg', 'invalid')}")
    if (body.match_id is None) == (body.replay is None):
        raise HTTPException(status_code=422, detail="Give either a match id or a replay file")
    return body


def _fetch_opendota_match(match_id: int):
    try:
        data = ingest.opendota_get_json(f"{ingest.OPEN_DOTA_URL}/matches/{match_id}",
                                        label=f"match {match_id} (add match)")
    except Exception:
        logger.exception("Add match: OpenDota fetch for %d failed", match_id)
        return None
    if isinstance(data, dict):
        data = dict(data)
        data["match_id"] = match_id
    return data


def _manual_payload(db, body: ManualMatchBody):
    """(source, OpenDota-shaped payload, missing stats) for either path, with every
    refusal that doesn't depend on the league or teams."""
    if body.replay is not None:
        replay = validate_replay(body.replay)
        existing_match(db, replay["match_id"])
        check_short(replay["duration"], replay["match_id"])
        return "replay", replay_to_store_payload(replay), replay["missing_stats"]
    existing_match(db, body.match_id)  # a league duplicate needs no OpenDota call
    data = _fetch_opendota_match(body.match_id)
    check_opendota_data(data, body.match_id)
    return "opendota_manual", data, []


def preview(db, body: ManualMatchBody) -> dict:
    try:
        source, data, missing = _manual_payload(db, body)
    except ManualMatchError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return build_preview(db, data, source, missing)


def store(db, body: ManualMatchBody, admin: dict) -> dict:
    try:
        check_league(db, body.league_id)
        check_teams(db, body.radiant_team_id, body.dire_team_id)
        source, data, missing = _manual_payload(db, body)
        match_id = int(data["match_id"])
        existing = existing_match(db, match_id, confirm=body.confirm)
    except ManualMatchError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    previous_source = existing.source if existing is not None else None

    if not ingest.INGEST_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="An ingest is already in progress — try again shortly")
    try:
        outcome = ingest.store_manual_match(
            db, data, body.league_id, body.radiant_team_id, body.dire_team_id, source,
            replace=existing is not None,
            actor_id=admin["user_id"], actor_username=admin["username"],
        )
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(e))
    finally:
        ingest.INGEST_LOCK.release()
    if outcome != "stored":
        raise HTTPException(status_code=422, detail=f"Match {match_id} is shorter than 15 minutes")

    detail = (f"source={source} match_id={match_id} league_id={body.league_id} "
              f"radiant_team_id={body.radiant_team_id} dire_team_id={body.dire_team_id} "
              f"replaced={'yes' if existing is not None else 'no'}")
    if previous_source:
        detail += f" previous_source={previous_source}"
    if missing:
        detail += f" missing_stats={','.join(missing)}"
    _audit(db, "admin_match_added", actor_id=admin["user_id"], actor_username=admin["username"],
           detail=detail)
    db.commit()
    match = db.get(Match, match_id)
    return {
        "match_id": match_id,
        "source": match.source,
        "league_id": match.league_id,
        "radiant_team_id": match.radiant_team_id,
        "dire_team_id": match.dire_team_id,
        "parse_status": match.parse_status,
        "missing_stats": missing,
        "replaced": existing is not None,
        "players": db.query(PlayerMatchStats).filter(PlayerMatchStats.match_id == match_id).count(),
    }
