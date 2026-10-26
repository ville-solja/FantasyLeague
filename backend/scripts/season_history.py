"""
Season history from OpenDota: who played in each past season and who won it.
Read-only: writes a JSON report and prints a summary; never touches the database.
See markdown/features/reference/season-participation-backfill.md.

Seasons and their league ids come from kanaliiga_leagues.json (the same file as
backfill_played.py). Each division is its own league. From backend/:

  python scripts/season_history.py --all                 # every season in the file
  python scripts/season_history.py --season 14 --season 15
  python scripts/season_history.py --all --out season_history.json

Per division the report lists every account id seen in the league's matches (with
its last personaname, its team names and games played) and the winner. OpenDota has
no standings, so the winner is inferred: the team that won the league's last match by
start time (the grand final), with the runner-up, the final's match id and date, and
the five account ids on each side. Check it against the league's own records.

Matches are cached in a local JSON file (--cache), so a rerun fetches only what it
hasn't read. --max-calls (default 900) caps OpenDota calls per run; on a budget stop
the run writes what it finished and exits 2, and a rerun continues from the cache.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ingest  # noqa: E402
from backfill_played import (  # noqa: E402
    DEFAULT_MAX_CALLS, DEFAULT_PAUSE_SECONDS, LEAGUE_FILE, _BudgetUsed, _Calls,
    _clean_name, _valid_id, fetch_match, load_cache, load_league_file, save_cache,
)

DEFAULT_CACHE = "season_history_cache.json"
DEFAULT_OUT = "season_history.json"


def _team(data: dict, side: str) -> tuple[int | None, str | None]:
    team = data.get(f"{side}_team")
    team = team if isinstance(team, dict) else {}
    tid = team.get("team_id", data.get(f"{side}_team_id"))
    name = team.get("name", data.get(f"{side}_name"))
    return (tid if _valid_id(tid) else None), _clean_name(name)


def slim(data: dict) -> dict:
    """What the history needs from a match: time, result, teams and each slot's side."""
    players = []
    raw = data.get("players")
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict):
            slot = p.get("player_slot")
            players.append({"account_id": p.get("account_id"),
                            "personaname": _clean_name(p.get("personaname")),
                            "radiant": isinstance(slot, int) and slot < 128})
    rid, rname = _team(data, "radiant")
    did, dname = _team(data, "dire")
    rw = data.get("radiant_win")
    st = data.get("start_time")
    return {"start_time": st if isinstance(st, int) else None,
            "radiant_win": rw if isinstance(rw, bool) else None,
            "radiant": {"team_id": rid, "name": rname},
            "dire": {"team_id": did, "name": dname},
            "players": players}


