# Weekly Report popup

Opened from the **Weekly Report** button at the top right of the header (logged-in users only), or from the recap popup. Feature details: `markdown/features/core/weekly-summary.md`, `core/weekly-report-fixes.md` and `reference/weekly-recap-animations.md` (points breakdown and reveal animation).

## Header button

- **Weekly Report** button (`#weeklyReportBtn`) with a dot (`#weeklyReportBadge`) while a newer week's report has not been opened. Opening the popup clears the dot.

## Popup layout (`#weeklySummaryModal`)

- **Title bar** — "Weekly Report" and an X close button.
- **Week tabs** (`#weeklySummaryTabs`) — one tab per available week, newest first. These are the only tabs. Opening the popup selects the newest week, or the week the recap popup announced.
- **Two columns** below the tabs, side by side: **My roster** (480 px) and **Match results** (the rest). Each has a fixed header and its own scrolling body with the shared thin `.k-scroll` scrollbar.
- **Reveal footer** (`#weeklySummaryRevealFooter`) — a "Reveal results" button under both columns, shown while any listed week is unrevealed. It reveals every listed week at once.
- **Size** — at most 1280 px wide and 85% of the window height; below 600 px, the full width less 16 px and 92% of the window height.
- **Below 1100 px** — the columns stack (roster first) and the whole popup scrolls as one page; the reveal footer stays at the bottom. No horizontal scrolling at 375 px.
- Closing: X, Esc or a click on the backdrop.

## My roster column

### Header

