# Plan: Container Health Check

## Context
The issue asks for containers to report their health "in one way or another" and for the
options to be evaluated before picking one — not a specific implementation to build directly.
This app already has a `GET /health` endpoint and a `healthcheck:` block in
`docker-compose.yml`, but neither has been re-examined since they were added: `GET /health`
unconditionally returns `{"status": "ok"}` with no dependency check, and the compose
healthcheck's `test` command depends on `curl`, which is not installed anywhere in
`backend/Dockerfile`'s `apt-get install` list — `python:3.11-slim` does not ship `curl` by
default, so the existing healthcheck likely fails outright rather than reporting real status.
Like `plan-frontend-framework-evaluation.md`, this plan first documents an options comparison
grounded in the codebase's actual current state, then gates any Dockerfile/backend change
behind explicit review and approval of that recommendation.

*Resolves GitHub issue #96.*

## User Stories

### Evaluate Container Health-Check Options
**User story**
As an operator/hoster, I want a documented comparison of container health-reporting approaches
for this app, grounded in what's actually in the Docker/Compose setup today, so I can be
confident the chosen approach actually detects failure rather than always reporting healthy.

**Acceptance criteria**
- Doc inventories the current state: `GET /health`'s actual behavior (unconditional
  `{"status": "ok"}`, no dependency check), the existing `docker-compose.yml` `healthcheck:`
  block (test command, interval, timeout, retries, start_period), and confirms whether
  `docker-compose.dev.yml` inherits it via Compose file merge
- Doc flags the concrete risk found in the current setup: the healthcheck's `test` command
  depends on `curl`, which is not installed in the image built by `backend/Dockerfile`
- Doc compares at least three concrete options: (a) status quo — compose-level healthcheck
  only, orchestrator-dependent; (b) a `HEALTHCHECK` instruction baked into `backend/Dockerfile`
  itself, so it works under any orchestrator and not only via this repo's Compose files; (c)
  deepening `GET /health` to verify a real dependency (DB connectivity) instead of just
  process liveness
- Doc ends with one clear recommendation and explicitly states no Dockerfile/backend change
  happens until the user reviews and approves it

### Implement the Recommended Health Check *(not yet implemented)*
**User story**
As an operator, I want the recommended health-check approach actually implemented, so
containers accurately report health to whatever monitoring or orchestration the hoster uses.

**Acceptance criteria**
- `GET /health` reflects real service health (e.g. a lightweight DB connectivity check)
  without becoming a performance or availability risk (no heavy queries, fast timeout, a
  dependency failure returns a non-2xx status rather than raising an unhandled exception)
- A `HEALTHCHECK` instruction is added to `backend/Dockerfile` so the built image reports
  health under any orchestrator, not only via this repo's `docker-compose.yml`
- The healthcheck command does not depend on a binary absent from the image — either install
  `curl` explicitly in the Dockerfile, or use a dependency-free Python-based check
- `docker-compose.yml`'s existing `healthcheck:` block is updated to match (or removed if the
  Dockerfile-level one alone is judged sufficient), so there is no conflicting or silently
  broken duplicate definition
- `markdown/features/reference/commands.md`'s Docker section documents how an operator checks
  health status (`docker compose ps`, `docker inspect --format='{{json .State.Health}}'`)

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `markdown/features/reference/container-health-check.md` | The evaluation document (this plan's first story) |
| `backend/main.py` | *(pending approval)* Deepen `GET /health` to check DB connectivity |
| `backend/Dockerfile` | *(pending approval)* Add a `HEALTHCHECK` instruction |
| `docker-compose.yml` | *(pending approval)* Align/replace the existing `healthcheck:` block |
| `markdown/features/reference/commands.md` | *(pending approval)* Document how to check container health status |

### Step 1 — Write the evaluation document
Covered directly by `markdown/features/reference/container-health-check.md` — no code changes.

### Step 2 — (Gated) Deepen `GET /health`
Only after approval. Sketch, following this codebase's existing `Depends(get_db)` /
try-except-with-typed-error-response conventions (see `backend/routers/admin_ingest.py`'s
`schedule_debug` for the "log full exception, return only the error type" pattern used
elsewhere for diagnostic endpoints):

```python
@app.get("/health")
def health(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check DB connectivity failure")
        return JSONResponse(status_code=503, content={"status": "error"})
    return {"status": "ok"}
```

### Step 3 — (Gated) Dockerfile `HEALTHCHECK` + Compose alignment
Only after approval. Add to `backend/Dockerfile` (dependency-free — no new `apt-get install`
needed since Python is already present in the image):

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1
```

Update or remove `docker-compose.yml`'s `healthcheck:` block to match, so the two definitions
don't silently diverge (Compose's `healthcheck:` overrides the image's `HEALTHCHECK` when both
are present).

---

## Verification
- Confirm today's behavior first, before changing anything: run
  `docker compose up -d && docker compose ps` and check whether the `backend` service actually
  reaches a `healthy` state, or stays `starting`/`unhealthy` — this confirms or disproves the
  suspected missing-`curl` issue without guessing
- After implementing (Step 2): stop the container's access to its DB file (e.g. temporarily
  `chmod 000` the SQLite file in a throwaway test) and confirm `GET /health` returns 503, then
  restore access and confirm it returns 200 again
- After implementing (Step 3): `docker inspect --format='{{json .State.Health}}' <container>`
  shows a real `Healthy`/`Unhealthy` status under a plain `docker run` (no Compose), proving
  the check is orchestrator-independent
- Confirm `docker-compose.dev.yml` still passes through the (possibly updated) healthcheck
  correctly when both compose files are merged
