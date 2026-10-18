"""
Backfill of "played" accolades for past seasons, from OpenDota (issues #50 and #212).
See markdown/features/reference/season-participation-backfill.md.

Each division is its own OpenDota league. Past seasons' league ids are listed in
kanaliiga_leagues.json next to this script (Season 4 onward; Seasons 1-3 have no
league). Take a backup first (bash scripts/backup-db.sh), then from backend/:

  # every season in the league file except the live one, oldest first
  python scripts/backfill_played.py --all --dry-run
  python scripts/backfill_played.py --all
  # one season: from the league file, else found on OpenDota by name
  python scripts/backfill_played.py --season "Season 14" --dry-run
  # or name the leagues; the label comes from their names
  python scripts/backfill_played.py --league <div1 id> --league <div2 id>

--league takes precedence over the league file. --season is needed only when no
--league is given or when the league names carry no season number; when given with
leagues it must agree with their names. --all can't be combined with either.

Every account id in the leagues' matches gets one played row for the season
(source "admin"). Names come from the current player pool, else the match's
personaname, else "Player <id>". Anonymous slots are skipped and counted. Existing
rows are left alone (INSERT … ON CONFLICT DO NOTHING), and fetched league names and
matches are cached in a local JSON file (--cache), so a rerun fetches only what it
hasn't read yet. A match that can't be read is reported and retried on the next run.

--max-calls (default 900) caps OpenDota calls per run. When the budget is used the
run stops, keeps what it finished and the cache, and exits 2; run it again to
continue. Exit code 1 when the season can't be resolved (nothing is written) or a
league can't be read (nothing is recorded for it); 0 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
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
LEAGUE_FILE = str(Path(__file__).resolve().with_name("kanaliiga_leagues.json"))
DEFAULT_MAX_CALLS = 900


class LeagueFileError(ValueError):
    """The league file is missing or malformed."""


class _BudgetUsed(Exception):
    """The run's OpenDota call budget (--max-calls) is used."""


def load_league_file(path: str) -> dict[int, list[int]]:
    """{season number: [league ids to fetch]}, seasons ascending. empty_leagues and
    unused_leagues are only checked (valid, unique ids), never fetched. Raises
    LeagueFileError when the file is unreadable or invalid."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise LeagueFileError(f"cannot be read ({type(e).__name__})") from None
    seasons = data.get("seasons") if isinstance(data, dict) else None
    if not isinstance(seasons, list) or not seasons:
        raise LeagueFileError('no "seasons" list')
    seen: set[int] = set()

    def ids(values, what: str) -> list[int]:
        if not isinstance(values, list) or not all(_valid_id(v) for v in values):
            raise LeagueFileError(f"{what} must be a list of positive integer league ids")
        for v in values:
            if v in seen:
                raise LeagueFileError(f"league {v} is listed twice")
            seen.add(v)
        return list(values)

    out: dict[int, list[int]] = {}
    last = 0
    for entry in seasons:
        number = entry.get("season") if isinstance(entry, dict) else None
        if not _valid_id(number):
            raise LeagueFileError("every season needs a positive integer \"season\"")
        if number <= last:
            raise LeagueFileError(f"seasons must be ascending (Season {number} after Season {last})")
        last = number
        leagues = ids(entry.get("leagues"), f"Season {number} leagues")
        if not leagues:
            raise LeagueFileError(f"Season {number} lists no leagues")
        ids(entry.get("empty_leagues", []), f"Season {number} empty_leagues")
        out[number] = leagues
    unused = data.get("unused_leagues", [])
    if not isinstance(unused, list):
        raise LeagueFileError("unused_leagues must be a list")
    ids([u.get("league") if isinstance(u, dict) else None for u in unused], "unused_leagues")
    return out


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
    """Waits `pause` seconds before every OpenDota call after the first, and raises
    _BudgetUsed instead of making a call past `max_calls` (None: no cap)."""

    def __init__(self, pause: float, sleep, max_calls: int | None = None):
        self.pause, self.sleep, self.n, self.max_calls = pause, sleep, 0, max_calls

    def __call__(self, fn, *args):
        if self.max_calls is not None and self.n >= self.max_calls:
            raise _BudgetUsed
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
            out=print) -> tuple[dict[int, str | None], int, int, list[int], int]:
    """({account_id: personaname}, matches read, anonymous slots, failed league ids,
    unreadable matches). An unreadable match isn't cached, so the next run retries it."""
    accounts: dict[int, str | None] = {}
    anonymous = 0
    matches = 0
    unreadable = 0
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
                    unreadable += 1
                    continue
                cache["matches"][key] = _slim(data)
                save_cache(cache_path, cache)
            league_matches += 1
            entry = cache["matches"][key]
            players = entry.get("players") if isinstance(entry, dict) else None
            for slot in players if isinstance(players, list) else []:
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
    return accounts, matches, anonymous, failed, unreadable


