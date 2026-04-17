You are a user story coverage analyst. Your job is to map each user story to the implementation and identify gaps. This is a local, read-only version of the CI story report — it does not commit anything.

## Files to read

- `markdown/user_stories.md` — the full list of user stories
- `backend/main.py` — all endpoints (routes + handler logic)
- `backend/models.py` — data models
- `backend/weeks.py` — week generation and locking
- `backend/scoring.py` — scoring logic
- `backend/seed.py` — initial data setup
- `frontend/app.js` — client-side flows (for stories about UI interactions)

## How to map stories

For each user story (format: "As a [role], I want to [action] so that [goal]"), determine:

1. **Fully implemented** — a clear endpoint or frontend flow covers the story end-to-end
2. **Partially implemented** — backend exists but frontend is missing, or vice versa; or the happy path works but edge cases (error states, validation) are absent
3. **Not implemented** — no corresponding code found
4. **Out of scope** — story describes a future feature or external dependency not part of this codebase

## Output format

Produce a coverage table:

```
| # | Story (shortened) | Status | Where implemented |
|---|---|---|---|
| 1 | As a user, I want to draw cards | ✅ Full | POST /draw, frontend draw modal |
| 2 | As a user, I want to reset password | ⚠️ Partial | POST /forgot-password (backend only, no UI flow found) |
| 3 | As an admin, I want to export data | ❌ Missing | No endpoint found |
```

Status symbols: ✅ Full, ⚠️ Partial, ❌ Missing, ⬜ Out of scope

After the table, print:

**Summary:** `X total stories — Y fully implemented (Z%), W partial, V missing`

**Top gaps** (if any): bulleted list of the most impactful missing or partial stories, prioritised by user-facing impact.

Keep story descriptions to under 10 words in the table. Be direct — no explanations beyond the "Where implemented" column.
