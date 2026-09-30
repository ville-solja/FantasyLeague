# Plan: Stored Card Points

## Context
A user reported that a card shows different values on My Team and on the leaderboard. Investigating (2026-09-30) found that nothing is calculated in the browser. The front end only formats numbers the server sends. The cost and the differences both come from the server, which recalculates every card's points on every request:
- `_build_roster_response` in `backend/routers/cards.py` sums raw stats for My Team: this week, and the season total.
- `weekly_leaderboard` and `compute_season_standings` in `backend/routers/leaderboard.py` do the same for every non-tester user. Each runs a large aggregate query, then `card_fantasy_score()` in Python for every card.

The same card can show different numbers for three reasons:
1. **Different scopes, similar labels.** My Team shows a card's points for the selected week ("wk pts"). The season leaderboard's card chips show the card's total across every locked week it was rostered, with no label saying so.
2. **The death bonus is floored at 0 over a whole period, not per match.** `_death_contribution` computes `max(0, pool × games − deaths × deduction)` over all the games being summed. A season total is therefore not the sum of the weekly values when one week hits the floor, and a card's weekly value is not the sum of its per-match values. The Players tab's per-match `fantasy_points` floor each match separately, so it disagrees too.
3. **Rounding.** The leaderboard rounds each card to 2 decimals, and the pages show 1 decimal. The totals use unrounded values, so a card list can look like it doesn't add up.

This plan stores each card's points **per match** once, when the inputs change, and has every view sum those stored values. All views then agree by construction, and pages do one simple `SUM` instead of recalculating.

**Decision in this plan:** points are defined per match, so the death bonus is floored per match. This matches the Players tab and how the other stats behave. Some existing totals will change slightly, never downwards: a match can no longer lose death points to another match's deaths. Every stored value is rebuilt on deploy, and the release notes must mention it.

**Baseline (measured 2026-09-30 with `scripts/bench_leaderboards.py`, saved in `scripts/bench-leaderboards-baseline.json`):**

| Size | Weekly leaderboard | Season leaderboard | My Team (one user) |
|---|---|---|---|
| 60 users, 10 weeks, 80 matches, 3,000 roster entries | 18.3 ms, 6 queries | 112.5 ms, 5 queries | 3.8 ms, 9 queries |
| 60 users, 20 weeks, 240 matches, 6,000 roster entries | 32.9 ms | 583.8 ms | 7.0 ms |

The season leaderboard grows much faster than the data: 2× weeks and 3× matches make it about 5× slower. It runs on every Leaderboard tab open.

**Assumptions:**
- Weights only change at startup (`seed.py` applies `WEIGHTS_JSON`); there is no weight-editing endpoint. A startup check rebuilds the stored points when the weights have changed.
- Match exclusion (`excluded_from_scoring`) and week assignment stay query-time filters, as today, so toggling them needs no rebuild.
- The table holds about (cards × matches per player). With about 25 users, 15 cards each and 20 matches per player a season, that's under 10,000 rows.

Resolves GitHub issue #141.

## User Stories

### One Card Value Everywhere
**User story**
As a player, I want a card to show the same points on My Team, the weekly leaderboard, the season leaderboard and in season archives so that I can trust the numbers.

**Acceptance criteria**
- A card's points for a week are the sum of its stored per-match points for the scored matches in that week's window, on every page that shows them
- A card's season points equal the sum of its weekly points over the locked weeks it was rostered in
- A user's weekly and season totals equal the sum of their cards' points in that scope
- The death bonus is floored at 0 per match, so it matches the Players tab's per-match `fantasy_points` before card modifiers and rarity
- The season leaderboard view shows totals only (no card chips); the weekly leaderboard's card chips and My Team ("wk pts") show the same stored week value for a card
- Values are stored and summed unrounded and rounded only in the response (2 decimals on the leaderboards) and on the page (1 decimal), and a list of card values adds up to the shown total within 0.1

### Stored Per-Match Card Points
**User story**
As a developer, I want each card's points per match stored when the inputs change so that pages read totals instead of recalculating them on every request.

