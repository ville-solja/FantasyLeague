# Plan: Streamer Approval Notifications

## Context
When a broadcaster opens the MVP tool on a channel that isn't approved, a pending request waits in Admin › Twitch › Approved streamers (#175). #214 added a pending badge on the Admin tab, but that only helps while an admin has the site open, so a streamer can wait hours on match night. This issue tells admins outside the site, so approvals are handed out quickly. It was split off from #214.

**What we have to build on:**
- **Requests:** `twitch_channels.record_request` creates one `twitch_channel_approvals` row the first time a channel asks. Later visits only bump `last_seen_at`, and a rejected channel stays rejected. So "a new request" is a new pending row. It is called from `twitch.py` (MVP tool, match list) and `twitch_mvp_poll.py`. At most `PENDING_CAP` (200) pending rows are kept.
- **Names:** `twitch_channels._lookup_names` fills display names from Helix, best effort.
- **Email:** `email_utils.send_email` and `email_configured()` use the SMTP settings already in use for password resets. Steam-only accounts have no email.
- **Background loop:** `main._week_maintenance_loop` runs every `WEEK_CHECK_INTERVAL` (300 s) and already hosts the daily cleanups.
- **Admin › Twitch status:** `twitch_status.build_status` returns a list of checks (`key`, `state`, `label`, `detail`) shown in Admin › Twitch (#180).
- **Shoutrrr (#97):** a generic push channel to an operator-hosted Shoutrrr service. It is planned but not built, and needs a separate service, so this issue doesn't wait for it. The notifier is written so Shoutrrr can be added as one more channel later.

**Decisions** (change them in review if needed):
- **Channels: email and a Discord webhook,** either or both.
  - **Email** goes through the existing SMTP setup, so it works as soon as an admin has an email address. No new service.
  - **Discord webhook** (`ADMIN_NOTIFY_DISCORD_WEBHOOK_URL`) reaches the league's organisers where they already talk, on phones too.
  - **Not Twitch chat:** the extension can only post to the channel that is asking, which is the wrong audience.
- **Who gets the email:**
  - by default, every admin account with an email address, so the list follows admin changes without a deploy;
  - `ADMIN_NOTIFY_EMAILS` replaces the default with a comma-separated list, and `off` turns email off;
  - the Discord webhook goes to whichever channel the operator created it for.
- **When to send: batched, never repeated.**
  - The week maintenance loop checks every 5 minutes for pending requests that haven't been notified (`notified_at` empty).
  - It sends **one** message listing them: up to 10 names, then "and N more".
  - It marks them notified, so each channel is announced once.
  - Messages are at least 30 minutes apart. A burst of fake channels makes at most two messages an hour, and a quiet night's first request goes out within about 5 minutes.
  - Approved, rejected and already-notified channels are never announced.
  - Requests are marked notified only when at least one channel sent. Nothing is marked while nothing is configured, so the first message after setup lists the waiting backlog.
- **Message:** plain text with counts and names, no ids beyond what is needed:
  - `2 Twitch channels are waiting for MVP approval: Kanaliiga (kanaliiga), channel 123456789. Approve or reject them in Admin › Twitch › Approved streamers: <APP_BASE_URL>`;
  - with no `APP_BASE_URL` the link is left out;
  - email subject: `Kana Cards: 2 streamers waiting for approval`.
- **Safety:**
  - display names are cleaned (`clean_display_text`) and Discord markdown is escaped;
  - Discord is sent with `allowed_mentions: {"parse": []}`, so a name like `@everyone` can't ping anyone;
  - the webhook URL must be an `https://discord.com/api/webhooks/…` or `https://discordapp.com/api/webhooks/…` address, otherwise the channel is treated as off and the status says so;
  - the URL is a secret: never logged, never in a response or audit row, and the status shows only "set";
  - SMTP failures and webhook errors are logged as a kind (`http 404`, `timeout`) without the URL or recipient addresses, and never stop the loop.
- **Seeing it work without logs:**
  - **Admin › Twitch › status** gets an **Approval notifications** check: OK when at least one channel is ready, a warning when none is. The detail names the channels, the email recipient count, the last message time and the last error kind.
  - **Send test notification** (`POST /admin/twitch/notify-test`, admin with a recent re-auth, rate-limited) sends a test message to every configured channel and reports each result.
- **Audit:** `twitch_approval_notified` (channel count and the channels used, never addresses) and `admin_twitch_notify_test`.
- **Data:** one new column, `twitch_channel_approvals.notified_at`, with migration `044_twitch_channel_approvals_notified_at`. Existing pending rows keep `notified_at` empty, so the first message after deploy lists the current backlog once.
- **Privacy:** admins' own emails are used only for this. Twitch channel names are public. The privacy page needs no change.

Resolves GitHub issue #215.

## User Stories

### Admins Hear About a New Streamer Request Outside the Site
**User story**
As an admin, I want a message by email or Discord when a streamer asks for MVP approval, so that I can approve them before their match even when I don't have the site open.

**Acceptance criteria**
- **Trigger:** a new pending request (a channel's first visit to the MVP tool) is announced by the next check, within about 5 minutes.
- **One message for many:** pending requests not yet announced are sent together in one message. It names up to 10 channels (display name and login, or the channel id when Helix has no name), then "and N more", plus the total waiting and a link to the admin page when `APP_BASE_URL` is set.
- **Once per channel:** an announced channel is never announced again, and neither is a channel's later visit, an approved channel or a rejected one.
- **Spacing:** messages are at least 30 minutes apart. Requests arriving in between go into the next message.
- **Email:** sent to every admin with an email address, or to `ADMIN_NOTIFY_EMAILS` when set. `off` turns email off, and nothing is sent without SMTP.
- **Discord:** posted to `ADMIN_NOTIFY_DISCORD_WEBHOOK_URL` when it is a Discord webhook address, with mentions disabled.
- **Failure:** when every channel fails, the requests stay unannounced and are retried on a later check. One channel failing doesn't stop the other.

### The Operator Configures and Checks the Notifications
**User story**
As the operator, I want to see in Admin whether approval notifications are set up and working, and to send a test, so that I know admins will hear about requests without reading the server logs.

**Acceptance criteria**
- **Status:** Admin › Twitch status shows an **Approval notifications** check.
  - OK names the ready channels (Discord, email to N recipients).
  - A warning appears when none is ready, for example no webhook and no SMTP, or a webhook URL that isn't a Discord webhook.
  - The detail shows the last message time and the last error kind.
- **Test:** **Send test notification** sends a test message to each configured channel and shows the result per channel. It needs an admin with a recent re-authentication and is rate-limited. It is audited as `admin_twitch_notify_test`.
- **Secrets:** the webhook URL never appears in a response, the audit log or the logs (only "set"). Recipient addresses never appear in the status or the audit log, only their count.
- **Docs:** `.env.example` and the feature doc describe `ADMIN_NOTIFY_DISCORD_WEBHOOK_URL` and `ADMIN_NOTIFY_EMAILS`.

### Notifications Can't Be Used to Spam Admins
**User story**
As an admin, I want notifications to stay few and harmless even if someone creates many channels, so that the alert stays useful.

**Acceptance criteria**
- **Rate:** however many requests arrive, at most one message goes out per 30 minutes, with at most 10 names in it.
- **No pings or links from names:**
  - channel names are cleaned of control and hidden characters;
  - Discord markdown in a name is escaped;
  - `@everyone`, `@here` and role or user mentions don't notify anyone;
  - a name that looks like a link is shown as the channel id instead.
- **Bounded:** the existing cap of 200 pending requests still applies. A dropped request is not announced.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | `TwitchChannelApproval.notified_at` (Integer, nullable) |
| `backend/migrate.py` | `044_twitch_channel_approvals_notified_at`, guarded by `PRAGMA table_info` |
| `backend/admin_notify.py` (new) | Channels (email, Discord), recipients, message text, sending, last result |
| `backend/twitch_channels.py` | `notify_pending(db, now)`: pick unannounced pending rows, spacing, Helix names, send, mark |
| `backend/main.py` | Call `notify_pending` from the week maintenance loop (best effort) |
| `backend/twitch_status.py` | Approval notifications check |
| `backend/routers/admin_twitch.py` | `POST /admin/twitch/notify-test` |
| `frontend/app-admin-users.js` (renders Admin › Twitch and its status) | Send test notification button and per-channel result |
| `.env.example`, `markdown/features/reference/commands.md` | The two new env vars |
| `markdown/features/reference/streamer-approval-notifications.md`, `approved-streamers-admin.md`, `twitch-integration-status.md`, `markdown/ui_description/admin.md` | Docs |
| `backend/tests/test_issue_215_streamer_approval_notifications.py` | Tests |

### Step 1 — Column and migration
Add `notified_at` to `TwitchChannelApproval`, and migration 044 as `ALTER TABLE twitch_channel_approvals ADD COLUMN notified_at INTEGER`, guarded by a `PRAGMA table_info` check like the existing ones. Existing rows keep NULL.

### Step 2 — `admin_notify.py`
```python
def channels() -> dict          # {"discord": {...ready, reason}, "email": {...ready, recipients: n, reason}}
def send(subject: str, text: str, db) -> dict   # {"discord": "ok" | "error: <kind>" | "off", "email": ...}
def last_result() -> dict       # in memory: at, per-channel outcome
```
- **Discord:** `requests.post(url, json={"content": text, "allowed_mentions": {"parse": []}, "username": "Kana Cards"}, timeout=5)`. A 2xx is ok. Log only the status code or exception class.
- **Email:** `email_utils.send_email` to each recipient, one message per recipient, no CC lists. Recipients are the `User.is_admin` accounts with an email, or `ADMIN_NOTIFY_EMAILS`. Skip it when `email_configured()` is false.
- **Safe names:** a helper escapes Discord markdown (`\ * _ ~ ` | > #`) after `clean_display_text`.
- **Later:** a Shoutrrr channel (#97) slots in here.

### Step 3 — `twitch_channels.notify_pending(db, now=None)`
- Return early when no channel is ready, or when the last message (the latest `notified_at`) is less than 30 minutes old.
- Take the pending rows with `notified_at IS NULL`, oldest first, and fill missing names with `_lookup_names` (best effort).
- Build the text and send it. When at least one channel returned ok, set `notified_at = now` on those rows and audit `twitch_approval_notified`. Then commit.
- Use constants for the spacing (30 min) and the name limit (10).

### Step 4 — Loop, status and test route
- **Loop:** `_week_maintenance_loop` calls `notify_pending` in its own try/except on every pass.
- **Status:** `twitch_status` gets the check described in the stories.
- **Test route:** `POST /admin/twitch/notify-test` (`require_admin`, `require_recent_reauth`, 3/minute) calls `admin_notify.send` with a fixed test text. It returns the per-channel results and audits `admin_twitch_notify_test`.

### Step 5 — Admin UI
In Admin › Twitch, next to the status, add a **Send test notification** button that goes through `adminFetch` (re-auth popup) and shows "Discord: sent · Email: sent to 2 admins" or the error kind.

### Step 6 — Tests
- **Trigger and batching:**
  - a new pending row is announced once;
  - later visits, approved and rejected channels are not;
  - several requests go in one message, with the 10-name limit and "and N more".
- **Spacing:** no message within 30 minutes of the last one, and the next message picks up the waiting requests.
- **Failure:** both channels failing leaves `notified_at` empty; one failing still marks the requests.
- **Unconfigured:** nothing is sent or marked.
- **Recipients:** the default is admins with an email; the env list and `off` work; no email without SMTP.
- **Discord:** the payload has `allowed_mentions` empty, names are escaped, a link-like name falls back to the id, and a non-Discord URL counts as not ready.
- **Secrets:** the URL and addresses never appear in responses, status, audit or logs (caplog).
- **Test route:** admin only, recent re-auth, rate-limited, per-channel results, audited.
- **Migration:** the column exists after `run_migrations`, and the schema coverage test passes.

## Verification
- Set up a Discord webhook and SMTP on a test instance, open the MVP tool on an unapproved test channel, and check that one Discord message and one email per admin arrive within about 5 minutes. Opening it again sends nothing.
- Use **Send test notification** with the webhook set and unset, with SMTP off, and with an invalid webhook URL.
- Open the tool from three channels within a few minutes: one message names all three. A fourth channel 10 minutes later waits for the 30-minute spacing.
- Run `bash scripts/backup-db.sh` before deploying (migration 044).
- After deploy, the existing pending backlog arrives once in the first message.
