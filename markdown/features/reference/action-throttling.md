# Action Throttling

Per-user limits on every player action, a request body size cap, clear 429 responses, and a layered checklist for running the app behind a proxy. Resolves GitHub issue #184. Extends [Rate Limiting](rate-limiting.md).

---

## Card actions

`POST /draw`, `POST /draw/booster/{team_id}` and `POST /roster/{card_id}/reroll` share one per-user budget (`RATE_LIMIT_CARD_ACTION`, keyed by `key_by_user_or_ip`) and one per-IP budget (`RATE_LIMIT_CARD_ACTION_IP`). Both use slowapi's `shared_limit` (scopes `card_action` and `card_action_ip`, defined once in `backend/routers/cards.py`), so mixing draws, booster draws and rerolls counts against the same budget.

The routes are thin wrappers (`draw_card_route`, `draw_booster_route`, `reroll_modifiers_route`) that take `request: Request` and call the plain `draw_card(db, current_user)`, `draw_booster(team_id, db, current_user)` and `reroll_modifiers(card_id, db, current_user)`, which tests and other code still call directly. FastAPI resolves `get_current_user` first (it sets `request.state.session_user_id`, the per-user key), then slowapi checks the limits, then the handler runs. A refused request never reaches `spend_tokens`, so it spends no tokens and creates no card.

## Other player actions

`RATE_LIMIT_USER_ACTION` (per user, each route counted on its own) covers:
- `PUT /profile/username`, `PUT /profile/password` (`PUT /profile/player-id` was removed in #209)
- `POST /weekly-summary/{week_id}/reveal`, `POST /weekly-summary/reveal-all`, `POST /weekly-summary/seen`, `POST /weekly-summary/prompted`
- `POST /claim-events`, `POST /notifications/{notification_id}/dismiss`
- `DELETE /sessions/{session_id}`, `POST /logout-everywhere`
- `POST /twitch/merge/confirm`, `POST /twitch/disconnect`, `POST /profile/steam/unlink`

`POST /simulate/{match_id}` (public, scores a whole match per call) has a per-IP limit, `RATE_LIMIT_SIMULATE`. `POST /twitch/mvp` has the panel's per-IP limit, `RATE_LIMIT_TWITCH_JOIN_IP` (route wrapper `set_mvp_route`; `set_mvp(body, payload, db)` is unchanged).

Admin routes stay on the global baseline: they need admin rights, and destructive ones need a recent re-auth.

### Route coverage test

`backend/tests/test_issue_184_action_throttling.py::TestEveryPlayerActionHasALimit::test_every_non_admin_write_route_has_explicit_limit` walks every `APIRoute` in the app and fails when a `POST`/`PUT`/`PATCH`/`DELETE` route has no route-level slowapi limit, unless it is an admin route (path under `/admin`, or `require_admin` anywhere in its dependencies) or in the commented `ALLOWED_GLOBAL_ONLY` allowlist:
- `POST /logout`: needs no login and deletes at most one session row; a limit could keep a player signed in.
- `main.py`'s catch-alls for unknown `/twitch/*` and `/auth/steam/*` paths: they only answer 404.

A new player write route therefore needs a limit (or a reasoned allowlist entry) before the suite passes.

## Request size cap

`BodySizeLimitMiddleware` in `backend/main.py` is a pure-ASGI middleware, added last so it is the outermost app middleware and runs before sessions, CSRF checks and routing:
- A `POST`/`PUT`/`PATCH`/`DELETE` whose `Content-Length` is above `MAX_REQUEST_BODY_BYTES` gets 413 `{"detail": "Request too large"}` at once.
- A body without `Content-Length` (chunked) is read up to the cap: past it, 413; otherwise the buffered body is replayed to the app. At most the cap is held in memory.
- `GET`, `HEAD` and `OPTIONS` pass through untouched.

The cap is read once at import (`_read_max_request_body_bytes`); a missing, non-numeric or non-positive value means 65536. The app has no file uploads, and its largest bodies (admin player and week forms, a full bench reorder) are well under 64 KiB.

## 429 responses

Every slowapi refusal, route-level or global, returns:
```json
{"detail": "Too many requests. Wait a moment and try again."}
```
with `Retry-After` set to the limit's window in seconds (`60` for a `/minute` limit, `3600` for `/hour`).

The website shows `detail` in the action's existing status area: draws and booster draws through `setStatus("deckStatus", ...)`, rerolls in `#rerollStatus`, roster changes in `#rosterStatus` (all `textContent`). Since #186 roster changes are saved by the autosave's `PUT /roster`: its errors go through `_setRosterStatus` (`textContent`). A 429 is waited out and retried once while the status still says "Saving…"; a second refusal shows "Couldn't save." with the server's `detail` and a Retry button. The Twitch panel keeps its own neutral message.

Each refusal logs one INFO line from `main`:
```
Rate limited: POST /roster/{card_id}/reroll (user)
```
with the method, the route template (never the raw path) and the key kind (`user`, `ip` or `twitch`). It never names the IP or the user id. A key and route pair is logged at most once a minute; the key is held only as a SHA-256 hash. slowapi's own "ratelimit ... exceeded" warning names the key, so a logging filter on the `slowapi` logger drops it.

## Layered protection

The app limits what reaches it. Floods must be stopped earlier: at a CDN or WAF, if used, and at the reverse proxy (per-IP rates, connection limits, body size, timeouts). The checklist, with nginx and Caddy snippets and what the app can't do, is in [Rate Limiting › Layered protection](rate-limiting.md#layered-protection).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_CARD_ACTION` | `20/minute` | Per-user budget shared by draws, booster draws and rerolls |
| `RATE_LIMIT_CARD_ACTION_IP` | `60/minute` | Per-IP budget shared by the same routes |
| `RATE_LIMIT_USER_ACTION` | `60/minute` | Per-user limit on each other player write route |
| `RATE_LIMIT_SIMULATE` | `20/minute` | Per-IP limit on `POST /simulate/{match_id}` |
| `MAX_REQUEST_BODY_BYTES` | `65536` | Largest accepted request body; larger gets 413 |

The four limits are defined in `backend/rate_limit.py`, the cap in `backend/main.py`. All are read at startup; changing them needs a restart.
