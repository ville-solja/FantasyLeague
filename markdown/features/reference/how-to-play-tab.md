# How to Play Tab

A static informational tab visible to all users that explains the fantasy league rules, the
scoring formula, card modifiers, and the Twitch extension MVP flow. It is organised into four
role-based subtabs so each audience can jump straight to what applies to them. Scoring weight
values are loaded live from `GET /weights` so the displayed numbers stay accurate when an admin
adjusts weights.

---

## Role-based subtabs

| Subtab | Audience | Content |
|---|---|---|
| **Users** *(default)* | Every visitor | Getting Started (a **Show the tour** button `#htpTourBtn` under the intro that starts the My Team guided tour, or opens the login popup for logged-out visitors — see `reference/guided-tour.md`; drawing cards, including the team draw bullet whose cost span `#htpTeamDrawCost` is filled from `GET /config` `team_booster_cost`, roster/weekly lock, earning tokens), Watching on Twitch (playing in the Kana Cards panel: the Live tab for everyone, **Join Kana Cards** with the Twitch login, draws and roster in the panel, token drop eligibility while the panel is open; connecting Twitch on Profile with Twitch sign-in so the panel plays with the website account (#160; the panel link-code UI was removed in #157 and the link-code routes retired in #160), and Scoring & Modifiers (live stat/rarity/modifier tables + MVP bonus, all from `GET /weights`, plus a note that points are shown to one decimal and totals are rounded from exact points) |
| **Players** | Kanaliiga players | How to link your league player to a Fantasy account with **Link Steam** on the Profile tab (the id comes from Steam and can't be typed in, #209) so admin-granted tags appear as tag symbols on cards and leaderboard chips (see `reference/player-linking-and-tag-visibility.md`); clarifies linking is optional/changeable and that match performance counts toward other users' rosters regardless of whether the player has linked (or even has) a Fantasy account |
| **Streamers** | Broadcasters | Since #246 it opens with a list of the four streamer tools, each linking to its section: **Pause screen overlay** (an OBS browser source, no extension or approval needed; a URL builder with two team pickers sorted by name from `GET /teams`, a Transparent background checkbox, the URL in a read-only field, **Copy** and **Open preview**, and the three OBS steps; see [OBS Last Game Overlay](obs-last-game-overlay.md)), **Kana Cards extension** (Getting access: not yet approved by Twitch, so not yet available on Twitch, so channels install it as testers with a test install link from the league; the Twitch Extension Manager once publicly released; no broadcaster-side URL configuration; Quick Actions → Select match MVP → series → match → player → Confirm MVP & Drop Tokens, only matches in the 5 most recent series; the resulting token drop and fantasy score bonus), **Viewer MVP vote** (coming with extension version 1.4.0: Start viewer vote, 1, 2 or 3 minutes, End now, Cancel vote, Confirm MVP & Drop Tokens) and **Kana Cards MVP Vote** (the vote-only extension, not yet submitted to Twitch; its button is Confirm MVP). Each extension section says a channel needs the league's approval (`TWITCH_MVP_CHANNEL_IDS` or Admin › Twitch › Approved streamers, #175) before it can set MVPs |
| **Developers** | Contributors | High-level design-decision summary (dynamic per-draw card generation, SQLite with a migration registry + backup script, admin-driven season lifecycle, Demo Mode, the generic tag system) linking out to `README.md`, `markdown/features/README.md`, and `markdown/process-diagrams.md` rather than duplicating their content |

Subtab switching is client-side only (no additional network request): clicking a
`.howtoplay-tab-btn` sets Alpine's `howToPlayTab`, which shows one panel through `x-show`, and
does not re-fetch `GET /weights` or call any other endpoint. The Users subtab is shown first
(`x-data="{ howToPlayTab: 'users' }"`).

---

## Implementation

The tab is entirely frontend. It reads the public `GET /weights` and, for the overlay URL builder (#246), `GET /teams`.

| Surface | Change |
|---|---|
| `frontend/index.html` | Tab button `#tab-btn-howtoplay`; content div `#tab-howtoplay` containing a `#howtoplay-tab-bar` of four `.howtoplay-tab-btn` buttons (`data-tab="users\|players\|streamers\|developers"`) and four panel divs `#howtoplay-panel-users`, `#howtoplay-panel-players`, `#howtoplay-panel-streamers`, `#howtoplay-panel-developers`. Switching is Alpine (see `reference/frontend-framework-evaluation.md`): `#tab-howtoplay` has `x-data="{ howToPlayTab: 'users' }"`, each button sets it with `@click` and gets `.active` through `:class`, each panel has `x-cloak x-show="howToPlayTab === '...'"`. Since #246 the Streamers panel's sections have ids `#htp-streamers-overlay`, `#htp-streamers-extension`, `#htp-streamers-viewer-vote` and `#htp-streamers-mvp-vote`, the targets of the overview list's links |
| `frontend/app-init.js` | `loadHowToPlay()` fetches `GET /weights` and populates three `<tbody>` elements (`#howtoplay-stats-tbody`, `#howtoplay-rarity-tbody`, `#howtoplay-mods-tbody`) and one inline span (`#howtoplay-mvp-bonus`), all inside the Users panel |
| `frontend/app-init.js` (#246) | `loadHowToPlay()` first calls `loadObsOverlayBuilder()`, which fills `#obs-team-a` / `#obs-team-b` once from `GET /teams` (`obsOverlayTeamOptions`, sorted by name, names escaped); `updateObsOverlayUrl()` (the pickers' and checkbox's `onchange`) builds the URL with `obsOverlayUrl(location.origin, a, b, transparent)` and enables **Copy** and the preview link only when `obsOverlayCopyEnabled(a, b)`; `copyObsOverlayUrl()` uses the Clipboard API and falls back to selecting the field |
| `frontend/app-tour.js` | `startTourFromHowToPlay()`, wired to `#htpTourBtn` (see `reference/guided-tour.md`) |
| `frontend/style.css` | `.howtoplay-tab-btn` / `.howtoplay-tab-btn.active` (shared rule with `.admin-tab-btn`, mirroring the Admin panel's subtab styling); `[x-cloak]` hides panels until Alpine starts; since #246 `.htp-tool-list` (the Streamers overview) and `.obs-builder*` (the overlay URL builder, one column under 520px) |

`switchTab('howtoplay')` calls `loadHowToPlay()`, which starts `loadObsOverlayBuilder()` and then
fetches `GET /weights`. The tab button and all four subtabs have no auth-state visibility
logic — they are always shown, matching the tab's public nature.

### Graceful fallback
If `GET /weights` fails, the stat/rarity/modifier tables in the Users subtab are empty but all
surrounding explanatory text remains visible. No error banner is shown for this failure.
If `GET /teams` fails, the overlay pickers keep "Loading teams…", **Copy** and **Open preview**
stay disabled, and the next visit to the tab tries again (#246).
