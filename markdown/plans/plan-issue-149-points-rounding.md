# Plan: Consistent Points Rounding

## Context
A user's points for a week sometimes differ by 0.1 between My Team and the weekly leaderboard.

Both pages show one decimal, but they get there differently:
- **My Team** (`GET /roster/{user_id}`) returns the exact week total (`combined_value`), and the browser rounds it once with `toFixed(1)`.
- **The weekly leaderboard** (`GET /leaderboard/weekly`) rounds each total to **two** decimals on the server (`round(x, 2)` in `routers/leaderboard.py` `_leaderboard_rows`), and the browser rounds it **again** to one.

Rounding twice gives different answers near the halfway point, and binary floating point makes it worse: `round(240.4506, 2)` gives 240.45, which is stored as 240.4499…, so `toFixed(1)` shows 240.4, while the exact value shows 240.5.

**Measured 2026-10-01** on the deterministic benchmark season (`scripts/bench_leaderboards.py`, 60 users × 10 weeks): **29 of 600 user-weeks (4.8 %)** showed different numbers. For example, week 1 user 28 showed 240.5 on My Team and 240.4 on the leaderboard, and user 58 showed 231.2 and 231.3.

The same double rounding affects the season totals and the per-card chips. Several other places round points with Python's `round()`, which rounds half to even on binary values, so they can disagree with the browser too:
- the Twitch MVP panel's player points (`twitch.py`),
- the Weekly Report's per-match points (`weekly_summary.py`),
- `/top` and `/leaderboard` player averages, and `/simulate` (`leaderboard.py`).

The fix: **round once, in one place, on the server**, to one decimal, half away from zero, using the decimal value rather than the binary one. Pages then show exactly what the API returns.

**Assumptions:**
- One decimal everywhere a total, card value or per-match value is shown, as today. The stored values (`card_match_points.points`, `player_match_stats.fantasy_points`) stay unrounded.
- A total is rounded from its exact sum, not added up from rounded card values. A card list can therefore still look 0.1 off from its total when several cards each round the same way. The leaderboard shows a short footnote for this, the way scoreboards usually do.
- Twitch extension 1.1.6/1.1.7 displays the number as it receives it, so a rounded value from the server needs no extension release.

Resolves GitHub issue #149.

## User Stories

### Same Week Points Everywhere
**User story**
As a player, I want my week points to show the same number on My Team and on the leaderboard so that I can trust the scores.

**Acceptance criteria**
- One helper, `display_points(x)` in `backend/scoring.py`, rounds a points value to one decimal, half away from zero, using its decimal value (`Decimal(repr(x))`) so binary artefacts don't change the result. For example 240.45 → 240.5, 231.25 → 231.3, 0.05 → 0.1, −0.05 → −0.1, and 2.675 → 2.7
- My Team's `combined_value`, `season_points` and each card's `total_points`, and the weekly and season leaderboards' totals and card `points`, all come from `display_points` applied to the exact sum
- For every user and week in the benchmark season, My Team's week total equals the weekly leaderboard's total exactly (0 mismatches, against 29 of 600 before)
- For every user, My Team's `season_points` equals the season leaderboard total

### One Rounding Rule for All Points
**User story**
As a player, I want every points number in the app and the Twitch panel rounded the same way so that the same value never shows two different ways.

**Acceptance criteria**
- `display_points` is used for:
  - the Twitch MVP panel player points (`GET /twitch/matches/current`),
  - Weekly Report per-match points,
  - `/top` points and `/leaderboard` average points,
  - archived season standings,
  - `/simulate` results, with two decimals there via a `places` argument, since the simulator compares weights
- No other `round(` on a points value remains in `backend/routers/` or `backend/twitch.py`, checked by a test that searches the source
- The frontend shows the server's value: `toFixed(1)` on an already-rounded number only formats it, and no frontend code rounds a points value any other way

### Explain Card Totals
**User story**
As a player, I want to know why my cards' values don't always add up exactly to my total so that a 0.1 difference isn't confusing.

**Acceptance criteria**
- Where the leaderboard lists a user's cards under their total, a one-line note reads "Totals are rounded from exact points, so card values may differ by 0.1 in sum"
- The How to Play scoring section has the same note once

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/scoring.py` | `display_points(x, places=1)` |
| `backend/routers/cards.py` | Round `combined_value`, `season_points`, card `total_points` with the helper (exact sums, rounded once) |
| `backend/routers/leaderboard.py` | `_leaderboard_rows` rounds with the helper; `/top`, `/leaderboard`, archived seasons, and `/simulate` with `places=2` |
| `backend/routers/weekly_summary.py`, `backend/twitch.py` | Per-match points via the helper |
| `frontend/app-leaderboard.js`, `frontend/index.html` | Footnote under card lists; How to Play note |
| `markdown/features/reference/points-rounding.md`, `markdown/features/reference/stored-card-points.md`, `markdown/ui_description/leaderboards.md` | Docs |
| `backend/tests/test_issue_149_points_rounding.py` | Tests, including the benchmark-season consistency check |

### Step 1 — Helper
```python
from decimal import Decimal, ROUND_HALF_UP

def display_points(x, places: int = 1) -> float:
    """Round a points value for display: half away from zero, on its decimal value."""
    if x is None:
        return 0.0
    q = Decimal(1).scaleb(-places)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))
```
`ROUND_HALF_UP` in `decimal` rounds half away from zero, so −0.05 becomes −0.1.

### Step 2 — Apply it
Replace every `round(<points>, n)` in the listed files with the helper, keeping exact sums until the final step. In `_leaderboard_rows`, compute `totals[uid]` from exact card values, then round. Do the same for cards.

### Step 3 — Consistency test
Reuse the season builder from `scripts/bench_leaderboards.py` (seed 141) to compare `_build_roster_response(...)["combined_value"]` with `weekly_leaderboard(...)["week_points"]` for every user and week, and the season values. Expect exact equality. Add a source-search test that finds no `round(` applied to points in the routers and `twitch.py`.

### Step 4 — Note and docs
Add the footnote and the How to Play line, keeping the phrases tests pin there. Write the feature doc and correct the rounding description in `stored-card-points.md` and `leaderboards.md`.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_149_points_rounding.py -v`, then the full suite.
- Helper cases: 240.45 → 240.5, 231.25 → 231.3, 227.35 → 227.4, 0.05 → 0.1, −0.05 → −0.1, None → 0.0, `places=2` with 2.675 → 2.68.
- Benchmark season: 0 of 600 user-weeks differ between My Team and the weekly leaderboard (29 before), and season totals match for all 60 users.
- `python3 scripts/bench_leaderboards.py --compare scripts/bench-leaderboards-baseline.json`: timings unchanged, and totals differ only in the second decimal.
- Manual: open My Team and the weekly leaderboard for the same week on test.kana-cards.com and compare a few users.
