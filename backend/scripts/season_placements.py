"""
Placements 1-3 of past seasons, from OpenDota (issue 233).
See markdown/features/reference/season-placements-backfill.md.

Two steps with a reviewed table in between. From backend/:

  # 1. fetch and derive: writes scripts/season_placements.csv (nothing in the database)
  python scripts/season_placements.py build
  python scripts/season_placements.py build --season 15 --dry-run   # print, write nothing
  # 2. review the CSV: check each row's evidence, fix it, set reviewed=yes, commit it
  # 3. take a backup (bash scripts/backup-db.sh), then write the reviewed rows
  python scripts/season_placements.py apply --dry-run
  python scripts/season_placements.py apply

build reads kanaliiga_leagues.json (every season except the live one). The first league
of a season is Div 1, the second (the "Lower" league, listed under leagues or
empty_leagues) is Div 2. Each league's match ids and matches are fetched once into a
local JSON cache (--cache); --max-calls (default 900) caps OpenDota calls per run, and
a budget stop exits 2 with the cache kept, so a rerun continues where it stopped.

Placement rules, per league, with matches grouped into series by series_id (old
matches without one by team pair and UTC day), series ordered by their last game:
  1st and 2nd: the winner and loser of the last series, which must have two or more
               games, a winner and both team names; otherwise every place is `review`.
  3rd (high):  a series between the two semifinal losers that follows both semifinals
               (each finalist's last series before the final, both won by them).
  3rd (low):   otherwise the loser of the final loser's last series before the final
               (a double-elimination lower-bracket final), when the final loser won it.
  Anything else, and a league with no matches, is `review` with no guessed team.

apply writes only rows marked reviewed=yes: place 1 through accolades.set_champions,
places 2 and 3 through accolades.set_placement (runner_up, third_place). A place whose
recorded rows differ from the table (champions entered by hand, say) is skipped unless
--replace is given. A rerun changes nothing. Each season that changes writes one
`admin_placements_backfilled` audit entry.

Exit codes: 0 done; 1 invalid league file, table or rows; 2 budget stop (build).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import accolades  # noqa: E402
import backfill_played as bp  # noqa: E402
import database  # noqa: E402
import ingest  # noqa: E402
from models import AuditLog, Player, SeasonAccolade  # noqa: E402

DEFAULT_CACHE = "season_placements_cache.json"
DEFAULT_TABLE = str(Path(__file__).resolve().with_name("season_placements.csv"))
LEAGUE_FILE = bp.LEAGUE_FILE
DEFAULT_MAX_CALLS = bp.DEFAULT_MAX_CALLS
MAX_TEAM_PLAYERS = 50  # the same cap as PUT /admin/season-champions (MAX_CHAMPIONS)
DEFAULT_PAUSE_SECONDS = bp.DEFAULT_PAUSE_SECONDS
COLUMNS = ["season", "division", "place", "team_name", "team_id", "players",
           "matches_per_player", "evidence", "confidence", "reviewed"]
PLACE_KINDS = {1: "champion", 2: "runner_up", 3: "third_place"}
DAY = 86400
AUDIT_ACTION = "admin_placements_backfilled"
_KIND_NAMES = {k["key"]: k["name"] for k in accolades.ACCOLADE_KINDS}


# ---------------------------------------------------------------------------
# OpenDota and the cache
# ---------------------------------------------------------------------------

def fetch_match_ids(league_id: int):
    return ingest.get_league_matches(league_id)


def fetch_match(match_id: int):
    return bp.fetch_match(match_id)


def load_cache(path: str) -> dict:
    """{"league_matches": {league_id: [match ids]}, "matches": {match_id: slim match}}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    data = data if isinstance(data, dict) else {}
    return {k: data.get(k) if isinstance(data.get(k), dict) else {}
            for k in ("league_matches", "matches")}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _side_of(p: dict) -> bool | None:
    """True for Radiant, False for Dire, None when unknown."""
    if isinstance(p.get("isRadiant"), bool):
        return p["isRadiant"]
    if isinstance(p.get("radiant"), bool):
        return p["radiant"]
    slot = _int(p.get("player_slot"))
    return None if slot is None else slot < 128


