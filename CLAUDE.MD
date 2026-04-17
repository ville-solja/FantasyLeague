## Documentation

The `markdown/` folder is the single source of truth for product intent. Always consult and keep these three locations up to date:

### markdown/user_stories.md
Canonical list of user stories for the whole project. Before implementing a feature, check whether it is already covered. After implementing, mark it complete and add any new stories that emerged.

### markdown/ui_description/
Short specifications for each UI tab and major component (one file per tab). Describes visible elements, table columns, button behaviours, and conditional states. When a tab changes — new element added, interaction changed, column removed — update the corresponding file. When adding a new tab or major section, create a new file here.

### markdown/feature_description/
In-depth documentation for non-trivial features and mechanics (e.g. card rarity system, weekly roster locking, scoring weights). When implementing a feature with enough complexity to warrant explanation, create or update a file here. The README should link to these rather than duplicate their content.

When a suitably large or complex subject is identified during implementation, ask the user whether a feature description document should be created.

## Readme
The README should stay reasonably sized with links to the markdown documentation. Do not duplicate content that belongs in `markdown/feature_description/`.

---

## Developer Agents

Slash commands are available for feature planning and ongoing quality checks. Run them in Claude Code by typing the command name.

### `/new-feature`
Formalises the creation of a new feature in one step. Given a feature description as the argument, it:
- Reads `markdown/user_stories.md` to assign the correct next section number
- Drafts 2–5 user stories in the project's standard format
- Writes a plan file to `markdown/plans/plan-{slug}.md` (with user stories embedded)
- Appends the stories to `markdown/user_stories.md` (TOC entry + body)
- Creates a stub in `markdown/feature_description/{slug}.md`

**When to run:** At the start of any new feature, before writing any implementation code.

**Usage:** `/new-feature <description>` — e.g. `/new-feature Add a weekly summary email to notify users of their points`

---

### `/api-audit`
Scans all FastAPI endpoints in `backend/main.py` for:
- Missing authentication (`Depends(get_current_user)` / `Depends(require_admin)`)
- Leaked DB sessions (`SessionLocal()` without try/finally)
- Request body fields with no Pydantic `Field()` length constraints
- Endpoints returning raw SQLAlchemy objects (data over-exposure)

**When to run:** Before pushing any change to `backend/main.py`.

---

### `/doc-sync`
Compares `markdown/feature_description/*.md` against the actual backend implementation. Reports:
- Features described in docs with no corresponding endpoint or model
- Backend systems with no documentation counterpart
- Env vars in `.env.example` not mentioned in any doc

**When to run:** After a significant backend change, or before writing a new plan.

---

### `/score-check`
Validates the fantasy scoring pipeline without running the code:
- Checks that every stat in `SCORING_STATS` has a matching `PlayerMatchStats` field
- Traces `fantasy_score()` and `card_fantasy_score()` with synthetic inputs and shows expected output
- Verifies `run_enrichment()` applies updates correctly and without double-counting
- Flags division-by-zero risks or unconstrained `CardModifier.stat_key` values

**When to run:** After any change to `backend/scoring.py`, `backend/enrich.py`, or the `WEIGHTS_JSON` env var.

---

### `/story-check`
Maps each entry in `markdown/user_stories.md` to the implementation and marks it as Fully implemented / Partial / Missing. Produces a coverage percentage and a prioritised list of gaps.

**When to run:** Before sprint reviews or feature planning sessions. A CI version also runs automatically on GitHub Actions (`story-report.yml`) and commits its output to `markdown/story-report.md`.

---

### `/run-tests`
Runs the pytest suite in `backend/tests/` and reports results grouped by module.
- Covers `scoring.py` (unit tests for `fantasy_score` and `card_fantasy_score`)
- Covers `weeks.py` (fixture tests with in-memory SQLite for `generate_weeks` and `auto_lock_weeks`)
- Covers `auth.py` (bcrypt hash/verify round-trips)

**When to run:** After any change to `backend/scoring.py`, `backend/weeks.py`, or `backend/auth.py`. Also useful as a quick sanity check before pushing.

---

### `/architect`
Reviews the full application architecture and produces a prioritised findings table covering:
- Separation of concerns (business logic mixed into request handlers, repeated query patterns)
- Data layer risks (N+1 queries, missing indexes, SQLite write-serialisation limits)
- Background job resilience (exception handling in `_week_maintenance_loop` and `_ingest_poll_loop`)
- Error handling and observability (print vs logging, unhandled 500 paths)
- Security posture (SQL injection in raw `text()` queries, insecure `SECRET_KEY` defaults, session config)
- Dependency and configuration hygiene (hardcoded values, unpinned packages, missing health check)
- Frontend structure (split points in `app.js`, async state management)

Each finding is classified **High / Medium / Low** and includes a concrete recommendation. The report ends with the top 3 highest-impact changes in priority order.

**When to run:** Before a refactor, after a significant feature addition, or when onboarding a new contributor.

**Usage:** `/architect` — no arguments needed.

---

### Scheduled: Dependency Scout
A weekly scheduled job (runs Monday 09:23) checks every pinned package in `backend/requirements.txt` against PyPI and flags outdated or security-relevant versions. It is session-scoped — re-register it at the start of a session with:

```
/schedule weekly dep check on Monday mornings
```

Or run an ad-hoc check any time by asking: *"Check backend/requirements.txt packages for CVEs."*