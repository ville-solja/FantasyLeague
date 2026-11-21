# Plan: Courier Kills as a Scoring Stat

## Context
Issue #134: "Courier kills as fantasy point factor." The issue has only its title. Killing the enemy courier is a real play (it costs the other team items and time), but fantasy scoring ignores it today: the scored stats are in `scoring.SCORING_STATS` and courier kills are not among them.

OpenDota has the number per player: `players[].courier_kills` in a parsed match (checked on a season 16 league match: three players with 1 each, matching their `killed.npc_dota_courier` counts). Like stuns, wards and camps, it is filled only once OpenDota has parsed the replay; an unparsed match has no value, and it counts as 0 like the other parse-only stats.

This plan adds courier kills as a scored stat for season 17: stored per player per game, weighted like the other stats, shown wherever per-game stats and the scoring formula are shown.

**Decisions** (change them in review if needed):
- **Weight 1.0 per courier kill**, the same as a tower or Roshan kill: rare (0 to 2 a game), worth about three hero kills (0.3 each). An admin changes it like any weight (`WEIGHTS_JSON`; the Admin Scoring Weights table is read-only).
- **No backfill of past matches.** Stored season 16 games keep `courier_kills = 0`, so season 16 points, leaderboards and accolades do not move. Refetching every past match from OpenDota is possible later but is not part of this issue.
- **Not a card modifier.** Card modifiers pick from the scored stats; a modifier on a stat this rare would almost never pay out and would read as a wasted draw. Courier kills are scored but left out of the modifier pool. Existing cards keep their modifiers.
- **Parse-only.** The "Partial stats" note names courier kills among the stats an unparsed replay lacks.
- **Gate:** this changes scoring, so `/scoring-analyst` traces it before it ships (CLAUDE.md review gates).

Resolves GitHub issue #134.

## User Stories

### Courier Kills Earn Fantasy Points
**User story**
As a fantasy player, I want a player who kills the enemy courier to earn points for it, so that the score rewards a play that matters in the game.