def _names(db, accounts: dict[int, str | None]) -> dict[int, str]:
    pool = {p.id: p.name for p in db.query(Player.id, Player.name)
            .filter(Player.id.in_(list(accounts))).all() if p.name} if accounts else {}
    return {aid: pool.get(aid) or persona or f"Player {aid}" for aid, persona in accounts.items()}


def _no_league_hint(number: int | None) -> str:
    if number is not None and number < FIRST_NUMBERED_SEASON:
        return (f" Seasons 1-{FIRST_NUMBERED_SEASON - 1} have no numbered OpenDota league "
                f"(Season {accolades.FIRST_COUNTED_SEASON}'s unnumbered league is in the league file): "
                "record the others with Add accolade's Played paste in Player management.")
    return " Pass the ids with --league, or use Add accolade's Played paste."


class SeasonResult:
    """One season's outcome. A plain class: tests load this script without registering
    it in sys.modules, which @dataclass needs."""

    def __init__(self, label: str | None, code: int, accounts: set | None = None, matches: int = 0,
                 new: int = 0, already: int = 0, anonymous: int = 0, unreadable: int = 0,
                 budget: bool = False):
        self.label, self.code, self.accounts = label, code, accounts or set()
        self.matches, self.new, self.already = matches, new, already
        self.anonymous, self.unreadable, self.budget = anonymous, unreadable, budget


def _season(db, season: str | None, leagues: list[int], dry_run: bool, cache: dict,
            cache_path: str, call, out, name_prefix: str,
            file_seasons: dict[int, list[int]] | None) -> SeasonResult:
    """One season: resolve its leagues and label, read the matches, record the rows.
    The same code serves --season, --league and every season of --all."""
    leagues = [lid for lid in (leagues or []) if _valid_id(lid)]
    names: dict[int, str | None] = {}
    label = None
    try:
        if not leagues:
            number = accolades.season_number(season) if season else None
            if number is None:
                out('Give --league ids, or --season "Season N" to find the leagues by name. Nothing written.')
                return SeasonResult(None, 1)
            if file_seasons and number in file_seasons:
                leagues = list(file_seasons[number])
                label = f"Season {number}"
                out(f"{label}: leagues {', '.join(str(x) for x in leagues)} from the league file")
            else:
                found = discover_leagues(number, name_prefix, call, out)
                if not found:
                    out(f'No OpenDota league is named "{name_prefix} Season {number}".{_no_league_hint(number)}')
                    return SeasonResult(None, 1)
                for lid, name in found:
                    out(f"Found league {lid}: {name}")
                    leagues.append(lid)
                    names[lid] = name
                    cache["leagues"][str(lid)] = name
                save_cache(cache_path, cache)
        if label is None:
            for lid in leagues:
                if lid not in names:
                    names[lid] = league_name(lid, cache, cache_path, call)
            label = resolve_season(season, names, out)
            if label is None:
                return SeasonResult(None, 1)
        accounts, matches, anonymous, failed, unreadable = collect(label, leagues, cache, cache_path, call, out)
    except _BudgetUsed:
        return SeasonResult(label or (season.strip() if season else None), 2, budget=True)
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
    already = len(accounts) - new
    out(f"{label}: {matches} matches, {len(accounts)} players, {new} new rows, "
        f"{anonymous} anonymous slots skipped, {already} already recorded, {unreadable} unreadable matches")
    return SeasonResult(label, 1 if failed else 0, set(accounts), matches, new, already,
                        anonymous, unreadable)


def _budget_message(label: str | None) -> str:
    where = f" from {label}" if label else ""
    return f"Budget used: resume to continue{where}. The cache keeps every match read so far."


def _unreadable_hint(n: int) -> str:
    return f"{n} matches could not be read; run again to retry them."


