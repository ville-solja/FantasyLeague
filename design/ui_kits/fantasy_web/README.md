# Kanaliiga Fantasy — Web App UI Kit

Hi-fi recreation of the Kanaliiga Fantasy web app rebuilt against the target visual direction (stream-overlay aesthetic — Big Shoulders display type, orange/red flame palette, Dota dusk imagery, angular chrome).

**Functional reference:** `ville-solja/FantasyLeague/frontend/` (vanilla HTML/CSS/JS).
**Visual reference:** stream overlay assets in `/assets/stream/` — NOT the current implementation screenshots.

## Files
- `index.html` — click-through prototype (7 tabs: My Team, Profile, Leaderboards, Players, Teams, Schedule, Admin).
- `Header.jsx` — top bar with logo + season badge + token counter + account.
- `Tabs.jsx` — tab strip.
- `Panel.jsx` — base card surface.
- `Button.jsx` — primary / secondary / ghost / twitch variants.
- `CardSlot.jsx` — Fantasy card slot with rarity glow.
- `MatchupRow.jsx` — schedule row.
- `LeaderboardTable.jsx` — ranked table.

## Coverage note
This kit reimagines the Fantasy app visually while keeping the exact information architecture and tab structure from the source frontend. It is a cosmetic rebrand, not a new product design.
