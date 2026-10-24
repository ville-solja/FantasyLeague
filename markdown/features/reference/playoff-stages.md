# Playoff Stages

A stage is a kind of fantasy week for playoff rounds that don't follow the weekly rhythm, such as semifinals and grand finals played at different paces by the two divisions (issue #222). A stage locks at its own start and scores only the series assigned to it. Plan: `markdown/plans/plan-issue-222-playoff-stages.md`.

---

## How a stage works

*(planned)* `weeks.kind` is `"week"` or `"stage"`.

- **Locking:** a stage locks at `start_time` like any week: roster snapshot, +1 token, irreversible.
- **Ending:** its `end_time` sets when the Weekly Report and bench substitution fall due.
- **Overlap:** a stage may overlap ordinary weeks and other stages.
- **Separate snapshots:** each stage snapshots the roster as it stood at its own lock. A player can therefore change their team between rounds, even while an earlier stage is still being played.

## Which matches count

*(planned)* `match_scoring.match_in_week_sql()` is the single rule. A match counts for:
- the week or stage its `week_override_id` points to; or
- when unassigned, the ordinary week whose window contains its start.

Time never places a match in a stage, so a match is never counted twice. Admins assign playoff series to stages with Admin › Matches "Move to week".

## Endpoints

### `POST /admin/weeks`, `PUT /admin/weeks/{week_id}` *(planned)*
Accept `kind`. A stage takes a start and end date and time, and skips the overlap check against ordinary weeks.

### `PUT /matches/{match_id}/week`
Unchanged; a stage's id is a valid `week_id`.

## Alternatives considered

- **One long Playoffs week:** needs no code, but locks the roster for the whole playoffs.
- **Overriding playoff series into ordinary weeks:** needs no code, but the lock times don't follow the bracket.
- **Parallel rosters per event:** too large a change to the roster model.

See the plan's Options table.

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
