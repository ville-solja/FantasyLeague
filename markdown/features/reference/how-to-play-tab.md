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
| **Users** *(default)* | Every visitor | Getting Started (drawing cards, roster/weekly lock, earning tokens), Watching on Twitch (linking a Fantasy account via Profile → Generate Twitch Code, token drop eligibility), and Scoring & Modifiers (live stat/rarity/modifier tables + MVP bonus, all from `GET /weights`) |
| **Players** | Kanaliiga players | How to link a Dota 2 (OpenDota) player ID to a Fantasy account via the Profile tab so admin-granted tags appear as card stickers and leaderboard chips (see `reference/player-linking-and-tag-visibility.md`); clarifies linking is optional/changeable and that match performance counts toward other users' rosters regardless of whether the player has linked (or even has) a Fantasy account |
| **Streamers** | Broadcasters | How to apply for the Twitch extension (developer-provided test install link while in Twitch's Local Test status; not needed once publicly released), how to install it (Twitch Extension Manager, no broadcaster-side URL configuration), and the broadcaster half of the MVP flow: Quick Actions → Select match MVP → series → match → player → confirm, plus the resulting token drop and fantasy score bonus |
| **Developers** | Contributors | High-level design-decision summary (dynamic per-draw card generation, SQLite with a migration registry + backup script, admin-driven season lifecycle, Demo Mode, the generic tag system) linking out to `README.md`, `markdown/features/README.md`, and `markdown/process-diagrams.md` rather than duplicating their content |

Subtab switching is client-side only (no additional network request) — clicking a
`.howtoplay-tab-btn` toggles which `[data-howtoplay-tab]` panel is visible and does not re-fetch
`GET /weights` or call any other endpoint. The Users subtab is always shown first when the How
to Play tab is opened.

---

## Implementation

The tab is entirely frontend. No new backend endpoints are introduced.

| Surface | Change |
|---|---|
| `frontend/index.html` | Tab button `#tab-btn-howtoplay`; content div `#tab-howtoplay` containing a `#howtoplay-tab-bar` of four `.howtoplay-tab-btn` buttons (`data-tab="users\|players\|streamers\|developers"`) and four panel divs `#howtoplay-panel-users`, `#howtoplay-panel-players`, `#howtoplay-panel-streamers`, `#howtoplay-panel-developers` (each tagged `data-howtoplay-tab="..."`) |
| `frontend/app-init.js` | `switchHowToPlayTab(role)` toggles panel `display` via `[data-howtoplay-tab]` and active-button state via `.howtoplay-tab-btn.active`; `initHowToPlayTabs()` wires button click listeners and calls `switchHowToPlayTab('users')` as the default; `loadHowToPlay()` calls `initHowToPlayTabs()` then fetches `GET /weights` and populates three `<tbody>` elements (`#howtoplay-stats-tbody`, `#howtoplay-rarity-tbody`, `#howtoplay-mods-tbody`) and one inline span (`#howtoplay-mvp-bonus`), all inside the Users panel |
| `frontend/style.css` | `.howtoplay-tab-btn` / `.howtoplay-tab-btn.active` (shared rule with `.admin-tab-btn`, mirroring the Admin panel's subtab styling) |

`switchTab('howtoplay')` calls `loadHowToPlay()`, which in turn calls `initHowToPlayTabs()` before
its `GET /weights` fetch. The tab button and all four subtabs have no auth-state visibility
logic — they are always shown, matching the tab's public nature.

### Graceful fallback
If `GET /weights` fails, the stat/rarity/modifier tables in the Users subtab are empty but all
surrounding explanatory text remains visible. No error banner is shown for this failure.
