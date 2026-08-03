# Plan: Week Management Inline Editing & Overlap Guard

## Context

Issue #84 reports that the Week Management admin tool has three problems: the date fields
don't reliably open a picker and can surface the backend's raw
`"Dates must be ISO format (YYYY-MM-DD)"` error to the admin; editing a week requires opening
a separate form lower on the page instead of editing in place in the weeks table; and nothing
stops an admin from creating or editing a week so its date range overlaps another week's,
which would let a single calendar day belong to two weeks at once and double-count (or
mis-count) scoring.

The date-entry problem is largely already addressed by work done earlier in this session: the
Week Management create/edit date fields were rebuilt as a self-contained calendar-picker
component (`frontend/app-admin.js`: `dateInputIso()` / `setDateInputIso()` / `_openDatePicker()`
et al.) that displays and accepts the Nordic `d.m.yyyy` format (e.g. `15.5.2026`) and always
converts to strict ISO `yyyy-mm-dd` before the request leaves the browser — so the raw backend
error text should no longer reach the admin in the normal flow. This plan's first story
formalises that as a testable contract (so a regression is caught) rather than re-implementing
it. The remaining two problems — inline table editing and overlap prevention — are net-new work
covered by stories 2 and 3.

Assumptions (flagged for review):
- "Saving the changes on a button low on the page" is read as a single bulk **Save Changes**
  button below the weeks table that submits every edited (dirty) row, rather than a per-row
  save button. Each dirty row is still submitted as an individual `PATCH /admin/weeks/{id}`
  call (the endpoint already validates lock status and, after this plan, overlap) so one row's
  failure doesn't block the others — no new bulk endpoint is introduced.
- Overlap is checked as a half-open interval `[start_time, end_time)` against every other week
  regardless of lock status: a locked week's dates are historical fact and must still be
  respected by new/edited unlocked weeks.
- The picker/format work already in `app-admin.js` is left as-is; only the parts needed to make
  it verifiably error-free (client-side validation before submit, invalid-input styling) are
  called out as acceptance criteria.

Resolves GitHub issue #84.

---

## User Stories

### Frictionless Date Entry Without Raw Backend Errors
**User story**
As an admin, I want to enter week start/end dates in a familiar calendar-based way and never
see a raw backend error message so that scheduling a week doesn't require knowing the internal
ISO date format.

**Acceptance criteria**
- Clicking or focusing a start/end date field opens a calendar picker defaulting to the current
  month, or the field's existing month if a valid date is already entered
- Typed dates are parsed and validated entirely client-side; the request sent to the backend is
  always well-formed ISO `YYYY-MM-DD` or the field is blocked from submitting
- If a typed value cannot be parsed, the field is visually flagged invalid with a plain-language
  status message instead of submitting and surfacing the backend's
  `"Dates must be ISO format (YYYY-MM-DD)"` text
- Behaviour is identical across browsers/locales — it does not rely on `<input type="date">`'s
  locale-dependent native rendering

### Inline Week List Editing
**User story**
As an admin, I want to edit a week's label and date range directly in the weeks table so that
I don't have to open a separate edit panel lower on the page.

**Acceptance criteria**
- The standalone edit form below the weeks table is removed
- Each unlocked week's row in the table has editable label, start date, and end date fields,
  using the same calendar-picker date inputs as week creation
- Locked weeks remain read-only in the table, matching current behaviour
- A single "Save Changes" button below the table submits every edited (dirty) row
- Rows with unsaved edits are visually indicated until saved (or reverted)
- Each row is saved via its own request so one row's rejection (e.g. an overlap) does not
  prevent the other changed rows from saving; per-row success/error is shown after saving
- Successful saves refresh the table and are logged to the audit log, one entry per changed week

### Prevent Overlapping Week Date Ranges
**User story**
As an admin, I want the system to reject a week create/edit that would make any calendar day
belong to two weeks at once so that scoring windows never conflict.

**Acceptance criteria**
- `POST /admin/weeks` rejects a new week whose `[start_time, end_time)` range overlaps any
  existing week's range, with a `409` and an error naming the conflicting week's label
- `PATCH /admin/weeks/{id}` rejects an edit whose resulting range would overlap any other
  week's range (excluding the week being edited itself), same error shape
