"""Typed Dota ids to names and medals (issue 214, shared since issue #220).

Admin › Player Management and the Team Finder's captain form both preview typed ids:
the pool's name first, else OpenDota's personaname. OpenDota answers (including "no
such player") are cached in process for ten minutes, so retyping an id doesn't spend
OpenDota quota; failures are not cached, so the next lookup retries.
"""
import re
import threading
import time

from fastapi import HTTPException

from models import Player
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json
from opendota_client import get_json_once as opendota_get_json_once, try_throttle
from player_rank import medal_name, parse_rank
from steam_openid import STEAM32_OFFSET
from text_safety import clean_display_text

# Interactive lookups fail fast instead of using the long backoff shared with the
# background jobs (see routers/admin_players.py).
INTERACTIVE_RETRIES = 2
INTERACTIVE_BACKOFF = 2.0
INTERACTIVE_TIMEOUT = 6.0

LOOKUP_MAX_IDS = 50
LOOKUP_TTL_SECONDS = 600
LOOKUP_CACHE_MAX = 5000   # entries; expired ones are pruned first, then the oldest
# account id -> (expires_at, personaname or None, rank_tier, leaderboard_rank)
_lookup_cache: dict = {}
_lookup_lock = threading.Lock()

MAX_ACCOUNT_ID = 2**32 - 1   # Dota's 32-bit friend id
UNKNOWN_PLAYER = "Unknown player"
NAME_MAX = 64   # OpenDota personanames are player-chosen: cleaned and capped before caching

# Issue #220: captains' lookups share the server's OpenDota budget with ingest, so they
# are capped per user and in total (uncached ids per rolling hour), never wait for the
# rate window, and never retry. Over a cap or with the window full an id is simply
# "Unknown player" (not cached, so it can be looked up again later).
CAPTAIN_USER_PER_HOUR = 20
CAPTAIN_TOTAL_PER_HOUR = 60
CAPTAIN_TIMEOUT = 4.0
_BUDGET_WINDOW = 3600
_captain_calls: dict = {}    # user key -> [wall times of OpenDota calls]
_captain_total: list = []    # wall times of every captain OpenDota call


def _lookup_now() -> float:
    return time.monotonic()


def clear_lookup_cache() -> None:
    with _lookup_lock:
        _lookup_cache.clear()
        _captain_calls.clear()
        _captain_total.clear()


def _clean_name(profile, pid: int) -> str:
    return clean_display_text(profile.get("personaname"), NAME_MAX) or str(pid)


def _parse_lookup_ids(raw: str) -> list[int]:
    """Admin lookup: a comma-separated list of positive ids, as typed (no conversion)."""
    parts = [s.strip() for s in raw.split(",")]
    if not parts or any(not s for s in parts):
        raise HTTPException(status_code=422, detail="ids must be a comma-separated list of OpenDota ids")
    if len(parts) > LOOKUP_MAX_IDS:
        raise HTTPException(status_code=422, detail=f"At most {LOOKUP_MAX_IDS} ids per lookup")
    ids = []
    for s in parts:
        if not re.fullmatch(r"\d{1,19}", s) or not 0 < int(s) <= 2**63 - 1:
            raise HTTPException(status_code=422, detail="Each id must be a positive whole number")
        ids.append(int(s))
    return ids


def to_account_id(value) -> int:
    """A 32-bit Dota id from a typed 32-bit id or a Steam64 id (converted); 422 otherwise."""
    s = str(value).strip()
    if not re.fullmatch(r"\d{1,19}", s):
        raise HTTPException(status_code=422, detail="Dota ids are digits only")
    n = int(s)
    if STEAM32_OFFSET < n <= STEAM32_OFFSET + MAX_ACCOUNT_ID:
        n -= STEAM32_OFFSET
    if not 0 < n <= MAX_ACCOUNT_ID:
        raise HTTPException(status_code=422, detail="Not a Dota id or a Steam64 id")
    return n


def parse_ids(raw: str, max_ids: int = LOOKUP_MAX_IDS) -> list[int]:
    """Comma- or space-separated Dota or Steam64 ids, as 32-bit ids in typed order."""
    parts = [s for s in re.split(r"[,\s]+", raw or "") if s]
    if not parts:
        raise HTTPException(status_code=422, detail="Type at least one Dota id")
    if len(parts) > max_ids:
        raise HTTPException(status_code=422, detail=f"At most {max_ids} ids per lookup")
    return [to_account_id(s) for s in parts]


def _prune_lookup_cache(now: float, cache_max: int = LOOKUP_CACHE_MAX) -> None:
    """Keep the cache bounded: drop expired entries, then the oldest beyond the cap.
    Called with _lookup_lock held."""
    if len(_lookup_cache) <= cache_max:
        return
    for key in [k for k, v in _lookup_cache.items() if v[0] <= now]:
        del _lookup_cache[key]
    while len(_lookup_cache) > cache_max:
        del _lookup_cache[next(iter(_lookup_cache))]   # dicts keep insertion order


