# Table Element Sortability

Client-side sortable column headers for the Players tab table, letting users rank players
by any displayed stat with a single click.

---

## How it works

Clicking a `<th>` header in the Players table triggers a client-side re-sort of the
rendered rows. No new API calls are made — all data is already in the DOM or in the
in-memory player array fetched on tab load.

Sort state is tracked in a module-level object (`{ col, dir }`). On each click the
comparator is applied to the in-memory rows array and the table is re-rendered.

## Visual indicator

The active sort column gets a CSS pseudo-element arrow:
- `th.sort-desc::after` → ` ↓` (highest first — default for numeric columns)
- `th.sort-asc::after` → ` ↑` (lowest first / A → Z for text columns)

All other headers show no arrow. The cursor changes to `pointer` on sortable headers.

## Column type map

| Column | Type | Default direction |
|---|---|---|
| Player name | string | ascending |
| Team | string | ascending |
| Matches | number | descending |
| Avg pts | number | descending |
| Total pts | number | descending |
| MVPs | number | descending |

These match `GET /players`'s actual response fields (`name`, `team_name`, `matches`,
`avg_points`, `total_points`, `mvp_count`) — there is no per-stat kills/deaths/assists/GPM
average anywhere in that response; only the aggregate fantasy-point averages and MVP count.
