# Linkable Tabs

Every main tab has its own address, `https://<site>/#<tab>`, which opens that tab directly, and the address bar follows the tab a person is on, so it can be copied and shared. For the league advertising a feature (the Finals tab) and for anyone sharing a page. Issue #245. Plan: `markdown/plans/plan-issue-245-linkable-tabs.md`.

---

## Links

| Link | Opens |
|---|---|
| `/#leaderboards` | Leaderboards (also the page with no link) |
| `/#my-team` | My Team (login required) |
| `/#history`, `/#players`, `/#teams`, `/#schedule` | That tab |
| `/#finals` | Finals, when open; otherwise Leaderboards with "The Finals tab isn't open yet." |
| `/#team-finder` | Team Finder, when open (admins: always); otherwise Leaderboards with "Team Finder isn't open right now." |
| `/#how-to-play`, `/#how-to-play/<users \| players \| streamers \| developers>` | How to Play, on that subtab |
| `/#profile` | Profile (login required) |
| `/#admin` | Admin, for admins only; anyone else lands on Leaderboards with no notice |

The internal ids (`#team`, `#leaderboard`, `#teamfinder`, `#howtoplay`) work too, in any letter case. An unknown name opens Leaderboards; an unknown How to Play subtab opens How to Play on Users. A fallback rewrites the address to the tab actually shown (`#leaderboards`, `#how-to-play`).

## Behaviour

- **Address bar:** a click on a tab (tab bar, the header username, "How scoring works" on My Team, **Show the tour** in How to Play) adds a history entry with the tab's link, so Back and Forward move between tabs, each with its saved scroll position. Clicking the tab already open adds nothing. Switches made by code (after login, logout, a sign-in return) replace the entry. Choosing a How to Play subtab replaces the address with `#how-to-play/<subtab>`. The path and query string are kept. A plain `/` visit keeps its address until a tab is chosen.
- **Opening from a link:** the tab is decided after `/config` and `/me` have answered, with the same conditions that show each tab button, so an open tab is never refused early and a link can never open a tab its button doesn't show. Opening from a link adds no history entry.
- **Login:** a link to My Team or Profile while logged out opens the login dialog; login, registration and the Steam sign-up then go to that tab instead of My Team. The tab is kept in `sessionStorage` (`pendingTab`), so it also survives the Steam sign-in's round trip to steamcommunity.com. Closing the login, register or Steam sign-up dialog drops it.
- **Sign-in returns:** hashes with a `?` (`#profile?twitch=…`, `#login?steam=…`, `#welcome?…`, `#admin?…`) and `?reset_token=` / the Twitch `?error=&state=` return are handled by their handlers exactly as before; afterwards the address shows the tab the flow ended on (`/#profile`, `/#leaderboards`).
- **In-page jumps:** the Streamers overview in How to Play uses buttons that scroll to their section without touching the address; the Back/Forward handler ignores any hash that isn't a tab link.
- **Frontend only:** no server route, no setting. Link previews are the same for every tab, because the hash isn't sent to the server.

## Implementation

| Piece | Where | What |
|---|---|---|
| `_TAB_LINKS`, `_HTP_SUBTABS` | `frontend/app-globals.js` (after `switchTab`) | Tab id → readable name; the four How to Play subtabs |
| `tabLink(name[, subtab])` | `app-globals.js` | `#<readable name>[/<subtab>]`, or `""` for an unknown id |
| `tabFromLink(hash)` | `app-globals.js` | `{ tab, subtab }` or `null` (empty, unknown, or containing `?`); case-insensitive, readable names and internal ids |
| `switchTab(name, opts)` | `app-globals.js` | Unchanged for one-argument callers; writes the address through `_writeTabAddress` with `opts.history` = `"replace"` (default), `"push"` or `"none"`; clears the notice when the tab changes |
| `openTab(name)` | `app-globals.js` | `switchTab(name, { history: "push" })`, used by every click in the markup and by the tour's start |
| `_tabLinkRouting` | `app-globals.js` | `true` until `init()` has routed: `switchTab` writes no address meanwhile, so `applyAuthState()`'s `switchTab("leaderboard")` and the return handlers see the address untouched |
| `_setPendingTab`, `_takePendingTab`, `_dropPendingTab` | `app-globals.js` | The login-only tab a link asked for (sessionStorage, module variable when storage is blocked); only `team` and `profile` are honoured |
| `init()` | `frontend/app-init.js` | Captures `location.hash` / `location.search` first, then (after the return handlers) calls `_routeInitialLink(startHash, startSearch)` |
| `_routeInitialLink`, `_openLinkedTab`, `_tabLinkAvailable` | `app-init.js` | Decide the tab: Finals / Team Finder by `btn.hidden`, My Team / Profile by `activeUserId`, Admin by `activeUserId && activeIsAdmin` (never `switchTab("admin")` otherwise); write the final address with `replaceState` |
| `popstate` listener | `app-init.js` | Empty hash → Leaderboards; a tab link → `switchTab(tab, { history: "none" })` (a login-only tab while logged out falls back to Leaderboards); anything else is ignored |
| `setHowToPlaySubtab`, `htpSubtabOnStart`, `htpSubtabChanged`, `scrollToHtpSection` | `app-init.js` | Bridge to Alpine's `howToPlayTab` (`x-init` and `@htp-subtab.window` on `#tab-howtoplay`) and the Streamers overview buttons; see [How to Play Tab](how-to-play-tab.md) |
| `_switchAfterLogin()` | `frontend/app-auth.js` | Shared by `login()`, `register()` and `submitSteamSignup()`: Profile when the password must change, else the pending tab, else My Team |
| `handleTwitchReturn()` | `frontend/app-profile.js` | Handles only `#profile?…`; a plain `#profile` is a tab link |
| `#tabLinkNotice` | `frontend/index.html`, top of `#tab-leaderboard` | `role="status"`, written with `setStatus` |

Tests: `backend/tests/test_issue_245_linkable_tabs.py` (Node harness over the real `switchTab`, routing, `init()`, login and return handlers, with an emulated Alpine component built from the `x-init` and event attributes in `index.html`).