- The overlap check runs against all weeks regardless of locked status
- Existing non-overlapping create/edit flows are unaffected — a week that exactly abuts another
  (its `end_time` equals the other's `start_time`) is not treated as an overlap

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/admin.py` | Add `_check_week_overlap(db, start_time, end_time, exclude_week_id=None)` helper; call it from `create_week` and `edit_week` after deriving/resolving the final `start_time`/`end_time`, before commit |
| `frontend/index.html` | Remove the `#weekEditForm` panel; make each unlocked row in the admin weeks table (`#adminWeeksBody`) render editable label/start/end inputs; add a "Save Changes" button and status area below the table |
| `frontend/app-admin.js` | Rewrite `loadAdminWeeks()` to render inline-editable rows for unlocked weeks (reusing `_initNordicDateInput`, `dateInputIso`, `setDateInputIso` already built for the create form); track dirty rows; replace `openWeekEdit` / `saveWeekEdit` / `cancelWeekEdit` with a `saveWeekChanges()` that loops dirty rows and `PATCH`es each individually |
| `markdown/features/reference/admin-week-management.md` | Document the inline-edit UX and the overlap error shape |

### Step 1 — Backend: overlap guard

Add a helper next to `_derive_week_times`:

```python
def _check_week_overlap(db, start_time: int, end_time: int, exclude_week_id: int | None = None):
    q = db.query(Week).filter(Week.start_time < end_time, Week.end_time > start_time)
    if exclude_week_id is not None:
        q = q.filter(Week.id != exclude_week_id)
    conflict = q.first()
    if conflict:
        raise HTTPException(
            status_code=409,
            detail=f'Overlaps existing week "{conflict.label}"',
        )
```

Call it in `create_week` after `start_time`/`end_time` are resolved and the
`end_time > start_time` check passes. Call it in `edit_week` the same way, passing
`exclude_week_id=week_id`, using the final resolved `w.start_time`/`w.end_time` (i.e. after
applying whichever of `date_start`/`body.start_time` etc. won).

### Step 2 — Frontend: inline table editing

- In `index.html`, drop the `#weekEditForm` block entirely. Add editable `label`, start-date,
  and end-date inputs to each unlocked row rendered in `#adminWeeksBody` (locked rows keep their
  current read-only rendering). Add a "Save Changes" button and a status line below the table.
- In `app-admin.js`, `loadAdminWeeks()` renders those inputs per unlocked row instead of plain
  text, wiring each date input through `_initNordicDateInput`/`dateInputIso`/`setDateInputIso` so
  it gets the same picker and validation as the create-week fields. Track which rows have been
  changed (e.g. a `data-dirty` flag set on input) so `saveWeekChanges()` only submits rows the
  admin actually touched.
- `saveWeekChanges()` iterates dirty rows, calling `PATCH /admin/weeks/{id}` for each with
  whatever of label/start_date/end_date changed, collecting per-row results, and reporting a
  summary (`N updated, M failed: <reasons>`) rather than aborting on the first failure.
- Remove `openWeekEdit`, `saveWeekEdit`, `cancelWeekEdit`, and the now-unused
  `editWeekId`/`editWeekLabel`/`editWeekStart`/`editWeekEnd`/`weekEditForm` element references.

### Step 3 — Documentation

Update `markdown/features/reference/admin-week-management.md`'s Overview to describe inline
table editing (replacing the "adjust unlocked weeks" phrasing that implied a separate form) and
add the overlap-rejection behaviour to the `POST`/`PATCH /admin/weeks` endpoint descriptions.

---

## Verification

- Existing week-management tests in `backend/tests/test_issue_81_season_lifecycle.py`
  (`TestManualWeekCreationDateOnly`) still pass.
- New backend tests: creating a week overlapping an existing one returns 409; editing a week to
  overlap another returns 409; editing a week's own unchanged range against itself does not
  false-positive as an overlap; a week that exactly abuts another (touching boundary, no
  overlap) is accepted.
- Manual/UI check: confirm the standalone edit form is gone, unlocked rows are editable in
  place, locked rows remain read-only, and "Save Changes" reports per-row success/failure when
  one edited row is deliberately made to overlap another.
- Confirm no code path can still surface the raw
  `"Dates must be ISO format (YYYY-MM-DD)"` string to the admin through the UI.
