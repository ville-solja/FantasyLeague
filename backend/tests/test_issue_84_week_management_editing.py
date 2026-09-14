"""
Tests for plan-issue-84-week-management-editing.md (resolves GitHub issues #84 and #104).

Covers all four user stories from the plan. Backend acceptance criteria (the overlap guard
on POST/PATCH /admin/weeks, and get_current_week()'s tie-break during legacy overlaps) are
tested by calling the router/weeks functions directly, matching the established pattern in
test_issue_51_weekly_summary.py -- FastAPI, `routers.admin_weeks`, and `weeks` all import
cleanly in this environment (verified fresh this session per the 2026-09-07 test-planner
lessons-learned entry), so no replicated-logic helpers are needed here, unlike the older
test_admin_week_management.py (written before that was confirmed). Frontend-only acceptance
criteria (the Nordic calendar-picker date entry, inline table editing replacing the
standalone edit form) are covered as frontend file-content assertions, following the same
established pattern (see test_issue_51_weekly_summary.py's TestViewWeeklyReport /
TestRevealWeeklyResults frontend-wiring tests).

Note: the plan's Critical Files table cites `frontend/app-admin.js` for the inline-editing
rewrite (loadAdminWeeks, openWeekEdit/saveWeekEdit/cancelWeekEdit, saveWeekChanges), but that
logic actually lives in `frontend/app-admin-weeks.js` -- `app-admin.js` was split down to
owning only the admin tab bar itself by an earlier session (see its own header comment), the
same class of stale-path drift the plan already flags and corrects for
`backend/routers/admin.py` -> `admin_weeks.py`. These stubs assert against the correct file.

  Story: Frictionless Date Entry Without Raw Backend Errors
  Story: Inline Week List Editing
  Story: Prevent Overlapping Week Date Ranges
  Story: Deterministic Current-Week Resolution During Legacy Overlaps

STATUS: stubs only -- every test body is `pytest.fail("not yet implemented")`.
The developer implementing plan-issue-84-week-management-editing.md fills these in.

Run with: cd backend && python -m pytest tests/test_issue_84_week_management_editing.py -v
"""

import os
import sys
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import Base
from models import Week
from routers.admin_weeks import create_week, edit_week, WeekCreateBody, WeekEditBody
from weeks import get_current_week

_ADMIN = {"user_id": 1, "username": "admin"}

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_INDEX_HTML_PATH = os.path.join(_FRONTEND_DIR, "index.html")
_APP_ADMIN_WEEKS_JS_PATH = os.path.join(_FRONTEND_DIR, "app-admin-weeks.js")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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
    """Seed a Week row directly via the ORM, bypassing the Story 3 overlap guard --
    used to construct existing/conflicting/legacy weeks the way
    test_admin_week_management.py's `_make_week` does, and per the plan's own
    Verification note ("seed both via raw start_time/end_time, bypassing the new
    overlap guard, to simulate a pre-existing legacy overlap")."""
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
# Story: Frictionless Date Entry Without Raw Backend Errors
# (frontend-only -- covered as file-content assertions once implemented)
# ---------------------------------------------------------------------------

class TestFrictionlessDateEntry:
    def test_date_fields_use_custom_calendar_picker_not_native_date_input(self):
        """Focusing or clicking a start/end date field opens the Nordic-format
        calendar picker (defaulting to the current month, or the field's existing
        month if a valid date is already entered) instead of relying on
        locale-dependent `<input type="date">` native rendering, so behaviour is
        identical across browsers/locales."""
        html = _read(_INDEX_HTML_PATH)
        js = _read(_APP_ADMIN_WEEKS_JS_PATH)

        # No native date input anywhere in index.html -- every date field in the
        # app (including the week-management create fields) is a plain text
        # input paired with the custom picker.
        assert 'type="date"' not in html
        assert 'id="weekStart"' in html
        assert 'id="weekEnd"' in html

        # The custom picker opens on focus/click and defaults to "now" when the
        # field is empty, or the field's own parsed month otherwise.
        assert "function _openDatePicker(" in js
        assert 'el.addEventListener("focus", () => _openDatePicker(el));' in js
        assert 'el.addEventListener("click", () => _openDatePicker(el));' in js
        assert "const base = iso ? new Date(" in js
        assert "function _initNordicDateInput(" in js
        assert "function dateInputIso(" in js
        assert "function setDateInputIso(" in js

    def test_unparseable_typed_date_is_flagged_invalid_without_raw_backend_error(self):
        """A typed value that cannot be parsed client-side is visually flagged
        invalid with a plain-language status message and blocks submission, so the
        backend's raw "Dates must be ISO format (YYYY-MM-DD)" error text is never
        surfaced to the admin through the normal UI flow."""
        js = _read(_APP_ADMIN_WEEKS_JS_PATH)

        # blur handler flags an unparseable value invalid via CSS, not a raw
        # backend round-trip.
        assert 'el.classList.toggle("invalid", !!el.value && !dateInputIso(el));' in js
        # dateInputIso() returns "" (falsy) for anything that doesn't parse,
        # which createAdminWeek()/saveWeekChanges() both check before sending
        # a request -- an invalid typed date blocks submission client-side.
        assert 'if (!start_date || !end_date) return setStatus("weeksAdminStatus"' in js
        assert "if (startEl.value && !start_date)" in js
        assert "if (endEl.value && !end_date)" in js

        # The raw backend error string is never hardcoded/echoed verbatim in the
        # frontend -- it only ever reaches the DOM via data.detail from a
        # response the client-side validation above should have already blocked.
        assert "Dates must be ISO format" not in js


