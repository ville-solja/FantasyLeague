"""Turn a Dota 2 replay (.dem) into the match summary Admin > Matches > Add match >
From replay accepts (issue 224). Runs on the operator's own machine only; the server
never sees the .dem file.

The replay is parsed by OpenDota's open-source parser (github.com/odota/parser), run
locally as a Docker container:

    git clone https://github.com/odota/parser && cd parser
    docker build -t odota-parser . && docker run --rm -p 5600:5600 odota-parser

    python scripts/replay_to_match.py 1234567890.dem            # writes match-<id>.json
    python scripts/replay_to_match.py replay.dem --out-dir out --parser-url http://localhost:5600

The parser answers a POST of the raw .dem with line-delimited JSON events. This script
reads three kinds:
  - "player_slot": slot (key, 0-9) -> player_slot (value: 0-4 Radiant, 128-132 Dire);
  - "interval": one per player per game second, with the game's own scoreboard counters
    (kills, deaths, assists, lh, denies, gold (total earned), obs_placed, sen_placed,
    camps_stacked, rune_pickups, towers_killed, roshans_killed, stuns, tower_damage,
    teamfight_participation, firstblood_claimed, hero_id, unit); the last one per slot
    holds the final values;
  - "epilogue": `key` is the replay's CDemoFileInfo serialised by Gson (protobuf field
    names with a trailing underscore: gameInfo_.dota_.matchId_, gameWinner_, endTime_,
    playerInfo_[].steamid_/heroName_/playerName_/gameTeam_, picksBans_, radiantTeamTag_;
    playbackTime_ at the top level). Text fields are Gson ByteStrings.

A stat that no player's final interval carries is written as 0 and listed under
`missing_stats`; the server then marks the match as having partial stats. Standard
library only.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_PARSER_URL = os.getenv("REPLAY_PARSER_URL", "http://localhost:5600")
STEAM_ID64_BASE = 76561197960265728

# Output stat -> parser interval field.
_INTERVAL_STATS = {
    "kills": "kills",
    "deaths": "deaths",
    "assists": "assists",
    "last_hits": "lh",
    "denies": "denies",
    "obs_placed": "obs_placed",
    "sen_placed": "sen_placed",
    "tower_damage": "tower_damage",
    "towers_killed": "towers_killed",
    "roshan_kills": "roshans_killed",
    "teamfight_participation": "teamfight_participation",
    "camps_stacked": "camps_stacked",
    "rune_pickups": "rune_pickups",
    "firstblood_claimed": "firstblood_claimed",
    "stuns": "stuns",
}
_FLOAT_STATS = {"teamfight_participation", "stuns"}
# Same order as manual_match.STAT_FIELDS (the server's schema).
STAT_ORDER = ["kills", "deaths", "assists", "last_hits", "denies", "gold_per_min",
              "obs_placed", "sen_placed", "tower_damage", "towers_killed", "roshan_kills",
              "teamfight_participation", "camps_stacked", "rune_pickups",
              "firstblood_claimed", "stuns"]


class ReplayError(Exception):
    """The replay or the parser output can't be turned into a match summary."""


class ParserUnavailable(ReplayError):
    """The local parser container could not be reached."""


