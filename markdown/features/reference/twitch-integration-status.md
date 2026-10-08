# Twitch Integration Status

This feature shows why the Twitch extension isn't working. The panel shows a reason code, the extension's configuration page runs a step-by-step connection check for the broadcaster, and an admin Twitch status checklist lists server settings and the panel traffic the server has seen (issue #180). Plan: `markdown/plans/plan-issue-180-twitch-integration-status.md`.

---

## Panel reason codes

`twitch-extension/extension.js` defines the codes (`EXT_REASON`) and keeps the last one in `ext.failReason`:

| Code | Set when | Usual fix |
|---|---|---|
| `E-ORIGIN` | The configured `ebs_url`'s origin is not in this package's `EBS_ALLOWED_ORIGINS`. Set in `_onCfgChanged`, which calls `onConfigTimeout()` at once instead of after 8 seconds | Build a version with `package.sh <version> --ebs-origin <origin>`, upload it and install it |
| `E-CONFIG` | No `ebs_url` in the global configuration after 8 seconds | Run `set-ebs-url.sh` with the backend URL |
| `E-REACH` | `fetch` rejected: DNS, TLS, a missing URL Fetching Domain or a CORS refusal (the browser does not say which) | Check the URL Fetching Domains in the Twitch console and `TWITCH_EXTENSION_CLIENT_ID`; check the backend is up over HTTPS |
| `E-TOKEN` | The backend answered 401 to the Twitch token: wrong secret, or an expired token | `TWITCH_EXTENSION_SECRET` must be this extension's secret; an expired token clears on reload |
| `E-SERVER` | The backend answered 5xx | Check the server log; `TWITCH_EXTENSION_SECRET` may be empty or not base64, or `TWITCH_LOCAL_DEV=true` is set with `ENV=production` |

- Each code is logged once as `console.warn("[ext] E-… backend origin: <origin>")`, with the configured origin only (never the token or a path).
- The "not available" / "unavailable right now" messages in `panel.js` and the MVP tool (`live_config.js`) end with ` (code: E-…)` (`failReasonSuffix()`). Viewers see only the generic text and the code: no URL, id or setting name.
- The configuration page (broadcaster only) shows the URL and the packaged origins.

## Connection check

The extension's configuration page (`config.html`, `config.js`) checks these steps in order, on `onReady` or on `onConfigTimeout`, and again on **Check again**. Each row is **OK**, **Failed** or **Not checked**:

1. **Package:** the version and origins stamped into it (`EXT_BUILD`). Failed when the package has no stamp (built before #180); the other steps still run.
2. **Backend address:** the configured `ebs_url`, and whether its origin is packaged. Failed with `E-CONFIG` (none) or `E-ORIGIN` (not packaged).
3. **Backend reachable:** `GET /twitch/ping` without a token. Failed with `E-REACH` or `E-SERVER`.
4. **Twitch token accepted:** `GET /twitch/check`. Failed with `E-TOKEN`, `E-SERVER` or `E-REACH`.
5. **MVP selection:** `approved` (OK), `pending` or `rejected` (Failed), from the check's answer; Not checked for a role other than broadcaster.

A step after a failed one shows Not checked. Backend address stays Not checked ("Waiting for the extension configuration…") until the configuration arrives or the 8-second timeout. Backend reachable reports `E-REACH` for any other non-OK answer below 500 (for example a 404 from a backend older than #180, or a 429 from the ping limit). Twitch token accepted fails without a code on other statuses such as 403 or 429. Below the list the page shows `Reason code: E-…` for the first failed step that has a code. Every value is set with `textContent`.

## Package stamp

`package.sh` writes `var EXT_BUILD = {version: "<version>", origins: [...]};` into the staged `ebs-origins.js`, after `EBS_ALLOWED_ORIGINS`, and prints the same line at the end of the build. The version may contain only letters, digits, dots, `+` and `-`. The repository copy holds `var EXT_BUILD = {version: "dev", origins: []};`.

## Endpoints

### `GET /twitch/ping`
No token, no database. Returns `{"ok": true}`. Rate-limited per IP with `RATE_LIMIT_TWITCH_JOIN_IP` (default `60/minute`). `ping()` holds the logic and `ping_route` carries the limit. CORS applies as on every `/twitch/*` route, so an answer read from the extension iframe proves the backend is reachable from it.

### `GET /twitch/check`
Twitch JWT (`verify_twitch_jwt`). No route-specific limit (the global per-IP limit applies). Returns `{"ok": true, "role": …}`, plus `mvp_allowed` and `approval` for `role: broadcaster` (the values `GET /twitch/matches/current` returns, from `twitch.channel_approval`). Unlike that route it records no approval request. `check(payload, db)` holds the logic.

### `GET /admin/twitch/status`
Admin only (`require_admin`; no password re-check, as it is read-only and holds no secrets). Built by `backend/twitch_status.py` (`build_status`). It never returns a secret, its length, a token or a viewer's Twitch id.

```json
{"checks": [{"key": "extension_client_id", "state": "ok", "label": "…", "detail": "…"}, …],
 "traffic": {"last_ok_at": 1760000000, "failures": {"expired": 0, "invalid": 2, "not_configured": 0},
             "last_failure_at": 1760000100, "refused_origins": ["other.example"]},
 "console": [{"label": "…", "expected": "https://league.example"}, …]}
```

`checks`, in order (`state` is `ok`, `warning` or `problem`):

| Key | Ok | Warning | Problem |
|---|---|---|---|
| `extension_client_id` | `TWITCH_EXTENSION_CLIENT_ID` set; the detail names the CORS origin `https://{id}.ext-twitch.tv` | — | Empty |
| `extension_secret` | `TWITCH_EXTENSION_SECRET` decodes as base64 (standard or URL-safe) | — | Empty or not base64 |
| `extension_version` | `TWITCH_EXTENSION_VERSION` set | Empty: chat announcements are skipped | — |
| `local_dev` | `TWITCH_LOCAL_DEV` off | On | On with `ENV=production` |
| `mvp_channels` | Counts from `TWITCH_MVP_CHANNEL_IDS`, portal-approved and waiting channels; ok when any channel may set MVPs, or outside production | Production, none approved, some waiting | Production and all three zero |
| `connect_twitch` | The three `TWITCH_OAUTH_*` set and `cryptography` importable (`importlib.util.find_spec`) | Not all three set (Connect Twitch off) | All set, `cryptography` missing |
| `app_base_url` | `APP_BASE_URL` set | Empty | — |
| `steam_api_key` | `STEAM_API_KEY` set | Empty: live games are not listed before their stats arrive | — |

`traffic` since the last restart, in memory in `twitch.py` behind a lock (`traffic_snapshot()`; `reset_traffic()` for tests):
- `last_ok_at`: the last token `verify_twitch_jwt` accepted (the `TWITCH_LOCAL_DEV` bypass does not count).
- `failures`: refused tokens by kind: `expired`, `invalid`, and `not_configured` (empty secret, or a secret that fails to decode). `last_failure_at`: the time of the last one.
- `refused_origins`: up to five most recent distinct hosts (host and port only, cleaned with `clean_display_text`, at most 100 characters) of cross-origin `/twitch/*` requests whose `Origin` CORS refuses. `RefusedOriginMiddleware` in `twitch_status.py` records them; `main.py` gives it CORS's own allow list (`CORS_EXTRA_ORIGINS` and the extension origin). It ignores same-origin requests (the request's host or `APP_BASE_URL`'s) and never blocks: CORS stays the gate. A literal `Origin: null` is kept as `null`.

Anyone can send a junk token or a made-up `Origin`, so the counters and hosts are hints to read alongside `checks`, not proof of a fault. A token with role `external` (refused with 403) counts neither as accepted nor as a failure; `not_configured` also counts any unexpected decode error. The UI shows `not_configured` as "server not configured".

`console`: the checks only the Twitch developer console can show, with `expected` built from `APP_BASE_URL`:
- URL Fetching Domains contains the backend origin;
- the global configuration's `ebs_url` is the backend URL;
- the installed version was packaged with this backend's origin (`package.sh <version> --ebs-origin <origin>`).

## Admin UI

Admin › Users › **Twitch status**, above Approved streamers. See `markdown/ui_description/admin.md`.

## Troubleshooting

The reason code table for operators is in `markdown/features/core/twitch-extension.md` (Panel reason codes).

