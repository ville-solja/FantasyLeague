# Plan: Weekly Points Clarity and a Points Check

## Context
Issue #250 asked to verify in production that points are counted as intended. The two screenshots show "Single Match Performance" topping out at 48.2 and the Final week's standings with cards at 86–105.

**Verification (production, 2026-11-15, public endpoints): the counting is correct.**
- **Four games per player:** the Final week (id 10, Sat 14 Nov 03:00 to Mon 16 Nov 02:59 UTC) held four games for each player, on Sat 14 Nov at 11:16, 12:23, 17:56 and 19:37 UTC. A card's week points are the sum of those games.
- **Common cards equal the raw sums:**
  - Glete: 13.9 + 15.2 + 30.8 + 26.5 = 86.4 per game rounded, 86.3 from exact points;
  - Speismän 78.2, fatKO 71.3, Hoetaa 57.1, CamperBanana 49.6 (49.5 rounded per game), ximbong 99.7.
  - The 0.1 gaps are the rounding the chip footnote already mentions (#149).
- **Rare, epic and legendary cards differ only by their modifiers,** for example Glete common 86.3 against legendary 90.4.
- **"Single Match Performance" (`GET /top`) is each player's best single game of the season.** Glete's is 30.8. So a 30.8 best and an 86.3 week total don't contradict each other.

**What is actually wrong is that nothing says so.** A chip shows one number without the number of games behind it. The panel's heading doesn't say it is per game. And there is no way to check the stored card points (#141) without reading the database. This plan fixes those three things.

**Decisions** (change them in review if needed):
- **Games on the chip:** each weekly-standings chip shows its number of games, `86.3 · 4 games`. A tooltip spells it out: "Glete (common): 86.3 points from 4 games this week". The API already counts them (`match_count`). The expanded row's footnote becomes "Card points are the week's total over every game the player played, rounded from exact points."
- **Single match panel:** the heading reads **Best single games**, with the sub-line "One game each, this season". Each row adds the date and the opponent, so it reads as one game. `GET /top` gains `match_id`, `start_time` and `opponent`, from the stat row's team and the match.
- **Admin points check:**
  - Admin › Settings › Scoring gets **Check points**. It recomputes every card's points for the chosen week from the stored stats, modifiers and weights (`card_points._compute`) and compares them with `card_match_points`.
  - It lists any card or game whose stored value differs by more than 0.05, plus a count of cards checked.
  - It writes nothing. The existing **Recalculate Fantasy Points** fixes any difference it finds.
  - Next time "do the points add up?" comes up, an admin can answer it in a minute.
- **No scoring change:** formulas, weights, rounding and the stored points stay as they are.

Resolves GitHub issue #250.

## User Stories

### A Card's Week Points Say How Many Games They Cover
**User story**
As a player looking at the weekly standings, I want each card's points to show how many games they add up, so that a week total higher than any single game doesn't look like a mistake.

**Acceptance criteria**
- **Count:** each card chip in the weekly standings shows its points and its number of games in the week, for example `86.3 · 4 games` or `21.1 · 1 game`. A card with no games isn't shown, as today.
- **Tooltip:** the chip's tooltip reads "<player> (<rarity>): <points> points from <N> games this week".
- **Footnote:** the expanded row's note reads "Card points are the week's total over every game the player played, rounded from exact points."
- **API:** `GET /leaderboard/weekly` returns `games` on each card (the existing `match_count`), and the numbers are unchanged.

### The Single-Game Panel Reads as Single Games
**User story**
As a player, I want the single-match leaderboard to show which game each score came from, so that I don't compare it with week totals.

**Acceptance criteria**
- **Heading:** the panel's heading is **Best single games**, with the sub-line "One game each, this season".
- **Rows:** each row shows rank, player, the date (`14.11.`) and the opponent ("vs Elisa Oyj"), and the points.
- **API:** `GET /top` adds `match_id`, `start_time` and `opponent` (the other team's name, or null) to each row, and the order and points are unchanged. The Twitch panel, which uses the same function, keeps working.

### An Admin Can Check That Stored Points Add Up
**User story**
As an admin, I want to check a week's stored card points against a fresh calculation, so that I can answer "is the counting right?" without reading the database.

**Acceptance criteria**
- **Run:** Admin › Settings › Scoring has **Check points** with a week picker (default: the latest locked week). It calls `GET /admin/points-check?week_id=…`.
- **Result:**
  - the number of rostered cards and games checked;
  - each card and game where the stored value and the fresh calculation differ by more than 0.05: user, card (player, rarity), match id, stored and fresh values;
  - or "All N card points match".
- **Writes nothing:** a mismatch is only reported. The panel points to **Recalculate Fantasy Points** to fix it.
- **Admin only:** `403` for non-admins. Rate-limited like other admin reads.
- **Bounded:** it checks only cards on that week's rosters. An unknown week returns `404`.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/leaderboard.py` | `games` on weekly chips (`_leaderboard_rows`); `top_performance_rows` adds `match_id`, `start_time`, `opponent` |
| `backend/card_points.py` | `check_week(db, week_id)`: fresh values for the week's rostered cards against `card_match_points` |
| `backend/routers/admin_ingest.py` (holds `POST /recalculate`) | `GET /admin/points-check` |
| `frontend/app-leaderboard.js` | Chip count and tooltip, footnote, single-game panel rows |
| `frontend/index.html` | Panel heading and sub-line; Check points controls in Settings › Scoring |
| `frontend/app-admin-ingest.js` (holds `recalculate()`) | Check points call and result table |
| `markdown/features/reference/weekly-points-clarity.md`, `stored-card-points.md`, `markdown/ui_description/leaderboards.md`, `admin.md` | Docs |
| `backend/tests/test_issue_250_weekly_points_clarity.py` | Tests |

No migration, no env var.

### Step 1 — Weekly chips
In `_leaderboard_rows`, add `"games": int(r.match_count)` to each chip. The season standings don't show chips, so nothing changes there. In `_lbStandingsRow`, render `· N game(s)` after the points, with the tooltip, and the new footnote.

### Step 2 — Best single games
In `top_performance_rows`:
- join `matches` for `start_time`;
- take the opponent from the team that isn't the stat row's `team_id` (`radiant_team_id`/`dire_team_id`), with its name from `teams`;
- keep `ORDER BY s.fantasy_points DESC LIMIT :limit`.

In `loadTop`, render the date and "vs <opponent>", escaped. Check that the Twitch panel's use of `top_performance_rows` ignores the extra keys.

### Step 3 — Points check
`card_points.check_week(db, week_id)`:
- takes the card ids from `weekly_roster_entries` for the week (`counted_roster_entry_sql`) and the week's match ids (`scored_match_sql` and the week rule);
- calls `_compute(db, card_ids=…, match_ids=…)` and reads the stored rows for the same pairs;
- returns `{"week", "cards", "games", "mismatches": [{user, player, card_type, match_id, stored, fresh}]}`, comparing at 0.05.

Missing stored rows count as mismatches (stored `null`). The route is admin-only and read-only.

### Step 4 — Tests
- **Weekly chips:** `games` on each chip matches the games in the week, and the totals are unchanged.
- **Best single games:** `GET /top` keeps its order and adds date and opponent, with a null opponent when the team is unknown.
- **Points check:**
  - all match after a fresh refresh;
  - an edited stored value is reported;
  - a missing stored row is reported;
  - it writes nothing;
  - an unknown week returns 404, and non-admins get 403.
- **Frontend source checks:** the chip text and tooltip, the footnote, the heading, and escaping of the opponent name.

## Verification
- On a copy of production data, open the Final week standings: Glete's common card shows `86.3 · 4 games`, and the tooltip matches.
- The Leaderboards tab's Best single games shows tanelidota:) 48.2 with its date and opponent.
- **Check points** on the Final week reports all cards matching. Change one `card_match_points` value in a local copy, and it is reported. Then **Recalculate Fantasy Points** clears it.
- Comment the verification findings on issue #250 when this ships.
