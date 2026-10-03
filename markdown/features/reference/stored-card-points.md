# Stored Card Points

Stores each card's fantasy points per match, so My Team, the weekly and season leaderboards and season archives all sum the same stored values instead of recalculating them on every request. Resolves GitHub issue #141.

---

## Why

Before this, every view recalculated card points from raw stats per request, with two problems:
- It was slow.
- The death bonus was floored at 0 over a whole week or season rather than per match. A card's season total was therefore not the sum of its weekly values, and a week didn't match the Players tab's per-match points.

## How it works

### Storage

`card_match_points` (`CardMatchPoints` in `backend/models.py`) holds one row per (card, match), unique on `(card_id, match_id)` (`uq_card_match_points`):

| Column | Meaning |
|---|---|
| `card_id` | The card |
| `match_id` | The match |
| `player_id` | The card's player (for scoped refreshes) |
| `points` | The card's final points for that match |

`points` is `card_fantasy_score(match stats, card modifiers, match_count=1)`, plus the MVP bonus (`_mvp_bonus_delta`) when the player was that match's MVP, times the rarity multiplier. The rarity multiplier is `1 + mod_<type>`, where `mod_<type>` (from `card_utils._load_weights`) is the weight `rarity_<type>` (a percent, e.g. `rarity_rare` = 1.0) divided by 100. `points` is stored unrounded. The death bonus is therefore floored at 0 per match, the same way the Players tab's `fantasy_points` are. A covering index `(card_id, match_id, points)` serves the readers.

`scoring_state` (`ScoringState`) is a small key/value table. The key `card_points_weights_fingerprint` holds the SHA-256 of the sorted weight key/value pairs the stored rows were built with.

Both are new tables, created by `create_all`; no migration is needed.

### Writing: `backend/card_points.py`

| Function | Does |
|---|---|
| `refresh_card_points(db, card_ids=None, match_ids=None, player_ids=None)` | Recomputes the rows in the scope (filters combine with AND), upserts them with `INSERT … ON CONFLICT (card_id, match_id) DO UPDATE`, and deletes rows in the scope whose stat row no longer exists. Flushes first; does not commit, so it joins the caller's transaction |
| `delete_card_points(db, card_ids=None, match_ids=None)` | Deletes rows for deleted cards or matches; no filter deletes everything |
| `rebuild_all(db)` | Deletes and rewrites every row and stores the weights fingerprint, then commits. On any error it rolls back (previous rows and fingerprint stay), logs, and re-raises. Returns the row count |
| `ensure_card_points_current(db)` | Startup check: calls `rebuild_all` when the table is empty or the stored fingerprint differs from the current weights; returns the row count, or `None` when skipped |
| `weights_fingerprint(weights)` | Order-independent hash of the weights |

Triggers:

| Change | Call |
|---|---|
| Match ingested (`ingest.ingest_match`) or stats replaced by a parse retry (`ingest.refresh_match_stats`) | `ingest._reapply_mvp_bonus` refreshes the match after re-applying any confirmed MVP |
| MVP set or changed (`POST /twitch/mvp`, `POST /admin/matches/{match_id}/mvp`) | Refresh the match, in the same transaction. A provisional Twitch MVP for a match that is not ingested yet (issue #139) has no stat rows, so nothing is refreshed; the MVP is applied when the match is ingested (`_reapply_mvp_bonus`) |
| Card drawn (`POST /draw`, `POST /draw/booster/{team_id}`) | Refresh the new card for all of its player's matches, before the token spend commits |
| Modifiers rerolled (`POST /roster/{card_id}/reroll`) | Refresh that card |
| Season reset (`POST /admin/season/reset`) | Delete all rows; the response's `counts` include `card_match_points` |
| League purge (`DELETE /admin/leagues/{league_id}/data`) | Delete the rows for that league's matches |
| Weights changed | Startup check or `POST /recalculate` rebuilds everything |

Player removal (`POST /admin/players/remove`) only deactivates cards, so their rows are kept and past locked weeks still score.

### Reading

Every view sums stored rows with the same joins as before; no view calls `card_fantasy_score` per request:

- **My Team** (`GET /roster/{user_id}`, `_build_roster_response`): per card, `SUM(points)` over rows whose match is in the week window (or has `week_override_id` = the week) and passes `scored_match_sql()`. A locked week uses the roster snapshot; an unlocked week uses the user's current cards. `season_points` sums the same over every locked week in which the card's entry counted (after bench substitution: active and not subbed out, or subbed in; `counted_roster_entry_sql()`).
- **Weekly leaderboard** (`GET /leaderboard/weekly`): the same week sum per rostered card and user.
- **Season leaderboard and End Season** (`compute_season_standings`): a grouped subquery sums rows per (user, card) over locked weeks, then names are joined on. Card chips carry `"scope": "season"`, but the season view in the frontend shows totals only (no card chips). The weekly leaderboard's chips and My Team show the same stored week value for a card.

Match exclusion and week assignment are applied at read time, so toggling them changes totals immediately without a rebuild.

Rounding: stored `points` and all sums are unrounded. Every reader (weekly and season leaderboards, My Team's `total_points`, `combined_value` and `season_points`) rounds each card value and each user total once, with `scoring.display_points` (1 decimal, half away from zero), each from its own exact sum, so My Team and the leaderboards always show the same number. The frontend only formats the value (`toFixed(1)`). The chips shown for a user can therefore add up to a slightly different number than the shown total. See [points-rounding.md](points-rounding.md).

Each reader runs a fixed number of queries regardless of users and cards: weekly 3, season 2, My Team 5.

## Endpoints

### `POST /recalculate` (admin)
Recomputes every `player_match_stats.fantasy_points` and commits them, then calls `rebuild_all`. Response:

```json
{"status": "ok", "recalculated": 800, "card_points": 18000}
```

`card_points` is the number of stored rows written. The `admin_recalculate` audit entry records both counts. The Admin panel's status line shows both.

If `rebuild_all` fails, the recalculated `fantasy_points` stay committed, the previous stored card points are kept (the rebuild rolls back its own transaction), the audit entry records `card_points=failed`, and the endpoint returns 500 with a message saying so. Run Recalculate again once the cause is fixed.

## Startup check and logs

On startup, after `seed_weights()` applies `WEIGHTS_JSON`, `main._ensure_card_points_current()` calls `ensure_card_points_current`. Log lines:

| Line | Meaning |
|---|---|
| `Card points: stored rows match the current weights; no rebuild` | Nothing to do |
| `Card points: rebuilding (table empty)` / `Card points: rebuilding (weights changed)` | A rebuild is starting |
| `Card points rebuilt: N rows` | `rebuild_all` finished (also logged by Recalculate) |
| `Startup: rebuilt N stored card points` | The startup rebuild finished |
| `Card points rebuild failed; previous stored points kept` | `rebuild_all` failed and rolled back (with traceback) |
| `Startup: stored card points check failed` | The startup check raised (with traceback). Startup continues; the previous stored rows are served until the next restart or Recalculate |

## Performance

Measured with `scripts/bench_leaderboards.py` (the seed step now calls `rebuild_all` after seeding), median of the runs:

| Size | Weekly leaderboard | Season leaderboard | My Team (one user) |
|---|---|---|---|
| 60 users, 10 weeks, 80 matches, 3,000 roster entries — before | 18.3 ms, 6 queries | 112.5 ms, 5 queries | 3.8 ms, 9 queries |
| same — after | 5.4 ms, 3 queries | 15.4 ms, 2 queries | 1.8 ms, 5 queries |
| 60 users, 20 weeks, 240 matches, 6,000 roster entries — before | 32.9 ms | 583.8 ms | 7.0 ms |
| same — after | 11.7 ms | 57.2 ms | 3.4 ms |

The pre-change baseline is saved in `scripts/bench-leaderboards-baseline.json`; compare with `python3 scripts/bench_leaderboards.py --compare scripts/bench-leaderboards-baseline.json`.

## Release note

> Card points are now calculated per match and stored. A card's value is now the same on My Team, the weekly leaderboard, the season leaderboard and season archives, and the season total is exactly the sum of the weeks. The death bonus is now floored at 0 in each match separately, so a bad game no longer cancels another game's survival points: some totals go up slightly, and none go down. All stored points are rebuilt automatically the first time the server starts after this update.

Deploy: take a backup (`bash scripts/backup-db.sh`), deploy, check the startup log for `Startup: rebuilt N stored card points`, and spot-check one user across My Team and both leaderboards.
