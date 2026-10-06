# Schedule tab

Visible to everyone. Loads data from a structured JSON fixtures feed (`SCHEDULE_FIXTURES_URL`)
when configured, otherwise a public Google Sheets CSV export; the parsed result is cached in
memory and the response shape is identical for both sources. See
`markdown/features/reference/schedule-fixtures-api.md`. The layout below is from issue #156;
see `markdown/features/reference/schedule-visuals.md`.

## Season Schedule panel

### Header

- **Season Schedule** title.
- **Hide results** toggle (`#scheduleHideToggle`, `aria-pressed`). The label always reads "Hide results"; the pressed state (orange outline) shows that hide mode is on. Hide mode is on by default and the choice is remembered in the browser (`kc_schedule_hide`).
- **Refresh** button: reloads the schedule without clearing the screen.
- Stale notice (`#scheduleStale`): shown when the server returned stale cached data ("Cached data from …").

### Right now strip (`#scheduleNow`)

Up to three cards side by side; each card is left out when it has nothing to show, and the strip is hidden when all three are empty.

- **Live now** (red border and pulsing dot): a series whose two teams have a game in progress. Shows the teams, division, "Started HH:MM" and a "Watch live ↗" link when a stream URL is known.
- **Next up**: the next three upcoming series with a real planned time (never a "Time TBD" fixture), as compact rows: weekday and time, division, the teams (lined up on "vs"), the streamer and a Watch button. The card header shows a countdown in orange to the first one ("starting now" under a minute away, "in 45 min", "in 1 h 20 min", "in 2 days"). With fewer than three timed series, the card fills up with one row per coming week whose matches have no time yet: the week and its start ("Week 5", "Mon 12.10."), how far away it is in plain words and the match count ("**Next week** · 7 matches, times to be announced"; later weeks "In 2 weeks", "In 3 weeks"), and a **View week** button. On phone each row puts the time and button on top and the teams below, and the streamer name is left out.
- **Latest result**: the most recently played series.
  - Hidden: teams at equal weight, "Result hidden" and a **Reveal** button. No score or MVP.
  - Shown: winner bold, loser muted, the series score, and a **Games** button that opens that series' week with its games unfolded.

The countdown is computed when the tab renders (tab switch or refresh), not on a timer.

### Week strip (`#scheduleWeeks`)

- One chip per fantasy week (`W1`, `W2` … from the admin week labels) with its start date. With no fantasy weeks, one chip per Monday-start calendar week, labelled with its date range.
- The current week's chip has an orange border, "This week" in orange and `aria-current="date"`. Weeks before the current one have a darker fill; upcoming weeks a dashed border. The selected chip is brighter (`aria-pressed="true"`).
- A small orange marker sits on the chip of every week that still has hidden results.
- Previous / next arrow buttons and a **This week** button (disabled while the current week is shown).
- The tab opens on the current week: the week containing now, else the next to start, else the last. The selected week survives a refresh.

### Week panel (`#scheduleContent`)

- Header: the week's label and date range, then either "Revealed in your Weekly Report" (when the logged-in player revealed this fantasy week in the Weekly Report), or **Reveal week** (when the week has hidden results) and **Hide week again** (when hide mode is on and series in the week were revealed on this tab; it hides them again), then the division chips **All / Div 1 / Div 2**.
- Series grouped by day (English weekday, Finnish day-month order, e.g. "Mon 5.10.2026"), earliest first, both divisions mixed. "Time TBD" fixtures close the week in their own "Time TBD" group.
- In the current week an orange **Now** line ("Now · Wed 18:00") sits between the last started series and the next one.
- Empty states: "No matches this week." and "No matches for this division this week."

### Series rows

Each row: time and division badge, team 1, centre cell, team 2, actions.

| State | Centre | Actions |
|---|---|---|
| Upcoming | "vs" | Stream link or label. Time shows "Time TBD" for an unscheduled fixture. |
| Live | red "LIVE" tag, plus the partial score when results are visible | "Watch live" stream link |
| Hidden (played, hide mode on, not revealed) | "Played" | **Reveal** |
| Shown | series score in display type; winner bold, loser muted | **N games** (`aria-expanded`), VOD/stream link |

- A hidden row outputs no score, game count, game rows, kills, heroes, MVP or "Not scored" badge at all.
- **N games** unfolds the per-game rows: game number, both sides' hero icons, kills score, MVP with a star, duration, OpenDota link, and a "Not scored" badge for a game excluded from fantasy scoring.
- A played series with no resolved games shows its score and no games button.
- Team names open the team popup; MVP names open the player popup. In a hidden row (and a hidden Latest result card) team names are plain text, because the team popup lists results.
- A fixture past its date with no resolved games shows "No result" in the centre and no games button, instead of "vs".
- **Caster TBD:** an upcoming fixture with no stream link yet shows "Caster TBD" in italics (or the feed's stream label, if it named one) and a greyed-out, dashed Watch button that is not a link.
- **Streamer name:** before each watch button, in muted text: the feed's stream label, or else the channel taken from the stream URL (`twitch.tv/kanaliiga` → "kanaliiga", `youtube.com/@name` → "name", other sites → their host).
- **Stream and watch links** are outlined buttons in the display face with an arrow icon (they open in a new tab), next to the games button. A live match's "Watch live" link is the filled orange button. A stream label without a URL stays plain muted text.
- **Alignment:** series rows and game rows share one column grid (time and division, team 1, score, team 2, link and button). Team 1 is right-aligned and team 2 left-aligned so both face the score, and each game's heroes sit under their team next to the kills. Links and buttons have fixed slots, so they line up down the list.
- **Keyboard:** after Reveal, "N games", a week chip or a division chip, focus returns to the same control (after Reveal, to the row's games button; failing that, to the week heading).

### Phone layout (below 700 px)

The Right now cards stack, the week strip scrolls sideways with the arrows hidden, each series row becomes two lines (time, division and action on top; teams and score below), and game rows hide hero icons. Buttons in the panel are at least 44 px tall.

### Loading and errors

"Loading..." shows only on the tab's first load. Later visits keep the fixtures on screen while they refresh and change only what changed; if a refresh fails, the fixtures stay and the status line (`#scheduleStatus`) reads "Couldn't load the schedule. Refresh to try again." (the raw error goes to the browser console). When the source is unavailable and the database has no results, the panel shows the error text.

Team name matching between the schedule source and the database is fuzzy (case-insensitive, ignores parenthetical content, substring fallback). Div 2 teams without an OpenDota team_id are matched via stored team name fields on match records.