def opendota_lookup(pid: int, fetch=None, now: float | None = None,
                    cache_max: int | None = None) -> tuple[bool, str | None, int | None, int | None]:
    """(found, name, rank_tier, leaderboard_rank) from the cache or OpenDota; found is
    False when OpenDota has no such player or could not be reached. `fetch`, `now` and
    `cache_max` default to this module's (the admin router passes its own)."""
    fetch = fetch or opendota_get_json
    now = _lookup_now() if now is None else now
    with _lookup_lock:
        hit = _lookup_cache.get(pid)
    if hit and hit[0] > now:
        return hit[1] is not None, hit[1], hit[2], hit[3]
    result = fetch(f"{OPEN_DOTA_URL}/players/{pid}", label=f"player {pid}",
                   retries=INTERACTIVE_RETRIES, base_backoff=INTERACTIVE_BACKOFF,
                   timeout=INTERACTIVE_TIMEOUT)
    if not isinstance(result, dict):
        return False, None, None, None   # unreachable: not cached, so the next lookup retries
    return _store(pid, result, now, LOOKUP_CACHE_MAX if cache_max is None else cache_max)


def _store(pid: int, result: dict, now: float, cache_max: int = LOOKUP_CACHE_MAX):
    profile = result.get("profile") or None
    name = _clean_name(profile, pid) if isinstance(profile, dict) else None
    tier, lb = parse_rank(result) if name else (None, None)
    with _lookup_lock:
        _lookup_cache[pid] = (now + LOOKUP_TTL_SECONDS, name, tier, lb)
        _prune_lookup_cache(now, cache_max)
    return name is not None, name, tier, lb


def cached(pid: int, now: float | None = None):
    """(found, name, tier, lb) from the cache only, or None when not cached."""
    now = _lookup_now() if now is None else now
    with _lookup_lock:
        hit = _lookup_cache.get(pid)
    if hit and hit[0] > now:
        return hit[1] is not None, hit[1], hit[2], hit[3]
    return None


def _take_captain_budget(user_key, wall: float) -> bool:
    """Count one uncached lookup against the user's and the total hourly caps."""
    cutoff = wall - _BUDGET_WINDOW
    with _lookup_lock:
        mine = [t for t in _captain_calls.get(user_key, []) if t > cutoff]
        _captain_total[:] = [t for t in _captain_total if t > cutoff]
        for k in [k for k, v in _captain_calls.items() if not v or v[-1] <= cutoff]:
            del _captain_calls[k]
        if len(mine) >= CAPTAIN_USER_PER_HOUR or len(_captain_total) >= CAPTAIN_TOTAL_PER_HOUR:
            _captain_calls[user_key] = mine
            return False
        mine.append(wall)
        _captain_calls[user_key] = mine
        _captain_total.append(wall)
        return True


def captain_lookup(pid: int, user_key, now: float | None = None, wall: float | None = None):
    """(found, name, tier, lb) for a captain's typed id: the cache, else one OpenDota
    call within the caps and only if the rate window has room right now."""
    now = _lookup_now() if now is None else now
    hit = cached(pid, now)
    if hit is not None:
        return hit
    if not _take_captain_budget(user_key, time.time() if wall is None else wall):
        return False, None, None, None
    if not try_throttle():
        return False, None, None, None
    result = opendota_get_json_once(f"{OPEN_DOTA_URL}/players/{pid}", timeout=CAPTAIN_TIMEOUT,
                                    label=f"player {pid}")
    if not isinstance(result, dict):
        return False, None, None, None
    return _store(pid, result, now)


def describe(db, ids: list[int], known: dict | None = None, *, user_key=None,
             fetch: bool = True) -> list[dict]:
    """Name and medal per 32-bit id, in order: `known` rows first (already stored),
    then the player pool, then the lookup cache, then (with `fetch`) one capped,
    non-blocking OpenDota call per id (captain_lookup); otherwise name None
    ("Unknown player"). After a failed call the rest of the ids skip OpenDota."""
    known = known or {}
    pool = {p.id: p for p in db.query(Player).filter(Player.id.in_(set(ids))).all()} if ids else {}
    out = []
    for pid in ids:
        if pid in known:
            name, tier, lb, source = known[pid]
        elif pid in pool and pool[pid].name:
            p = pool[pid]
            name, tier, lb, source = p.name, p.rank_tier, p.leaderboard_rank, "pool"
        else:
            hit = cached(pid)
            if hit is None and fetch:
                hit = captain_lookup(pid, user_key)
                fetch = cached(pid) is not None   # a failed or refused call isn't cached
            found, name, tier, lb = hit or (False, None, None, None)
            source = "opendota" if found else None
        out.append({"account_id": pid, "name": name, "rank_tier": tier, "leaderboard_rank": lb,
                    "medal": medal_name(tier, lb), "source": source})
    return out
