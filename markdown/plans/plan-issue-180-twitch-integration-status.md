# Plan: Twitch Integration Status

## Context
On the test environment the Twitch extension (v1.2.1 installed on the channel) does not work although the environment variables are set, and nothing says why. Today every failure on the way from the Twitch iframe to the backend ends in the same place: the panel waits 8 seconds and shows "not available on this channel right now". That one message covers at least six different causes, and none of them is visible to the operator:

- **Origin not packaged:** the configured backend URL's origin is not among the origins baked into that extension version by `package.sh --ebs-origin` (issue #164), so `_ebsUrlAllowed()` refuses it and nothing is called.
- **No backend URL:** the global configuration segment has no `ebs_url`.
- **Backend unreachable:** the browser can't reach the backend, because of DNS or TLS, the host is not in the console's URL Fetching Domains, or CORS refuses it (`TWITCH_EXTENSION_CLIENT_ID` missing or different from the installed extension's id).
- **Token refused:** the backend refuses the Twitch token because `TWITCH_EXTENSION_SECRET` is wrong or belongs to another extension (401 on every call).
- **Server error:** the backend answers 5xx, for example when `TWITCH_EXTENSION_SECRET` is empty.
- **MVPs refused:** the channel isn't approved and `ENV=production` is set (#165 / #175), so MVP selection is refused while the panel works.

This plan makes each of these visible:
- a reason code in the panel;
- a **Connection check** on the extension's configuration page for the broadcaster;
- a **Twitch status** checklist in the admin portal built from the server's own configuration and the panel traffic it has seen;
- a troubleshooting table that maps each code to its fix.

It also stamps the packaged origins and version into the package, so the operator can see which backend a given extension version may call.

Assumptions:
- The issue's two screenshots could not be opened from the planning environment, so the plan targets every failure path above rather than one observed error. Once the status checklist exists, the test environment's actual cause should be identifiable and fixed by configuration. If it turns out to be a code bug, it gets its own fix in the same PR.
- Nothing here reads the Twitch developer console (there is no API for URL Fetching Domains or the installed version's files). The checklist lists those as manual checks, with the value they must hold.
- New text stays league-agnostic: no league or product name in new messages (the existing "Kana Cards" strings in the extension are out of scope).
- No new tables or columns; the traffic counters are in memory and reset on restart, like the login lockout stores.

Resolves GitHub issue #180.

## User Stories

### See Why the Panel Is Not Available
**User story**
As a viewer or broadcaster, I want the panel to say which step failed when it can't load so that the person running the stream can tell the league what is wrong.

**Acceptance criteria**
- When the panel, the MVP tool (`live_config.html`) or the configuration page can't load, the message ends with a short reason code: `E-ORIGIN` (configured backend origin not in this package), `E-CONFIG` (no backend URL in the configuration after 8 seconds), `E-REACH` (the backend could not be reached: network, TLS or CORS), `E-TOKEN` (backend answered 401 to the Twitch token), `E-SERVER` (backend answered 5xx)
- `E-ORIGIN` is shown at once instead of after the 8-second timeout
- The browser console logs the same code with the configured origin (never the token)
- Viewers see only the generic message and the code; no URL, id or setting name

### Connection Check for the Broadcaster
**User story**
As a broadcaster installing the extension, I want the extension's configuration page to check the connection step by step so that I can see which part of the setup is missing.

**Acceptance criteria**
- The configuration page has a **Connection check** list with one row per step, each marked OK, Failed or Not checked:
  - **Package:** the extension version and the backend origins packaged into it
  - **Backend address:** the configured `ebs_url`, and whether its origin is one of the packaged ones
  - **Backend reachable:** `GET /twitch/ping` answers
  - **Twitch token accepted:** `GET /twitch/check` answers 200
  - **MVP selection:** whether this channel may set MVPs (`approved`, `pending` or `rejected`)
- A step that can't run because an earlier one failed shows Not checked
- A **Check again** button reruns the list
- The page shows the same reason code as the panel for the first failed step

### Twitch Status in the Admin Portal
**User story**
As an admin, I want one Twitch status checklist in the admin portal so that I can see which server setting or traffic signal explains a broken extension without reading server logs.

**Acceptance criteria**
- The admin panel has a **Twitch status** section above Approved streamers, with a **Refresh** button, loading `GET /admin/twitch/status` (admin only; non-admins get 403)
- Each row has a state (OK, Warning, Problem), a label and one sentence saying what to do. The server rows are:
  - `TWITCH_EXTENSION_CLIENT_ID` set, with the extension origin CORS allows (`https://{id}.ext-twitch.tv`)
  - `TWITCH_EXTENSION_SECRET` set and decodes as base64 (the value and its length are never returned)
  - `TWITCH_EXTENSION_VERSION` set (Warning when empty: chat announcements are skipped)
  - `TWITCH_LOCAL_DEV` off
  - MVP channels: number from `TWITCH_MVP_CHANNEL_IDS`, number approved in the portal and number waiting (Problem when all are zero and `ENV=production`)
  - Connect Twitch: the three `TWITCH_OAUTH_*` set, and the `cryptography` package importable (Problem when OAuth is set but `cryptography` is missing)
  - `APP_BASE_URL` set
  - `STEAM_API_KEY` set (Warning when empty: live games are not listed before their stats arrive)
- Traffic rows since the last restart:
  - time of the last panel request with an accepted Twitch token
  - number of refused tokens by kind (expired, invalid, server not configured) and time of the last one
  - up to five most recent cross-origin hosts refused on `/twitch/*` (host only)
- A **Twitch console** block lists the checks only the console can show, each with the value it must hold: the URL Fetching Domains contains the backend origin; the global configuration's `ebs_url` is the backend URL; the installed version was packaged with this backend's origin
- Nothing in the response contains a secret, a token, or a viewer's Twitch id

### Know What a Package Can Call
**User story**
As the operator, I want each extension package to record which backend origins and version it was built for so that I can tell whether the version installed on a channel can reach this server.

**Acceptance criteria**
- `package.sh` writes the version and the packaged origins into the staged `ebs-origins.js` (`EXT_BUILD = {version, origins}`) alongside `EBS_ALLOWED_ORIGINS`
- `package.sh` prints the same at the end of the build
- The repository copy of `ebs-origins.js` has `EXT_BUILD = {version: "dev", origins: []}`
- The configuration page's **Package** row shows these values

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/twitch.py` | `GET /twitch/ping` (no token), `GET /twitch/check` (Twitch JWT); in-memory traffic counters recorded in `verify_twitch_jwt` |
| `backend/twitch_status.py` | New: builds the status checklist from env, the approvals table and the counters |
| `backend/routers/admin_twitch.py` | `GET /admin/twitch/status` |
| `backend/main.py` | Record refused cross-origin hosts on `/twitch/*` (host only, last five) |
| `twitch-extension/extension.js` | Reason codes; immediate `E-ORIGIN`; shared `ext.failReason` |
| `twitch-extension/panel.js`, `live_config.js` | Show the reason code in the "not available" messages |
| `twitch-extension/config.html`, `config.js` | Connection check list and Check again |
| `twitch-extension/package.sh`, `ebs-origins.js` | `EXT_BUILD` stamp |
| `frontend/index.html`, `frontend/app-admin-users.js` | Twitch status section |
| `markdown/features/core/twitch-extension.md`, `markdown/ui_description/admin.md`, `markdown/features/reference/twitch-integration-status.md` | Troubleshooting table, admin UI, feature doc |
| `backend/tests/test_issue_180_twitch_integration_status.py` | Tests |

### Step 1 — Ping, check and traffic counters (`twitch.py`)
- `GET /twitch/ping`: no token, no database; returns `{"ok": true}`. Rate limit per IP (`RATE_LIMIT_TWITCH_JOIN_IP`'s limit). CORS applies as for every `/twitch/*` route, so a success from the extension iframe proves the origin is allowed.
- `GET /twitch/check`: `Depends(verify_twitch_jwt)`. Returns `{"ok": true, "role": …}`, plus `mvp_allowed` and `approval` for `role: broadcaster` (the same values `GET /twitch/matches/current` returns; it does not record a request).
- Counters in `verify_twitch_jwt`:
  - `last_ok_at` on success;
  - `failures[kind]` and `last_failure_at` for `expired`, `invalid` and `not_configured`;
  - process-local, guarded by a lock.

### Step 2 — Refused origins (`main.py`)
A small middleware before CORS: for paths under `/twitch/`, when an `Origin` header is present and is not the extension origin nor in `CORS_EXTRA_ORIGINS`, record its host (cleaned with `clean_display_text`, at most 100 characters) in a deque of five. It never blocks; CORS keeps doing that.

### Step 3 — Status checklist (`twitch_status.py`, `GET /admin/twitch/status`)
```python
{"checks": [{"key": "extension_client_id", "state": "ok" | "warning" | "problem",
             "label": "...", "detail": "..."}, ...],
 "traffic": {"last_ok_at": int | None, "failures": {"expired": n, "invalid": n, "not_configured": n},
             "last_failure_at": int | None, "refused_origins": ["host", ...]},
 "console": [{"label": "...", "expected": "..."}, ...]}
```
Secret check: base64-decode only, never return the value or its length. `cryptography` check: `importlib.util.find_spec("cryptography")`. `expected` values are built from `APP_BASE_URL` (the backend origin) when it is set. Admin only (`require_admin`); no reauth, since it is read-only and holds no secrets.

### Step 4 — Reason codes in the extension (`extension.js`, `panel.js`, `live_config.js`)
- `_onCfgChanged`: when the configured URL is refused, set `ext.failReason = "E-ORIGIN"` and call `onConfigTimeout()` at once.
- The 8-second timeout without config sets `E-CONFIG`.
- `_parseResponse` and the fetch helpers set:
  - `E-TOKEN` on 401;
  - `E-SERVER` on 5xx;
  - `E-REACH` when `fetch` rejects (network, TLS or CORS: the browser does not say which).
- The "not available" messages append " (code: {failReason})" when set.
- `console.warn("[ext] " + code + " …")` with the configured origin only.

### Step 5 — Connection check (`config.html`, `config.js`)
Run the five steps in order on `onReady`, or on `onConfigTimeout` with the later steps Not checked. Use `textContent` for every value. The **Check again** button reruns the steps. The panel and MVP tool show only the code; the configuration page (seen by the broadcaster) shows the origins and the URL.

### Step 6 — Package stamp (`package.sh`, `ebs-origins.js`)
Write `var EXT_BUILD = {version: "<version>", origins: [...]};` into the staged `ebs-origins.js`, and print it at the end of the build. The repository copy gets the `dev` value.

### Step 7 — Admin UI and docs
- **Twitch status** section in the admin Users area above Approved streamers. It loads with the approved-streamers lists and has a Refresh button. Rows are coloured by state. Every value is escaped with `_escHtml`. Times are relative ("3 min ago").
- `core/twitch-extension.md`: a "Panel reason codes" troubleshooting table (code → likely cause → fix), which also replaces the stale "Kana Cards is not available" wording.
- `ui_description/admin.md`: the new section.
- The feature doc.

## Verification
- `cd backend && python -m pytest tests/test_issue_180_twitch_integration_status.py tests/test_issue_175_approved_streamers_admin.py tests/test_issue_163_twitch_steam_account_hardening.py`
- **Backend tests:**
  - `/twitch/ping` needs no token.
  - `/twitch/check` returns 401 for a bad token and records an `invalid` failure; with a good token it records `last_ok_at` and returns `approval` for broadcasters only.
  - `/admin/twitch/status` returns 403 for non-admins.
  - The status response never contains the secret, its length or a token.
  - Each check's state follows its env var (empty secret → problem; production with no channels → problem; OAuth set with `cryptography` missing → problem).
  - Refused origins keep at most five hosts.
- **Static tests:**
  - `extension.js` defines the five codes and calls `onConfigTimeout` when the origin is refused.
  - `package.sh` writes `EXT_BUILD`.
  - The repository `ebs-origins.js` has the `dev` stamp.
- **Manual, on the test environment:**
  - Open Admin › Twitch status and fix every Problem row.
  - Open the extension's configuration page on the test channel and read the Connection check.
  - If the Package row doesn't list the test origin, build a new version with `package.sh <version> --ebs-origin <test origin>`, upload it to Twitch and install it.
  - Confirm the panel loads and an MVP can be set on an approved channel.
