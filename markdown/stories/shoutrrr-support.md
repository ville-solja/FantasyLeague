# Shoutrrr Support

### Configure Shoutrrr Push Notifications
**User story**
As an operator, I want to configure a separately-hosted Shoutrrr instance's endpoint and an
auth token via environment variables, so the app can send push notifications without needing to
know anything about the downstream notification channels Shoutrrr forwards to.

**Acceptance criteria**
- `SHOUTRRR_URL` and `SHOUTRRR_AUTH_TOKEN` environment variables configure the outbound
  endpoint and its authentication
- When `SHOUTRRR_URL` is unset, the app never attempts an outbound request and raises no
  error — the feature is a silent no-op, exactly as the issue requires
- The outbound request is a simple HTTP POST with a JSON body (`title`, `message`, plus the
  structured fields for the specific notification), so it works with any shoutrrr-fronting
  HTTP service without this app needing to know the specific downstream channel
- A failed or unreachable Shoutrrr endpoint is logged server-side and never raises an
  unhandled exception or crashes the background loop that triggers it
- `.env.example` documents both variables and their default (unset → disabled) behavior

---

### Receive a Match-Starting-Soon Reminder
**User story**
As a viewer/fan, I want a push notification roughly 15 minutes before a scheduled match
starts, including the two teams, the scheduled time, and the stream link, so I don't miss the
start of a match I care about.

**Acceptance criteria**
- A background check compares the current time against each upcoming scheduled series' start
  time, sourced from the existing Schedule sheet data (the same parsed data `GET /schedule`
  already returns — `team1`, `team2`, `datetime_iso`, `stream_url`)
- A reminder is sent once a series is within a configurable lead time (default 15 minutes) of
  its scheduled start and has not already been sent for that series
- The notification payload includes team1, team2, the scheduled start time, and the stream
  link when one is set in the schedule sheet
- Each scheduled series triggers at most one reminder — re-running the check after a reminder
  has already been sent for that series does not send a duplicate
- A series with no stream link set still gets a reminder, with the stream link field simply
  omitted/null rather than the check being skipped
- If the app was not running during a series' 15-minute lead window (e.g. downtime) and the
  window has already passed by the time the check next runs, no late reminder is sent for it
