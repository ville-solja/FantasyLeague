# Points Rounding

Every points number the app shows is rounded once, on the server, by one rule, so the same value looks the same on My Team, the leaderboards, the Players tab, the Weekly Report and the Twitch panel.

---

## Rule

`scoring.display_points(x, places=1)` rounds to one decimal, half away from zero, using the number's decimal value rather than its binary one (`Decimal(repr(float(x)))` quantized with `ROUND_HALF_UP`). So 240.45 → 240.5 (plain `round()` gives 240.4, because 240.45 is stored as 240.4499…), 231.25 → 231.3, −0.05 → −0.1, and `None` → 0.0.

- Stored values (`card_match_points.points`, `player_match_stats.fantasy_points`) stay exact. The one exception is `season_archive.points`: End Season stores the already-rounded one-decimal standings. Archives made before this change hold two-decimal values and are re-rounded when read.
- `GET /leaderboard/roster` (`roster_value`) is deliberately left unrounded: no page reads it.
- A total is rounded from its exact sum, not added up from rounded card values. A list of card values can therefore differ from its total, typically by 0.1. The weekly leaderboard says so in a note under each user's card chips, and the How to Play scoring section says it once.
- The frontend formats the server's value with `Number(x).toFixed(1)` and never rounds it any other way. On an already-rounded number, `toFixed(1)` only formats.

## Where it is applied

| Endpoint | Fields | Places |
|---|---|---|
| `GET /roster/{user_id}` (`routers/cards.py` `_build_roster_response`) | card `total_points`, `combined_value` (from the exact card sums), `season_points` | 1 |
| `GET /leaderboard/weekly`, `GET /leaderboard/season`, End Season archive (`routers/leaderboard.py` `_leaderboard_rows`) | user total (from the exact card sums), card chip `points` | 1 |
| `GET /top`, `GET /leaderboard` | `fantasy_points`, `avg_points` | 1 |
| `GET /leaderboard/seasons/{season_id}`, `GET /profile/{user_id}` `past_seasons` | archived `points` | 1 |
| `GET /players`, `GET /players/{id}`, `GET /teams/{id}` | `avg_points`, `total_points` (from exact values), match-history and best-match `fantasy_points` | 1 |
| `GET /weekly-summary/{week_id}` (`routers/weekly_summary.py`) | per-match player `points` (excluded matches stay `null`) | 1 |
| `GET /twitch/matches/current` (`twitch.py`) | player `fantasy_points` | 1 |
| `POST /simulate/{match_id}` | player `fantasy_points` | 2, since the simulator compares weights |

`backend/tests/test_issue_149_points_rounding.py` searches `backend/routers/*.py` and `backend/twitch.py` for `round(` calls and fails on any not in its allowlist. The only allowed one is the MVP bonus written to `player_match_stats.fantasy_points` at 4 decimals in `routers/admin_ingest.py`, which is a stored value, not a displayed one.

The same test also checks the frontend JavaScript: points values may only be formatted with `toFixed(1)` on the server's value. `Math.round`, `floor`, `ceil`, `toPrecision` and other `toFixed` precisions are refused on points, with exceptions for the non-points fields `gold_per_min`, `avg_gpm` and `win_rate`.

Twitch extension 1.1.6/1.1.7 shows `fantasy_points` as it receives it, so no extension release was needed.

## Why

Before this, the leaderboard rounded totals to two decimals and the browser rounded again to one, while My Team rounded once. On the benchmark season (`scripts/bench_leaderboards.py`, seed 141, 60 users × 10 weeks), 29 of 600 user-weeks (4.8 %) showed a 0.1 difference between the two pages (issue #149). After the change, all 600 user-weeks and all 60 season totals match; the test file checks this in a subprocess.
