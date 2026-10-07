# Twitch Panel Abuse Limits

Limits on the cheap ways to game or misuse the Twitch panel: alt accounts farming drops, logged-out viewers filling the presence table, team logos loaded from arbitrary hosts, and other extensions calling the backend. Resolves issue #171 (part of #163).

---

## Drop pool

- **Minimum account age:** `twitch._active_pool(db, channel_id)` includes a soft account (`users.account_type = "twitch"`) only once its `created_at` is at least `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` old (default 24, read on each drop; `0` turns the rule off). A soft account with a null `created_at` is never in a pool, and its `drops_from` is `null`; accounts created through Join always have `created_at`, so this only affects hand-made rows. Website accounts (code-linked before #160, or connected with Twitch sign-in) are always eligible.
- **Panel line:** `GET /twitch/me` returns `drops_from`: the Unix time from which the caller's soft account is in drop pools, while that is still in the future, else `null` (website accounts, old-enough accounts, rule off). The Live tab then shows "Drops start for your account on <date>." (`renderDropsStart` in `twitch-extension/panel.js`).
- **Audit:** each `twitch_token_drop` audit entry reads `channel=<id> match=<id> count=<winners> pool_size=<n> excluded_new=<n> [pool_spike=true] winners=<names>`. `excluded_new` counts present soft accounts left out for being too new.
- **Only new accounts present:** when the pool is empty only because every present account was too new, an entry `count=0 pool_size=0 excluded_new=<n>` is still written. Nothing is claimed in `twitch_token_drops`, so the one-drop-per-match rule is unchanged: a later confirmation of the same match can still drop. Chat then says "Match MVP: <name>! No tokens were dropped: new accounts join drops <N> hours after joining." (`<N>` is the configured age, "1 hour" when it is 1). With nobody eligible or new present, chat keeps "No tokens were dropped: no joined viewers were watching."
- **Spike watch:** before granting, the drop's `pool_size` is compared with the median of the channel's last ten `twitch_token_drop` entries that carry a `pool_size=` above zero (entries written before #171, empty pools and other channels are skipped). With at least five such entries and a pool more than three times the median, the `twitch` logger writes a warning and the audit detail gets `pool_spike=true`. The drop itself still goes ahead.
- **Why not stricter:** requiring the identity share doesn't stop alts (each alt shares its own Twitch id); requiring a website account would make drops depend on an outside login and break policy 4.5. The #160 one-merge limit already keeps farmed tokens from adding up in one website account; what's left is alts taking winner slots when a pool is larger than `TWITCH_DROP_MAX`.

## Heartbeats

`POST /twitch/heartbeat` (`twitch.heartbeat_route`, Twitch JWT) ignores logged-out viewers: an opaque id not starting with `U` gets `{"ok": true}` and nothing is written. A `U…` id upserts its `twitch_presence` row as before. The route is limited per viewer (`RATE_LIMIT_TWITCH_ACTION`, key `key_by_twitch_viewer_or_ip`) and per IP (`RATE_LIMIT_TWITCH_JOIN_IP`), like the other panel routes. The plain `twitch.heartbeat(payload, db)` holds the logic.

## Team logos

`backend/logo_hosts.py`:
- `DEFAULT_LOGO_HOSTS`: Steam's CDNs, which OpenDota team logos use (`steamcdn-a.akamaihd.net`, `steamusercontent-a.akamaihd.net`, `cdn.steamusercontent.com`, `cdn.cloudflare.steamstatic.com`, `shared.cloudflare.steamstatic.com`).
- `logo_hosts()`: the hosts from `LOGO_HOST_ALLOWLIST` (comma-separated, case-insensitive, read on each call); empty means the defaults.
- `safe_logo_url(url) -> str | None`: the stripped URL when it is `https`, has no explicit port and no userinfo (`user@host`), and its host is allowlisted; otherwise `None`. Non-strings, other schemes, look-alike hosts and malformed URLs give `None`.

Where it applies:
- **Ingest:** `ingest._match_logo_url` turns `//host/...` into `https://host/...` and stores only what passes, so an unknown host is never written to `teams.logo_url`.
- **Output:** every response carrying a team logo: `_build_roster_response` (`GET /roster/{user_id}`, the panel roster), `collection_for_user` (panel collection), `POST /draw`, `POST /draw/booster/{team_id}`, `GET /cards/{card_id}`, `booster_deck_for_user` (`GET /deck/booster`, `GET /twitch/teams`), and the Weekly Report's `_team_logo_url` fallback. A stored value on an unknown host comes back as `null`, so rows stored before #171 need no data migration. `GET /teams`, `GET /teams/{team_id}` and the schedule return no logo field.
- **Card images:** `image._fetch_team_logo_image` (used by `GET /cards/{card_id}/image`) passes the URL through `safe_logo_url` before fetching, so the server never requests a logo from an unknown host.
- **Order of preference:** the local Dotabuff PNG under `/assets/dotabuff_league_logos/` stays first in the Weekly Report and card images.
- **When `null`:** the panel shows the team monogram, the website's team draw shows its blank circle placeholder and the Weekly Report shows the team name alone.

Player avatars (`players.avatar_url`) are out of scope; `logo_hosts.py` keeps the Steam hosts in one place if they get the same check later.

## CORS

`backend/main.py` builds the origin rule from `TWITCH_EXTENSION_CLIENT_ID` at import: `^https://<TWITCH_EXTENSION_CLIENT_ID>\.ext-twitch\.tv$`, with the client id passed through `re.escape`. Other extensions' origins get no `Access-Control-Allow-Origin`. Without a client id the regex is unset, no `ext-twitch.tv` origin is allowed, and start-up logs one warning (`TWITCH_EXTENSION_CLIENT_ID unset: no Twitch extension origin is allowed by CORS`). `CORS_EXTRA_ORIGINS` still works either way (Local Test uses `http://localhost:8080`), and `allow_credentials` stays false. The CSP `frame-ancestors` keeps `https://*.ext-twitch.tv`: it controls embedding, not cross-origin calls.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS` | `24` | Hours before a new soft account joins drop pools; `0` turns it off. An invalid or negative value falls back to 24 |
| `LOGO_HOST_ALLOWLIST` | Steam CDN hosts | Comma-separated hosts team logo URLs may use |
| `TWITCH_EXTENSION_CLIENT_ID` | *(empty)* | Also the only extension origin CORS allows; set it wherever the extension runs |

## Tests

`backend/tests/test_issue_171_twitch_panel_abuse_limits.py`.
