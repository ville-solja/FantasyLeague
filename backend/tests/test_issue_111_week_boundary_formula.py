"""
Tests for plan-issue-111-week-boundary-formula.md (resolves GitHub issue #111).

Covers the plan's single user story:

  Story: Monday-Start, Sunday-End Weeks Never Overlap by Default

The plan changes `_derive_week_times` (`backend/routers/admin_weeks.py`) so that
`start_time` = `start_date` at `03:00:00 UTC` (was `00:00:00 UTC`) and `end_time` =
`(end_date + 1 day)` at `02:59:59 UTC` (was `03:00:00 UTC`), so a normal Monday-start /
Sunday-end week's `end_time` lands exactly one second before the next Monday-start
week's `start_time` -- contiguous, no gap, no overlap, with no admin raw-timestamp
workaround needed for the standard weekly cadence.

Backend acceptance criteria are tested by calling `routers.admin_weeks` functions
directly (`_derive_week_times`, `create_week`), matching the established pattern in
test_issue_84_week_management_editing.py / test_issue_51_weekly_summary.py -- FastAPI
and `routers.admin_weeks` import cleanly in this environment (verified fresh this
session per the 2026-09-07 test-planner lessons-learned entry), so no replicated-logic
helpers are needed. The "existing BETWEEN-based scoring queries" acceptance criterion is
tested with a raw SQL `BETWEEN` query mirroring the pattern used throughout
`routers/cards.py` / `routers/leaderboard.py` / `routers/weekly_summary.py`
(`m.start_time BETWEEN wk.start_time AND wk.end_time`), run directly against the
in-memory `db` fixture's SQLite connection.

One stub per acceptance criterion (six), plus one additional stub covering the
story's primary failure path -- a genuinely overlapping (non-contiguous, non-abutting)
range is still rejected by the overlap guard under the new formula, i.e. the formula
change does not weaken or disable `_check_week_overlap`.

STATUS: stubs only -- every test body is `pytest.fail("not yet implemented")`.
The developer implementing plan-issue-111-week-boundary-formula.md fills these in.

Run with: cd backend && python -m pytest tests/test_issue_111_week_boundary_formula.py -v
"""

import datetime
import os
import sys
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from models import Match, Week
from routers.admin_weeks import _derive_week_times, create_week, WeekCreateBody

_ADMIN = {"user_id": 1, "username": "admin"}


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _make_week(db, label="Week 1", start_time=None, end_time=None, locked=False):
    """Seed a Week row directly via the ORM, bypassing the overlap guard -- used to
    construct existing/legacy weeks, matching test_issue_84_week_management_editing.py's
    `_make_week` helper."""
    now = int(time.time())
    w = Week(
        label=label,
        start_time=start_time if start_time is not None else now,
        end_time=end_time if end_time is not None else now + 86400,
        is_locked=locked,
    )
    db.add(w)
    db.flush()
    return w


# ---------------------------------------------------------------------------
# Story: Monday-Start, Sunday-End Weeks Never Overlap by Default
# ---------------------------------------------------------------------------

