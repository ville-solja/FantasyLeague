# Dependency Locking and Release Gating

Fixes from the 2026-10-31 systems architecture review. They make sure the image that reaches the test server or production runs exactly the dependency versions CI tested, and only after the tests passed.

---

## Hash-locked dependencies

| File | Role |
|---|---|
| `backend/requirements.txt` | Version ranges for the app. Edit these |
| `backend/requirements-dev.txt` | Ranges for the test tools (pytest, pytest-xdist) |
| `backend/requirements.lock` | Exact versions with sha256 hashes. The Dockerfile installs only this (`pip install --require-hashes -r requirements.lock`) |
| `backend/requirements-dev.lock` | The same versions plus the test tools. Unit Tests installs this |

Before this change, every Docker build and CI run took the newest release inside each range, so the image could run versions no PR had tested. On 2026-10-28 pytest 9.2.0 arrived between a PR's run and its merge, and `main` went red.

**To change a version:** edit the range, run `bash scripts/lock-deps.sh` (needs [uv](https://docs.astral.sh/uv/)), review the diff, run the tests and commit both `.lock` files. The script resolves for Python 3.11 (the image) and later (CI uses 3.12), with the dev lock constrained to the runtime lock's versions. `pip-audit` in Unit Tests checks the locked versions (`pip-audit -r backend/requirements.lock --require-hashes`).

`backend/tests/test_architecture_review_fixes.py` fails when a range and its lock disagree, when a pin has no hashes, or when the Dockerfile or CI installs anything but the locks.

## Image built only after the tests pass

`docker-publish.yml` calls `unit-tests.yml` and `ui-tests.yml` as reusable workflows (`workflow_call`), and its build job `needs` both. A push to `main` or a `v*` tag therefore runs the tests once, inside the publish run, and a failing test means no image. The two test workflows still run on their own for pull requests.

## Single process

The rate limiter, `INGEST_LOCK`, the in-memory caches (finals, Twitch panel, schedule) and the background threads all assume one process. Startup refuses `WEB_CONCURRENCY` above 1 (`main._single_process_guard`). Don't pass `--workers` to uvicorn, and don't run two replicas on the same database.

## Background-job safeguards

- **Profile enrichment:** one long-lived worker runs the batches. A batch still running after 300 s (`_ENRICHMENT_TIMEOUT_SECONDS`) is left to finish, and later cycles are skipped until it does, so two batches never write at once. Before, a `with ThreadPoolExecutor()` block waited for the stuck batch on exit, so the timeout did nothing.
- **Finals check:** besides the live-poll thread, it now runs on every week-maintenance tick (`WEEK_CHECK_INTERVAL`, 5 minutes). So the finals lock, results and correct picks keep up where the live thread doesn't run (no `STEAM_API_KEY`, or `DEMO_MODE`). See [Finals Predictions](../core/finals-predictions.md).
