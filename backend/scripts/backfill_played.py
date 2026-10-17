"""
One-off backfill of "played" accolades for seasons before issue #50, from OpenDota.
See markdown/features/reference/season-winners-and-holo-cards.md.

Each division is its own OpenDota league, named after its season ("Kanaliiga Season 14",
"Kanaliiga Season 14 Lower"), so the season label comes from the league names. Take a
backup first (bash scripts/backup-db.sh), then from backend/:

  # find the season's leagues by name and show what would be recorded
  python scripts/backfill_played.py --season "Season 14" --dry-run
  # or name the leagues; the label comes from their names
  python scripts/backfill_played.py --league <div1 id> --league <div2 id> --dry-run
  python scripts/backfill_played.py --league <div1 id> --league <div2 id>

--season is needed only when no --league is given (discovery by name, --name-prefix,
default "Kanaliiga") or when the league names carry no season number; when given with
leagues it must agree with their names. Seasons 1-4 have no numbered OpenDota league:
use Add accolade's Played paste for them.

Every account id in the leagues' matches gets one played row for the season
(source "admin"). Names come from the current player pool, else the match's
personaname, else "Player <id>". Anonymous slots are skipped and counted. Existing
rows are left alone (INSERT … ON CONFLICT DO NOTHING), and fetched league names and
matches are cached in a local JSON file (--cache), so an interrupted run resumes
without fetching them again. Exit code 1 when the season can't be resolved (nothing is
written) or a league can't be read (nothing is recorded for it); 0 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import accolades  # noqa: E402
import database  # noqa: E402
import ingest  # noqa: E402
from models import AuditLog, Player, SeasonAccolade  # noqa: E402
from opendota_client import OPEN_DOTA_URL, get_json as opendota_get_json  # noqa: E402

DEFAULT_CACHE = "backfill_played_cache.json"
MAX_ID = 2**63 - 1
MAX_NAME = 100
DEFAULT_PAUSE_SECONDS = 1.2
DEFAULT_PREFIX = "Kanaliiga"
FIRST_NUMBERED_SEASON = 5  # Seasons 1-4 have no numbered OpenDota league


def fetch_match(match_id: int) -> dict | None:
    return opendota_get_json(f"{OPEN_DOTA_URL}/matches/{match_id}", label=f"match {match_id}")


def fetch_leagues() -> list | None:
    """OpenDota's whole league list (GET /leagues)."""
    return opendota_get_json(f"{OPEN_DOTA_URL}/leagues", label="league list")


def load_cache(path: str) -> dict:
    """{"matches": {match_id: {...}}, "leagues": {league_id: name}}; a cache from an
    earlier version (match ids at the top level) is read as its matches."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        return {"matches": {}, "leagues": {}}
    if "matches" not in data and "leagues" not in data:
        return {"matches": data, "leagues": {}}
    return {"matches": data.get("matches") if isinstance(data.get("matches"), dict) else {},
            "leagues": data.get("leagues") if isinstance(data.get("leagues"), dict) else {}}


def save_cache(path: str, cache: dict) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f)
    os.replace(tmp, path)


def _valid_id(v) -> bool:
    """A real int (not a bool) that SQLite can bind: 1..2^63-1."""
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_ID


def _clean_name(v) -> str | None:
    if not isinstance(v, str):
        return None
    # Drop control characters so external names can't garble the operator's terminal.
    v = re.sub(r"[\x00-\x1f\x7f]", "", v).strip()
    return v[:MAX_NAME] or None


def _slim(data: dict) -> dict:
    """Keep only what the backfill needs from a match: each slot's id and name."""
    players = []
    raw = data.get("players")
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict):
            players.append({"account_id": p.get("account_id"), "personaname": _clean_name(p.get("personaname"))})
    return {"players": players}


class _Calls:
    """Waits `pause` seconds before every OpenDota call after the first."""

    def __init__(self, pause: float, sleep):
        self.pause, self.sleep, self.n = pause, sleep, 0

    def __call__(self, fn, *args):
        if self.n:
            self.sleep(self.pause)
        self.n += 1
        return fn(*args)


