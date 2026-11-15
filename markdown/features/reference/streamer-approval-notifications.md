# Streamer Approval Notifications

Tells admins outside the site when a Twitch channel asks for MVP approval, by email and/or a Discord webhook, so a streamer isn't left waiting on match night. Issue #215, split off from #214, which added the in-site pending badge. Plan: `markdown/plans/plan-issue-215-streamer-approval-notifications.md`. The approval flow itself is in [Approved Streamers Admin](approved-streamers-admin.md).

---

## How it works

A broadcaster opening the MVP tool on a channel that isn't approved creates one pending `twitch_channel_approvals` row (`twitch_channels.record_request`). Later visits only bump `last_seen_at`. Every 5 minutes the week maintenance loop calls `twitch_channels.notify_pending(db)` through `main._run_approval_notifications`, which has its own try/except, so a failure is logged and rolled back and never stops the loop. `notify_pending`:

- **Skips** the pass when no channel is ready (see below).
- **Waits** while the latest `notified_at` is less than `NOTIFY_SPACING` (30 minutes) old, so a burst of requests makes at most two messages an hour.
- **Picks** the pending rows with no `notified_at`, oldest first. Approved, rejected and already-announced channels are skipped. A request dropped by the 200-row `PENDING_CAP` is gone, so it is never announced.
- **Fills names** for the first rows from Helix (`_lookup_names`, best effort) and stores them.
- **Sends one message** (`admin_notify.approval_message`): up to `NOTIFY_NAME_LIMIT` (10) names, then "and N more", and a link to Admin when `APP_BASE_URL` is set. For example: `2 Twitch channels are waiting for MVP approval: Kanaliiga (kanaliiga), channel 123456789. Approve or reject them in Admin › Twitch › Approved streamers: https://…`. When older, already-announced requests are still waiting, the text reads `N new Twitch channels asked for MVP approval: … M are waiting in all.` The email subject is `<APP_NAME>: M streamers waiting for approval` (`Kana Cards` by default), where M counts every pending request.
- **Commits before sending:** the names, the counts and the targets (`admin_notify.targets`) are read and the names committed first, so no database transaction is open during the network calls (`admin_notify.deliver`); a slow Discord or SMTP server never holds the SQLite write lock. `admin_notify.send`, used by the test route, also commits before sending.
- **Marks** every row in the batch `notified_at = now` and audits `twitch_approval_notified` (`channels=<count> via=discord,email`) when at least one channel delivered. When none did, nothing is marked, and the next try waits `NOTIFY_SPACING` too (the failed try's time is kept in memory, so a restart retries at once). While nothing is configured, nothing is marked, so the first message after setup lists the backlog. Existing rows keep `notified_at` empty after migration 044, so the backlog at deploy is announced once.

## Channels

`backend/admin_notify.py`:

- **Email:** through the existing SMTP setup (`email_utils.send_email`), one message per recipient, no CC. Recipients are every `is_admin` account with an email address (Steam-only admins have none), or the addresses in `ADMIN_NOTIFY_EMAILS`. `ADMIN_NOTIFY_EMAILS=off` turns email off. Nothing is sent without `SMTP_HOST`. Each SMTP connection has a 10-second timeout (`email_utils.SMTP_TIMEOUT`). The channel counts as delivered when at least one recipient got the message.
- **Discord:** `POST` to `ADMIN_NOTIFY_DISCORD_WEBHOOK_URL` with `{"content", "allowed_mentions": {"parse": []}, "username": "Kana Cards"}` a 5-second timeout and `allow_redirects=False`; a 2xx answer is success, and anything else, a redirect included, is `error: http <code>`. Only `https://discord.com/api/webhooks/…` and `https://discordapp.com/api/webhooks/…` addresses (no port, no user info) are accepted; any other value turns the channel off and the status says so.
- **Shoutrrr** ([#97](shoutrrr-support.md), planned) can be added as a third entry in `admin_notify.CHANNELS`.

Each channel's outcome is `ok`, `off` or `error: <kind>` (`http 404`, `timeout`, `connection`, `smtp`). `admin_notify.last_result()` keeps the last outcome and its time in memory, so it is empty after a restart.

**Names:** a channel reads `Display (login)`, or `channel <id>` when Helix has no name or the name or login looks like a link (`text_safety.looks_like_url`). Names go through `clean_display_text` (control, zero-width and bidi characters removed, 50 characters at most), and in the Discord text the markdown characters `\ * _ ~ ` | > #` are escaped. With `allowed_mentions` empty, `@everyone`, `@here` and role or user mentions notify nobody.

**Secrets:** the webhook URL and the recipient addresses never appear in this feature's logs, responses, the status or the audit log. Failures are logged only as a kind (`Admin notification: discord failed (http 404)`). `email_utils.send_email` logs no address either: only the subject, the number of refused recipients and the error type.

## Admin › Twitch

- **Approval notifications** check in the Twitch status (`key: approval_notifications`): OK with `Ready: Discord, email to N recipients.` when at least one channel is ready, otherwise a warning. Each channel that isn't ready gets its reason (`not set`, `set, but not a Discord webhook address`, `SMTP is not configured`, `no admin has an email address`, `no address in ADMIN_NOTIFY_EMAILS`, `off (ADMIN_NOTIFY_EMAILS=off)`). The detail ends with the last message time and each channel's outcome, or, after a restart, the latest `notified_at`. A **Send test notification** also counts as the last message there, so right after a test the line shows the test's outcome.
- **Send test notification** button under the status: calls the endpoint below through `adminFetch` (the re-auth popup when needed) and shows `Discord: sent · Email: sent to 2 recipients`, `off` or the error kind per channel.

## Endpoints

### `POST /admin/twitch/notify-test`
`require_admin` and `require_recent_reauth`, rate-limited to 3 a minute (`RATE_LIMIT_NOTIFY_TEST` in `routers/admin_twitch.py`). Sends a fixed test message to every configured channel through `admin_notify.send_test` and returns `{"discord": "ok" | "off" | "error: <kind>", "email": …, "email_sent": n}`. Audited `admin_twitch_notify_test` with the outcomes only. A test message doesn't affect the 30-minute spacing.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ADMIN_NOTIFY_DISCORD_WEBHOOK_URL` | *(empty)* | Discord webhook for approval notifications. A secret: shown in Admin only as "set" |
| `ADMIN_NOTIFY_EMAILS` | *(empty)* | Empty: every admin with an email address. A comma-separated list replaces that; `off` turns email off |

Email also needs the `SMTP_*` settings ([commands.md](commands.md)).

## Data

Migration `044_twitch_channel_approvals_notified_at` adds `twitch_channel_approvals.notified_at` (Unix time the request was announced, NULL until then). Run `bash scripts/backup-db.sh` before deploying it.

## Tests

`backend/tests/test_issue_215_streamer_approval_notifications.py`.
