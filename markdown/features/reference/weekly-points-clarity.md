# Weekly Points Clarity and a Points Check

Makes it clear that a card's weekly points are a total over several games, labels the single-match leaderboard as single games, and gives admins a read-only check of stored card points. Issue #250. Plan: `markdown/plans/plan-issue-250-weekly-points-clarity.md`. No scoring change: formulas, weights, rounding and stored points are as before.

---

## Why

Issue #250 asked whether points count correctly. A production check on 2026-11-15 showed they do:
- **Four games per player:** the Final week held four games for each player. Glete's common card, 86.3, is 13.9 + 15.2 + 30.8 + 26.5 from exact points.
- **Single Match Performance** is each player's best single game; Glete's is 30.8.

Nothing in the UI said so, which made the two views look inconsistent.

## Weekly standings chips

- **API:** `_leaderboard_rows` (`backend/routers/leaderboard.py`) adds `"games": int(match_count)` to every card chip: the number of scored games behind the chip's points. `GET /leaderboard/weekly` therefore returns `games` per card. The season standings' chips (`compute_season_standings`, also used by End Season) carry it too, but the season view shows no chips. Points and totals are unchanged.
- **UI:** `_lbStandingsRow` (`frontend/app-leaderboard.js`) renders `86.3 · 4 games` (`· 1 game` for one) in a `.lb-chip-games` span after the points. The chip's `title` reads "Glete (common): 86.3 points from 4 games this week", escaped with `_escHtml`.
- **Footnote:** the expanded row's note reads "Card points are the week's total over every game the player played, rounded from exact points." The How to Play scoring note keeps its earlier rounding wording.

## Best single games

- **API:** `top_performance_rows` (behind `GET /top` and the Twitch panel's `GET /twitch/panel`) now `LEFT JOIN`s `matches` and `teams` and adds to each row:
  - `match_id`;
  - `start_time` (the match's Unix time);
  - `opponent`: the name of the team on the other side from the stat row's `team_id` (`dire_team_id` when it equals `radiant_team_id`, and the reverse), or `null` when the stat row's team, the match's teams or the `teams` row is unknown.

  The order (`ORDER BY fantasy_points DESC`), limit and points are unchanged. `twitch.panel_live` copies only `id`, `name` and `fantasy_points`, so the panel's payload is unchanged.
- **UI:** the Players tab panel formerly titled "Single match performance" is **Best single games**, with the sub-line "One game each, this season" (`.panel-subline`). `loadTop` renders the date (`14.11.`, local time) and "vs <opponent>" (escaped) under the player name in a `.top-game-meta` line; with no opponent only the date shows.

## Points check

`card_points.check_week(db, week_id)` compares a week's stored card points with a fresh calculation (see [Stored Card Points](stored-card-points.md)):
1. **Cards:** the distinct cards on the week's rosters whose entries count (`counted_roster_entry_sql()`: active and not subbed out, or subbed in), with the roster's user.
2. **Games:** the week's scored matches (`scored_match_sql()`), by the same week rule as the readers: `week_override_id` = the week, or no override and `start_time` within the week.
3. **Compare:** `_compute(db, card_ids=…, match_ids=…)` against the stored `card_match_points` rows for the same cards and matches. A pair is a mismatch when the values differ by more than `CHECK_TOLERANCE` (0.05), or when it exists on only one side: a missing stored row has `stored: null`, and a stored row with no stat row behind it has `fresh: null`.

It issues only `SELECT`s. **Recalculate Fantasy Points** (`POST /recalculate`) fixes what it finds.

**Admin UI** (Admin › Settings › Scoring › **Check Points**, `frontend/app-admin-ingest.js`): a week picker (`#pointsCheckWeekSelect`, filled from `GET /weeks` with the locked weeks; defaults to the latest) and a **Check points** button. With no mismatches the status line reads "All N card points match. C cards, G games checked in <week>."; otherwise a table (User, Card, Match, Stored, Fresh) and a status line pointing to Recalculate Fantasy Points. Table values are escaped with `_escHtml`; the status line is set as text (`setStatus`).

## Endpoints

### `GET /admin/points-check?week_id=<id>`
`require_admin` (403 for non-admins); the global default rate limit applies. A thin wrapper in `backend/routers/admin_ingest.py` over `card_points.check_week`. `404 {"detail": "Week not found"}` for an unknown week; `week_id` must be 1 to 2^63−1, so anything else (or a non-integer) is a `422`. Response:

```json
{
  "week": {"id": 10, "label": "Final"},
  "cards": 48,
  "games": 12,
  "checked": 192,
  "mismatches": [
    {"user_id": 2, "user": "bob", "card_id": 31, "player": "Glete", "card_type": "common",
     "match_id": 8123456789, "stored": 14.9, "fresh": 13.9}
  ]
}
```

- `cards`: distinct rostered cards checked.
- `games`: distinct games those cards played in the week.
- `checked`: card-and-game values compared.
- `stored` and `fresh` are rounded to 2 decimals for display; the comparison uses the exact values.

### `GET /top` and `GET /leaderboard/weekly`
See above: `match_id`, `start_time`, `opponent` on `GET /top` rows; `games` on weekly card chips.