# ---------------------------------------------------------------------------
# Story: Inline Week List Editing
# (frontend-only -- covered as file-content assertions once implemented)
# ---------------------------------------------------------------------------

class TestInlineWeekListEditing:
    def test_unlocked_rows_render_inline_editable_fields_with_save_changes_button(self):
        """The standalone `#weekEditForm` panel is removed; each unlocked row in
        `#adminWeeksBody` instead renders editable label/start-date/end-date inputs
        (reusing the same calendar-picker date inputs as week creation), with a
        single "Save Changes" button below the table, while locked weeks remain
        read-only in the table as before."""
        html = _read(_INDEX_HTML_PATH)
        js = _read(_APP_ADMIN_WEEKS_JS_PATH)

        # The standalone edit form panel and its old control functions are gone.
        assert "weekEditForm" not in html
        assert "weekEditForm" not in js
        assert "function openWeekEdit(" not in js
        assert "function saveWeekEdit(" not in js
        assert "function cancelWeekEdit(" not in js
        assert "editWeekId" not in js
        assert "editWeekLabel" not in js

        # A single Save Changes button lives below the table in index.html.
        assert 'id="saveWeekChangesBtn"' in html
        assert 'onclick="saveWeekChanges()"' in html

        # loadAdminWeeks() renders per-row inline inputs, reusing the same
        # date-input helpers wired for the create-week fields, and keeps locked
        # rows read-only (no editable inputs in that branch).
        assert "async function loadAdminWeeks()" in js
        assert "week-edit-label" in js
        assert "week-edit-start" in js
        assert "week-edit-end" in js
        assert "_initNordicDateInput(startEl.id)" in js
        assert "_initNordicDateInput(endEl.id)" in js
        locked_branch = js[js.index("if (w.is_locked) {") : js.index("return;\n      }")]
        assert "<input" not in locked_branch
        assert "LOCKED" in locked_branch

    def test_save_changes_submits_each_dirty_row_independently_and_reports_per_row_result(self):
        """`saveWeekChanges()` PATCHes each dirty (edited) row individually rather
        than as one batch request, so one row's rejection (e.g. an overlap) does not
        prevent the other changed rows from saving, per-row success/error is shown
        after saving, and successful saves refresh the table."""
        js = _read(_APP_ADMIN_WEEKS_JS_PATH)
        start = js.index("async function saveWeekChanges()")
        end = js.index("\n}\n", start)
        body = js[start:end]

        # Rows are only submitted once the admin has actually touched them
        # (tracked via a per-row dirty flag set by _markWeekRowDirty()).
        assert '#adminWeeksBody tr[data-dirty="1"]' in body
        assert "function _markWeekRowDirty(" in js

        # Each dirty row is PATCHed individually inside a loop, with its own
        # try/catch, rather than batched into one request -- so one row's
        # rejection is caught and recorded without stopping the loop.
        assert "for (const tr of dirtyRows)" in body
        assert "await fetch(`${API}/admin/weeks/${id}`" in body
        assert "method: \"PATCH\"" in body
        assert "failures.push(" in body
        assert "break" not in body  # a failure never aborts the remaining rows

        # A per-row-result summary is reported and the table is refreshed after
        # saving.
        assert "updated, ${failures.length} failed" in body
        assert "setStatus(\"weeksAdminStatus\", summary" in body
        assert "loadAdminWeeks();" in body


