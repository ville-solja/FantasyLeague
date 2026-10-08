# Twitch Integration Status

This feature shows why the Twitch extension isn't working. The panel shows a reason code, the extension's configuration page runs a step-by-step connection check for the broadcaster, and an admin Twitch status checklist lists server settings and the panel traffic the server has seen (issue #180). Plan: `markdown/plans/plan-issue-180-twitch-integration-status.md`.

---

## Panel reason codes *(planned)*

| Code | Meaning | Usual fix |
|---|---|---|
| `E-ORIGIN` | The configured backend origin is not packaged in this extension version | Build a version with `package.sh <version> --ebs-origin <origin>`, upload it and install it |
| `E-CONFIG` | No `ebs_url` in the global configuration after 8 seconds | Run `set-ebs-url.sh` with the backend URL |
| `E-REACH` | The backend could not be reached: network, TLS or CORS | Check the URL Fetching Domains in the Twitch console and `TWITCH_EXTENSION_CLIENT_ID`; check the backend is up over HTTPS |
| `E-TOKEN` | The backend answered 401 to the Twitch token | `TWITCH_EXTENSION_SECRET` must be this extension's secret |
| `E-SERVER` | The backend answered 5xx | Check the server log; `TWITCH_EXTENSION_SECRET` may be empty |

Viewers see only the code. The configuration page shows the URL and the packaged origins.

## Connection check *(planned)*

The extension's configuration page checks these steps in order:
1. **Package:** the version and the origins stamped into it (`EXT_BUILD`).
2. **Backend address:** the configured `ebs_url`.
3. **Backend reachable:** `GET /twitch/ping`.
4. **Twitch token accepted:** `GET /twitch/check`.
5. **MVP selection:** whether the channel is approved.

## Endpoints

### `GET /twitch/ping` *(planned)*
No token. Returns `{"ok": true}`. Proves the backend is reachable from the extension iframe and that CORS allows it.

### `GET /twitch/check` *(planned)*
Twitch JWT. Returns `{"ok": true, "role": …}`, plus `mvp_allowed` and `approval` for broadcasters.

### `GET /admin/twitch/status` *(planned)*
Admin only. Returns three groups; never a secret, its length, a token or a viewer's Twitch id:
- `checks`: one row per server setting, with a state (`ok`, `warning`, `problem`), a label and what to do;
- `traffic` since the last restart: the last accepted token, refused tokens by kind, and refused cross-origin hosts;
- `console`: the Twitch console checks, with the value each must hold.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
