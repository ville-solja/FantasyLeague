# Plan: Shoutrrr Support

## Context
The app has no outbound push-notification channel today — everything is either an in-app popup
(Notification System, Token Grant Event) or email (forgot-password). This plan adds a generic
integration point: the app sends a plain JSON HTTP POST to a separately-hosted
[Shoutrrr](https://containrrr.dev/shoutrrr/)-fronting instance the operator runs and configures
via environment variables; what that instance does with the payload (forwarding to Discord,
Telegram, ntfy, etc.) is explicitly out of scope here, per the issue. Since the exact request
shape Shoutrrr instance deployments expect varies, this plan uses a minimal, generic JSON body
(`title`/`message` plus the structured fields) rather than inventing a specific downstream
provider's schema — this is a reasonable assumption, not something observed in this codebase or
confirmed with the operator's actual instance, and may need a small adjustment once that's known.

The first concrete notification built on top of this integration point is a "match starting
soon" reminder: roughly 15 minutes before a scheduled series' start time (sourced from the
existing Schedule Google Sheet data — the same data `GET /schedule` already parses), send a
reminder with team1, team2, the scheduled time, and the stream link. Per the issue, a missing or
unreachable Shoutrrr endpoint must be a silent no-op (never raises, never blocks other
background work), and a given series must never be notified more than once.

*Resolves GitHub issue #97.*

## User Stories

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

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | Add `MatchStartNotification` model (dedupe/audit record — new table, no migration needed) |
| New: `backend/shoutrrr_client.py` | `send_notification(title, message, **fields)` — the generic outbound HTTP POST, reading `SHOUTRRR_URL`/`SHOUTRRR_AUTH_TOKEN` at call time (same pattern as `SCHEDULE_SHEET_URL` in `backend/schedule.py`) |
| New: `backend/match_reminders.py` | `check_and_send_match_reminders(db)` — scans `get_schedule(db)`'s series for ones inside the lead-time window, calls `shoutrrr_client.send_notification`, records `MatchStartNotification` |
| `backend/main.py` | New `_match_reminder_loop()` background thread, started in `lifespan()` alongside the existing loops |
| `.env.example` | Document `SHOUTRRR_URL`, `SHOUTRRR_AUTH_TOKEN`, `MATCH_REMINDER_LEAD_MINUTES`, `MATCH_REMINDER_CHECK_INTERVAL` |

### Step 1 — Dedupe model
```python
class MatchStartNotification(Base):
    """Marks a scheduled series as already reminded, so the background check never
    sends the same "starting soon" push twice."""
    __tablename__ = "match_start_notifications"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_match_start_notification_key"),)

    id           = Column(Integer, primary_key=True, autoincrement=True)
    dedupe_key   = Column(String)   # f"{team1}|{team2}|{datetime_iso}" — stable per sheet row
    sent_at      = Column(Integer)  # Unix timestamp
```

### Step 2 — Outbound Shoutrrr client
`backend/shoutrrr_client.py`, mirroring `schedule.py`'s env-read-at-call-time convention:
```python
import logging
import os
import requests

logger = logging.getLogger(__name__)


def send_notification(title: str, message: str, **fields) -> bool:
    """POST a JSON notification to the configured Shoutrrr-fronting instance.
    No-ops (returns False) when SHOUTRRR_URL is unset — never raises."""
    url = os.getenv("SHOUTRRR_URL", "")
    if not url:
        return False
    headers = {}
    token = os.getenv("SHOUTRRR_AUTH_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {"title": title, "message": message, **fields}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code >= 400:
            logger.warning("Shoutrrr notification failed: %s %s", res.status_code, res.text[:200])
            return False
        return True
    except Exception:
        logger.exception("Shoutrrr notification request failed")
        return False
```

### Step 3 — Match reminder check
`backend/match_reminders.py`:
```python
import os
import time
from datetime import datetime

from models import MatchStartNotification
from schedule import get_schedule
from shoutrrr_client import send_notification

_LEAD_MINUTES = int(os.getenv("MATCH_REMINDER_LEAD_MINUTES", "15"))


def _dedupe_key(series: dict) -> str:
    return f"{series.get('team1')}|{series.get('team2')}|{series.get('datetime_iso')}"


def check_and_send_match_reminders(db):
    data = get_schedule(db)
    now = datetime.now()
    for week in data.get("weeks", []):
        for series in week.get("div1", []) + week.get("div2", []):
            dt_iso = series.get("datetime_iso")
            if not dt_iso or series.get("match_status") != "upcoming":
                continue
            try:
                scheduled = datetime.fromisoformat(dt_iso)
            except ValueError:
                continue
            minutes_until = (scheduled - now).total_seconds() / 60
            if not (0 <= minutes_until <= _LEAD_MINUTES):
                continue
            key = _dedupe_key(series)
            if db.query(MatchStartNotification).filter_by(dedupe_key=key).first():
                continue
            send_notification(
                title="Match starting soon",
                message=f"{series.get('team1')} vs {series.get('team2')} starts soon",
                team1=series.get("team1"), team2=series.get("team2"),
                start_time=dt_iso, stream_url=series.get("stream_url"),
            )
            db.add(MatchStartNotification(dedupe_key=key, sent_at=int(time.time())))
            db.commit()
```

### Step 4 — Background loop wiring
In `backend/main.py`, alongside the existing loops:
```python
_MATCH_REMINDER_CHECK_INTERVAL = int(os.getenv("MATCH_REMINDER_CHECK_INTERVAL", "60"))

def _match_reminder_loop():
    while not _stop_event.is_set():
        try:
            db = SessionLocal()
            try:
                check_and_send_match_reminders(db)
            finally:
                db.close()
        except Exception:
            logger.exception("Match reminder loop error")
        _stop_event.wait(timeout=_MATCH_REMINDER_CHECK_INTERVAL)
```
Started in `lifespan()` the same way `_week_maintenance_loop` is.

---

## Verification
- With `SHOUTRRR_URL` unset, confirm `check_and_send_match_reminders(db)` runs against a
  schedule with an imminent series and neither raises nor makes any HTTP call
- With `SHOUTRRR_URL` set to a local test receiver, confirm a series scheduled ~10 minutes out
  triggers exactly one POST with team1/team2/start_time/stream_url populated
- Confirm a series scheduled 30+ minutes out does not trigger a reminder yet
- Confirm re-running the check after a reminder was sent for a series does not send a second one
- Confirm a series whose scheduled time has already passed (simulating missed-window downtime)
  never triggers a reminder
- Confirm a series with no stream link still sends a reminder, with `stream_url: null`
- Confirm an unreachable/erroring `SHOUTRRR_URL` is logged and does not crash
  `_match_reminder_loop`
