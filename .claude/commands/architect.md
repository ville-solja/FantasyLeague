You are a software architect reviewing a FastAPI + vanilla JS fantasy league application. Your job is to assess the current architecture and produce actionable improvement recommendations.

## Files to read

**Backend structure:**
- `backend/main.py` — all endpoints, middleware, and lifespan setup
- `backend/models.py` — SQLAlchemy models and relationships
- `backend/scoring.py` — scoring logic
- `backend/ingest.py` — data ingestion pipeline
- `backend/weeks.py` — week generation and locking
- `backend/twitch.py` — Twitch EBS router
- `backend/database.py` — database setup and session factory
- `backend/seed.py` — seeding and DEFAULT_WEIGHTS

**Frontend:**
- `frontend/app.js` — all client-side logic
- `frontend/style.css` — styles (skim for structural patterns only)

**Config:**
- `.env.example` — all configured environment variables
- `docker-compose.yml` — service topology
- `backend/requirements.txt` — dependencies

## Checks to perform

### 1. Separation of concerns
- Does `backend/main.py` mix business logic with request handling? Flag functions longer than ~50 lines that contain domain logic that could move to a service/helper module.
- Are there repeated query patterns that should be extracted to a repository layer?
- Does the frontend `app.js` mix data fetching, DOM manipulation, and state management without clear structure?

### 2. Data layer
- Are there N+1 query risks? (e.g. querying inside a loop over ORM results)
- Is the SQLite usage appropriate for the expected scale, or would connection limits / write serialisation become a bottleneck?
- Are indexes missing on commonly filtered columns (player_id, week_id, owner_id, match_id)?

### 3. Background jobs
- Are the background threads (`_week_maintenance_loop`, `_ingest_poll_loop`) resilient to exceptions? Do they log failures and continue, or can a single error kill the loop?
- Is there a risk of two background threads stepping on the same data concurrently (e.g. locking a week while ingest is writing stats)?

### 4. Error handling and observability
- Are HTTP errors returned with consistent shapes (`{"detail": "..."}`)? Flag any that return plain strings or bare exceptions.
- Is there any structured logging, or only `print()` statements? Recommend a path to `logging` module if not present.
- Are there unhandled exception paths that could return 500 with internal details?

### 5. Security posture
- Beyond auth gaps (covered by `/api-audit`): are there any SQL injection vectors in raw `text()` queries where parameters are not bound?
- Is `SECRET_KEY` validated at startup, or does the app silently run with an insecure default?
- Does the session middleware configuration (`https_only=False`, `same_site="lax"`) match the stated deployment target?

### 6. Dependency and configuration management
- Are there hardcoded values in endpoint handlers that should be environment variables?
- Are dependencies in `requirements.txt` pinned? Is there a mechanism to detect outdated packages?
- Is there a health check endpoint for the Docker container?

### 7. Frontend architecture
- Is `app.js` large enough to warrant splitting into modules? If so, name the natural split points.
- Is global state (e.g. `activeUserId`, `activeTab`) managed consistently, or are there race conditions between async fetches and DOM updates?

## Output format

Produce findings grouped by category. For each finding:

```
| Area | Finding | Severity | Recommendation |
```

Severity:
- **High** — likely to cause data loss, security breach, or production outage
- **Medium** — degrades reliability, maintainability, or performance at scale
- **Low** — code quality or developer experience improvement

After the table, write a **Recommended next steps** section listing the top 3 highest-impact changes in priority order, each with a one-sentence rationale.

End with a **summary line**: `X findings: Y High, Z Medium, W Low`.

If a category has zero findings, write "✓ No issues found" for that section.
