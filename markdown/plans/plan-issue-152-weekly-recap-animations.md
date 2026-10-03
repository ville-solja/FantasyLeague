# Plan: Weekly Recap Animations

## Context
The Weekly Report's My roster column (#151) shows each counted card's week points, but not what produced them. Issue #152 asks for a reveal animation that tells that story card by card:
1. A card appears and counts its weekly raw points up with an escalating animation, taking 1 to 3 seconds depending on the value.
2. Short highlights then add each bonus to the card's total: first the rarity bonus, then each modifier (for example "GPM +10%"), then the MVP bonus.
3. The next card appears at the top of the list, and the earlier cards move down.

The end result is a visual breakdown of what each card scored and what contributed. Mock: https://claude.ai/artifact/CSAhGz2DRr4RTGtHL5p4wp, frame "Recap reveal animation (#152)" (press Play).

**How a card's points split up.** Only final points are stored (`card_match_points`, #141). The breakdown is recomputed from the same inputs. Per game, `card_utils._compute_card_points` is:

```
points = (card_fantasy_score(stats, weights, mods) + mvp_bonus) × (1 + rarity_mod)
```

- `card_fantasy_score` without modifiers equals `fantasy_score(stats)`: the raw points.
- Each modifier adds `weight × value × pct/100` for its stat, or `death_contribution × pct/100` for deaths.
- `mvp_bonus` is `fantasy_score × mvp_bonus_pct/100` on MVP games (`_mvp_bonus_delta`).
- `rarity_mod` is `rarity_<type>` / 100 (`_load_weights`).

To show the steps in the issue's order (raw, rarity, modifiers, MVP) and have them add up exactly, each later step includes the rarity multiplier on its own part:

| Step | Exact value (summed over the card's counted, scored games in the week) |
|---|---|
| Raw | `fantasy_score(stats)` |
| Rarity | `raw × rarity_mod` |
| Each modifier | `modifier_part × (1 + rarity_mod)` |
| MVP | `mvp_bonus × (1 + rarity_mod)` |

Raw + rarity + modifiers + MVP = `(raw + Σ modifier_part + mvp_bonus) × (1 + rarity_mod)` = the stored points.

**Assumptions:**
- **Reveal order.** Cards are revealed in reverse roster order: the last counted slot first, the first slot last. Each new card is inserted at the top, so the finished list is in My Team order, the same order #151 shows. "Did not play" cards are not animated; they appear in their group once the counted cards finish.
- **When it plays.** It plays once per week per browser, the first time that week's revealed roster is shown, which is usually right after "Reveal results". The played weeks are remembered in `localStorage` (a per-viewer convenience). After that the week shows the finished breakdown at once, with a "Replay" button.
- **Opting out.** A "Skip" button finishes the animation instantly. With `prefers-reduced-motion`, nothing animates and the finished state is shown.
- **Length.** A full five-card roster takes about 20 to 25 seconds: per card, about 0.9 s for the entry, a 1 to 3 s count, about 0.7 s per bonus step, and about 0.8 s to add to the week total. That's why Skip is always visible while it plays.
- **Labels.** Modifier labels reuse the card-image labels (`_STAT_LABELS_CARD` in `backend/image.py`), moved to a shared place so the API doesn't import the image module.
- No new tables or columns, so no migration. No new env vars.

Resolves GitHub issue #152.

## User Stories

### Points Breakdown per Card
**User story**
As a player, I want each card in the Weekly Report to show how its points were made up so that I understand what my rarity, modifiers and MVPs contributed.

**Acceptance criteria**
- Every counted card in a revealed week's `roster.cards` (`GET /weekly-summary/{week_id}`) has a `breakdown` covering its counted, scored games that week:
  - `raw`,
  - `steps`, a list in this order:
    - rarity (only when the rarity bonus is above 0),
    - one entry per modifier (stat label and %),
    - one MVP entry **per MVP game** (with that game's `match_id`). A player who was MVP in two games gets two MVP steps, so two separate scoring ticks.
  
  Each step has its points, rounded with `display_points`.
- The exact (unrounded) parts add up to the card's stored points within 1e-6. The rounded `raw` plus the rounded steps equal the card's `week_points` exactly, because the rounding remainder goes to the last step (or to `raw` when there are no steps).
- Cards in the "Did not play" group and unrevealed weeks have no `breakdown`.
- When the reveal animation is finished, skipped or never played, each card shows its breakdown where each bonus comes from:
  - **Chip row** under the player's name, in the order the bonuses are added, left to right: "RAW 48.2", then the modifier chips ("KILLS +10% +1.2", "GPM +10% +1.6"), then a status tag ("SUBBED IN") at the end. There is no rarity chip or tag in this row. The row wraps when needed.
  - **Rarity bonus:** shown on the card thumbnail on the left. The thumbnail keeps its rarity-coloured border, with the rarity name at its foot. Below it, a small caption in the rarity colour reads "+3% +1.4". A card with no rarity bonus (common) has no caption.
  - **MVP bonus:** shown on the MVP tag of the game row that earned it: "MVP +1.5". Each MVP game shows its own bonus.
  - The game rows (#151) stay below the tag row, so the breakdown and the games don't compete for the same place.

### Card-by-Card Reveal
**User story**
As a player opening a revealed week, I want my cards revealed one at a time with their points counting up so that the recap feels like a reveal, not a table.

**Acceptance criteria**
- **Order:** cards appear one at a time in reverse roster order, each at the top of the My roster list, so the finished list is in My Team order.
- **Entry transition:** the cards already shown move down smoothly while the new card's slot opens from zero height at the top, in about 340 ms with an ease-out. Then the new card **slides in from the left edge of the column** into the open slot: about 420 ms, ease-out (cubic), with its opacity rising from 0 to 1 over the first 60% of the slide.
- **Count-up:**
  - each card's number counts up from 0 to its `raw` with an accelerating (ease-in) curve,
  - the number grows slightly and gains an orange glow as it rises,
  - the count lasts `clamp(1000 + raw × 35, 1000, 3000)` ms,
  - **the RAW chip is highlighted (filled, glowing) for the whole count and shows the running value**, then settles to its lit state about 0.2 s after the count ends. It doesn't flash only at the end.
- **Week total:** the header's week total starts at 0 and counts up by each card's final points as that card finishes. At the end it equals `roster.week_total`.
- **After the counted cards:** the "Did not play" group appears without animation.
- **Results column:** stays usable during the animation.

### Bonus Highlights
**User story**
As a player, I want each bonus on a card highlighted as it is added so that I can see what my rarity, each modifier and an MVP were worth.

**Acceptance criteria**
- After the count-up, each step in `breakdown.steps` plays in order: rarity, then the modifiers left to right, then MVP. For each step:
  - its chip changes from a dashed placeholder to a filled, glowing chip with its label and "+points",
  - **at the same moment** the card total jumps to its new value. It doesn't count up as the raw points do. Instead, the number pops (about 28% larger, shrinking back over about 520 ms) and a small "+points" label floats up from it and fades out.
- **Rarity step:** played only on the card thumbnail on the left:
  - the thumbnail glows in the rarity colour and scales up slightly (rarity colours are allowed on card badges); the card's own border doesn't change,
  - its "+pct% +points" caption appears,
  - the floating "+points" uses the rarity colour.
- **Modifier step:** the modifier's chip glows orange.
- **MVP step:** played on the game row with that MVP:
  - the row is tinted orange,
  - its MVP tag fills and glows and gains "+points".
  
  A player who was MVP in several games gets one tick per game, in game order, each with its own pop.
- **Steps without a bonus:** a card with no steps (a common card with no modifiers and no MVP) goes straight to the next card.
- **Final value:** after the last step, the card total equals its `week_points`.

### Control and Accessibility
**User story**
As a player, I want to skip or replay the reveal, and to have it respect reduced motion, so that it never gets in my way.

**Acceptance criteria**
- **Skip:** a "Skip" button in the My roster header is visible while the animation plays. It shows the finished state at once, with all chips lit and totals final.
- **Replay:** a "Replay" button shows when the animation isn't playing, and plays it again from the start.
- **Plays once per week:** the animation plays once per week per browser. The played week ids are stored in `localStorage` under one key per user. Reads and writes are wrapped in try/catch, so if storage is unavailable the animation simply plays again.
- **Reduced motion:** with `prefers-reduced-motion: reduce` (`_prefersReducedMotion()`), nothing animates and the finished state is shown.
- **Leaving early:** switching week tab, closing the report or opening another week stops a running animation cleanly, with no timers left running.
- **Screen readers:**
  - while animating, the roster body has `aria-busy="true"`,
  - each card's final points are in its accessible text from the start, so screen readers never hear the counting numbers,
  - the counting number itself is `aria-hidden`.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/card_utils.py` | `card_points_breakdown(stat_dict, card_type, weights, rarity, mods, mvp_bonus)`, returning the exact parts per game, beside `_compute_card_points` |
| `backend/scoring.py` (or `card_utils.py`) | Shared `STAT_LABELS` moved out of `backend/image.py` (`_STAT_LABELS_CARD`); `image.py` imports it |
| `backend/routers/weekly_summary.py` | `_build_roster_block` adds `breakdown` per counted card for revealed weeks, summing per-game parts over counted, scored games (same week window and `scored_match_sql()` as `games`) |
| `frontend/app-weekly-summary.js` | Breakdown chips in `_weeklySummaryRosterCardHtml`; new reveal controller (`_recapAnimation` state, run id, `requestAnimationFrame` tweens, Skip/Replay, played-weeks storage); hooks in `selectWeeklySummaryTab` and `closeWeeklySummary` to stop a running animation |
| `frontend/style.css` | Chip styles (`.recap-chip`, `.recap-chip.pending`, `.recap-chip.lit`, `.recap-chip.hl`), count-up number and glow, card insert transition; tokens only; `@media (prefers-reduced-motion: reduce)` turns transitions off |
| `frontend/index.html` | Skip/Replay buttons in the My roster column header |
| `markdown/features/reference/weekly-recap-animations.md` | Feature doc (stub at planning) |
| `markdown/features/core/weekly-summary.md`, `markdown/ui_description/weekly-report.md` | `breakdown` field; animation states and buttons |
| `backend/tests/test_issue_152_weekly_recap_animations.py` | API, breakdown math and static frontend tests |

### Step 1 — Breakdown math
In `backend/card_utils.py`:

```python
def card_points_breakdown(stats: dict, card_type: str, weights: dict, rarity: dict,
                          mods: dict, mvp_bonus: float = 0.0) -> dict:
    """Exact parts of one game's card points, in display order; they sum to
    _compute_card_points(stats, card_type, weights, rarity, mods, mvp_bonus)."""
    r = rarity.get(f"mod_{card_type}", 0)
    raw = fantasy_score(stats, weights)
    mod_parts = {}
    for stat, pct in mods.items():
        if stat == "deaths":
            base = _death_contribution(stats.get("deaths", 0), weights)
        else:
            base = weights.get(stat, 0) * stats.get(stat, 0)
        mod_parts[stat] = base * pct / 100 * (1 + r)
    return {"raw": raw, "rarity": raw * r, "modifiers": mod_parts,
            "mvp": mvp_bonus * (1 + r), "rarity_pct": r * 100}
```

Test: for random stat rows, modifiers, every rarity and MVP on/off, the sum of the parts equals `_compute_card_points` within 1e-9.

### Step 2 — API
In `_build_roster_block`, for revealed weeks and counted cards only:
- load each card's counted, scored games' `PlayerMatchStats` rows (the same set `games` uses, minus excluded matches),
- use `_load_weights` and `card_points._modifiers` for the card's modifiers,
- sum `card_points_breakdown`'s `raw`, `rarity` and `modifiers` over those games, and keep `mvp` per game (one MVP step for each game with a non-zero MVP part).

Then round:
- `raw` and each step with `display_points`,
- add `week_points - (raw + Σ steps)` to the last step (or to `raw`).

Shape:

```json
"breakdown": {
  "raw": 48.2,
  "steps": [
    {"kind": "rarity",   "label": "Legendary", "pct": 3.0,  "points": 1.4},
    {"kind": "modifier", "stat": "gold_per_min", "label": "GPM", "pct": 10.0, "points": 1.6},
    {"kind": "mvp",      "label": "MVP", "pct": 10.0, "points": 1.5, "match_id": 8001},
    {"kind": "mvp",      "label": "MVP", "pct": 10.0, "points": 1.2, "match_id": 8002}
  ]
}
```

- **Step order:** rarity (only when `pct > 0`), then modifiers in the card's modifier order, then one MVP step per MVP game in game order. Each MVP step's `match_id` matches a `games[].match_id`, so the UI can find the row.
- **Modifier pct:** from the modifier row.
- **MVP pct:** `mvp_bonus_pct`.

### Step 3 — Static breakdown chips
`_weeklySummaryRosterCardHtml` renders:
- **Tag row under the name**, left to right:
  - "RAW {raw}",
  - one chip per modifier step: "{LABEL} +{pct}% +{points}",
  - the status tag, if any, last.
  
  The separate rarity tag from #151 is removed.
- **Under the thumbnail:** a caption in the rarity colour, "+{pct}% +{points}", when there is a rarity step.

In the game rows below, an MVP game's tag reads "MVP +{points}", using that game's MVP step.

**Orange marks only the current card.**
- During the animation, only the card being revealed has the orange border and glow; it goes when the card finishes.
- The subbed-in card's tinted background and orange border from #151 are removed. The "SUBBED IN" tag alone marks it, with a neutral tag colour, so orange isn't mistaken for "current". This changes `.weekly-summary-roster-card` styling from #151.

Game rows are always shown in full, during and after the animation. The recap is where players look for this information, so the rows aren't folded or collapsed.

All values are escaped. This is the finished state and the reduced-motion state.

### Step 4 — Reveal controller
In `app-weekly-summary.js`:
- **When it runs:** `_maybePlayRecap(weekId, roster)` runs after a revealed week's columns render. It plays when the week isn't in the played list and reduced motion is off; otherwise it leaves the static state.
- **Run id:** the controller keeps `_recapAnimation = {runId, weekId}`. Every wait and tween checks the run id, so Skip, a tab switch or closing the report (which bump it) stop it at once.
- **Sequence:**
  1. Render the column with no counted cards and the header total at 0.
  2. For each counted card in reverse order:
   - open its slot at the top (the other cards shift down) and play the entry effect,
   - count up `raw` and light the RAW chip,
   - play each step: highlight the chip, set the card total to its new value at once, and pop it with a floating "+points",
   - add the card's points to the header total.
  3. Append the "Did not play" group.
  4. Mark the week played.
- **Numbers:** they come from the API's rounded values, so the final displays equal `week_points` and `week_total`.

Skip renders the static state. Replay clears the played mark for that week in memory only and runs again.

### Step 5 — Styles
In `style.css`, using tokens only:
- `.recap-chip.pending`: dashed `var(--border)`, dim text,
- `.recap-chip.lit`: `var(--bg-card-hi)`,
- `.recap-chip.hl`: background in the accent or rarity colour, with a glow,
- the count-up number grows and glows through inline `transform` and `text-shadow` set by the controller,
- the bonus pop on the card total and the floating "+points" label,
- the slot opening (animated height on a wrapper, so the cards below shift down) and the slide-in from the left (`transform: translateX`, with opacity) on the card inside it.

`@media (prefers-reduced-motion: reduce)` sets these transitions to none.

### Step 6 — Tests and docs
`backend/tests/test_issue_152_weekly_recap_animations.py`:
- **Breakdown math:**
  - the parts sum to `_compute_card_points` for each rarity, with and without modifiers, with and without MVP, and with a deaths modifier,
  - a player who was MVP in two counted games gets two MVP steps, each with its game's `match_id` and its own points,
  - API rounding: `raw + Σ steps == week_points`,
  - step order and the rarity, MVP and modifier fields.
- **Leave-outs:**
  - no `breakdown` on "Did not play" cards or unrevealed weeks,
  - excluded matches are left out of the breakdown.
- **Static checks:**
  - the Skip/Replay buttons,
  - the `.recap-chip` styles with no hex colours,
  - `prefers-reduced-motion` handling,
  - `aria-busy` and `aria-hidden` use,
  - `localStorage` access wrapped in try/catch,
  - the run-id cancellation in `closeWeeklySummary` and `selectWeeklySummaryTab`.

Bump the suite-size check in `backend/tests/test_issue_85_split_admin_router.py`. Fill in the feature doc and update `core/weekly-summary.md` and `ui_description/weekly-report.md`.

## Verification
- Reveal a week with a legendary MVP card, a rare card with a modifier, a common card and a substitution:
  - cards appear last-slot-first at the top,
  - each counts up for 1 to 3 s,
  - the rarity bonus plays on the thumbnail, then the modifiers on their chips left to right, then each MVP on its own game row, each adding to the card total,
  - only the card being revealed has an orange border,
  - the header total ends at the weekly leaderboard value.
- Card totals and chips match My Team's week points for the same week.
- Press Skip mid-way: everything is final at once. Press Replay: it plays again.
- Switch week tab or close the report mid-animation: nothing keeps running, and no console errors.
- Reopen the week: no animation; the static chips show.
- With reduced motion turned on in the OS, or in a private window where `localStorage` may fail, the report still works.
- `cd backend && python3 -m pytest tests/ -q` passes.
