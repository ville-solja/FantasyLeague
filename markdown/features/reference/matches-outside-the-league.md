# Matches Outside the League

Admins can add a Kanaliiga game that wasn't started as a league lobby. OpenDota's league list doesn't include such games, so ingest never finds them. A match comes in from OpenDota by its id, or from a replay parsed on the operator's own machine. Either way it is stored and scored like any league match. Plan: `markdown/plans/plan-issue-224-matches-outside-the-league.md` (issue #224). Stories: `markdown/stories/data-and-players.md`, "Matches Outside the League".

---

## Two ways in

Both are in **Admin › Matches › Add match** (see `markdown/ui_description/admin.md`).

- **From OpenDota.** OpenDota has the match, but not under the league. The admin enters the match id, checks the preview, and picks the league (division) and the Radiant and Dire teams. The server fetches `/matches/{id}` again when storing, so the client never supplies stats. Stored with `source = opendota_manual`. Parse retry treats it like an ingested match: when OpenDota hasn't parsed it yet (`version: null`), a parse is requested and the retry pass picks it up. A refresh keeps the teams the admin chose.
- **From a replay.** OpenDota has no usable data. The operator runs `backend/scripts/replay_to_match.py` on their own machine against the `.dem` file and uploads the `match-<id>.json` it writes. The server validates the JSON and stores it with `source = replay`.

The server never parses `.dem` files. Replays are 50–150 MB of untrusted binary data, so only a small, strictly validated JSON summary reaches the server.

## How a manual match is stored

Every path stores through one function, `ingest._store_match_payload()`: league ingest (`ingest_match`) and both manual paths (`ingest.store_manual_match()`). They share:

- the short-match rule: under 900 s nothing is stored (`MIN_MATCH_SECONDS`);
- `Player` rows for unknown account ids (`_ensure_players`), stat rows from `_build_stat_row`, and `match_bans` from the non-pick `picks_bans` entries;
- the follow-ups: the Twitch MVP bonus is re-applied and the match's stored card points are refreshed (`_reapply_mvp_bonus`), its live-match row is dropped, `match_timings.ingested_at` is set, and the Twitch panel cache is cleared.

`store_manual_match()` also:

- uses the admin-chosen team ids for `matches.radiant_team_id` / `dire_team_id` and each stat row's `team_id`. These ids drive the Schedule series results (`schedule.resolve_series_result`) and the team views. Team rows are not created from the payload for a chosen side;
- re-runs bench substitutions for the affected scoring weeks (`weeks.rerun_substitutions_for`, reason `match_added`, with the old and new week when a replacement moves the match). Only weeks whose substitutions have already run are re-run;
- clears the schedule cache (`schedule.bust_cache`), so the series result appears on the next load.

The chosen league must be a monitored league. It sets the division (`accolades.league_division`), which the Teams tab and accolades read. The scoring week comes from `start_time` as usual, and a week override (issue #193) still applies.

### Partial stats (replay matches)

A replay match uses the existing partial-stats marker, `matches.parse_status` (see `unparseable-match-handling.md`):

| Replay summary | `parse_status` | Effect |
|---|---|---|
| `missing_stats` is empty | `parsed` | No marker |
| `missing_stats` lists any stat | `unparseable` | The player popup shows the existing "Partial stats" badge. The missing stats are stored as 0 |

`unparseable` was chosen because it already means "OpenDota will never parse this match", it shows the existing badge, and the retry pass already skips it. In Admin › Matches › Scoring, unticking **Unparseable** on a replay match sets `parsed` (a replay match is never re-fetched, so it is never `unparsed`).

### Parse retry leaves replay matches alone

- `ingest.find_unparsed_match_ids()` skips `source = 'replay'`, so the background pass and `POST /ingest/retry-unparsed` never fetch or replace a replay match.
- `ingest.mark_stuck_matches_unparseable()` skips them.
- `POST /admin/matches/{id}/retry-parse` answers 409 for a replay match, and the Admin UI shows no **Retry parse** button on it.

### Replace rule

- A match ingested from the league (`source = 'league'`) is never replaced: 409, with or without `confirm`.
- An earlier `opendota_manual` or `replay` match is replaced only with `"confirm": true`. Without it the answer is 409 with the message "… Confirm to replace its stats."; the dialog asks and resends. The match row keeps its admin fields (VOD link, week override, exclusion from scoring). Its match fields, stat rows and bans are replaced, and `source` becomes the new path's source.
- If the league later lists the match, `ingest_league` skips it because the id is already stored, so the manual row stays. To refresh it, add it again from OpenDota.
- There is no delete. To take a manual match out of scoring, use the existing **Not scored** toggle.

## Endpoints

Both routes are in `backend/routers/admin_matches.py`; the request handling, validation and preview are in `backend/manual_match.py` (`read_body`, `preview`, `store`). The body is read raw and size-checked before parsing: anything over 56 KB plus 4 KB of envelope (60 KB, under the site-wide 64 KB `MAX_REQUEST_BODY_BYTES`) answers 413, and anything that isn't a JSON object answers 422 ("The request is not valid JSON"). The body is `{"match_id": int}` or `{"replay": {…}}`, never both. Unknown body keys answer 422. The OpenDota fetch and the store run in a worker thread.

### `POST /admin/matches/manual/preview`
Admin only (`require_admin`). Writes nothing. Refusals (`detail` is a message):

| Status | When |
|---|---|
| 409 | The match id is already stored as a league match (checked before calling OpenDota) |
| 422 | OpenDota answers nothing or has no player data: "… Use a replay import instead." |
| 422 | Shorter than 15 minutes |
| 422 | The replay summary fails validation: `"<field>: <reason>"`, e.g. `players[3].hero_id: unknown hero id` |

Response (the same shape for both paths):

```json
{
  "source": "opendota_manual" | "replay",
  "match_id": 8100000001, "start_time": 1790000000, "duration": 2400,
  "radiant_win": true, "winner": "radiant",
  "radiant_name": "…", "dire_name": "…",
  "suggested_radiant_team_id": 11, "suggested_dire_team_id": null,
  "players": [{"account_id", "name", "side", "hero_id", "hero_name", "kills", "deaths", "assists", "in_pool"}],
  "not_in_pool": [account ids],
  "missing_stats": ["teamfight_participation"],
  "partial_note": "Partial stats: teamfight_participation" | null,
  "existing_source": null | "opendota_manual" | "replay",
  "leagues": [{"id", "name", "division", "division_label"}],
  "teams": [{"id", "name"}]
}
```

A suggested team id is a team whose name equals the payload's team name (ignoring case and extra spaces), when exactly one team matches. `in_pool` means the player has an active `Player` row; players outside the pool are still stored. `hero_name` comes from the cached OpenDota hero constants and is null on a cold cache.

### `POST /admin/matches/manual`
Admin with a recent re-auth (route dependency `require_recent_reauth`, 403 `{"detail": "reauth_required"}`). Body: `match_id` or `replay`, plus `league_id`, `radiant_team_id`, `dire_team_id` and optional `confirm` (default false). Refusals: the preview's, plus 422 for a league that isn't monitored, a missing or unknown team (`radiant_team_id: choose the Radiant team`), or the same team on both sides. A replacement without `confirm`, or any league match, gets 409. While `ingest.INGEST_LOCK` is held (a poll cycle, a manual ingest or a parse retry), the answer is 409.

Response: `{"match_id", "source", "league_id", "radiant_team_id", "dire_team_id", "parse_status", "missing_stats", "replaced", "players"}`.

Audited as `admin_match_added`: `detail="source=<source> match_id=<id> league_id=<id> radiant_team_id=<id> dire_team_id=<id> replaced=yes|no[ previous_source=<source>][ missing_stats=a,b]"`.

### `GET /admin/matches`
Each row also has `source`, plus `added_by` and `added_at` (the actor and time of the latest `admin_match_added` audit row for that match; null for league matches). Public endpoints don't expose `source`.

## Replay summary schema (`backend/manual_match.py`)

Validation is strict: an unknown key at any level is refused, and so is a missing required key or an out-of-range number. Booleans are not accepted as numbers.

| Key | Rule |
|---|---|
| `match_id` | required, integer 1 … 2⁶³−1 |
| `start_time` | required, Unix time between 2010 and 2100 |
| `duration` | required, seconds 1 … 14400 (under 900 is refused as too short) |
| `radiant_win` | required, boolean |
| `radiant_name`, `dire_name` | optional, text up to 100 characters, or null |
| `picks_bans` | optional, up to 48 entries `{hero_id, is_pick, team (0 Radiant, 1 Dire), order?}` |
| `missing_stats` | optional, names from the stat list below |
| `players` | required, exactly ten, five with `side: "radiant"` and five with `"dire"`, no repeated account id |

Each player has `account_id` (1 … 2⁶³−1), `side`, `hero_id` (a known hero), an optional `personaname`, and every stat `_build_stat_row` reads, with these ranges:

| Stat | Range | Stat | Range |
|---|---|---|---|
| `kills`, `deaths`, `assists` | 0–200 | `towers_killed` | 0–11 |
| `last_hits` | 0–5000 | `roshan_kills` | 0–10 |
| `denies` | 0–1000 | `teamfight_participation` | 0–1 (number) |
| `gold_per_min` | 0–3000 | `camps_stacked` | 0–300 |
| `obs_placed` | 0–200 | `rune_pickups` | 0–500 |
| `sen_placed` | 0–300 | `firstblood_claimed` | 0–1 |
| `tower_damage` | 0–100000 | `stuns` | 0–7200 seconds (number) |

A known hero is any id in `manual_match.KNOWN_HERO_IDS` (Dota hero ids up to Largo, 155) or in the cached OpenDota hero constants. So a hero released later is accepted once the cache is warm.

## Data

`matches.source` (`String`, not null, default `league`): `league`, `opendota_manual` or `replay`. Added by migration `043_matches_source`, which backfills `league` for every existing row. Run `bash scripts/backup-db.sh` before deploying it.

## Replay run book

For the operator, on their own machine. You need Docker, Python 3 and the `.dem` file (from the players, or from the client's replay folder, `.../dota/replays/<match id>.dem`). A `.dem.bz2` has to be decompressed first (`bunzip2`).

1. Build and start OpenDota's parser once:
   ```
   git clone https://github.com/odota/parser ~/odota-parser && cd ~/odota-parser
   docker build -t odota-parser .
   docker run --rm -p 127.0.0.1:5600:5600 odota-parser
   ```
   The container listens on port 5600 (bound to this machine only). Building it needs Maven, which the Dockerfile provides.
2. In another terminal, from the repository's `backend/` folder:
   ```
   python scripts/replay_to_match.py /path/to/8100000001.dem --out-dir "$(dirname /path/to/8100000001.dem)"
   ```
   It prints `wrote /tmp/match-8100000001.json`, and lists any partial stats. If the parser is elsewhere, use `--parser-url http://host:5600` (or `REPLAY_PARSER_URL`). When the container isn't running, the script prints "could not reach the replay parser …" and exits with code 2 without writing a file.
3. In **Admin › Matches › Add match › From replay**, choose the file and click **Check file**. Compare the preview with the in-client scoreboard: winner, duration, and every player's hero and K/D/A.
4. Pick the league and the two teams, then click **Add** (you may be asked to confirm your password or Steam sign-in).
5. To correct a mistake, add a fixed file again and confirm the replacement.

### What the script reads

The parser answers a POST of the raw `.dem` with line-delimited JSON events (`scripts/test.sh` in odota/parser). The script reads three kinds:

- `player_slot`: `key` is the slot (0–9), `value` the player slot (0–4 Radiant, 128–132 Dire).
- `interval`: one per player per game second until the game ends, with the game's own scoreboard counters. The last one per slot gives the final values: `kills`, `deaths`, `assists`, `lh` → `last_hits`, `denies`, `obs_placed`, `sen_placed`, `camps_stacked`, `rune_pickups`, `towers_killed`, `roshans_killed` → `roshan_kills`, `stuns`, `tower_damage`, `teamfight_participation`, `firstblood_claimed` (capped at 1), `hero_id` and `unit` (the hero's entity class).
- `epilogue`: `key` is the replay's `CDemoFileInfo` serialised by Gson. Protobuf field names have a trailing underscore: `gameInfo_.dota_.matchId_`, `gameWinner_` (2 Radiant, 3 Dire), `endTime_`, `radiantTeamTag_`, `direTeamTag_`, `picksBans_`, and `playerInfo_[]` with `steamid_`, `heroName_`, `playerName_` and `gameTeam_`; and, at the top level of the epilogue, `playbackTime_` (the whole replay's length in seconds, draft and pre-game included). Text fields arrive as Gson ByteStrings (below).

From these:

- **Account ids**: the account id is `steamid − 76561197960265728`. Each slot is matched to its file-info player by hero name (`CDOTA_Unit_Hero_ShadowShaman` → `npc_dota_hero_shadow_shaman`, both spellings, as odota's `processMetadata` builds them), falling back to the order within the team. A slot that can't be matched stops the script with an error.
- **Duration**: the time of the last interval (seconds from the horn). **Start time**: `endTime_` minus `playbackTime_` (within about 25 s of OpenDota's `start_time` on the Step 0 replay); without `playbackTime_`, `endTime_` minus the duration, which is about 20 minutes late.
- **GPM**: total earned gold (`gold`) × 60 / duration. This is close to, but not guaranteed to equal, OpenDota's scoreboard GPM.
- **Missing stats**: any stat that no player's final interval carries is set to 0 for everyone and listed under `missing_stats`. The parser leaves out `teamfight_participation` when the game reports none, so it is the likeliest one.

The script uses the Python standard library only. It contains no `@dataclass` (tests load it with `spec_from_file_location`).

### Step 0: checked on a real replay (2026-10-26)

Run on the Div 2 series SC vs HOLISA (Season 16): game 2, `9061985546`, is on OpenDota (league 20163, parsed) and served as the reference. Games 1 and 3 (`9061891961`, `9062072752`) are not on OpenDota at all and were imported from their replays.

Game 2's JSON against OpenDota's match data:

| Field | Result |
|---|---|
| Players, sides, accounts, heroes, names | All 10 match |
| Winner, duration, picks and bans | Match (duration 1 s longer) |
| K/D/A, last hits, denies, wards, towers, Roshans, camps, runes, first blood | Exact |
| `teamfight_participation`, `stuns` | Within 2 % (the game's own counters) |
| `gold_per_min` | Within 1 (three players +1, from the 1 s duration difference) |
| `tower_damage` | About 1 % low for three players |
| `start_time` | 25 s later than OpenDota's |

Two fixes came out of the run:

- **Names are ByteStrings.** The parser serialises protobuf strings (`heroName_`, `playerName_`, the team tags) as Gson ByteStrings, `{"bytes": [...], "hash": 0}`, with Java's signed bytes. `_text` decodes them and drops control characters, so names can't garble the operator's terminal. Before the fix, hero names were empty, so slots fell back to their order within the team: right on this replay, but fragile. Player names and team tags were empty too.
- **Start time.** `endTime_` minus the game duration was 20.5 minutes late, because the duration excludes the draft and pre-game. The script now uses `endTime_ − playbackTime_` (the whole replay), which landed within 25 s. Output without `playbackTime_` falls back to the old rule.

No stat had to move to `missing_stats`: all of them are present and within the tolerances above. The team tags (for example "SC", "HOLISA") are short tags, not the full team names, so the Add match preview won't suggest teams from them; pick both teams by hand.

The replay files live in the git-ignored `parse/` folder (`*.dem` is ignored too); the upload files are written next to them.

### Test fixture

`backend/tests/fixtures/replay_parser_sample.jsonl` is **synthetic**. It was written by hand in the parser's event format, not recorded from a real replay: ten players, `player_slot` events, intervals at −30, 0, 600 and 2400 s without `teamfight_participation`, two other events, and an epilogue whose players are listed out of slot order. It stays synthetic on purpose (a real recording carries players' Steam ids); since Step 0 the script's tests also cover the real format: ByteString names and `playbackTime_`.

## Tests

`backend/tests/test_issue_224_matches_outside_the_league.py` (79 tests, no network): migration, the shared store, both preview and store paths with their refusals, re-auth and audit, the week, Schedule, leaderboard and team-view follow-ups, replay validation, parse-retry exclusion, re-imports, the script against the fixture and the real parser format (ByteString names, `playbackTime_`), the admin list, and the frontend dialog, chips, filter and CSS.

