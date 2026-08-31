# Container Health Check

A decision document evaluating how this app's Docker container should report its health,
grounded in what's actually in the Docker/Compose setup today rather than a generic survey of
Docker healthcheck patterns.

*(see `markdown/plans/plan-issue-96-container-health-check.md`, resolves GitHub issue #96)*

---

## Current State

**`GET /health`** (`backend/main.py`):
```python
@app.get("/health")
def health():
    return {"status": "ok"}
```
Unconditional — it never touches the database, never checks the background threads
(`_week_maintenance_loop`, `_ingest_poll_loop`, `_profile_enrichment_loop`), and cannot return
anything other than 200. This is a pure **liveness** check ("the ASGI process is accepting
HTTP requests"), not a **readiness** check ("the service can actually do its job").

**`docker-compose.yml`** already wires a healthcheck against it:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 5s
  retries: 5
  start_period: 10s
```
`docker-compose.dev.yml` does not redefine `healthcheck:`, so when both files are merged
(`docker compose -f docker-compose.yml -f docker-compose.dev.yml up`, the documented local-dev
command — see `reference/commands.md`) it inherits this same block.

**`backend/Dockerfile`** has no `HEALTHCHECK` instruction of its own — health reporting exists
only because this specific `docker-compose.yml` defines it, not as a property of the image
itself.

### Concrete risk found: the healthcheck likely fails outright

The compose healthcheck's `test` command shells out to `curl`. `backend/Dockerfile`'s
`apt-get install` list only installs `fonts-liberation`:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
```
The base image, `python:3.11-slim`, does not ship `curl` — Debian slim images strip most
utilities to save space. So `curl -f http://localhost:8000/health` almost certainly cannot even
run inside the container: `docker compose ps` would report the service `unhealthy` (or stuck
`starting`) regardless of whether the app itself is fine, because the *check command* fails,
not the *app*. This has not been confirmed by running the container in this session — it's a
finding from reading the Dockerfile and compose file together — but it should be the first
thing verified before anything else here (see Verification in the plan).

## Options

| | (a) Status quo | (b) Dockerfile `HEALTHCHECK` | (c) Deepen `GET /health` |
|---|---|---|---|
| What it is | Keep only the compose-level `healthcheck:` block | Bake `HEALTHCHECK` into `backend/Dockerfile` itself | Have `/health` check a real dependency (DB) |
| Works outside this repo's Compose files (plain `docker run`, Kubernetes, Swarm) | No — health reporting only exists if the deployer uses this exact `docker-compose.yml` | Yes — it's a property of the image | N/A (orthogonal — this changes *what* is checked, not *how* Docker calls it) |
| Detects the app being "up but broken" (DB unreachable, disk full) | No — and currently likely broken outright (missing `curl`) | No, by itself — same shallow `/health` | Yes — this is the one option that changes what "healthy" means |
| Implementation cost | None | Low — one Dockerfile line, no new package if using a Python-based check | Low — one DB query with a try/except |
| Risk if done wrong | Stays silently broken/uninformative | A slow or hanging check command can itself cause false-unhealthy flapping | An expensive query on every 30s poll could add load; must stay a cheap check |

(a) and (b) are not really alternatives to each other — (b) is what makes health reporting a
property of the *image* rather than of *this specific Compose setup*, which is precisely the
gap the issue is asking about ("enable hoster to check and create monitoring" — a hoster is not
guaranteed to be running `docker compose up` with this repo's files). (c) is orthogonal to both:
it changes what the check verifies, independent of how Docker invokes it.

## Recommendation

**Adopt (b) + (c) together, replacing (a):**

1. Add a `HEALTHCHECK` instruction directly to `backend/Dockerfile`, using a small inline
   Python one-liner (`urllib.request`) instead of `curl` — this needs no new `apt-get install`
   at all, since Python is already present in the image, and it sidesteps the missing-`curl`
   problem entirely rather than just patching it in place.
2. Deepen `GET /health` to attempt a trivial `SELECT 1` against the database and return 503 on
   failure, so the check actually reflects whether the app can do its job — not just whether
   the process is scheduling requests.
3. Update (or remove) `docker-compose.yml`'s existing `healthcheck:` block so it doesn't
   silently diverge from the Dockerfile's — Compose's `healthcheck:` overrides the image's
   `HEALTHCHECK` when both are defined, so leaving the old broken one in place would keep
   masking the fix for anyone deploying via Compose.

This keeps the check cheap (a single indexed-free `SELECT 1`, not a real query against app
tables) and keeps it working the same way regardless of whether the hoster uses this repo's
Compose files, a bare `docker run`, or another orchestrator — which is the actual ask in the
issue. **No changes to `backend/Dockerfile`, `docker-compose.yml`, or `backend/main.py` happen
as a result of this document alone** — implementing this requires the user to review this
recommendation and explicitly approve it (the plan's second, currently-deferred story).

## Implemented

The recommendation above was approved and implemented:

- `GET /health` (`backend/main.py`) now runs `db.execute(text("SELECT 1"))` and returns a 503
  `{"status": "error"}` response on failure (logged server-side via `logger.exception`),
  instead of unconditionally returning `{"status": "ok"}`.
- `backend/Dockerfile` carries a `HEALTHCHECK` instruction using an inline Python
  `urllib.request` call — no `curl` install needed, and it now works under any orchestrator,
  not only via this repo's `docker-compose.yml`.
- `docker-compose.yml`'s `healthcheck:` block was updated to the same Python-based `test`
  command (interval/timeout/retries/start_period unchanged), so it no longer silently
  overrides the Dockerfile's fix with the old broken `curl`-based one.
- `reference/commands.md` documents `docker compose ps` / `docker inspect --format='{{json
  .State.Health}}'` for checking status.

The suspected-broken `curl` dependency described above was not separately re-verified by
actually running the old image before replacing it — the fix removes the dependency outright,
which is strictly safer than confirming the failure mode first.

---

*This document is the deliverable for plan-issue-96-container-health-check. Both stories are
now implemented.*
