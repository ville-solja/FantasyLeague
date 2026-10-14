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

`frontend/app-weekly-summary.js` runs the reveal after a revealed week's columns render (`_maybePlayRecap` from `renderWeeklySummaryContent`), but only when `renderWeeklySummaryContent(data, {playRecap})` is called with `playRecap` true. `selectWeeklySummaryTab` passes `false` for a week already cached (#159; since #202 the cache lasts for the page visit, not one opening), so re-rendering a week, from the cache or its quiet refresh, shows the finished state. `_playRecap` rebuilds the roster column by hand, so it calls `forgetRendered` on the roster body first; the next `renderIfChanged` then writes the column again.



1. Cards are revealed in reverse roster order, each inserted at the top, so the finished list is in My Team order. The new card's slot (`.recap-slot`) opens from zero height in 340 ms (ease-out) while the cards already shown shift down. The card then slides in from the left edge of the column (`translateX`, 420 ms ease-out cubic, opacity rising over the first 60%).
2. The card's number counts up to its raw points with an ease-in curve over `clamp(1000 + raw × 35, 1000, 3000)` ms, growing slightly and gaining an orange glow. The RAW chip is highlighted (`.recap-chip.hl`) for the whole count and shows the running value, then settles to lit 0.2 s later.
3. Each step in `breakdown.steps` plays in turn (about 0.7 s each). At the same moment the card total jumps to its new value with a 28% pop over 520 ms and a floating "+points" (no count-up). Each bonus plays on the thing that earned it:
   - **rarity:** only the card thumbnail glows in the rarity colour and scales up slightly, and its "+3% +1.4" caption appears; the floating "+points" is in the rarity colour,
   - **each modifier:** its chip turns from a dashed placeholder to a filled orange chip,
   - **each MVP game:** that game's row is tinted orange and its MVP tag fills and gains "+points", one tick per MVP game.
4. The header's week total counts up by each card's points as the card finishes and ends at `roster.week_total`. The "Did not play" group is appended at the end without animation.

Only the card being revealed has the orange border and glow (`.recap-current`). A card with no steps (common, no modifiers, no MVP) goes straight to the next card. A full five-card roster takes about 20 to 25 seconds.

### Controls and accessibility

- **Plays once per week per browser.** Played week ids are kept in `localStorage` under `weeklyRecapPlayed:<user id>` (`weeklyRecapPlayed:anon` when no user id is known), keeping the last 200 week ids; every access is in try/catch, so when storage is unavailable the animation plays again. A week is marked played when the animation finishes or is skipped. A recap interrupted by `_stopRecap()` (a week switch or closing the popup) is not marked played. Since issue #202 the week cache lasts for the page visit, so a recap plays at most once per week per page visit: one interrupted by a week switch or by closing the popup does not play again on reopening; the **Replay** button plays it. On a later page visit it plays again.
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

## Shared motion principles

The recap set the rules that later animations follow, starting with My Team (#155):

- **Short.** Each animation is short (up to about 1.2 s; count-ups up to 2 s).
- **Once.** Each plays once per event, remembered per browser in `localStorage`, with every access in try/catch.
- **Skippable.** A click finishes it at once (the token chip's 600 ms count-up is the exception: it simply ends, or jumps on the next update).
- **Reduced motion.** With `prefers-reduced-motion: reduce` nothing moves and the final state shows; the CSS also turns every animation off in a media query.
- **No new backend data.** The page compares what it shows now with what it showed last time.
- **Screen readers** get final values only: counting text is `aria-hidden`, with the final value in visually hidden text (the roster and recap count-ups; the header token chip counts its own number directly).

## My Team motion (issue #155)

*(plan `markdown/plans/plan-issue-155-my-team-motion.md`; user view in `markdown/ui_description/my-team.md#motion`)*

Shared helpers in `frontend/app-globals.js`: `prefersReducedMotion()`, `flipMove(els, first, opts)` (#186), `seenStore(key)` (a JSON `localStorage` entry with `get(fallback)`, `set`, `has` and `add(item, cap)`; storage that is missing, blocked or holds bad JSON reads as the fallback) and `tweenNumber(el, from, to, ms, opts)` (animation-frame count-up, ease-out, ends exactly at `to`, returns a finish function).

`frontend/app-roster.js` runs `_playRosterMotion` at the end of `loadRoster`. `_rosterMotion = {runId, finishers}` holds one finish function per running animation; `_finishRosterMotion()` (at the start of every `loadRoster`, on a click on the roster grids, where it replaces the card click, and on a click anywhere in `#tab-team`) bumps `runId` and calls them all.

| Moment | Stored in | Plays when | What moves |
|---|---|---|---|
| New points | `rosterSeenPoints:<user id>:<week id>` = `{cards: {id: points}, total}` | a roster card's points are higher than stored | `.card-slot-pts` counts up over `clamp(600 + delta × 20, 600, 2000)` ms, `.roster-pts-float` "+delta", `.roster-pts-glow`; `#rosterCombined` counts up by the summed gains over the longest card's time |
| Week locks | `rosterLockSeen:<user id>`, last 50 week ids | a locked week not in the list | `#rosterLockedBanner.roster-lock-stamp` (scale 1.15 → 1, fade, 300 ms) with a CSS lock whose shackle closes; both grids get `.roster-lock-enter` (the cards dim to the locked filter over 400 ms) |
| Substitutions | `rosterSubsSeen:<user id>`, entries `<week id>:<pairs>` such as `5:2>7,4>8`, last 50 | `substitutions_done`, at least one substitution, entry not stored | renders the before-layout (subbed-out cards in their slots), then per pair in slot order a 700 ms FLIP to the final layout, 300 ms apart; `.roster-sub-out` fades the leaving card, `.roster-sub-pending` / `.roster-sub-in` hide and fade in the "Subbed in for" label. Starts after the lock stamp when both play |
| Token gain | `tokensSeen:<user id>` | `updateTokenDisplay` gets a balance higher than the one shown (after page load: than the stored one) | `#headerTokenNum` counts up over 600 ms, `.header-tokens.token-chip-pulse`, `.token-float` "+N" |

Pairs come from the roster response: a `subbed_in` card names the replaced player in `subbed_in_for`, matched to a `subbed_out` bench card with that name, or to the next unused `subbed_out` card when no name matches. Seen state is written even under reduced motion. The first visit to a week, decreases and `updateTokenDisplay(null)` (logout, which keeps `tokensSeen`) never animate. The CSS is the "My Team motion (issue #155)" block in `style.css`, before the guided tour section, with every animated class switched off under `prefers-reduced-motion: reduce`.

## Tests

`backend/tests/test_issue_152_weekly_recap_animations.py`: breakdown math against `_compute_card_points` for every rarity, with and without modifiers and MVP, and a deaths modifier; API step order, fields, rounding and leave-outs; static checks of the chips, controller, Skip/Replay, storage, reduced motion and ARIA.

`backend/tests/test_issue_155_my_team_motion.py`: the My Team motion helpers and each story, through the Node harness of #186 (fake DOM, timers, frames, a fake `localStorage` that can also throw or be missing) plus static CSS checks.
