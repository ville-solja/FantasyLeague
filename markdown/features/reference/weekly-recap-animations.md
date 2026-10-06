# Weekly Recap Animations

A card-by-card reveal in the Weekly Report's My roster column. Each counted card counts up its raw points, then its rarity, modifier and MVP bonuses are highlighted and added. The result is a breakdown of what each card scored and why. For players reading their weekly recap.

*(see `markdown/plans/plan-issue-152-weekly-recap-animations.md`, resolves GitHub issue #152; builds on the roster panel from #151, `core/weekly-report-fixes.md`)*

---

## Points breakdown

Only final per-game card points are stored (`card_match_points`, #141). The breakdown is recomputed from the same inputs by `card_utils.card_points_breakdown(stats, card_type, weights, rarity, mods, mvp_bonus)`, which returns one game's exact parts (`raw`, `rarity`, `modifiers` by stat, `mvp`, `rarity_pct`). Per game, a card's points are `(card_fantasy_score + mvp_bonus) × (1 + rarity_mod)`. Shown in display order, each step includes the rarity multiplier on its own part, so the steps add up exactly to `_compute_card_points` and so to the stored points:

| Step | Value |
|---|---|
| Raw | `fantasy_score(stats)` |
| Rarity | `raw × rarity_mod` (shown only when the rarity percentage is above 0) |
| Each modifier | `modifier_part × (1 + rarity_mod)`; `modifier_part` is `weight × value × pct/100`, or `death_contribution × pct/100` for deaths |
| MVP | `mvp_bonus × (1 + rarity_mod)`, one step per MVP game |

`routers/weekly_summary._card_breakdowns` sums the parts over each counted card's scored games in the week window (the same week window as `games`, restricted to scored matches with `scored_match_sql()`; `games` still lists excluded matches with `scored: false`, but they and other weeks add nothing to the breakdown), using `_load_weights`, `card_points._modifiers` and `_mvp_bonus_delta`. `raw` and every step are rounded with `display_points`; the rounding remainder (`week_points − (raw + Σ steps)`) goes to the last step, or to `raw` when there are no steps, so the rounded values add up to the card's `week_points` exactly.

Modifier labels come from `scoring.STAT_LABELS`, shared with the card image (`image.py`, formerly `_STAT_LABELS_CARD`).

## Reveal flow

`frontend/app-weekly-summary.js` runs the reveal after a revealed week's columns render (`_maybePlayRecap` from `renderWeeklySummaryContent`), but only when `renderWeeklySummaryContent(data, {playRecap})` is called with `playRecap` true. `selectWeeklySummaryTab` passes `false` for a week already cached during this opening of the popup (#159), so re-rendering a week in the same opening, from the cache or its quiet refresh, shows the finished state. `_playRecap` rebuilds the roster column by hand, so it calls `forgetRendered` on the roster body first; the next `renderIfChanged` then writes the column again.



1. Cards are revealed in reverse roster order, each inserted at the top, so the finished list is in My Team order. The new card's slot (`.recap-slot`) opens from zero height in 340 ms (ease-out) while the cards already shown shift down. The card then slides in from the left edge of the column (`translateX`, 420 ms ease-out cubic, opacity rising over the first 60%).
2. The card's number counts up to its raw points with an ease-in curve over `clamp(1000 + raw × 35, 1000, 3000)` ms, growing slightly and gaining an orange glow. The RAW chip is highlighted (`.recap-chip.hl`) for the whole count and shows the running value, then settles to lit 0.2 s later.
3. Each step in `breakdown.steps` plays in turn (about 0.7 s each). At the same moment the card total jumps to its new value with a 28% pop over 520 ms and a floating "+points" (no count-up). Each bonus plays on the thing that earned it:
   - **rarity:** only the card thumbnail glows in the rarity colour and scales up slightly, and its "+3% +1.4" caption appears; the floating "+points" is in the rarity colour,
   - **each modifier:** its chip turns from a dashed placeholder to a filled orange chip,
   - **each MVP game:** that game's row is tinted orange and its MVP tag fills and gains "+points", one tick per MVP game.
4. The header's week total counts up by each card's points as the card finishes and ends at `roster.week_total`. The "Did not play" group is appended at the end without animation.

Only the card being revealed has the orange border and glow (`.recap-current`). A card with no steps (common, no modifiers, no MVP) goes straight to the next card. A full five-card roster takes about 20 to 25 seconds.

### Controls and accessibility

- **Plays once per week per browser.** Played week ids are kept in `localStorage` under `weeklyRecapPlayed:<user id>` (`weeklyRecapPlayed:anon` when no user id is known), keeping the last 200 week ids; every access is in try/catch, so when storage is unavailable the animation plays again. A week is marked played when the animation finishes or is skipped. A recap interrupted by `_stopRecap()` (a week switch or closing the popup) is not marked played, so it plays again on a later opening.
- **Skip** (shown while playing) stops the animation and renders the finished state at once. **Replay** (shown when idle on a revealed week with at least one counted card, and hidden with reduced motion) plays it again without touching the stored list.
- **Cancellation.** `_recapAnimation.runId` is captured by every wait and `requestAnimationFrame` tween; `_stopRecap()` bumps it and clears every pending timer and frame. Skip, `selectWeeklySummaryTab` (switching or reopening a week) and `closeWeeklySummary` call it, so nothing keeps running.
- **Reduced motion.** With `prefers-reduced-motion: reduce` nothing animates and Replay is hidden; the CSS media query also turns the recap transitions and animations off.
- **Screen readers.** The roster body has `aria-busy="true"` while animating. The counting numbers are `aria-hidden`; each card's final points (and its raw value) are in visually hidden text (`.recap-sr`) from the start.
- The Results column is not touched and stays usable during the animation.

## Static breakdown (finished, skipped or reduced-motion state)

- **Tag row** under the player's name, left to right: "RAW 48.2", one chip per modifier ("GPM +10% +1.6"), then the status tag ("SUBBED IN", neutral colour) last. No rarity chip. The row wraps.
- **Thumbnail:** the player's avatar in a rarity-coloured border, the rarity name below it in the rarity colour, and a rarity-coloured caption "+3% +1.4" under that when there is a rarity step.
- **Game rows** (always shown in full): an MVP game's tag reads "MVP +1.5" with that game's MVP step.

## Endpoints

### `GET /weekly-summary/{week_id}` — changed
Also `POST /weekly-summary/{week_id}/reveal`, which returns the same body. Each counted card in a revealed week's `roster.cards` gains `breakdown`:

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

- Step order: rarity (when its pct is above 0), modifiers in the card's `modifiers` order, then one MVP step per MVP game in game order. Each MVP step's `match_id` is one of the card's `games[].match_id`.
- Modifier `pct` is the modifier row's bonus; MVP `pct` is the `mvp_bonus_pct` weight; rarity `pct` is the `rarity_<type>` weight.
- "Did not play" cards and unrevealed weeks have no `breakdown`.

No new tables, columns or environment variables.

## Tests

`backend/tests/test_issue_152_weekly_recap_animations.py`: breakdown math against `_compute_card_points` for every rarity, with and without modifiers and MVP, and a deaths modifier; API step order, fields, rounding and leave-outs; static checks of the chips, controller, Skip/Replay, storage, reduced motion and ARIA.