def _date(ts: int | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat() if ts else None


def _side_ids(match: dict, radiant: bool) -> list[int]:
    return sorted(p["account_id"] for p in match["players"]
                  if p.get("radiant") is radiant and _valid_id(p.get("account_id")))


def summarize_league(league_id: int, matches: dict[int, dict]) -> dict:
    """Participants and the inferred winner of one league from its slim matches."""
    names: dict[int, str | None] = {}
    games: Counter = Counter()
    teams: dict[int, set] = {}
    anonymous = 0
    for mid in sorted(matches, key=lambda m: (matches[m].get("start_time") or 0, m)):
        m = matches[mid]
        for p in m["players"]:
            aid = p.get("account_id")
            if not _valid_id(aid):
                anonymous += 1
                continue
            games[aid] += 1
            names[aid] = p.get("personaname") or names.get(aid)
            team = m["radiant" if p.get("radiant") else "dire"].get("name")
            if team:
                teams.setdefault(aid, set()).add(team)
    participants = [{"account_id": aid, "personaname": names.get(aid), "games": games[aid],
                     "teams": sorted(teams.get(aid, ()))}
                    for aid in sorted(games, key=lambda a: (-games[a], a))]
    winner = None
    timed = [mid for mid in matches if matches[mid].get("start_time")]
    if timed:
        fid = max(timed, key=lambda m: (matches[m]["start_time"], m))
        f = matches[fid]
        if f.get("radiant_win") is not None:
            win, lose = ("radiant", "dire") if f["radiant_win"] else ("dire", "radiant")
            winner = {"inferred_from": "last match by start time",
                      "final_match_id": fid, "final_date": _date(f["start_time"]),
                      "team": f[win], "account_ids": _side_ids(f, win == "radiant"),
                      "runner_up": f[lose], "runner_up_account_ids": _side_ids(f, lose == "radiant")}
    return {"league_id": league_id, "matches": len(matches), "anonymous_slots": anonymous,
            "players": len(participants), "winner": winner, "participants": participants}


def collect_league(league_id: int, cache: dict, cache_path: str, call, out=print) -> tuple[dict, int]:
    """({match_id: slim match}, unreadable count) for one league, via the cache."""
    match_ids = call(ingest.get_league_matches, league_id)
    if not isinstance(match_ids, list):
        out(f"league {league_id}: OpenDota returned no match list")
        return {}, 0
    got, unreadable = {}, 0
    for mid in match_ids:
        if not _valid_id(mid):
            continue
        key = str(mid)
        if key not in cache["matches"]:
            data = call(fetch_match, mid)
            if not isinstance(data, dict):
                out(f"league {league_id}: match {mid} could not be fetched; skipped")
                unreadable += 1
                continue
            cache["matches"][key] = slim(data)
            save_cache(cache_path, cache)
        got[mid] = cache["matches"][key]
    return got, unreadable


def _print_season(s: dict, out) -> None:
    out(f"Season {s['season']}: {s['players']} players")
    for d in s["divisions"]:
        w = d["winner"]
        line = f"  league {d['league_id']}: {d['matches']} matches, {d['players']} players"
        if d["unreadable"]:
            line += f", {d['unreadable']} unreadable"
        out(line)
        if w:
            out(f"    winner: {w['team'].get('name') or w['team'].get('team_id') or '?'} "
                f"over {w['runner_up'].get('name') or w['runner_up'].get('team_id') or '?'} "
                f"(final {w['final_date']}, match {w['final_match_id']}) "
                f"players {', '.join(map(str, w['account_ids']))}")
        else:
            out("    winner: unknown (no timed, decided match)")


def run(seasons: list[int] | None, cache_path: str = DEFAULT_CACHE, out_path: str = DEFAULT_OUT,
        pause: float = DEFAULT_PAUSE_SECONDS, max_calls: int | None = DEFAULT_MAX_CALLS,
        league_file: str = LEAGUE_FILE, sleep=time.sleep, out=print) -> int:
    table = load_league_file(league_file)
    wanted = sorted(table) if seasons is None else seasons
    missing = [n for n in wanted if n not in table]
    if missing:
        out(f"Not in the league file: {', '.join(f'Season {n}' for n in missing)}")
        return 1
    cache = load_cache(cache_path)
    call = _Calls(pause, sleep, max_calls)
    report, code = [], 0
    try:
        for n in wanted:
            divisions, everyone = [], set()
            for lid in table[n]:
                matches, unreadable = collect_league(lid, cache, cache_path, call, out)
                d = summarize_league(lid, matches)
                d["unreadable"] = unreadable
                divisions.append(d)
                everyone.update(p["account_id"] for p in d["participants"])
            s = {"season": n, "players": len(everyone), "account_ids": sorted(everyone),
                 "divisions": divisions}
            report.append(s)
            _print_season(s, out)
    except _BudgetUsed:
        out("Budget used: run again to continue; the cache keeps every match read so far.")
        code = 2
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "complete": code == 0, "seasons": report}, f, indent=1)
    out(f"Wrote {out_path} ({len(report)} seasons)")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Past seasons' participants and winners from OpenDota.")
    parser.add_argument("--all", dest="all_seasons", action="store_true",
                        help="Every season in the league file")
    parser.add_argument("--season", action="append", type=int, default=[],
                        help="Season number; repeat for several")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"JSON report (default {DEFAULT_OUT})")
    parser.add_argument("--cache", default=DEFAULT_CACHE, help=f"Local cache file (default {DEFAULT_CACHE})")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS,
                        help="Seconds to wait between OpenDota calls")
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                        help=f"OpenDota calls allowed in this run (default {DEFAULT_MAX_CALLS})")
    args = parser.parse_args(argv)
    if args.all_seasons == bool(args.season):
        parser.error("give --all or one or more --season numbers")
    if args.max_calls < 1:
        parser.error("--max-calls must be at least 1")
    return run(None if args.all_seasons else sorted(set(args.season)), args.cache, args.out,
               args.pause, args.max_calls)


if __name__ == "__main__":
    sys.exit(main())
