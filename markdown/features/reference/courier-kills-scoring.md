# Courier Kills Scoring

Courier kills count toward fantasy points from season 17: each player's courier kills in a game, from OpenDota's parsed match data, times a weight (default 1.0). For fantasy players and the admins who tune scoring. Issue #134. Plan: `markdown/plans/plan-issue-134-courier-kills-scoring.md`.

---

## Stat

- **Source:** OpenDota `players[].courier_kills`, filled only for a parsed replay. `ingest._build_stat_row` (first ingest, Add match from OpenDota, and the parse retry `refresh_match_stats`) stores it; a missing or null value stores 0, like the other parse-only stats.
- **Stored:** `player_match_stats.courier_kills` (`INTEGER DEFAULT 0`), added by migration `047_pms_courier_kills`. Run `bash scripts/backup-db.sh` before deploying it.
- **Scored:** one of `scoring.SCORING_STATS` (label "Couriers" in `STAT_LABELS`, which only names modifiers: card images, Weekly Report modifier chips and `modifier_values`, so it is never shown for this stat), so `fantasy_score` adds `courier_kills × weight` to every per-game score: card points, leaderboards, raw points (#244), the Weekly Report and the Twitch panel.
- **Not a card modifier:** `card_utils.NO_MODIFIER_STATS = {"courier_kills"}` keeps it out of the draw pool (`card_utils._SCORED_STAT_COLS`: every other scored stat plus `deaths`). `player_insights.modifier_values` (the popup's "A +10 % modifier is worth most on" list, also used by the team popup) uses the same pool. Existing modifiers and the `card_modifiers` table are unchanged; on a fresh database the `stat_key` CHECK allows `courier_kills`, on a migrated one it does not, and nothing assigns it either way.
- **Past matches:** not backfilled. Stored season 16 rows read 0, so their points are unchanged. Adding the weight changes the weights fingerprint, so the startup check (`card_points.ensure_card_points_current`) rebuilds the stored card points once, to the same values. No OpenDota request is made.

## Replay imports

`scripts/replay_to_match.py` counts each player's courier kills from the parser's `DOTA_COMBATLOG_DEATH` events whose `targetname` is a courier, credited to the slot whose hero is the `attackername`. On a real Season 16 replay (9061985546) its counts matched OpenDota's. When the parser output has no combat-log deaths at all, `courier_kills` is 0 and listed under `missing_stats`.

The replay JSON (`manual_match.STAT_FIELDS`) takes `courier_kills` per player, 0 to 10. It is the one stat a file may leave out (`manual_match.LATE_STATS`), so a file written before season 17 is still accepted: every player stores 0, `courier_kills` is added to `missing_stats` and the match is stored as Partial stats. See [Matches Outside the League](matches-outside-the-league.md).

## Shown

- **Player popup:** `GET /players/{id}` match history rows carry `courier_kills`; the Details panel shows "Courier kills" after Roshan, and the points breakdown counts it under Objectives (with towers and Roshan).
- **How to Play:** the scoring list shows "Courier kills" with its current weight from `GET /weights`.
- **Point simulator:** `POST /simulate/{match_id}` takes a `courier_kills` weight override and returns each player's stored courier kills in `stats`; `GET /simulate` documents both. The same change added the `assists` field the simulator was missing (it scored assists as 0). See [Point Simulator](point-simulator.md).
- **Partial stats tooltip:** "The replay has not been parsed, so wards, stuns, teamfight, runes, camps and courier kills count as 0." See [Unparseable Match Handling](unparseable-match-handling.md).

## Configuration

| Weight | Default | Description |
|---|---|---|
| `courier_kills` | `1.0` | Points per courier kill. Override with `WEIGHTS_JSON` (for example `{"courier_kills": 2.0}`); applied by `seed_weights()` at the next start. The Admin Scoring Weights table lists it read-only, like every weight |
