"""Demo Mode clock override.

Lets an operator running a DEMO_MODE=true deployment override the app's notion of
"now" so the season lifecycle (pre-lock roster editing, the lock transition, and
post-week scoring) can be demonstrated on demand instead of waiting for real time
to pass. Structurally inert when DEMO_MODE is unset: now() always falls back to
real wall-clock time, and the override row is simply ignored.

See markdown/plans/plan-issue-83-demo-mode.md.
"""
import os
import time

from models import DemoClock

_DEMO_CLOCK_ID = 1


def _demo_enabled() -> bool:
    return os.getenv("DEMO_MODE", "").lower() == "true"


def now(db) -> int:
    """Return the current simulated time: the stored override if DEMO_MODE is on
    and one is set, otherwise real wall-clock time."""
    if _demo_enabled():
        row = db.get(DemoClock, _DEMO_CLOCK_ID)
        if row and row.override_timestamp is not None:
            return row.override_timestamp
    return int(time.time())


def get_override(db) -> int | None:
    """Return the stored override timestamp, or None if unset."""
    row = db.get(DemoClock, _DEMO_CLOCK_ID)
    return row.override_timestamp if row else None


def set_override(db, timestamp: int) -> None:
    """Set (or replace) the demo clock override. Caller commits."""
    row = db.get(DemoClock, _DEMO_CLOCK_ID)
    if not row:
        row = DemoClock(id=_DEMO_CLOCK_ID)
        db.add(row)
    row.override_timestamp = timestamp
    row.updated_at = int(time.time())


def clear_override(db) -> None:
    """Clear the demo clock override, falling back to real time. Caller commits."""
    row = db.get(DemoClock, _DEMO_CLOCK_ID)
    if row:
        row.override_timestamp = None
        row.updated_at = int(time.time())
