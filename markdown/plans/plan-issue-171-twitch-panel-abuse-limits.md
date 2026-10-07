# Plan: Twitch Panel Abuse Limits

## Context
Issue #171 (items 9 and 10 of the hardening issue #163) collects four low-severity weak spots in the Twitch panel, and asks for a fix-or-accept decision on each.
- **Drop farming:** since #157, every logged-in Twitch account can Join, and each one is an entry in a channel's drop pool. Twitch accounts are free, so alt accounts multiply a viewer's chances.
- **Anonymous heartbeats:** logged-out viewers (`A…` opaque ids) write `twitch_presence` rows, although they can't Join or win.
- **Logo hosts:** team logos load from whatever `https:` host the ingested data names, which shows viewers' IP addresses to that host.
- **CORS:** the origin rule accepts every Twitch extension, not just ours.

**What exists today:**
- **Heartbeat:** `POST /twitch/heartbeat` (`backend/twitch.py`) upserts `twitch_presence` for any opaque id, with only the global per-IP limit.
- **Drop pool:** `_active_pool(db, channel_id)` joins `twitch_presence` with `users` on `twitch_user_id`, keeping presence seen within `_PRESENCE_TTL` (600 s). `_execute_token_drop` picks up to `TWITCH_DROP_MAX` (20) winners and audits `twitch_token_drop` with the count.
- **Join:** `POST /twitch/join` creates a soft account (#157), rate-limited per viewer and per IP.
- **The one-merge limit (#160)** means at most one soft account's tokens ever reach a website account. Alt accounts can't pool their winnings into one account.
- **Logos:**
  - `ingest._match_logo_url` accepts any `http(s)` URL into `teams.logo_url`.
  - The card routes (`routers/cards.py`) return `team_logo_url` straight from `teams.logo_url`, and so does the panel through the shared card functions.
  - `routers/weekly_summary.py::_team_logo_url` prefers the local Dotabuff PNGs under `/assets/dotabuff_league_logos/`, then falls back to `logo_url`.
  - The local copy of the database has no `logo_url` values stored at all.
- **CORS:** `backend/main.py` uses `allow_origin_regex=r"^https://[a-z0-9]+\.ext-twitch\.tv$"`, plus `CORS_EXTRA_ORIGINS`, without credentials. `TWITCH_EXTENSION_CLIENT_ID` is already set wherever the extension runs.

**Decisions** (recommended; flagged for review):
1. **Drop farming: limit it, don't try to prevent it.**
   - **Why the options in the issue don't work:**
     - Requiring the identity share doesn't stop alts, because each alt shares its own Twitch id.
     - Requiring a linked website account would make drops depend on an outside login, which breaks the policy 4.5 compliance from #157.
     - A weekly cap per soft account limits each alt separately.
   - **Why the harm is small:** the one-merge limit already keeps farmed tokens from adding up in a single website account. What's left is that alts take winner slots from real viewers when a pool is larger than 20.
   - **The plan:**
     - A soft account must be at least `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` old (default 24) to be in a pool. That stops alts made during a broadcast to farm that broadcast.
     - Website accounts (code-linked before #160, or connected through Twitch sign-in) are always eligible.
     - Pool sizes are watched: a drop whose pool is more than three times the median of that channel's last ten drops logs a warning and is audited with `pool_spike=true`.
2. **Anonymous heartbeats: fix.** A non-`U` opaque id returns `{"ok": true}` without writing. The route gets the per-viewer limit (`key_by_twitch_viewer_or_ip`, `RATE_LIMIT_TWITCH_ACTION`) plus the existing per-IP limit.
3. **Logo hosts: fix with an allowlist.**
   - **The allowlist:** a `logo_url` is used only when its host is in `LOGO_HOST_ALLOWLIST`. The default is Steam's CDNs, which OpenDota team logos use: `steamcdn-a.akamaihd.net`, `steamusercontent-a.akamaihd.net`, `cdn.steamusercontent.com`, `cdn.cloudflare.steamstatic.com`, `shared.cloudflare.steamstatic.com`.
   - **Where it applies:** in two places, at ingest (an unknown host is not stored) and at output (a stored value on an unknown host becomes `null`, so the client shows the monogram). Rows stored earlier are therefore safe without a data migration.
   - **Order of preference:** the local `/assets/` logo stays first everywhere, as in the Weekly Report.
   - **Not chosen:** proxying images through the backend would add an image proxy for a field the local copy doesn't even use.
4. **CORS: fix.**
   - **With a client id:** when `TWITCH_EXTENSION_CLIENT_ID` is set, the origin rule is exactly `^https://<client id>\.ext-twitch\.tv$`, with the client id regex-escaped.
   - **Without one:** no `ext-twitch.tv` origin is allowed. A warning is logged once at start-up, and `CORS_EXTRA_ORIGINS` still works (Local Test uses `http://localhost:8080`).
   - **Test environment:** the separate test extension sets its own client id, so it keeps working.

**Out of scope:** player avatars (`players.avatar_url`) come from Steam's avatar hosts through OpenDota and aren't named in the issue. The Steam hosts are kept in one module so avatars can use the same check later if wanted.

Resolves GitHub issue #171.

## User Stories

### New Accounts Wait a Day Before Joining Drops
**User story**
As a viewer, I want drops to go to real viewers, so that someone who makes a stack of Twitch accounts during a broadcast can't crowd out my chance to win.

**Acceptance criteria**
- `_active_pool` includes a soft account only when `users.created_at` is at least `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` (default `24`) before the drop. Website accounts are always included. `0` turns the age rule off.
- The panel tells a newly joined viewer: "Drops start for your account on <date>." It does this in the Live tab until the account is old enough.
- Each `twitch_token_drop` audit entry keeps `count=<winners>` and adds `pool_size=<n>` and `excluded_new=<count>`.
- When the pool is empty only because every present account is too new, the server still writes a `twitch_token_drop` entry with `count=0 pool_size=0 excluded_new=<count>`. The drop is not claimed, so a later confirmation of the same match can still drop. Chat then says "No tokens were dropped: new accounts join drops <N> hours after joining." (the configured age) instead of "no joined viewers were watching."
- When a drop's `pool_size` is more than three times the median of that channel's last ten `twitch_token_drop` entries (only with at least five earlier entries), the server logs a warning and the audit detail includes `pool_spike=true`. Entries without `pool_size=` (written before #171) and empty pools are left out of the median.
- **Failure path:** a soft account created one hour before a drop is not in the pool and gets no token. The drop still goes to the eligible viewers, and the chat count reflects only them.

### Logged-Out Viewers Don't Fill the Presence Table
**User story**
As the operator, I want heartbeats from logged-out viewers to be ignored, so that people who can't join or win don't add rows or load.

**Acceptance criteria**
- `POST /twitch/heartbeat` with an opaque id not starting with `U` returns `{"ok": true}` and writes no `twitch_presence` row.
- The route is limited per viewer (`key_by_twitch_viewer_or_ip`, `RATE_LIMIT_TWITCH_ACTION`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`), like the other panel routes.
- **Failure path:** a heartbeat with an `A…` id leaves `twitch_presence` unchanged, and a `U…` heartbeat still upserts its row.

### Team Logos Only From Known Hosts
**User story**
As a viewer, I want team logos to load only from known image hosts, so that opening Kana Cards or the panel doesn't show my IP address to arbitrary servers.

**Acceptance criteria**
- A new `backend/logo_hosts.py` has `safe_logo_url(url) -> str | None`. It returns the URL only when it is `https:`, has no explicit port and no userinfo (`user@host`), and its host is in `LOGO_HOST_ALLOWLIST`:
  - comma-separated, compared case-insensitively;
  - an empty value falls back to the default Steam CDN list.
  
  Otherwise it returns `None`.
- `ingest._match_logo_url` turns `//host/...` into `https://host/...` and then stores only URLs that pass `safe_logo_url`.
- Every response that carries `team_logo_url` or a team `logo_url` passes it through `safe_logo_url`: the card and roster routes, `GET /deck/booster`, the panel's teams and collection, and the Weekly Report fallback. `GET /teams` and `GET /teams/{team_id}` return no logo field, and the schedule returns no logos. The local `/assets/` logo stays preferred wherever it is used today.
- The card image (`GET /cards/{card_id}/image`) also passes the logo through `safe_logo_url` before the server fetches it, so the server never requests a logo from an unknown host.
- When the logo is `null`, the panel shows the team monogram, the website's team draw shows its blank circle placeholder and the Weekly Report shows the team name alone. This already happens for teams without a logo.
- **Failure path:** a team whose stored `logo_url` is `https://evil.example/logo.png` is returned with `logo_url: null`, and an ingest of such a URL stores nothing.

### Only Our Extension Can Call the Backend Cross-Origin
**User story**
As the operator, I want CORS to allow only our own extension's origin, so that another extension's iframe gets no `Access-Control-Allow-Origin` from our backend.

**Acceptance criteria**
- With `TWITCH_EXTENSION_CLIENT_ID=abc123`, a preflight from `https://abc123.ext-twitch.tv` gets `Access-Control-Allow-Origin` and one from `https://other999.ext-twitch.tv` doesn't.
- The client id is regex-escaped when the rule is built.
- Without `TWITCH_EXTENSION_CLIENT_ID`, no `*.ext-twitch.tv` origin is allowed. A warning is logged once at start-up, and `CORS_EXTRA_ORIGINS` origins keep working.
- `allow_credentials` stays false.
- **Failure path:** a preflight from another extension's origin gets no `Access-Control-Allow-Origin` header.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/twitch.py` | Heartbeat: early return for non-`U` ids and per-viewer limit. `_active_pool`: account-age rule for soft accounts. `_execute_token_drop`: `excluded_new`, pool-spike check and audit detail. `GET /twitch/me` adds `drops_from` (Unix time, or null). |
| `backend/logo_hosts.py` *(new)* | `DEFAULT_LOGO_HOSTS`, `logo_hosts()` (reads `LOGO_HOST_ALLOWLIST` at call time), `safe_logo_url(url)` |
| `backend/ingest.py` | `_match_logo_url` returns `safe_logo_url(...)` |
| `backend/routers/cards.py`, `backend/routers/weekly_summary.py` | Pass logo fields through `safe_logo_url` (`routers/players.py` returns no logo field) |
| `backend/image.py` | `_fetch_team_logo_image` fetches only URLs that pass `safe_logo_url` |
| `backend/main.py` | CORS origin rule built from `TWITCH_EXTENSION_CLIENT_ID`; start-up warning when unset |
| `twitch-extension/panel.js` | "Drops start for your account on <date>" from `drops_from` |
| `.env.example` | `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS`, `LOGO_HOST_ALLOWLIST`; CORS note updated |
| `markdown/features/core/twitch-extension.md`, `markdown/features/reference/twitch-extension-policy-compliance.md` | Pool rules, heartbeat, CORS, logos |
| `backend/tests/test_issue_171_twitch_panel_abuse_limits.py` | New tests |

### Step 1 — Heartbeat
Split like the other panel routes: the plain function holds the logic, the route wrapper carries slowapi's `request`.
```python
def heartbeat(payload: dict, db: Session) -> dict:
    opaque_id = str(payload.get("opaque_user_id") or "")
    if not opaque_id.startswith("U"):
        return {"ok": True}          # logged-out viewers can't join or win: nothing stored
    ...

@router.post("/heartbeat")
@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)
@limiter.limit(RATE_LIMIT_TWITCH_JOIN_IP)
def heartbeat_route(request: Request, payload: dict = Depends(verify_twitch_jwt), db=Depends(get_db)):
    return heartbeat(payload, db)
```

### Step 2 — Drop pool age rule and spike watch
- In `_active_pool`, add `AND (u.account_type <> 'twitch' OR u.created_at <= :min_created)`, where `min_created = now - hours*3600`. A soft account with a null `created_at` counts as new.
- `_execute_token_drop` counts the excluded new soft accounts. It then compares `pool_size` with the median of the channel's last ten `twitch_token_drop` audit entries, parsed from their `pool_size=` detail; entries written before this change carry no pool size and are skipped, as are empty pools. It logs a warning and adds `pool_spike=true` when the pool is more than three times that median, with at least five earlier entries.
- Audit detail: `channel=… match=… count=N pool_size=N excluded_new=N [pool_spike=true] winners=…`.
- When the pool is empty and `excluded_new > 0`, an entry `count=0 pool_size=0 excluded_new=N` is written without claiming the drop.

### Step 3 — Logo hosts
```python
DEFAULT_LOGO_HOSTS = ("steamcdn-a.akamaihd.net", "steamusercontent-a.akamaihd.net",
                      "cdn.steamusercontent.com", "cdn.cloudflare.steamstatic.com",
                      "shared.cloudflare.steamstatic.com")

def safe_logo_url(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    return url.strip() if parsed.scheme == "https" and host in logo_hosts() else None
```
The built version also refuses an explicit port (`parsed.port`, or a bare `:` in the netloc) and userinfo (`@` in the netloc). `_match_logo_url` keeps turning `//host/...` into https before the check. `image._fetch_team_logo_image` passes the URL through `safe_logo_url` before fetching.

Apply it at ingest and on every response field listed in the story. Grep for `logo_url` to make sure none is missed.

### Step 4 — CORS
```python
_ext_client_id = os.getenv("TWITCH_EXTENSION_CLIENT_ID", "").strip()
_ext_origin_regex = rf"^https://{re.escape(_ext_client_id)}\.ext-twitch\.tv$" if _ext_client_id else None
if not _ext_client_id:
    logger.warning("TWITCH_EXTENSION_CLIENT_ID unset: no Twitch extension origin is allowed by CORS")
app.add_middleware(CORSMiddleware, allow_origins=_extra_origins,
                   allow_origin_regex=_ext_origin_regex, allow_credentials=False, ...)
```

Check that the CSP `frame-ancestors` (`https://*.ext-twitch.tv`) is unchanged. It is about embedding, not cross-origin calls, and stays as it is.

### Step 5 — Panel and docs
- The Live tab shows the "Drops start" line when `drops_from` is in the future.
- Docs and `.env.example` updated.
- The extension change ships with the next extension version.

## Verification
- **Tests:**
  - **Heartbeat:** with an `A…` id, no row is written; a `U…` id is upserted; the per-viewer limit applies.
  - **Pool:** a soft account younger than 24 h is excluded; a website account is always included; `0` turns the rule off.
  - **Audit:** the entry carries `pool_size` and `excluded_new`; a pool more than 3× the median with ≥ 5 earlier entries logs a warning and `pool_spike=true`.
  - **Logos:** `safe_logo_url` accepts the default hosts over `https`, and refuses `http` and other schemes, unknown hosts, look-alike hosts (`steamcdn-a.akamaihd.net.evil.example`), explicit ports, userinfo and malformed URLs. Ingest stores nothing for an unknown host. Card, deck, panel-teams and weekly-report responses return `null` for a stored unknown-host logo (`GET /teams` bodies carry none). The card image never fetches an unknown-host logo.
  - **CORS:** a preflight from our client id's origin is allowed; one from another extension's origin gets no `Access-Control-Allow-Origin`; without a client id, no extension origin is allowed and `CORS_EXTRA_ORIGINS` still works.
- **Existing tests:** those that preflight with a made-up `*.ext-twitch.tv` origin (for example in `test_issue_136_security_audit_3.py`) need `TWITCH_EXTENSION_CLIENT_ID` set to match.
- **Manual, on the test environment:**
  - With the test extension, the panel loads and calls the backend. A brand-new Twitch account that joins sees "Drops start for your account on …" and isn't in the next drop.
  - Team logos still show, from the local assets or a Steam CDN.
- Run the full suite and update the suite-size check in `tests/test_issue_85_split_admin_router.py`.