def run(db, season: str | None, leagues: list[int] | None, dry_run: bool,
        cache_path: str = DEFAULT_CACHE, pause: float = DEFAULT_PAUSE_SECONDS,
        sleep=time.sleep, out=print, name_prefix: str = DEFAULT_PREFIX,
        league_file: str | None = None, max_calls: int | None = None) -> int:
    """One season (--season / --league). league_file: resolve a --season without
    --league through that file before name discovery (None: discovery only).
    Exit 2 when max_calls is used up."""
    if dry_run:
        out("Dry run: nothing is written.")
    cache = load_cache(cache_path)
    call = _Calls(pause, sleep, max_calls)
    file_seasons = None
    if league_file and not any(_valid_id(lid) for lid in (leagues or [])):
        try:
            file_seasons = load_league_file(league_file)
        except LeagueFileError as e:
            out(f"League file {league_file}: {e}. Nothing written.")
            return 1
    r = _season(db, season, list(leagues or []), dry_run, cache, cache_path, call, out,
                name_prefix, file_seasons)
    if r.budget:
        out(_budget_message(r.label))
        return 2
    if r.unreadable:
        out(_unreadable_hint(r.unreadable))
    return r.code


def _report(results: list[SeasonResult], out) -> None:
    """Totals and the seasons-per-player distribution over the seasons run."""
    per_player = Counter(aid for r in results for aid in r.accounts)
    rows = sum(len(r.accounts) for r in results)
    unreadable = sum(r.unreadable for r in results)
    out(f"Total: {len(results)} seasons, {len(per_player)} players, {rows} played rows, "
        f"{sum(r.new for r in results)} new rows, {sum(r.already for r in results)} already recorded, "
        f"{unreadable} unreadable matches")
    out("Seasons per player:")
    for n, count in sorted(Counter(per_player.values()).items()):
        out(f"  {n} season{'s' if n != 1 else ''}: {count} player{'s' if count != 1 else ''}")
    if unreadable:
        out(_unreadable_hint(unreadable))


def run_all(db, dry_run: bool, cache_path: str = DEFAULT_CACHE,
            pause: float = DEFAULT_PAUSE_SECONDS, sleep=time.sleep, out=print,
            league_file: str | None = None, max_calls: int | None = DEFAULT_MAX_CALLS,
            name_prefix: str = DEFAULT_PREFIX) -> int:
    """--all: every season in the league file except the live one, oldest first,
    sharing one cache and one call budget. Exit 2 on a budget stop, 1 when a season
    failed, 0 otherwise."""
    if dry_run:
        out("Dry run: nothing is written.")
    path = league_file or LEAGUE_FILE
    try:
        file_seasons = load_league_file(path)
    except LeagueFileError as e:
        out(f"League file {path}: {e}. Nothing written.")
        return 1
    live = accolades.current_season_label(db)
    live_number = accolades.season_number(live)
    if live_number in file_seasons:
        out(f"Skipping {live}: it is the live season.")
    cache = load_cache(cache_path)
    call = _Calls(pause, sleep, max_calls)
    results: list[SeasonResult] = []
    stopped = None
    code = 0
    for number in file_seasons:
        if number == live_number:
            continue
        r = _season(db, f"Season {number}", [], dry_run, cache, cache_path, call, out,
                    name_prefix, file_seasons)
        if r.budget:
            stopped = r.label or f"Season {number}"
            break
        results.append(r)
        code = max(code, r.code)
    _report(results, out)
    if stopped:
        out(_budget_message(stopped))
        return 2
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill played accolades for past seasons from OpenDota (#50, #212).")
    parser.add_argument("--all", dest="all_seasons", action="store_true",
                        help="Every season in the league file except the live one, oldest first")
    parser.add_argument("--season", help='Season label, e.g. "Season 14": takes its leagues from the '
                        "league file, else finds them by name, when no --league is given; must match "
                        "the league names otherwise")
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
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help=f"OpenDota calls allowed in this run (default {DEFAULT_MAX_CALLS}); "
                        "the client's own retries of a call are not counted; "
                        "a rerun continues from the cache")
    args = parser.parse_args(argv)
    if args.max_calls < 1:
        parser.error("--max-calls must be at least 1")
    if args.all_seasons and (args.season is not None or args.league):
        parser.error("--all runs every season in the league file; don't combine it with --season or --league")
    if args.season is not None and not args.season.strip():
        parser.error("--season cannot be empty")
    if not args.all_seasons and not args.league and not args.season:
        parser.error("give --all, --league ids, or --season to find the leagues")
    if any(not _valid_id(lid) for lid in args.league):
        parser.error("--league must be a positive id")
    db = database.SessionLocal()
    try:
        if args.all_seasons:
            return run_all(db, args.dry_run, args.cache, args.pause, league_file=LEAGUE_FILE,
                           max_calls=args.max_calls, name_prefix=args.name_prefix)
        return run(db, args.season, args.league, args.dry_run, args.cache, args.pause,
                   name_prefix=args.name_prefix, league_file=LEAGUE_FILE, max_calls=args.max_calls)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