- "MY ROSTER" title and, once revealed, "Week total {pts} pts" (equals the user's points on the weekly leaderboard for that week).
- **Skip** (shown only while the reveal animation plays) — shows the finished state at once. **Replay** (shown when it is not playing, on a revealed week with at least one counted card) — plays the animation again. Small ghost buttons between the title and the week total. Replay is hidden with reduced motion.
- Meta line: "{n} counted · {m} substitutions" when revealed, "{n} cards" before reveal.
- While bench substitutions are still pending for a revealed week: "Bench substitutions are made {N} hours after the week ends; roster marks may change."

### Cards (revealed week)

1. **Counted cards**, in My Team order for that week. A subbed-in bench card sits in the slot of the card it replaced, with a **SUBBED IN** tag (neutral colour, no tinted background or orange border) and the line "From your bench, for {name}, who did not play this week".
2. **Did not play** group, only when a substitution happened: the replaced original cards, greyed out with a dashed border, a **NOT COUNTED** tag and the line "No matches this week. Replaced by {name}". Their points don't count.

Unused bench cards are not shown.

Each card shows:

- a thumbnail: the player's avatar (64 × 64 px, initials when there is none) in a rarity-coloured border, with the rarity name in the rarity colour below it; clicking it (or Enter) opens the card viewer with the full card image and modifiers, footer "{pts} wk pts". The viewer opens on top of the report,
- below the rarity name, for a card with a rarity bonus, a caption in the rarity colour: "+{pct}% +{points}" (none for common cards),
- the player name (player link) and team name (team link),
- the card's week points,
- a tag row under the name, left to right in the order the bonuses are added: **RAW {points}**, one chip per modifier ("GPM +10% +1.6"), then the status tag (SUBBED IN / NOT COUNTED), if any. There is no rarity tag in this row. The row wraps. "Did not play" cards have no RAW or modifier chips,
- one row per game the player played that week, always shown in full: date, "vs {opponent}" (team link), game number in the series (G1, G2…), WIN or LOSS (no tag if the result is unknown), an MVP tag that reads "MVP +{points}" with that game's MVP bonus, and the card's points for that game. A game excluded from scoring shows "Not scored". A card whose player played no games shows "No games this week".

The RAW value plus the rarity caption, the modifier chips and the MVP bonuses add up to the card's week points.

### Reveal animation (revealed week)

Plays the first time a revealed week is shown in this browser (usually right after "Reveal results"); afterwards the week opens in the finished state above.

- The column starts empty and the header reads "Week total 0.0 pts". Cards appear one at a time in reverse order, each at the top: its slot opens and pushes the earlier cards down, then the card slides in from the left.
- The card being revealed has an orange border and glow; it goes when the card finishes.
- Its points count up from 0 to the RAW value (1 to 3 seconds, speeding up, growing and glowing); the RAW chip is filled orange during the count and shows the running value.
- Then each bonus in turn: the rarity bonus glows on the thumbnail (rarity colour) and its caption appears; each modifier chip changes from a dashed placeholder to a filled orange chip; each MVP game's row is tinted orange and its MVP tag fills and gains "+{points}". With each bonus the card's points jump to the new value with a short pop and a floating "+{points}".
- The header week total adds each card's points as it finishes. The "Did not play" group appears at the end without animation.
- The Match results column stays usable throughout.
- Skip, switching week tab or closing the report stops it. With reduced motion turned on, the finished state shows at once.
- Screen readers: the roster body is marked busy while animating; the counting numbers are hidden from them and each card's final points are read instead.

### Before reveal

- "Reveal results to see your points", then the cards as they were at lock time (a replaced card stays in its slot; the substitute is not shown).
- Thumbnails (avatar, rarity border and rarity name below), names and teams only. No points, chips, rarity caption, game rows, results, MVP or status tags, and no animation.
- Thumbnails still open the card viewer, with no points footer.

### Empty / loading / error

- "Loading…" while a week loads; the API error text if it fails.
- "No cards on your roster this week." when the user had no cards for that week.

## Match results column

### Header

- "MATCH RESULTS" title and "{n} series · {n} games".

### Content

- Matches grouped by series. Each match shows both teams (logo and team link), the date, a "Not scored" badge for excluded matches and a VOD link when set.
- After reveal: the winner is outlined with a "Winner" label, and each team's players appear as tiles (avatar, player link, points). The MVP has an outline and "MVP" label.
- **Your cards:** a player the user had as a counted card that week gets a filled tile with a **YOUR CARD** label (**YOUR SUB** for a subbed-in card), showing the user's card points for that game in the accent colour. Other players show match points in the muted colour. On a match excluded from scoring no tile is marked, since there are no card points.
- "No matches played during this week." when the week has none; "No weekly reports available yet." when no week is available.

## Typography and contrast

The report follows a readability floor, checked by `backend/tests/test_weekly_report_readability.py`:

- **Sizes:** data the player reads is 13 px (`--fs-sm`): game rows, tags, bonus chips, notes, player names and points on result tiles, column meta, the dates. Small all-caps labels (MVP, YOUR CARD, WINNER, the points unit) are 11 px (`--fs-xs`), the minimum.
- **Typeface:** Big Shoulders only at 13 px and up (titles, tags, chips, the rarity name under the thumbnail, the avatar initials, points). Labels smaller than that use Inter.
- **Colour:** readable text uses `--fg-muted` (5.4:1 on cards) or brighter. `--fg-dim` (3.2:1) is only for borders and the pending-chip placeholder.
- **Numbers:** all points use tabular numerals, so they line up.
- **"Did not play" cards:** marked by a dashed border and transparent background, not by fading the whole card.
- **Units:** the `--fs-*` tokens are `rem`, so the browser's font-size setting scales the report.

## Links and stacking

- All player and team names open the existing player and team popups, which open on top of the report; closing them returns to the report on the same week with scroll positions kept.
- The card viewer stacks above the report; a player link inside the viewer opens the player popup on top of the viewer.

## Recap popup (`#weeklyRecapPrompt`)

A small dialog shown after login or page load when the newest report week has not been announced to the user yet (not opened and not shown as this popup before, on any device).

- Eyebrow "WEEKLY REPORT", title "Week {label} recap is ready" (a label that already starts with "Week" is used as is), the line "See what your cards scored and how the matches went" and the note "You can also find every recap under Weekly Report at the top right."
- **Open recap** (primary) — opens the report on that week and clears the header dot.
- **Close**, the X, Esc or a backdrop click — closes it and marks the week announced; the header dot stays until the report is opened.
- Shows only the newest new week. Not shown while another popup or the guided tour is open, or while a password change is required (shown on a later page load instead).
- Gives no results, points or winners away.
- Focus moves to "Open recap" and Tab stays inside the popup.