**Acceptance criteria**
- **Stored:** ingest stores each player's `courier_kills` from OpenDota's match data in a new `player_match_stats.courier_kills` column (integer, default 0); a match without the field (unparsed, or OpenDota leaves it out) stores 0.
- **Scored:** `courier_kills` is one of `scoring.SCORING_STATS`, so `fantasy_score` adds `courier_kills × weight` to every per-game score: card points, leaderboards, raw points (#244), the Weekly Report and the Twitch panel all include it.
- **Weight:** a new weight `courier_kills` ("Courier kills", default 1.0) is seeded for new and existing databases and can be overridden by `WEIGHTS_JSON`; the Admin Scoring Weights table lists it (read-only, like every weight).
- **Re-parse:** when a match first stored unparsed is stored again parsed (the parse retry), its courier kills are stored and its points updated, like the other parse-only stats.
- **Manual matches:** a match added from OpenDota stores courier kills like a league match. A replay JSON (from `scripts/replay_to_match.py`, which counts each player's courier kills from the combat log's courier deaths) accepts `courier_kills` per player (0 to 10), like Roshan kills. An older replay JSON without it is still accepted: it stores 0, lists `courier_kills` under `missing_stats` and is marked Partial stats.

### Past Points Stay the Same
**User story**
As a player looking back at season 16, I want past scores to stay as they were, so that a change for next season does not rewrite the last one.

**Acceptance criteria**
- After the migration and the new weight, every stored match's `courier_kills` is 0, and every season 16 card point, leaderboard total, raw point and accolade value is unchanged (the startup card-point rebuild that runs when weights change produces the same numbers).
- Nothing refetches past matches from OpenDota.

### See Courier Kills in the Stats and the Rules
**User story**
As a fantasy player, I want to see courier kills in a player's game stats and in the scoring rules, so that I know where points came from.

**Acceptance criteria**
- **Player popup:** each game in a player's match history shows courier kills with the other objective stats (next to towers and Roshan); the popup's stat groups include it.
- **How to Play:** the scoring list shows "Courier kills" with its current weight, read from the weights like the others.
- **Point simulator:** `POST /simulate/{match_id}` accepts `courier_kills` as a weight override, returns each player's stored courier kills in `stats`, and its documentation (`GET /simulate`) lists it. (The simulator takes weight overrides only; stats come from the stored match.)
- **Partial stats:** the tooltip names courier kills among the stats an unparsed replay counts as 0.

### Card Modifiers Leave Courier Kills Out
**User story**
As a player drawing cards, I want modifiers only on stats that come up often enough to matter, so that a rare or better card is never wasted on a near-useless modifier.

**Acceptance criteria**
- A card drawn after this change never gets a `courier_kills` modifier, at any rarity, while every other scored stat (and deaths) can still be chosen.
- Existing cards and their modifiers are unchanged.
- The card rules list of modifier targets does not include courier kills.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py`, `backend/migrate.py` | `PlayerMatchStats.courier_kills` (`Integer, default 0`) and a numbered migration adding it (`PRAGMA table_info` guard) |
| `backend/ingest.py` | `_build_stat_row` (first ingest, manual matches and the parse retry) stores `courier_kills` (absent or null reads 0); PARSE RETRY comment |
| `backend/scoring.py` | Add `courier_kills` to `SCORING_STATS` and `STAT_LABELS` |
| `backend/seed.py` | `DEFAULT_WEIGHTS` gains `courier_kills` (1.0) |
| `backend/card_utils.py` | `_SCORED_STAT_COLS` (the modifier pool) is `SCORING_STATS` minus `NO_MODIFIER_STATS = {"courier_kills"}`, plus `deaths`; `player_insights.modifier_values` uses the same pool |
| `backend/routers/leaderboard.py` | `/simulate` weight override, docs, the stats query and output; also adds the missing `assists` (a pre-existing gap: the simulator scored assists as 0) |
| `backend/routers/players.py`, `backend/player_insights.py` | Match history query and the Objectives stat group |
| `backend/manual_match.py`, `backend/scripts/replay_to_match.py` | Replay JSON accepts courier kills (0 to 10), optional for older files (then listed under `missing_stats`); the script counts them from `DOTA_COMBATLOG_DEATH` events whose target is a courier |
| `frontend/app-init.js`, `frontend/app-player-popup.js`, `frontend/app-players.js` | How to Play scoring list and label, popup stat, Partial stats tooltip |
| `backend/tests/test_issue_134_courier_kills_scoring.py` | Tests |
| `markdown/features/core/cards.md`, `core/players.md`, `reference/point-simulator.md`, `reference/unparseable-match-handling.md`, `reference/matches-outside-the-league.md` | Formula, modifier targets, payloads, tooltip text, replay schema |

### Step 1 — Store it
Add the column and migration `047_pms_courier_kills` (`INTEGER DEFAULT 0`, `PRAGMA table_info` guard). In `ingest._build_stat_row`, store `courier_kills`. Check the re-parse path (OpenDota parse retry) replaces the row's stats including the new one. Grep `backend/tests` for tests that pin the `player_match_stats` column list or the migration list before adding.

### Step 2 — Score it
Add it to `SCORING_STATS` and `STAT_LABELS`, and the weight to `DEFAULT_WEIGHTS`. Confirm `seed_weights` adds a missing key to an existing database without touching the others, and that the card-point fingerprint changes so the startup rebuild runs and produces unchanged numbers for stored matches (all `courier_kills = 0`).

### Step 3 — Keep it out of modifiers
Build `_SCORED_STAT_COLS` from `SCORING_STATS` minus a small `NO_MODIFIER_STATS` set holding `courier_kills`, plus `deaths`. Check `image.py` and the Weekly Report breakdown, which label modifiers through `STAT_LABELS`, still work for every existing modifier.

### Step 4 — Show it
`/simulate` (model field, docs dict, stats query and output), the player match history query, the Objectives group in `player_insights`, the popup stat list, the How to Play scoring list and label, the manual match form bounds and the Partial stats tooltip. Grep `backend/tests` for each list this changes (the How to Play stat list, the simulate docs keys, the tooltip text) and update their pins together.

### Step 5 — Tests
- Ingest stores `courier_kills` from a payload and 0 when absent; re-parse updates it.
- `fantasy_score` adds `courier_kills × weight`; a weight change through `WEIGHTS_JSON` applies.
- Migration adds the column to a legacy database and is idempotent; schema coverage passes.
- Seeding adds the weight to an existing database without changing others.
- Past points unchanged: stored matches before and after the change give the same card points and raw points.
- The modifier pool never contains `courier_kills` (draw many cards with a seeded random) and still contains every other stat and `deaths`.
- `/simulate`, the match history payload, the popup stat list, the How to Play list and the manual match form include it.

## Verification
- Run `bash scripts/backup-db.sh` before deploying (a migration).
- After deploy, ingest a parsed league match with a courier kill (or re-ingest one on a copy): the player's stats show 1 courier kill and the points include the weight.
- The Admin Scoring Weights table lists "Courier kills" at 1.0; How to Play shows it.
- A season 16 leaderboard total is the same before and after.
- `/scoring-analyst` traces the new stat end to end.