**Acceptance criteria**
- A `card_match_points` table stores one row per (card, match) with the card's final points for that match: stats with card modifiers, plus the MVP bonus when the player was that match's MVP, times the rarity multiplier. It has a unique constraint on (card_id, match_id)
- Rows are written or updated when:
  - a match is ingested or its stats are replaced after a parse (for every card of the players in it),
  - an MVP is set or changed (Twitch or admin, for that match),
  - a card is drawn (for all of that player's matches),
  - a card's modifiers are rerolled (for that card)
- Rows are deleted when their card or match is deleted (season reset, league purge) or when a match's stat rows are removed. Player removal only deactivates cards, so their rows are kept and past locked weeks still score
- My Team, the weekly leaderboard, the season leaderboard and End Season's `compute_season_standings` read `SUM(points)` from `card_match_points` joined to roster entries and weeks. They no longer call `card_fantasy_score` per request
- Match exclusion and week assignment are applied when reading, as today, so toggling them changes totals immediately without a rebuild

### Rebuild Stored Points
**User story**
As an admin, I want stored card points rebuilt when scoring rules change so that stored values never go stale.

**Acceptance criteria**
- `POST /recalculate` also rebuilds every `card_match_points` row, and its response says how many rows were written
- At startup, after weights are seeded, the table is rebuilt if it is empty or if the weights differ from those it was built with (a stored fingerprint of the weight values)
- A rebuild runs in one transaction; a failure leaves the previous rows in place and logs the error

### Faster Pages
**User story**
As a player, I want My Team and the leaderboards to load quickly as the season grows.

**Acceptance criteria**
- Each leaderboard and roster request runs a fixed number of queries, independent of the number of users and cards (no per-card Python scoring loop)
- `scripts/bench_leaderboards.py --compare scripts/bench-leaderboards-baseline.json` (60 users, 10 locked weeks, 20 matches per player) shows the season leaderboard at least 5× faster than the pre-#141 baseline of 112.5 ms median, and the weekly leaderboard no slower than its 18.3 ms baseline
- At `--weeks 20 --games 3` (240 matches, 6,000 roster entries) the season leaderboard stays under 100 ms median, against 584 ms before #141

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New `CardMatchPoints` table (`card_match_points`), plus a one-row store for the weights fingerprint (for example a `scoring_state` key/value table); new tables, so `create_all` handles them |
| `backend/card_points.py` *(new)* | `refresh_card_points(db, card_ids=None, match_ids=None, player_ids=None)`, `rebuild_all(db)`, `weights_fingerprint(weights)` |
| `backend/ingest.py` | Refresh after `ingest_match`, after `_reapply_mvp_bonus`, and after the parse-retry stat replacement |
| `backend/twitch.py`, `backend/routers/admin_matches.py` | Refresh the match after an MVP change |
| `backend/routers/cards.py` | Refresh after a draw, team draw and reroll; `_build_roster_response` reads stored sums |
| `backend/routers/leaderboard.py` | `weekly_leaderboard` and `compute_season_standings` read stored sums; season card chips carry a scope field |
| `backend/routers/admin_ingest.py` | `POST /recalculate` calls `rebuild_all` |
| `backend/routers/admin_season.py`, `admin_leagues.py` | Delete stored rows with their cards or matches (`admin_players.py` removal only deactivates cards, so rows are kept) |
| `backend/main.py` | Startup rebuild check after seeding |
| `frontend/app-leaderboard.js` | Escape chip text; the season view renders no chips, so no season label is needed |
| `markdown/features/core/cards.md`, `markdown/features/core/weeks.md` | Scoring definition (per-match death floor) and storage |
| `backend/tests/test_issue_141_stored_card_points.py` | Tests |

### Step 1 — Table and per-match calculation
```python
class CardMatchPoints(Base):
    __tablename__ = "card_match_points"
    __table_args__ = (UniqueConstraint("card_id", "match_id", name="uq_card_match_points"),)
    id        = Column(Integer, primary_key=True, autoincrement=True)
    card_id   = Column(Integer, ForeignKey("cards.id"), index=True)
    match_id  = Column(Integer, ForeignKey("matches.match_id"), index=True)
    player_id = Column(Integer, index=True)
    points    = Column(Float, nullable=False)
```
For each (card, match): `_compute_card_points(stat_dict_from_row(stat_row), card.card_type, weights, rarity, mods, mvp_bonus=_mvp_bonus_delta(stat_row, weights) if stat_row.is_mvp else 0, match_count=1)`. Upsert with ON CONFLICT on (card_id, match_id), following `upsert_mvp`.

### Step 2 — Keep it current
Call `refresh_card_points` at each trigger in the stories, inside the same transaction as the change where one exists. Delete rows alongside card and match deletions.

### Step 3 — Read stored sums
Replace the aggregate stat queries with sums over `card_match_points`, keeping each view's existing joins:
- **Week scope:** roster entries for the week, matches in the week window or with `week_override_id`, and `scored_match_sql()`.
- **Season scope:** the same join over locked weeks, summed per card and per user.
- **Unlocked week on My Team:** the user's current cards, not roster entries, as today.

Keep the response shapes. Add `"scope": "season"` to season card chips (the season view does not render chips). Store and sum unrounded values; the leaderboard API rounds each chip and each user total to 2 decimals from its own unrounded sum, My Team returns unrounded values, and the frontend shows 1 decimal.

### Step 4 — Rebuild and startup check
`rebuild_all` deletes and rewrites all rows in one transaction, then stores `weights_fingerprint` (a hash of the sorted weight key/value pairs). The startup check compares the fingerprints after `seed_weights`. `POST /recalculate` commits its existing `fantasy_points` pass, then calls it; a rebuild failure keeps the recalculated stats and the previous stored rows and returns an error.

### Step 5 — Parity test, then docs
Before switching the readers, add a test that builds a fixture season and asserts that:
- the old per-request totals equal the new stored totals for weeks where the death floor doesn't trigger,
- where it does trigger, the new totals are the per-match sums.

Update the scoring docs and the release note.

## Verification
- `cd backend && python3 -m pytest tests/test_issue_141_stored_card_points.py tests/test_scoring.py tests/test_mvp_card_scoring_parity.py tests/test_scoring_pipeline_parity.py -v`, then the full suite.
- For a fixture user, one card shows the same points on `GET /roster/{user_id}?week_id=…`, the weekly leaderboard and in the per-week sum behind the season leaderboard. The season value equals the sum of weeks.
- A week where a player died enough to hit the floor in one match: the card's week points equal the sum of the per-match values, not the aggregate formula.
- Ingesting a match, setting an MVP, rerolling and drawing each update exactly the affected rows, and the leaderboard changes without a rebuild.
- Toggling `excluded_from_scoring` or a match's week changes totals immediately.
- Changing `WEIGHTS_JSON` and restarting triggers one rebuild; restarting again without changes does not.
- Run `python3 scripts/bench_leaderboards.py --compare scripts/bench-leaderboards-baseline.json` and `python3 scripts/bench_leaderboards.py --weeks 20 --games 3 --runs 10`, and check the targets in the "Faster Pages" story. Totals will shift slightly because of the per-match death floor; the benchmark prints them for review.
- Deploy: take a backup, deploy, check the startup log for the rebuild row count, spot-check one user across My Team and both leaderboards, and put the rounding and floor change in the release notes.