def league_name(league_id: int, cache: dict, cache_path: str, call) -> str | None:
    """The league's OpenDota name (cached), capped at 100 characters."""
    key = str(league_id)
    if key not in cache["leagues"]:
        info = call(ingest.get_league_info, league_id)
        cache["leagues"][key] = _clean_name(info.get("name")) if isinstance(info, dict) else None
        save_cache(cache_path, cache)
    return _clean_name(cache["leagues"][key])


def discover_leagues(number: int, prefix: str, call, out=print) -> list[tuple[int, str]]:
    """[(league id, name)] of OpenDota leagues named "<prefix> Season N", with or
    without a division suffix ("Lower", "Lower Division")."""
    data = call(fetch_leagues)
    if not isinstance(data, list):
        out("OpenDota's league list could not be read")
        return []
    pattern = re.compile(rf"\s*{re.escape(prefix)}\s+season\s+{number}(?!\d)(\s+\S.*)?\s*", re.I)
    found = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        lid, name = entry.get("leagueid"), _clean_name(entry.get("name"))
        if _valid_id(lid) and name and pattern.fullmatch(name):
            found.append((lid, name))
    return sorted(found)


def resolve_season(season: str | None, names: dict[int, str | None], out=print) -> str | None:
    """The season label from the league names ("Season N"), checked against --season.
    None (after saying why) when it can't be resolved."""
    numbers = sorted({n for n in (accolades.league_season_number(x) for x in names.values()) if n is not None})
    wanted = accolades.season_number(season) if season else None
    if len(numbers) > 1:
        out(f"The leagues name different seasons ({', '.join(f'Season {n}' for n in numbers)}); "
            "run one season at a time. Nothing written.")
        return None
    if numbers:
        if season and wanted != numbers[0]:
            out(f'--season "{season}" does not match the league names (Season {numbers[0]}). Nothing written.')
            return None
        return f"Season {numbers[0]}"
    if season and season.strip():
        return season.strip()
    out("The league names carry no season number; pass --season. Nothing written.")
    return None


def collect(season: str, leagues: list[int], cache: dict, cache_path: str, call,
            out=print) -> tuple[dict[int, str | None], int, int, list[int]]:
    """({account_id: personaname}, matches found, anonymous slots, failed league ids)."""
    accounts: dict[int, str | None] = {}
    anonymous = 0
    matches = 0
    failed: list[int] = []
    for league_id in leagues:
        match_ids = call(ingest.get_league_matches, league_id)
        if not isinstance(match_ids, list) or not match_ids:
            out(f"{season}: league {league_id}: OpenDota returned no matches; nothing recorded for it")
            failed.append(league_id)
            continue
        league_accounts: dict[int, str | None] = {}
        league_anonymous = 0
        league_matches = 0
        for match_id in match_ids:
            if not _valid_id(match_id):
                out(f"{season}: league {league_id}: skipped an invalid match id")
                continue
            key = str(match_id)
            if key not in cache["matches"]:
                data = call(fetch_match, match_id)
                if not isinstance(data, dict):
                    out(f"{season}: match {match_id} could not be fetched; skipped")
                    continue
                cache["matches"][key] = _slim(data)
                save_cache(cache_path, cache)
            league_matches += 1
            entry = cache["matches"][key]
            for slot in (entry.get("players") if isinstance(entry, dict) else None) or []:
                aid = slot.get("account_id") if isinstance(slot, dict) else None
                if not _valid_id(aid):
                    league_anonymous += 1
                    continue
                if league_accounts.get(aid) is None:
                    league_accounts[aid] = _clean_name(slot.get("personaname"))
        matches += league_matches
        anonymous += league_anonymous
        for aid, name in league_accounts.items():
            if accounts.get(aid) is None:
                accounts[aid] = name
    return accounts, matches, anonymous, failed


def _names(db, accounts: dict[int, str | None]) -> dict[int, str]:
    pool = {p.id: p.name for p in db.query(Player.id, Player.name)
            .filter(Player.id.in_(list(accounts))).all() if p.name} if accounts else {}
    return {aid: pool.get(aid) or persona or f"Player {aid}" for aid, persona in accounts.items()}