def run_parser(dem_path: str, parser_url: str = DEFAULT_PARSER_URL, timeout: int = 900) -> list:
    """POST the .dem to the local parser and return its events (one dict per line)."""
    with open(dem_path, "rb") as fh:
        data = fh.read()
    req = urllib.request.Request(parser_url.rstrip("/") + "/", data=data, method="POST",
                                 headers={"Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise ReplayError(f"the parser rejected the replay (HTTP {e.code})") from e
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
        raise ParserUnavailable(
            f"could not reach the replay parser at {parser_url} ({e}). "
            "Start it with: docker run --rm -p 5600:5600 odota-parser") from e
    return parse_events(text.splitlines())


def parse_events(lines) -> list:
    events = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            events.append(e)
    return events


def _get(obj, *names):
    """A Gson-serialised protobuf field: `fooBar_`, `fooBar` or `foo_bar`."""
    if not isinstance(obj, dict):
        return None
    for name in names:
        for key in (name + "_", name):
            if key in obj:
                return obj[key]
    return None


def _hero_names(unit: str) -> set:
    """Both combat-log names of an interval `unit` (as odota's processMetadata builds
    them): CDOTA_Unit_Hero_ShadowShaman -> npc_dota_hero_shadowshaman and
    npc_dota_hero_shadow_shaman."""
    if not unit or not unit.startswith("CDOTA_Unit_Hero_"):
        return set()
    ending = unit[len("CDOTA_Unit_Hero_"):]
    snake = "".join("_" + c.lower() if c.isupper() else c for c in ending).lower()
    return {"npc_dota_hero_" + ending.lower(), "npc_dota_hero" + snake}


# C0 and C1 controls (U+0080-U+009F include an 8-bit CSI some terminals honour) and
# the bidi embedding/override/isolate characters that can reorder terminal output.
_BIDI_CONTROLS = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _unsafe_char(ch: str) -> bool:
    cp = ord(ch)
    return cp < 0x20 or 0x7f <= cp <= 0x9f or ch in _BIDI_CONTROLS


def _text(value):
    """A text field. The parser serialises protobuf strings as Gson ByteStrings,
    {"bytes": [...], "hash": 0}, with Java's signed bytes; plain strings are accepted
    too. Control characters are dropped so names can't garble the terminal."""
    if isinstance(value, dict) and isinstance(value.get("bytes"), list):
        try:
            value = bytes(b & 0xFF for b in value["bytes"]).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        value = "".join(ch for ch in value if not _unsafe_char(ch))
        return value.strip() or None
    return None


def aggregate(events: list) -> dict:
    """The match summary (the server's replay JSON schema) from parser events."""
    slot_to_player_slot = {}
    last_interval = {}
    epilogue = None
    for e in events:
        etype = e.get("type")
        if etype == "player_slot":
            try:
                slot_to_player_slot[int(e["key"])] = int(e["value"])
            except (KeyError, TypeError, ValueError):
                continue
        elif etype == "interval" and isinstance(e.get("slot"), int):
            if (e.get("time") or 0) >= 0:
                prev = last_interval.get(e["slot"])
                if prev is None or (e.get("time") or 0) >= (prev.get("time") or 0):
                    last_interval[e["slot"]] = e
        elif etype == "epilogue":
            try:
                epilogue = json.loads(e.get("key") or "")
            except ValueError as err:
                raise ReplayError("the parser's epilogue is not valid JSON") from err
    if epilogue is None:
        raise ReplayError("the parser output has no epilogue (incomplete or failed parse)")
    if len(last_interval) != 10:
        raise ReplayError(f"expected ten players in the parser output, found {len(last_interval)}")

    dota = _get(_get(epilogue, "gameInfo", "game_info"), "dota") or {}
    match_id = _get(dota, "matchId", "match_id")
    if not match_id:
        raise ReplayError("the replay has no match id")
    winner = _get(dota, "gameWinner", "game_winner")
    if winner not in (2, 3):
        raise ReplayError("the replay has no winner")

    duration = max(int(e.get("time") or 0) for e in last_interval.values())
    if duration <= 0:
        raise ReplayError("could not tell the game's duration")
    end_time = _get(dota, "endTime", "end_time")
    # The replay's playback time covers the draft and pre-game too, so end time minus
    # playback time lands on the match's start (within about 25 s of OpenDota's
    # start_time on a real Kanaliiga replay); end time minus the game duration would
    # be about 20 minutes late. Older or partial output without it falls back.
    playback = _get(epilogue, "playbackTime", "playback_time")
    if end_time and isinstance(playback, (int, float)) and 0 < playback < 6 * 3600:
        start_time = int(end_time) - int(round(playback))
    else:
        start_time = int(end_time) - duration if end_time else None
    if not start_time:
        raise ReplayError("the replay has no end time")

    # Accounts by hero name; the file info lists each player's hero and Steam id.
    by_hero, by_team = {}, {2: [], 3: []}
    for info in _get(dota, "playerInfo", "player_info") or []:
        steamid = _get(info, "steamid")
        if not steamid or _get(info, "isFakeClient", "is_fake_client"):
            continue
        entry = {"account_id": int(steamid) - STEAM_ID64_BASE,
                 "personaname": _text(_get(info, "playerName", "player_name"))}
        hero = _text(_get(info, "heroName", "hero_name"))
        if hero:
            by_hero[hero.lower()] = entry
        team = _get(info, "gameTeam", "game_team")
        if team in by_team:
            by_team[team].append(entry)

    present = {stat: False for stat in _INTERVAL_STATS}
    gold_present = False
    players = []
    for slot in sorted(last_interval):
        e = last_interval[slot]
        player_slot = slot_to_player_slot.get(slot, slot if slot < 5 else 128 + slot - 5)
        side = "radiant" if player_slot < 128 else "dire"
        account = next((by_hero[n] for n in _hero_names(e.get("unit") or "") if n in by_hero), None)
        if account is None:
            team_list = by_team[2 if side == "radiant" else 3]
            index = player_slot if side == "radiant" else player_slot - 128
            account = team_list[index] if 0 <= index < len(team_list) else None
        if account is None or account["account_id"] <= 0:
            raise ReplayError(f"could not match the player in slot {slot} to a Steam account")
        hero_id = e.get("hero_id")
        if not isinstance(hero_id, int) or hero_id <= 0:
            raise ReplayError(f"no hero for the player in slot {slot}")
        row = {"account_id": account["account_id"], "side": side, "hero_id": hero_id}
        if account.get("personaname"):
            row["personaname"] = account["personaname"][:100]
        for stat, field in _INTERVAL_STATS.items():
            value = e.get(field)
            if isinstance(value, bool):
                value = int(value)
            if isinstance(value, (int, float)):
                present[stat] = True
                row[stat] = float(value) if stat in _FLOAT_STATS else int(round(value))
            else:
                row[stat] = 0.0 if stat in _FLOAT_STATS else 0
        gold = e.get("gold")
        if isinstance(gold, (int, float)) and not isinstance(gold, bool):
            gold_present = True
            row["gold_per_min"] = int(round(gold * 60 / duration))
        else:
            row["gold_per_min"] = 0
        row["firstblood_claimed"] = min(int(row["firstblood_claimed"]), 1)
        row["teamfight_participation"] = min(max(row["teamfight_participation"], 0.0), 1.0)
        players.append(row)

    missing = [s for s in STAT_ORDER if (s == "gold_per_min" and not gold_present)
               or (s != "gold_per_min" and not present[s])]
    for row in players:
        for stat in missing:
            row[stat] = 0.0 if stat in _FLOAT_STATS else 0
        ordered = {k: row[k] for k in ("account_id", "side", "hero_id", "personaname") if k in row}
        ordered.update({s: row[s] for s in STAT_ORDER})
        row.clear()
        row.update(ordered)

    picks_bans = []
    for i, pb in enumerate(_get(dota, "picksBans", "picks_bans") or []):
        hero_id = _get(pb, "heroId", "hero_id")
        team = _get(pb, "team")
        if not isinstance(hero_id, int) or hero_id <= 0 or team not in (2, 3):
            continue
        picks_bans.append({"hero_id": hero_id, "is_pick": bool(_get(pb, "isPick", "is_pick")),
                           "team": 0 if team == 2 else 1, "order": i})

    return {
        "match_id": int(match_id),
        "start_time": int(start_time),
        "duration": duration,
        "radiant_win": winner == 2,
        "radiant_name": _text(_get(dota, "radiantTeamTag", "radiant_team_tag")),
        "dire_name": _text(_get(dota, "direTeamTag", "dire_team_tag")),
        "picks_bans": picks_bans,
        "players": players,
        "missing_stats": missing,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Turn a .dem replay into an Add match JSON file.")
    ap.add_argument("replay", help="path to the .dem file")
    ap.add_argument("--out-dir", default=".", help="where match-<id>.json is written")
    ap.add_argument("--parser-url", default=DEFAULT_PARSER_URL,
                    help="local odota/parser URL (default %(default)s)")
    args = ap.parse_args(argv)
    try:
        events = run_parser(args.replay, args.parser_url)
        summary = aggregate(events)
    except OSError as e:
        print(f"error: cannot read {args.replay}: {e}", file=sys.stderr)
        return 1
    except ReplayError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"match-{summary['match_id']}.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")
    print(f"wrote {out_path}")
    if summary["missing_stats"]:
        print("partial stats (stored as 0): " + ", ".join(summary["missing_stats"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
