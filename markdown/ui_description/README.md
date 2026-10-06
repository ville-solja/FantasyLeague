# UI Descriptions

Short specifications for each tab and major UI element. Use these as the reference when implementing or reviewing features.

| File | Tab / Area |
|---|---|
| [my-team.md](my-team.md) | My Team — deck, card draw, roster management, bench |
| [leaderboards.md](leaderboards.md) | Leaderboards — season standings, weekly standings, player performance |
| [schedule.md](schedule.md) | Schedule — Right now strip (live, next up, latest result), fantasy-week strip with a Now line, hide/reveal results, stream/VOD links |
| [players.md](players.md) | Players — player table, player detail modal |
| [teams.md](teams.md) | Teams — team table, team detail modal |
| [profile.md](profile.md) | Profile — username, password, Dota 2 player link |
| [weekly-report.md](weekly-report.md) | Weekly Report popup — week tabs, My roster and Match results columns, recap popup |
| [admin.md](admin.md) | Admin — ingest, recalculate, schedule refresh, promo codes, token balances (website accounts / Twitch viewers), scoring weights |
| [twitch-panel.md](twitch-panel.md) | Twitch extension viewer panel — Live, Cards, Roster tabs, Join, team draw picker, bench picker, Settings |

## Shared UI elements

- **Header** — app title, logged-in username, token balance (e.g. "3 Kana Tokens"), Login/Logout button.
- **Tab bar** — clicking the open tab refreshes it quietly: the scroll position stays and nothing on screen changes unless the data did. Opening another tab shows its last content at once, returns to the scroll position it had earlier in this visit (top on a first visit), then refreshes quietly. A failed refresh keeps the content and shows the error in the tab's status line. See `features/reference/flicker-free-tab-switching.md`.
- **Login modal** — username + password fields, Forgot password button, link to registration. Enter submits; the fields are a form that password managers fill (see `features/reference/password-manager-autofill.md`).
- **Register modal** — username, email, password fields. A muted hint under the username lists the allowed characters (letters, digits, underscore, hyphen). Enter submits. Auto-logs in on success.
- **Card reveal modal** — shown after drawing a card. Displays rarity, player avatar, player name, team.
- **Player detail modal** — opened by clicking any player name. Stats summary + full match history.
- **Team detail modal** — opened by clicking any team name. Player roster with stats.
- **Modals (all)** — every popup closes on Esc or a backdrop click (`data-close`); Tab cycles within the open popup, skipping inputs with `tabindex="-1"` (`_getFocusableIn` in `app-init.js`); focus moves into a popup when it opens.