def slim_match(data: dict) -> dict:
    """Only what the placements need from GET /matches/{id}."""
    out = {"match_id": _int(data.get("match_id")),
           "series_id": _int(data.get("series_id")),
           "series_type": _int(data.get("series_type")),
           "start_time": _int(data.get("start_time")) or 0,
           "radiant_win": data.get("radiant_win") if isinstance(data.get("radiant_win"), bool) else None}
    for side in ("radiant", "dire"):
        team = data.get(f"{side}_team") if isinstance(data.get(f"{side}_team"), dict) else {}
        tid = data.get(f"{side}_team_id", team.get("team_id"))
        out[f"{side}_team_id"] = tid if bp._valid_id(tid) else None
        out[f"{side}_name"] = bp._clean_name(data.get(f"{side}_name") or team.get("name"))
    players = []
    raw = data.get("players")
    for p in raw if isinstance(raw, list) else []:
        if isinstance(p, dict):
            aid = p.get("account_id")
            players.append({"account_id": aid if bp._valid_id(aid) else None,
                            "personaname": bp._clean_name(p.get("personaname")),
                            "radiant": _side_of(p)})
    out["players"] = players
    return out


# ---------------------------------------------------------------------------
# Teams and series
# ---------------------------------------------------------------------------

def _norm(name) -> str:
    return " ".join(str(name or "").split()).lower()


class Teams:
    """Team identities in one league: the team id when OpenDota has one, else the
    name; a side without an id whose name matches a known team counts as that team."""

    def __init__(self, matches: list[dict]):
        self.names: dict = {}
        self._by_name: dict[str, int] = {}
        for m in sorted(matches, key=lambda m: m.get("start_time") or 0):
            for side in ("radiant", "dire"):
                tid, name = m.get(f"{side}_team_id"), m.get(f"{side}_name")
                if tid is not None and name:
                    self.names[tid] = name
                    self._by_name[_norm(name)] = tid
        for m in matches:
            for side in ("radiant", "dire"):
                key = self.key(m, side)
                if isinstance(key, str) and key not in self.names:
                    self.names[key] = m.get(f"{side}_name")

    def key(self, m: dict, side: str):
        tid, name = m.get(f"{side}_team_id"), m.get(f"{side}_name")
        if tid is not None:
            return tid
        if name:
            return self._by_name.get(_norm(name), f"name:{_norm(name)}")
        return None

    def name(self, key) -> str | None:
        return self.names.get(key) if key is not None else None

    @staticmethod
    def team_id(key):
        return key if isinstance(key, int) else None