# ---------------------------------------------------------------------------
# Story: Prevent Overlapping Week Date Ranges
# ---------------------------------------------------------------------------

class TestPreventOverlappingWeekDateRanges:
    def test_create_week_rejects_overlapping_range_with_409_naming_conflicting_week(self, db):
        """POST /admin/weeks (create_week) rejects a new week whose [start_time,
        end_time) range overlaps any existing week's range -- including a locked
        one, since the overlap check runs regardless of lock status -- raising a 409
        whose error detail names the conflicting week's label."""
        now = int(time.time())
        _make_week(db, label="Locked Week", start_time=now, end_time=now + 86400, locked=True)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_week(
                WeekCreateBody(label="Overlapper", start_time=now + 3600, end_time=now + 7200),
                db=db, admin=_ADMIN,
            )

        assert exc.value.status_code == 409
        assert "Locked Week" in exc.value.detail

    def test_edit_week_allows_unchanged_own_range_and_exact_boundary_abutment(self, db):
        """PATCH /admin/weeks/{id} (edit_week) does not treat a week's own unchanged
        range as overlapping itself (the overlap check excludes the week being
        edited), and a range that exactly abuts another week's (its end_time equals
        the other's start_time) is accepted rather than rejected as an overlap."""
        now = int(time.time())
        week1 = _make_week(db, label="Week 1", start_time=now, end_time=now + 3600)
        week2 = _make_week(db, label="Week 2", start_time=now + 90000, end_time=now + 180000)
        db.commit()

        # Editing week1 with its own unchanged range must not self-conflict.
        result = edit_week(
            week1.id, WeekEditBody(start_time=now, end_time=now + 3600),
            db=db, admin=_ADMIN,
        )
        assert result["start_time"] == now
        assert result["end_time"] == now + 3600

        # Extending week1's end_time so it exactly equals week2's start_time is
        # an abutment, not an overlap, and must be accepted.
        result2 = edit_week(
            week1.id, WeekEditBody(end_time=now + 90000),
            db=db, admin=_ADMIN,
        )
        assert result2["end_time"] == now + 90000
        assert db.get(Week, week2.id).start_time == now + 90000


# ---------------------------------------------------------------------------
# Story: Deterministic Current-Week Resolution During Legacy Overlaps
# ---------------------------------------------------------------------------

class TestDeterministicCurrentWeekResolution:
    def test_get_current_week_returns_the_containing_week_when_ranges_do_not_overlap(self, db):
        """With normal, non-overlapping week data, get_current_week()'s added
        ordering (`.order_by(Week.start_time.desc())`) does not change the result --
        it still returns the one week whose range actually contains `now`."""
        now = int(time.time())
        _make_week(db, label="Past", start_time=now - 10000, end_time=now - 5000, locked=True)
        current = _make_week(db, label="Current", start_time=now - 100, end_time=now + 100)
        _make_week(db, label="Future", start_time=now + 5000, end_time=now + 10000)
        db.commit()

        result = get_current_week(db)

        assert result is not None
        assert result.id == current.id
        assert result.label == "Current"

    def test_get_current_week_resolves_to_later_starting_week_during_legacy_overlap(self, db):
        """Reproducing the real issue #104 data shape -- two weeks seeded with raw
        start_time/end_time (bypassing the Story 3 guard) so their ranges overlap by
        the 3-hour end-of-week grace window, the previous week's end_time landing
        after the next week's start_time -- get_current_week() deterministically
        returns the week with the later start_time (the newly-starting week) during
        that overlap window, not the ending one."""
        now = int(time.time())
        # "Week 1" ends 3 hours into "Week 2" (the issue #104 grace-window
        # overlap) -- `now` falls inside both ranges.
        week1 = _make_week(db, label="Week 1", start_time=now - 500000, end_time=now + 100)
        week2 = _make_week(db, label="Week 2", start_time=now - 50, end_time=now + 500000)
        db.commit()

        # Sanity: both ranges genuinely contain `now`, confirming this is the
        # overlap scenario the tie-break exists for.
        assert week1.start_time <= now <= week1.end_time
        assert week2.start_time <= now <= week2.end_time
        assert week2.start_time > week1.start_time

        result = get_current_week(db)

        assert result is not None
        assert result.id == week2.id
        assert result.label == "Week 2"