class TestMondayStartSundayEndWeeksNeverOverlapByDefault:
    def test_derive_week_times_monday_start_stores_three_am_utc(self):
        """Selecting a Monday as start_date stores start_time = that Monday at
        03:00:00 UTC (not 00:00:00 UTC) -- 2026-09-14 is a Monday."""
        start_time, _ = _derive_week_times("2026-09-14", None)
        expected = int(datetime.datetime(2026, 9, 14, 3, 0, 0,
                                          tzinfo=datetime.timezone.utc).timestamp())
        assert start_time == expected

    def test_derive_week_times_sunday_end_stores_following_monday_two_fifty_nine_fifty_nine_utc(self):
        """Selecting a Sunday as end_date stores end_time = the following Monday at
        02:59:59 UTC (not 03:00:00 UTC) -- 2026-09-20 is a Sunday, so end_time lands
        one second before the next Monday-start week's start_time, contiguous with no
        gap and no overlap."""
        _, end_time = _derive_week_times(None, "2026-09-20")
        expected = int(datetime.datetime(2026, 9, 21, 2, 59, 59,
                                          tzinfo=datetime.timezone.utc).timestamp())
        assert end_time == expected

        # One second before the next Monday-start week's start_time.
        next_start_time, _ = _derive_week_times("2026-09-21", None)
        assert end_time == next_start_time - 1

    def test_create_week_monday_sunday_span_then_next_monday_week_not_rejected(self, db):
        """A week created via POST /admin/weeks (create_week) for a normal
        Monday-start/Sunday-end span (2026-09-14 to 2026-09-20), immediately followed
        by creating a second week starting the next Monday (2026-09-21), is accepted
        without triggering the overlap guard -- no manual raw-timestamp workaround
        needed for routine weekly scheduling."""
        week1 = create_week(
            WeekCreateBody(label="Week 1", start_date="2026-09-14", end_date="2026-09-20"),
            db=db, admin=_ADMIN,
        )
        # Should not raise -- the second week's start_time abuts (does not overlap)
        # the first week's end_time.
        week2 = create_week(
            WeekCreateBody(label="Week 2", start_date="2026-09-21", end_date="2026-09-27"),
            db=db, admin=_ADMIN,
        )
        assert week2["start_time"] == week1["end_time"] + 1

    def test_match_starting_two_fifty_nine_fifty_nine_after_end_date_still_resolves_to_ending_week(self, db):
        """A synthetic match with start_time = 02:59:59 UTC the Monday after the
        nominal end_date (one second before the next week's start_time) still falls
        inside the ending week's range under the existing BETWEEN-based scoring
        queries (`m.start_time BETWEEN wk.start_time AND wk.end_time`), preserving the
        existing grace-period intent for a match that runs past midnight from a
        Sunday-night start."""
        week1 = create_week(
            WeekCreateBody(label="Week 1", start_date="2026-09-14", end_date="2026-09-20"),
            db=db, admin=_ADMIN,
        )
        week2 = create_week(
            WeekCreateBody(label="Week 2", start_date="2026-09-21", end_date="2026-09-27"),
            db=db, admin=_ADMIN,
        )
        match_start = week1["end_time"]  # 2026-09-21 02:59:59 UTC
        m = Match(match_id=1, start_time=match_start, radiant_win=True)
        db.add(m)
        db.commit()

        row = db.execute(text("""
            SELECT wk.id FROM weeks wk, matches m
            WHERE m.match_id = :match_id
              AND m.start_time BETWEEN wk.start_time AND wk.end_time
        """), {"match_id": 1}).fetchone()

        assert row is not None
        assert row[0] == week1["id"]
        assert row[0] != week2["id"]

    def test_derive_week_times_non_monday_non_sunday_selection_gets_same_formula(self):
        """Non-Monday start_date / non-Sunday end_date selections still get the same
        03:00:00 UTC start / (+1 day) 02:59:59 UTC end treatment -- this is a blanket
        formula change, not a restriction on or special-case of which days can be
        chosen."""
        # 2026-09-16 is a Wednesday, 2026-09-17 is a Thursday.
        start_time, end_time = _derive_week_times("2026-09-16", "2026-09-17")
        expected_start = int(datetime.datetime(2026, 9, 16, 3, 0, 0,
                                                tzinfo=datetime.timezone.utc).timestamp())
        expected_end = int(datetime.datetime(2026, 9, 18, 2, 59, 59,
                                              tzinfo=datetime.timezone.utc).timestamp())
        assert start_time == expected_start
        assert end_time == expected_end

    def test_existing_week_rows_are_unchanged_by_the_formula_change(self, db):
        """A week seeded directly with the old formula's timestamps (start_time at
        00:00:00 UTC, end_time at 03:00:00 UTC the day after end_date) is left
        untouched by the change -- no migration is run, and the new
        `_derive_week_times` formula only affects timestamps computed for new
        create/edit calls going forward, not already-stored rows."""
        old_start = int(datetime.datetime(2026, 8, 3, 0, 0, 0,
                                           tzinfo=datetime.timezone.utc).timestamp())
        old_end = int(datetime.datetime(2026, 8, 10, 3, 0, 0,
                                         tzinfo=datetime.timezone.utc).timestamp())
        legacy_week = _make_week(db, label="Legacy Week", start_time=old_start, end_time=old_end)
        db.commit()

        stored = db.get(Week, legacy_week.id)
        assert stored.start_time == old_start
        assert stored.end_time == old_end

    def test_create_week_genuinely_overlapping_range_is_still_rejected_with_409(self, db):
        """Failure path: the formula change does not weaken the overlap guard itself
        -- a new week whose range genuinely overlaps an existing week's (not merely
        abutting/contiguous, e.g. it starts mid-week inside an already-created
        Monday-Sunday week's range) is still rejected by POST /admin/weeks
        (create_week) with a 409 naming the conflicting week."""
        create_week(
            WeekCreateBody(label="Week 1", start_date="2026-09-14", end_date="2026-09-20"),
            db=db, admin=_ADMIN,
        )

        with pytest.raises(HTTPException) as exc:
            create_week(
                WeekCreateBody(label="Mid-Week Overlapper", start_date="2026-09-16", end_date="2026-09-22"),
                db=db, admin=_ADMIN,
            )

        assert exc.value.status_code == 409
        assert "Week 1" in exc.value.detail