def group_series(matches: list[dict], teams: Teams | None = None) -> list[dict]:
    """Series in the order of their last game. Each: key, series_id, series_type,
    teams [a, b], wins {team: games won}, games, start (first game), end (last game),
    winner and loser (None on a tie), match_ids."""
    teams = teams or Teams(matches)
    groups: dict = {}
    for m in sorted(matches, key=lambda m: (m.get("start_time") or 0, m.get("match_id") or 0)):
        r, d = teams.key(m, "radiant"), teams.key(m, "dire")
        if m.get("series_id"):
            gkey = ("series", m["series_id"])
        elif r is not None and d is not None:
            gkey = ("pair", frozenset((str(r), str(d))), (m.get("start_time") or 0) // DAY)
        else:
            gkey = ("match", m.get("match_id"))
        s = groups.get(gkey)
        if s is None:
            s = groups[gkey] = {"key": gkey, "series_id": m.get("series_id") or None,
                                "series_type": m.get("series_type"), "teams": [], "wins": {},
                                "games": 0, "start": m.get("start_time") or 0, "end": 0,
                                "winner": None, "loser": None, "match_ids": []}
        for t in (r, d):
            if t is not None and t not in s["teams"]:
                s["teams"].append(t)
                s["wins"].setdefault(t, 0)
        s["games"] += 1
        s["end"] = max(s["end"], m.get("start_time") or 0)
        s["match_ids"].append(m.get("match_id"))
        if m.get("radiant_win") is not None:
            w = r if m["radiant_win"] else d
            if w is not None:
                s["wins"][w] = s["wins"].get(w, 0) + 1
    out = []
    for s in groups.values():
        if len(s["teams"]) == 2:
            a, b = s["teams"]
            if s["wins"][a] != s["wins"][b]:
                s["winner"], s["loser"] = (a, b) if s["wins"][a] > s["wins"][b] else (b, a)
        out.append(s)
    out.sort(key=lambda s: (s["end"], s["start"]))
    return out


def score(s: dict, teams: Teams) -> str:
    """"OP Platinum 2–1 Visma Tormentor" (winner first when there is one)."""
    a, b = (s["winner"], s["loser"]) if s["winner"] is not None else (s["teams"] + [None, None])[:2]
    def nm(t):
        return teams.name(t) or (f"team {t}" if t is not None else "unknown team")
    return f"{nm(a)} {s['wins'].get(a, 0)}–{s['wins'].get(b, 0)} {nm(b)}"


def _row(place, teams=None, key=None, evidence="", confidence="review") -> dict:
    return {"place": place, "team_key": key,
            "team_name": teams.name(key) if teams and key is not None else "",
            "team_id": Teams.team_id(key), "evidence": evidence, "confidence": confidence}


def _review(reason: str, places=(1, 2, 3)) -> list[dict]:
    return [_row(p, evidence=reason) for p in places]


def derive_placements(matches: list[dict], teams: Teams | None = None) -> list[dict]:
    """[place 1, place 2, place 3]: each {place, team_key, team_name, team_id, evidence,
    confidence}; review rows carry no team."""
    teams = teams or Teams(matches)
    series = group_series(matches, teams)
    if not series:
        return _review("no matches")
    final = series[-1]
    final_score = score(final, teams)
    if final["games"] < 2 or (final["series_id"] and final["series_type"] == 0):
        return _review(f"last series is a single game: {final_score}")
    if final["winner"] is None:
        return _review(f"last series has no winner: {final_score}")
    w, lo = final["winner"], final["loser"]
    if not teams.name(w) or not teams.name(lo):
        return _review(f"team names missing in the last series: {final_score}")
    final_ev = f"final {final_score}"
    rows = [_row(1, teams, w, final_ev, "high"), _row(2, teams, lo, final_ev, "high")]

    before = series[:-1]

    def last_before(team):
        return next((s for s in reversed(before) if team in s["teams"]), None)

    sw, sl = last_before(w), last_before(lo)
    if sw is not None and sl is not None and sw is not sl and sw["winner"] == w and sl["winner"] == lo:
        a, b = sw["loser"], sl["loser"]
        after = max(sw["end"], sl["end"])
        third = next((s for s in reversed(before)
                      if set(s["teams"]) == {a, b} and s["end"] > after and s["winner"] is not None), None)
        if third is not None and teams.name(third["winner"]):
            ev = (f"semifinal {score(sw, teams)}; semifinal {score(sl, teams)}; "
                  f"3rd-place match {score(third, teams)}; {final_ev}")
            rows.append(_row(3, teams, third["winner"], ev, "high"))
            return rows
    if sl is not None and sl["winner"] == lo and sl["loser"] not in (None, w) and teams.name(sl["loser"]):
        ev = f"last series before the final: {score(sl, teams)}; {final_ev}"
        rows.append(_row(3, teams, sl["loser"], ev, "low"))
        return rows
    if sl is None:
        reason = f"3rd unclear: {teams.name(lo)} played no series before the final"
    elif sl["winner"] != lo:
        reason = f"3rd unclear: {teams.name(lo)} lost its last series before the final ({score(sl, teams)})"
    else:
        reason = "3rd unclear"
    rows.append(_row(3, evidence=f"{reason}; {final_ev}"))
    return rows


# ---------------------------------------------------------------------------
# Rosters
# ---------------------------------------------------------------------------

def roster(matches: list[dict], team_key, teams: Teams | None = None) -> dict[int, dict]:
    """{account_id: {"matches": n, "personaname": name}} of every account with a match
    on that team's side (team id, else name). Anonymous slots are left out."""
    teams = teams or Teams(matches)
    out: dict[int, dict] = {}
    for m in matches:
        for side, radiant in (("radiant", True), ("dire", False)):
            if team_key is None or teams.key(m, side) != team_key:
                continue
            for p in m.get("players") or []:
                aid = p.get("account_id")
                if p.get("radiant") is not radiant or not bp._valid_id(aid):
                    continue
                e = out.setdefault(aid, {"matches": 0, "personaname": None})
                e["matches"] += 1
                e["personaname"] = e["personaname"] or p.get("personaname")
    return out


def roster_names(db, players: dict[int, dict]) -> dict[int, str]:
    """Pool name, else the match's personaname, else "Player <id>". Pool names are
    cleaned like OpenDota names before they reach the CSV or the terminal."""
    pool = {p.id: bp._clean_name(p.name) for p in db.query(Player.id, Player.name)
            .filter(Player.id.in_(list(players))).all() if bp._clean_name(p.name)} if players else {}
    return {aid: pool.get(aid) or e.get("personaname") or f"Player {aid}" for aid, e in players.items()}


def _csv_name(name: str) -> str:
    return str(name).replace(";", ",")


def format_players(players: dict[int, dict], names: dict[int, str]) -> tuple[str, str]:
    """("id:name;…", "id:matches;…"), most matches first."""
    order = sorted(players, key=lambda a: (-players[a]["matches"], names[a].lower(), a))
    return (";".join(f"{a}:{_csv_name(names[a])}" for a in order),
            ";".join(f"{a}:{players[a]['matches']}" for a in order))


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def load_seasons(path: str) -> list[dict]:
    """[{season, divisions: [(division, league id, empty)]}], validated by
    backfill_played.load_league_file. Division order: leagues, then empty_leagues."""
    bp.load_league_file(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for entry in data["seasons"]:
        ids = [(lid, False) for lid in entry["leagues"]] + [(lid, True) for lid in entry.get("empty_leagues", [])]
        out.append({"season": entry["season"],
                    "divisions": [(div, lid, empty) for div, (lid, empty) in zip(accolades.DIVISIONS, ids)]})
    return out


def _league_matches(league_id: int, cache: dict, cache_path: str, call, out) -> tuple[list[dict], int, bool]:
    """(slim matches, unreadable count, listed): the league's match ids (cached), then
    each match not yet cached. An unreadable match isn't cached, so a rerun retries it."""
    key = str(league_id)
    if key not in cache["league_matches"]:
        ids = call(fetch_match_ids, league_id)
        if not isinstance(ids, list):
            out(f"league {league_id}: OpenDota returned no match list")
            return [], 0, False
        cache["league_matches"][key] = [i for i in ids if bp._valid_id(i)]
        bp.save_cache(cache_path, cache)
    matches, unreadable = [], 0
    for mid in cache["league_matches"][key]:
        mk = str(mid)
        if mk not in cache["matches"]:
            data = call(fetch_match, mid)
            if not isinstance(data, dict):
                out(f"match {mid} could not be fetched; skipped")
                unreadable += 1
                continue
            slim = slim_match(data)
            slim["match_id"] = slim["match_id"] or mid
            cache["matches"][mk] = slim
            bp.save_cache(cache_path, cache)
        matches.append(cache["matches"][mk])
    return matches, unreadable, True


def _table_rows(db, number: int, division: str, matches: list[dict], note: str | None) -> list[dict]:
    teams = Teams(matches)
    placed = derive_placements(matches, teams) if note is None else _review(note)
    rows = []
    for p in placed:
        players_txt = counts_txt = ""
        if p["team_key"] is not None:
            members = roster(matches, p["team_key"], teams)
            players_txt, counts_txt = format_players(members, roster_names(db, members))
        rows.append({"season": number, "division": division, "place": p["place"],
                     "team_name": p["team_name"] or "", "team_id": p["team_id"] or "",
                     "players": players_txt, "matches_per_player": counts_txt,
                     "evidence": p["evidence"], "confidence": p["confidence"], "reviewed": ""})
    return rows


def _compare(db, rows: list[dict], out) -> None:
    """Prints where a derived champion differs from the champions recorded."""
    for r in rows:
        if r["place"] != 1 or not r["team_name"]:
            continue
        label = f"Season {r['season']}"
        recorded = {x[0] for x in db.query(SeasonAccolade.team_name).filter(
            SeasonAccolade.season_label == label, SeasonAccolade.kind == "champion",
            SeasonAccolade.division == r["division"]).all()}
        if recorded and {_norm(t) for t in recorded} != {_norm(r["team_name"])}:
            out(f"{label} {r['division']}: derived champion {r['team_name']} differs from the "
                f"recorded champion {', '.join(sorted(bp._clean_name(str(t)) or '?' for t in recorded))}")


def _reviewed_rows_exist(path: str) -> bool:
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return any((r.get("reviewed") or "").strip().lower() == "yes" for r in csv.DictReader(f))
    except OSError:
        return False


# A cell starting with one of these runs as a formula when the operator opens the CSV
# in a spreadsheet; write_table prefixes such cells with ' and parse_row drops it again.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _csv_cell(value):
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _uncell(value: str | None) -> str | None:
    if isinstance(value, str) and value.startswith("'") and value[1:].startswith(_FORMULA_START):
        return value[1:]
    return value


def write_table(path: str, rows: list[dict]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: _csv_cell(r.get(c, "")) for c in COLUMNS})
    Path(tmp).replace(path)


def run_build(db, league_file: str = LEAGUE_FILE, cache_path: str = DEFAULT_CACHE,
              table_path: str = DEFAULT_TABLE, max_calls: int | None = DEFAULT_MAX_CALLS,
              pause: float = DEFAULT_PAUSE_SECONDS, sleep=time.sleep, out=print,
              seasons: list[int] | None = None, dry_run: bool = False,
              overwrite: bool = False) -> int:
    """Fetch, derive and write the table. Reads the database (player names, the live
    season, recorded champions) but never writes to it."""
    if dry_run:
        out("Dry run: the table is printed, not written.")
    try:
        file_seasons = load_seasons(league_file)
    except bp.LeagueFileError as e:
        out(f"League file {league_file}: {e}. Nothing written.")
        return 1
    if not dry_run and not overwrite and _reviewed_rows_exist(table_path):
        out(f"{table_path} has reviewed rows; pass --overwrite to replace it. Nothing written.")
        return 1
    live = accolades.season_number(accolades.current_season_label(db))
    cache = load_cache(cache_path)
    call = bp._Calls(pause, sleep, max_calls)
    rows: list[dict] = []
    for entry in file_seasons:
        number = entry["season"]
        if seasons and number not in seasons:
            continue
        if number == live:
            out(f"Skipping Season {number}: it is the live season.")
            continue
        for division, league_id, empty in entry["divisions"]:
            note = "empty league: OpenDota has no matches" if empty else None
            matches: list[dict] = []
            if not empty:
                try:
                    matches, unreadable, listed = _league_matches(league_id, cache, cache_path, call, out)
                except bp._BudgetUsed:
                    out(f"Budget used: resume to continue from Season {number}. "
                        "The cache keeps every match read so far.")
                    return 2
                if not listed or not matches:
                    note = "OpenDota returned no matches"
                elif unreadable:
                    note = f"{unreadable} matches could not be read; run build again"
            div_rows = _table_rows(db, number, division, matches, note)
            rows.extend(div_rows)
            summary = ", ".join(f"{r['place']} {r['team_name'] or '?'} ({r['confidence']})" for r in div_rows)
            out(f"Season {number} {division}: {len(matches)} matches; {summary}")
    review = sorted({(r["season"], r["division"]) for r in rows if r["confidence"] == "review"})
    review_txt = ", ".join(f"S{n} {d}" for n, d in review) or "none"
    out(f"Total: {len(rows)} rows; divisions to review: {review_txt}")
    _compare(db, rows, out)
    if dry_run:
        for r in rows:
            out(",".join(str(r[c]) for c in COLUMNS))
    else:
        write_table(table_path, rows)
        out(f"Wrote {table_path}. Review it and set reviewed=yes before apply.")
    return 0


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

class RowError(ValueError):
    pass


def parse_row(r: dict) -> dict:
    """A table row as {season, label, division, place, kind, team_name, players}.
    Raises RowError with the reason."""
    try:
        number = int(str(r.get("season") or "").strip())
        place = int(str(r.get("place") or "").strip())
    except ValueError:
        raise RowError("season and place must be numbers") from None
    if number < 1:
        raise RowError("season must be positive")
    if place not in PLACE_KINDS:
        raise RowError("place must be 1, 2 or 3")
    division = (r.get("division") or "").strip()
    if division not in accolades.DIVISIONS:
        raise RowError("division must be div1 or div2")
    team = bp._clean_name(_uncell(r.get("team_name")))
    if not team:
        raise RowError("team_name is empty")
    players = []
    seen = set()
    parts = [x for x in (_uncell(r.get("players")) or "").split(";") if x.strip()]
    if len(parts) > MAX_TEAM_PLAYERS:
        raise RowError(f"players: at most {MAX_TEAM_PLAYERS} per team")
    for part in parts:
        if not part.strip():
            continue
        aid_txt, sep, name = part.partition(":")
        try:
            aid = int(aid_txt.strip())
        except ValueError:
            raise RowError(f"players: {part.strip()!r} is not id:name") from None
        name = bp._clean_name(name)
        if not sep or not bp._valid_id(aid) or not name:
            raise RowError(f"players: {part.strip()!r} is not id:name")
        if aid in seen:
            raise RowError(f"players: {aid} is listed twice")
        seen.add(aid)
        players.append({"account_id": aid, "name": name})
    if not players:
        raise RowError("players is empty")
    return {"season": number, "label": f"Season {number}", "division": division, "place": place,
            "kind": PLACE_KINDS[place], "team_name": team, "players": players}


def _existing(db, row: dict) -> dict[int, str | None]:
    return {r.player_account_id: r.team_name for r in db.query(SeasonAccolade).filter(
        SeasonAccolade.season_label == row["label"], SeasonAccolade.kind == row["kind"],
        SeasonAccolade.division == row["division"]).all()}


def run_apply(db, table_path: str = DEFAULT_TABLE, dry_run: bool = False,
              replace: bool = False, out=print) -> int:
    """Write the reviewed rows. Exit 1 when the table can't be read or a reviewed row
    is malformed (the other rows are still written)."""
    if dry_run:
        out("Dry run: nothing is written.")
    try:
        with open(table_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            raw = list(reader)
    except OSError as e:
        out(f"Table {table_path} cannot be read ({type(e).__name__}). Nothing written.")
        return 1
    if missing:
        out(f"Table {table_path} lacks columns {', '.join(missing)}. Nothing written.")
        return 1
    code = 0
    by_season: dict[int, list[dict]] = {}
    for i, r in enumerate(raw, start=2):
        # Raw table values reach the terminal only after the control-character strip.
        clean = {k: bp._clean_name(str(r.get(k) or "")) or "" for k in ("season", "division", "place", "team_name")}
        team = f" {clean['team_name']}" if clean["team_name"] else ""
        where = f"line {i} (Season {clean['season']} {clean['division']} place {clean['place']}{team})"
        if (r.get("reviewed") or "").strip().lower() != "yes":
            out(f"Skipped {where}: not reviewed")
            continue
        try:
            row = parse_row(r)
        except RowError as e:
            out(f"Rejected {where}: {e}")
            code = 1
            continue
        by_season.setdefault(row["season"], []).append(row)
    for number in sorted(by_season):
        rows = sorted(by_season[number], key=lambda x: (x["division"], x["place"]))
        label = f"Season {number}"
        added = removed = 0
        written = []
        for row in rows:
            name = _KIND_NAMES.get(accolades.kind_key(row), row["kind"])
            what = f"{label} {name} {row['team_name']} ({len(row['players'])} players)"
            existing = _existing(db, row)
            wanted = {p["account_id"] for p in row["players"]}
            same = set(existing) == wanted and all(t == row["team_name"] for t in existing.values())
            if existing and same:
                out(f"{what}: already recorded")
                continue
            if existing and not replace:
                out(f"{what}: skipped, {len(existing)} rows already recorded for "
                    f"{', '.join(sorted({str(t) for t in existing.values()}))}; use --replace to overwrite")
                continue
            if dry_run:
                out(f"Would write {what}")
                written.append(row)
                continue
            if row["place"] == 1:
                a, rm = accolades.set_champions(db, label, row["division"], row["team_name"], row["players"], None)
            else:
                a, rm = accolades.set_placement(db, label, row["division"], row["kind"], row["team_name"],
                                                row["players"], None)
            added, removed = added + a, removed + rm
            written.append(row)
            out(f"Wrote {what}: {a} added, {rm} removed")
        if written and not dry_run:
            places = ";".join(f"{d}:{','.join(str(r['place']) for r in written if r['division'] == d)}"
                              for d in accolades.DIVISIONS if any(r["division"] == d for r in written))
            players = ";".join(f"{r['division']}:{r['place']}={len(r['players'])}" for r in written)
            db.add(AuditLog(timestamp=int(time.time()), actor_id=None, actor_username="script",
                            action=AUDIT_ACTION,
                            detail=f"season_label={label} places={places} players={players} "
                                   f"added={added} removed={removed} source=backfill"))
            db.commit()
    return code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Past seasons' placements 1-3 from OpenDota into a reviewed table (issue 233).")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="Fetch and derive; write the table (never the database)")
    b.add_argument("--season", type=int, action="append", default=[],
                   help="Only this season number; repeat for more (default: every past season)")
    b.add_argument("--dry-run", action="store_true", help="Print the table instead of writing it")
    b.add_argument("--overwrite", action="store_true",
                   help="Replace a table that already has reviewed rows")
    b.add_argument("--table", default=DEFAULT_TABLE, help="The CSV to write")
    b.add_argument("--cache", default=DEFAULT_CACHE, help=f"Local cache file (default {DEFAULT_CACHE})")
    b.add_argument("--pause", type=float, default=DEFAULT_PAUSE_SECONDS,
                   help="Seconds to wait between OpenDota calls")
    b.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                   help=f"OpenDota calls allowed in this run (default {DEFAULT_MAX_CALLS}); "
                   "a rerun continues from the cache")
    a = sub.add_parser("apply", help="Write the reviewed rows as accolades")
    a.add_argument("--table", default=DEFAULT_TABLE, help="The reviewed CSV")
    a.add_argument("--dry-run", action="store_true", help="Print what would be written")
    a.add_argument("--replace", action="store_true",
                   help="Overwrite places whose recorded rows differ from the table")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build" and args.max_calls < 1:
        parser.error("--max-calls must be at least 1")
    db = database.SessionLocal()
    try:
        if args.command == "build":
            return run_build(db, LEAGUE_FILE, args.cache, args.table, args.max_calls, args.pause,
                             seasons=args.season, dry_run=args.dry_run, overwrite=args.overwrite)
        return run_apply(db, args.table, dry_run=args.dry_run, replace=args.replace)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