def _no_league_hint(number: int | None) -> str:
    if number is not None and number < FIRST_NUMBERED_SEASON:
        return (f" Seasons 1-{FIRST_NUMBERED_SEASON - 1} have no numbered OpenDota league: "
                "record them with Add accolade's Played paste in Player management.")
    return " Pass the ids with --league, or use Add accolade's Played paste."


def run(db, season: str | None, leagues: list[int] | None, dry_run: bool,
        cache_path: str = DEFAULT_CACHE, pause: float = DEFAULT_PAUSE_SECONDS,
        sleep=time.sleep, out=print, name_prefix: str = DEFAULT_PREFIX) -> int:
    if dry_run:
        out("Dry run: nothing is written.")
    cache = load_cache(cache_path)
    call = _Calls(pause, sleep)
    leagues = [lid for lid in (leagues or []) if _valid_id(lid)]
    names: dict[int, str | None] = {}
    if not leagues:
        number = accolades.season_number(season) if season else None
        if number is None:
            out('Give --league ids, or --season "Season N" to find the leagues by name. Nothing written.')
            return 1
        found = discover_leagues(number, name_prefix, call, out)
        if not found:
            out(f'No OpenDota league is named "{name_prefix} Season {number}".{_no_league_hint(number)}')
            return 1
        for lid, name in found:
            out(f"Found league {lid}: {name}")
            leagues.append(lid)
            names[lid] = name
            cache["leagues"][str(lid)] = name
        save_cache(cache_path, cache)
    for lid in leagues:
        if lid not in names:
            names[lid] = league_name(lid, cache, cache_path, call)
    label = resolve_season(season, names, out)
    if label is None:
        return 1
    accounts, matches, anonymous, failed = collect(label, leagues, cache, cache_path, call, out)
    names_by_account = _names(db, accounts)
    existing = {r[0] for r in db.query(SeasonAccolade.player_account_id).filter(
        SeasonAccolade.season_label == label, SeasonAccolade.kind == "played").all()}
    new = sum(1 for aid in accounts if aid not in existing)
    if not dry_run and accounts:
        now = int(time.time())
        added = accolades.insert_ignore(db, [
            {"season_label": label, "kind": "played", "player_account_id": aid,
             "player_name": names_by_account[aid], "source": accolades.SOURCE_ADMIN, "created_at": now}
            for aid in sorted(accounts)])
        db.add(AuditLog(timestamp=now, actor_id=None, actor_username="script",
                        action="admin_accolade_added",
                        detail=f"season_label={label} played={added} source=backfill"))
        db.commit()
        new = added
    out(f"{label}: {matches} matches, {len(accounts)} players, {new} new rows, "
        f"{anonymous} anonymous slots skipped")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill played accolades for one past season from OpenDota (#50).")
    parser.add_argument("--season", help='Season label, e.g. "Season 14": finds the leagues by '
                        "name when no --league is given; must match the league names otherwise")
    parser.add_argument("--league", action="append", type=int, default=[],
                        help="OpenDota league id; repeat for each division")
    parser.add_argument("--name-prefix", default=DEFAULT_PREFIX,
                        help=f'League name prefix for discovery (default "{DEFAULT_PREFIX}")')
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the report without writing anything")
    parser.add_argument("--cache", default=DEFAULT_CACHE,
                        help=f"Local cache file (default {DEFAULT_CACHE})")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS,
                        help="Seconds to wait between OpenDota calls")
    args = parser.parse_args(argv)
    if args.season is not None and not args.season.strip():
        parser.error("--season cannot be empty")
    if not args.league and not args.season:
        parser.error("give --league ids, or --season to find the leagues by name")
    if any(not _valid_id(lid) for lid in args.league):
        parser.error("--league must be a positive id")
    db = database.SessionLocal()
    try:
        return run(db, args.season, args.league, args.dry_run, args.cache, args.pause,
                   name_prefix=args.name_prefix)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
