# UI Descriptions

Short specifications for each tab and major UI element. Use these as the reference when implementing or reviewing features.

| File | Tab / Area |
|---|---|
| [my-team.md](my-team.md) | My Team — deck, card draw, roster management, bench |
| [leaderboards.md](leaderboards.md) | Leaderboards — season standings, weekly standings, player performance |
| [schedule.md](schedule.md) | Schedule — season fixture list with results and stream/VOD links |
| [players.md](players.md) | Players — player table, player detail modal |
| [teams.md](teams.md) | Teams — team table, team detail modal |
| [profile.md](profile.md) | Profile — username, password, Dota 2 player link |
| [admin.md](admin.md) | Admin — ingest, recalculate, schedule refresh, promo codes, token balances, scoring weights |

## Shared UI elements

- **Header** — app title, logged-in username, token balance (e.g. "3 Kana Tokens"), Login/Logout button.
- **Login modal** — username + password fields, link to registration.
- **Register modal** — username, email, password fields. Auto-logs in on success.
- **Card reveal modal** — shown after drawing a card. Displays rarity, player avatar, player name, team.
- **Player detail modal** — opened by clicking any player name. Stats summary + full match history.
- **Team detail modal** — opened by clicking any team name. Player roster with stats.
