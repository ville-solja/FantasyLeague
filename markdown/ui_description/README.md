# UI Descriptions

Short specifications for each tab and major UI element. Use these as the reference when implementing or reviewing features.

| File | Tab / Area |
|---|---|
| [my-team.md](my-team.md) | My Team — deck, card draw, roster management, bench |
| [leaderboards.md](leaderboards.md) | Leaderboards — season standings, weekly standings, player performance |
| [schedule.md](schedule.md) | Schedule — Right now strip (live, next up, latest result), fantasy-week strip with a Now line, hide/reveal results, stream/VOD links |
| [players.md](players.md) | Players — player table, player detail modal |
| [teams.md](teams.md) | Teams — team table, team detail modal |
| [profile.md](profile.md) | Profile — username, password, Steam link, Dota 2 player link |
| [weekly-report.md](weekly-report.md) | Weekly Report popup — week tabs, My roster and Match results columns, recap popup |
| [admin.md](admin.md) | Admin — ingest, recalculate, schedule refresh, promo codes, token balances (website accounts / Twitch viewers), scoring weights |
| [twitch-panel.md](twitch-panel.md) | Twitch extension viewer panel — Live, Cards, Roster tabs, Join, team draw picker, bench picker, Settings |

## Shared UI elements

- **Header** — app title, logged-in username, token balance (e.g. "3 Kana Tokens"), Login/Logout button.
- **Tab bar** — clicking the open tab refreshes it quietly: the scroll position stays and nothing on screen changes unless the data did. Opening another tab shows its last content at once, returns to the scroll position it had earlier in this visit (top on a first visit), then refreshes quietly. A failed refresh keeps the content and shows the error in the tab's status line. See `features/reference/flicker-free-tab-switching.md`.
- **Login modal** — username + password fields, Forgot password button, link to registration. Enter submits; the fields are a form that password managers fill (see `features/reference/password-manager-autofill.md`). When `LOGIN_METHOD` is `both` or `steam_signup` (`GET /config` `login_method`, issue #150) a Steam block follows the form: an "OR" divider, a full-width **Sign in with Steam** button (a full-page navigation to `GET /auth/steam/start?purpose=login`, then steamcommunity.com; never a pop-up or frame; no Steam image assets) and the line "Sign-in happens on steamcommunity.com. Kana Cards never asks for your Steam password." In `steam_signup` the **Create new account** link is hidden and "New players: sign in with Steam to create your account." shows instead. After a failed Steam sign-in the modal opens with a message in its status line (`failed`: "Steam sign-in did not complete. Nothing was changed. Try again."; `cancelled`: "Steam sign-in was cancelled. Nothing was changed."; `unavailable`: "Steam sign-in is unavailable right now. Try again later, or sign in with your password."). See `features/reference/steam-login.md`.
- **Choose your name modal** (`#steamSignupModal`, issue #150) — opened by `/#welcome?steam=choose_name` after a new Steam ID signs in: "Steam confirmed your account. Pick the name other players see on Kana Cards. You can change it later in Profile.", a display-name field with the allowed-characters hint, and **Create account** (`POST /auth/steam/signup`). Errors (taken name, invalid characters, "This sign-up has expired. Sign in with Steam again.") appear in its status line; success logs in and opens My Team.
- **Register modal** — username, email, password fields. A muted hint under the username lists the allowed characters (letters, digits, underscore, hyphen). Enter submits. Auto-logs in on success.
- **Card reveal modal** — shown after drawing a card. Displays rarity, player avatar, player name, team.
- **Player detail modal** — opened by clicking any player name. Stats summary + full match history.
- **Team detail modal** — opened by clicking any team name. Player roster with stats.
- **Demo notice** (`#demo-mode-badge`) — shown on every tab only when `GET /config` reports `demo_mode: true`: a small "DEMO MODE" chip (white Big Shoulders caps on the flame red, square `--r-xs` corners) fixed to the bottom-right corner, directly above the faint build version badge. It covers nothing in the header or tab bar, takes no clicks and can't be selected, stays above modals and the guided tour, and fits on one line at phone width. Hidden otherwise. See `features/reference/demo-mode.md` (issue #173).
- **Modals (all)** — every popup closes on Esc or a backdrop click (`data-close`); Tab cycles within the open popup, skipping inputs with `tabindex="-1"` (`_getFocusableIn` in `app-init.js`); focus moves into a popup when it opens.
