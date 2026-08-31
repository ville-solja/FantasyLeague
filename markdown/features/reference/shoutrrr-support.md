# Shoutrrr Support

Outbound push notifications sent to a separately-hosted
[Shoutrrr](https://containrrr.dev/shoutrrr/)-fronting HTTP instance the operator runs and
configures independently. This app is deliberately agnostic to what happens on the other end
(Discord, Telegram, ntfy, etc.) — it just POSTs a plain JSON payload. The first notification
type built on this integration point is a match-starting-soon reminder.

---

## Integration Point

`backend/shoutrrr_client.py`'s `send_notification(title, message, **fields)` POSTs
`{"title": ..., "message": ..., **fields}` as JSON to `SHOUTRRR_URL`, with an
`Authorization: Bearer <SHOUTRRR_AUTH_TOKEN>` header when a token is configured. When
`SHOUTRRR_URL` is unset, the call is a silent no-op — nothing is sent, and nothing raises. A
failed or unreachable endpoint is logged server-side (never raised), so a broken or
unconfigured Shoutrrr instance can never take down the background loop that calls it.

*The exact JSON shape here is a minimal, generic assumption — `title`/`message` plus
structured fields — not a shape confirmed against a specific operator's Shoutrrr-fronting
instance. It may need a small adjustment once that instance's expected request format is
known.*

## Match-Starting-Soon Reminder

`backend/match_reminders.py`'s `check_and_send_match_reminders(db)` runs from a background
loop (`_match_reminder_loop` in `backend/main.py`, interval `MATCH_REMINDER_CHECK_INTERVAL`).
It reads the same schedule data `GET /schedule` already parses (`backend/schedule.py`'s
`get_schedule(db)`) and, for every series marked `"upcoming"`, sends a reminder once the
series is within `MATCH_REMINDER_LEAD_MINUTES` (default 15) of its scheduled start —
including team1, team2, the scheduled start time, and the stream link (`null` if none is set
in the schedule sheet).

Each series is deduplicated via a `MatchStartNotification` row keyed on
`{team1}|{team2}|{datetime_iso}`, so re-running the check never sends a second reminder for
the same series, and a series whose window has already passed (e.g. the app was down) is
never reminded late.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `SHOUTRRR_URL` | *(empty)* | Outbound endpoint of the operator's Shoutrrr-fronting instance; unset disables the feature entirely (no-op, no error) |
| `SHOUTRRR_AUTH_TOKEN` | *(empty)* | Sent as `Authorization: Bearer <token>`; omitted if unset |
| `MATCH_REMINDER_LEAD_MINUTES` | `15` | How far ahead of a series' scheduled start to send the reminder |
| `MATCH_REMINDER_CHECK_INTERVAL` | `60` | Seconds between background checks |

---

*This document is a stub created at feature planning time. Fill in implementation details
once the feature is built.*
