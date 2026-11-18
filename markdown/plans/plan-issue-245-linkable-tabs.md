# Plan: Linkable Tabs

## Context
Issue #245: "Currently there is no way to directly link to a particular tab. This would allow to better advertise features like the 'finals' tab." The site is one page (`frontend/index.html`); `switchTab(name)` in `frontend/app-globals.js` shows a tab without touching the address bar, and every visit opens on Leaderboards. A link shared in Discord or on stream can only point at the front page.

This plan gives every main tab its own address, `https://<site>/#<tab>`, which opens that tab directly, and keeps the address bar in step as people move between tabs, so copying it always gives a working link.

**Decisions** (change them in review if needed):
- **Hash links, not paths.** `/#finals` needs no server change: the hash never reaches the server, and the single page reads it on load. Paths such as `/finals` would need a server fallback for every tab. The site already uses the hash for the Steam and Twitch sign-in returns (`#profile?twitch=…`, `#login?steam=…`, read by `handleTwitchReturn` and `handleSteamReturn` in `app-profile.js` and `app-auth.js`); those carry a `?` and keep being handled first.
- **Readable names.** The link uses the tab's label, not its internal id: `#my-team`, `#leaderboards`, `#history`, `#players`, `#teams`, `#schedule`, `#finals`, `#team-finder`, `#how-to-play`, `#profile`, `#admin`. The internal ids (`#team`, `#leaderboard`, `#teamfinder`, `#howtoplay`) also work, so a link typed either way opens.
- **How to Play subtabs** get links too, `#how-to-play/streamers` and so on, so a feature can be advertised down to its section (the OBS overlay builder lives in Streamers). Admin subtabs and other in-tab state (a schedule week, a player popup) are not part of this issue.
- **Back and Forward move between tabs.** A tab chosen by a click adds a history entry; Back returns to the previous tab. Opening the page with a link, or a redirect such as the Steam return, replaces the entry instead of adding one.
- **Tabs that aren't open:** Finals and Team Finder are hidden until `/config` says they're open. A link to one of them while it is hidden opens Leaderboards with a short notice ("The Finals tab isn't open yet."). A link to My Team or Profile while logged out opens the login dialog and goes to that tab after login. A link to Admin for anyone but an admin opens Leaderboards with no notice, so the link says nothing about admin pages. An unknown name opens Leaderboards.
- **No server change** and no new setting. Link previews (Discord, social media) stay the same for every tab, because the hash isn't sent to the server; per-tab previews would need server-side paths and are not part of this issue.

Resolves GitHub issue #245.

## User Stories

### Open a Tab From a Link
**User story**
As a player, I want a link to a tab to open that tab, so that when the league posts "the finals predictions are open" the link takes me straight there.

**Acceptance criteria**
- **Every main tab has a link:** `/#my-team`, `/#leaderboards`, `/#history`, `/#players`, `/#teams`, `/#schedule`, `/#finals`, `/#team-finder`, `/#how-to-play`, `/#profile` and `/#admin` each open that tab on page load, with the tab's data loaded as when it is clicked.
- **Old names:** `/#team`, `/#leaderboard`, `/#teamfinder` and `/#howtoplay` open the same tabs; names are matched without regard to case.
- **Subtabs:** `/#how-to-play/users`, `/players`, `/streamers` and `/developers` open How to Play on that subtab.
- **No link:** the page opens on Leaderboards, as today.
- **Unknown name** (`/#nonsense`): the page opens on Leaderboards with no error.

### Copy the Address of the Tab I'm On
**User story**
As the league admin, I want the address bar to show the tab I'm on, so that I can copy it and share it without knowing a special format.

**Acceptance criteria**
- Switching tab by a click, a link inside the site or a button sets the address to that tab's link (`/#schedule`), with the readable name; switching How to Play's subtab sets `/#how-to-play/<subtab>`.
- A click adds a history entry, so Back returns to the previous tab and Forward goes back again; the tab's scroll position is restored as it is today.
- Opening the page from a link does not add an extra history entry (one Back leaves the site, as before).
- Nothing else in the address changes: the path and any query string are kept.

### Links to Tabs That Aren't Available
**User story**
As a visitor, I want a link to a tab I can't see yet to land somewhere sensible, so that an early or private link never shows a broken page.

**Acceptance criteria**
- **Hidden tab:** `/#finals` while the Finals tab is hidden (`finals_available` is false in `/config`) opens Leaderboards and shows "The Finals tab isn't open yet."; `/#team-finder` while Team Finder is closed shows "Team Finder isn't open right now." The address is changed to `/#leaderboards`.
- **Needs a login:** `/#my-team` or `/#profile` while logged out opens the login dialog; after logging in the page opens that tab. Closing the dialog leaves the page on Leaderboards.
- **Admin:** `/#admin` for a visitor or a player who isn't an admin opens Leaderboards with no notice and no admin request.
- The decision waits for `/config` and the login check that `init()` already makes, so an available tab is never refused because the page hadn't loaded yet.

### Sign-in Returns Keep Working
**User story**
As a player connecting Steam or Twitch, I want the sign-in return to keep working, so that tab links don't break the flows that already use the address.

