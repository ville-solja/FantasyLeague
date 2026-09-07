# Schedule tab

Visible to everyone. Loads data from a structured JSON fixtures feed (`SCHEDULE_FIXTURES_URL`)
when configured, otherwise a public Google Sheets CSV export; the parsed result is cached in
memory and the response shape is identical for both sources. See
`markdown/features/reference/schedule-fixtures-api.md`.

## Season Schedule panel

Shows all series (fixtures) for the season in a single chronological list spanning both divisions.

### Layout

- **Upcoming** series appear at the top, sorted farthest future first. Each shows planned date, home vs. away team names, and a stream link where available. A fixture with no confirmed date/time yet (JSON feed source, `scheduled: false`) is grouped under the Monday of its week and shows "Time TBD" instead of a specific time.
- **Past** series appear below upcoming, sorted most recent first. Each shows:
  - Actual match start timestamp (from the database, not the planned date).
  - Series result (e.g. "2–0" or "1–1"), resolved from match outcomes in the database.
  - VOD link where available.
- Series with no database match (unresolved result) show "vs" and the planned date.

### Stale notice

If the cached schedule is older than a threshold, a notice is shown prompting a refresh.

Team name matching between the schedule source and the database is fuzzy (case-insensitive, ignores parenthetical content, substring fallback). Div 2 teams without an OpenDota team_id are matched via stored team name fields on match records.