**Acceptance criteria**
- `#profile?twitch=<key>`, `#login?steam=<key>` and the other Steam returns (`#welcome?…`, `#admin?…`) are handled exactly as today, and tab routing ignores any hash containing `?`.
- `?reset_token=…` (password reset) and the Twitch `?error=…&state=…` return are handled as today.
- After one of those flows the address bar shows the tab it ended on, in the readable form.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `frontend/app-globals.js` | A name map (readable name and old id → tab id), `tabLink(name)`, `tabFromLink(hash)`, `openTab(name)` (push), and `switchTab(name, opts)` updating the address (replace by default, nothing until init's routing finished) |
| `frontend/app-init.js` | After `init()`'s config and login checks: read the hash, decide the tab (open, hidden, needs login, admin), and listen for `popstate` |
| `frontend/app-auth.js` | After a successful login, go to the tab a link asked for |
| `frontend/index.html`, the How to Play module | Subtab switching updates the address; a subtab from the link is selected on load |
| `backend/tests/test_issue_245_linkable_tabs.py` | Tests (Node harness over the tab and routing functions) |
| `markdown/features/reference/linkable-tabs.md`, `markdown/ui_description/` | Docs |

No migration, no endpoint and no new setting.

### Step 1 — Names and the address
In `app-globals.js`, one table of the tabs: readable name, tab id, the old id as an alias (placed after `switchTab`, so the first line containing `"howtoplay"` stays the loader line older tests read). `switchTab(name, { history: "push" | "replace" | "none" })` keeps its current behaviour and, unless `"none"`, writes `#<readable name>` with `history.pushState` or `replaceState`, keeping `location.pathname` and `location.search`; the default is `"replace"`, so the existing one-argument code callers (`switchTab("team")` etc., pinned by older tests) are unchanged. Clicks go through a wrapper `openTab(name)` that pushes: the tab bar buttons, the header username button, the "How scoring works" link and the tour's start from How to Play. Clicking the active tab adds no entry. Every use of `history` / `location` is guarded, because older Node harnesses run `switchTab` without them. Keep the existing `switchTab(name)` signature working for every caller: grep `frontend/` for `switchTab(` and `backend/tests` for harnesses that stub it (lessons-learned 2026-10-31).

### Step 2 — Opening the page from a link
Capture `location.hash` and `location.search` at the very start of `init()` in `app-init.js`, before `applyAuthState()` and the return handlers. Until routing has finished, `switchTab` writes nothing to the address (a module flag), so `applyAuthState()`'s `switchTab("leaderboard")` cannot overwrite a Steam return before `handleSteamReturn` reads it. After `loadConfig()`, `loadMe()`, `applyAuthState()` and the existing return handlers: if the captured hash has no `?` and names a tab, decide as in the stories. Use the same flags the tab bar uses (`btn.hidden` for Finals and Team Finder, which admins always see; `activeUserId` for My Team and Profile; `activeUserId && activeIsAdmin` for Admin), decided before calling `switchTab`, so a link can never open a tab its button doesn't show and `switchTab("admin")` is never called for a non-admin. Then write the current tab's link with `replaceState` when the page came with a hash or a return changed the address; a bare `/` load keeps its address. The fallback notice is a `role="status"` element at the top of `#tab-leaderboard`, written with `setStatus` and cleared on the next tab switch.

`handleTwitchReturn` (`app-profile.js`) handles only `#profile?…`; a plain `#profile` is left to the tab routing (today it strips any hash starting `#profile`). The pending tab for the login case is kept in `sessionStorage` (every access in try/catch, a module variable as fallback), so it survives the Steam sign-in redirect; `login()`, `register()` and `submitSteamSignup()` go to it after success instead of My Team and clear it. Closing the login dialog drops it.

### Step 3 — Back and Forward
A `popstate` listener reads the hash and calls `switchTab(name, { history: "none" })`, with the same availability checks; an empty hash shows Leaderboards and any hash that is not a tab link is ignored. The Streamers overview links in How to Play (`href="#htp-streamers-…"`) become buttons that scroll to their section without changing the hash. `_tabScroll` already restores each tab's scroll position.

### Step 4 — How to Play subtabs
The How to Play subtab buttons set Alpine's `howToPlayTab`. Write `#how-to-play/<subtab>` when it changes (replace, not push, so Back leaves How to Play in one step), and set it from the link on load. Alpine loads with `defer`, so the subtab is set from Alpine's side: `x-init` reads the subtab the routing chose and watches for changes, and a window event carries a later choice (`@htp-subtab.window`). An unknown subtab opens Users with the address `#how-to-play`. Check `test_how_to_play_role_subtabs.py` and the other How to Play tests before editing.

### Step 5 — Tests
- Name map: every tab button in `index.html` has exactly one readable name; old ids and any letter case resolve; unknown names resolve to nothing.
- Routing (Node harness with stubbed `history`, `location` and `switchTab`): each link opens its tab; hidden Finals and closed Team Finder fall back with their notice and rewrite the address; logged-out My Team and Profile open the login and continue after it; Admin falls back silently for a non-admin; a hash with `?` is left to the sign-in handlers.
- History: a click pushes, code replaces, opening from a link replaces; popstate switches without pushing.
- Existing flows: the Steam, Twitch and password-reset tests still pass.

## Verification
- Open `/#finals`, `/#schedule`, `/#how-to-play/streamers` in a fresh browser tab: each opens there.
- Click through four tabs, then Back four times: each step returns to the previous tab with its scroll position, and the fifth Back leaves the site.
- Logged out, open `/#my-team`: the login dialog opens; after logging in, My Team shows.
- With finals not available, `/#finals` shows the notice on Leaderboards.
- Connect Twitch on Profile and complete the Steam sign-in: both returns work as before.
