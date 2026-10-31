# Lessons Learned

The rules agents read before starting work. Each entry condenses one or more lessons from earlier runs; the full history, with the original details, is in [lessons-archive.md](lessons-archive.md). Search the archive by keyword when a problem looks familiar; don't read it in full.

Entries are sorted newest-first. Add a new entry at the top only for a pitfall not covered here, in the format below, and keep each entry to a **Problem** and a **Solution** of a few lines. Keep this file under about 12 KB: when it grows past that, `/agent-steward` moves entries that no longer apply to the archive.

Format:

```
### YYYY-MM-DD — agent — category
**Problem:** One sentence.
**Solution:** What works instead.
```

### 2026-10-31 — curated — testing
**Problem:** Node harnesses load only slices of the frontend modules (`_js([...])`, `_fn_source`, `_fn_body`), so code calling a helper from another module, top-level `window.*` calls, moved constants, `append()`/`innerHTML` children and helpers called inside extracted renderers break far from the change; `_fn_body` drops `async`, and a stub defined before a module is replaced by the module's own function.
**Solution:** Before touching a module, grep `backend/tests` for harnesses that load it and add the helper or stub there (or load helpers with an indirect `(0, eval)(<ACCOLADES block>)`). Pass extra markup into extracted renderers as a trailing default parameter, re-add `async` when pasting, use `appendChild`/`replaceChildren`, stub only globals the modules don't define, and print `status()` when a harness fails oddly. Reuse: `_HARNESS` (`test_issue_186`, roster drag/FLIP, `_rule(css, selector)`), `_HARNESS`/`_run` (`test_issue_205`, draws), `_ADMIN_HARNESS` (`test_issue_213`, re-auth popup), `_popup` (`test_issue_230`, player popup), `_ROSTER_HARNESS` (`test_issue_155`).

### 2026-10-31 — curated — testing
**Problem:** Hand-built requests fail on sessions, re-auth and rate limits: the `session` cookie is a signed Starlette session that needs a `user_sessions` row and `SessionMiddleware`; destructive admin routes need a recent re-auth; slowapi checks `request`; another file reloading `rate_limit` leaves routers holding a different Limiter (a rate-limit test then passes alone and fails under `-n auto`); plain `:memory:` SQLite is invisible to TestClient's worker threads.
**Solution:** Build sessions with `{"sid": sessions.create_session(db, user)}` or `POST /login`, or override `deps.get_current_user` (`require_admin` still checks the database); `POST /reauth` or override `require_recent_reauth`. Split limited routes into a plain function plus a `*_route` wrapper. Take the limit and the Limiter from the router module itself (`<router>.limiter`), never from `rate_limit`. Give TestClient tests a `StaticPool` engine with `check_same_thread=False` (`test_issue_237_*`). Never parse HTML with regexes in tests (CodeQL `py/bad-tag-filter`).

### 2026-10-31 — curated — testing
**Problem:** The test environment is easy to break: the `db` fixture creates tables only for imported models; the shell may export real keys (`STEAM_API_KEY`) that start threads; `DEBUG` and `BACKGROUND_TASKS_ENABLED` come from conftest; backups and new loop steps default to the real `data/fantasy.db`; the system `python3` sees distro packages in `dist-packages`; cloud sessions refuse `api.opendota.com`; CI installs the hash-locked `requirements-dev.lock`, not your local versions.
**Solution:** Import `models` at module level. Pin env-dependent attributes with `monkeypatch` and pop real keys from subprocess envs. Import check: `DEBUG=true python3 -c "import main"`. Point backups at `tmp_path`; stub new background-loop steps in every test that runs the loop (`_run_finals_check`). Skip distributions without an `INSTALLER` file in environment guards. Treat the three `test_test_background_task_isolation` lifespan tests as environmental behind a refusing proxy. A failure only CI sees may be a newer locked version: compare with `backend/requirements-dev.lock`.

### 2026-10-31 — curated — frontend
**Problem:** CSS and design-file rules are pinned by tests: colour tokens live only in `frontend/colors_and_type.css` and `design/colors_and_type.css` must stay identical; tests that slice `style.css` from "GUIDED TOUR" to the end apply its rules to anything appended; `test_issue_188` forbids `innerHTML` between `function showCard(` and `let _revealBoosterTeamId`; `test_issue_50` takes the first `.claude/skills/README.md` symbol row containing an icon; a class setting `display` overrides `hidden`.
**Solution:** Add tokens to the frontend file and copy it over the design one. Put new CSS before "GUIDED TOUR (issue #144)", next to related rules. Render card-viewer markup in a helper defined before `showCard`. List a row that reuses an icon after the original. Add `.cls[hidden] { display: none; }` for classes the code hides with `hidden`.

### 2026-10-31 — curated — models
**Problem:** New `_week_maintenance_loop` steps are easy to get wrong: `test_issue_117` slices the loop from its first `try:` to its first `except Exception`, so a nested try hides later steps; and Demo Mode moves the clock but not the loop's timer.
**Solution:** Put a best-effort step in a helper with its own try/except (`_run_caster_tag_sync`, `_run_finals_check`) and call it from the loop. If the step depends on the demo clock (week locks, substitutions, summaries), add the same call to `set_demo_clock()` in `routers/admin_demo.py`. In requests, use a savepoint wrapper (`caster_tags.sync_safely`).

### 2026-10-31 — curated — security
**Problem:** Dependabot alerts can be blocked by a range's upper bound, nothing self-resolves since the image installs only `backend/requirements.lock`, and in cloud sessions the alerts API answers 403.
**Solution:** Compare each open alert's `first_patched_version` with the version pinned in `backend/requirements*.lock` and the range in `requirements*.txt`; ship a fix by editing the range if needed and running `bash scripts/lock-deps.sh`. On 403, report the dependency check as "not checked (403)".

### 2026-10-25 — developer — endpoints
**Problem:** `test_issue_85` caps each of the ten split `routers/admin_*.py` modules at 350 lines, so adding a feature's endpoints to `admin_matches.py` failed only in the full suite.
**Solution:** Check `wc -l` on the router before adding to it. Keep the routes there as thin wrappers and put request handling in a service module (`manual_match.read_body` / `preview` / `store` for issue 224).

### 2026-10-17 — developer — models
**Problem:** A plan's "unique on (a, b, c)" with nullable columns doesn't hold in SQLite: NULLs are distinct in a unique index, so two rows with the same values and a NULL never collide and `ON CONFLICT DO NOTHING` inserts duplicates.
**Solution:** Index the nullable parts through `COALESCE` (`Index(..., func.coalesce(col, ''), unique=True)`, as `ux_season_accolades_key` in `models.py`); `ON CONFLICT DO NOTHING` without a target then honours it. Test the NULL case explicitly.

### 2026-10-14 — developer — security
**Problem:** An unbounded Pydantic `int` (card ids in a request body) bound into a SQLite query raises `OverflowError` above 2**63-1, which surfaces as a 500.
**Solution:** Bound ids in request models, e.g. `Annotated[int, Field(ge=1, le=2**63 - 1)]` (`CardId` in `routers/cards.py`), so an oversized id answers 422. Also size list caps (`max_length`) from what a user can actually reach, not a guess.

### 2026-10-13 — curated — plans
**Problem:** Plans and stubs are often wrong about the code: file paths after a split, "as today" behaviour, step numbers, which rules gate a flow, token sources, status codes, model constraints.
**Solution:** Before pinning a plan's claim in a test, in reviewer-facing copy or in docs, check it in the code (grep the function, route, column or text). When they disagree, follow the code and fix the plan and stories.

### 2026-10-13 — curated — testing
**Problem:** Changing a function's output or signature, moving a route between modules, or rewording UI text breaks older tests far from the change: pinned literals, key-set assertions, route lookups per module, Node harnesses that stub `extension.js` globals, regexes over markup.
**Solution:** Before the change, grep `backend/tests` for the function, route path, quoted phrase or element id. Add new parameters as trailing optional ones, keep message literals inside the functions tests extract, put new markup after the elements older regexes look for, and add stubs to harnesses (`_LIVE_CONFIG_HARNESS`, `_EXT_HARNESS`).

### 2026-10-13 — curated — testing
**Problem:** Concurrency tests passed against broken code: with pysqlite's legacy transactions, the first write takes SQLite's write lock, so threads were already serialised.
**Solution:** Run a race test against the old code first and confirm it fails. For "insert once, then credit", use `INSERT … ON CONFLICT DO NOTHING` and act only when `rowcount == 1`. In multi-statement roster changes, free the slot first and stop on `rowcount == 0`.

### 2026-10-13 — curated — models
**Problem:** Scoring and migrations have traps: card points are stored per match in `card_match_points` and readers return rounded `display_points`; a migration test's legacy engine runs migrations before `create_all`; earlier migrations can delete seeded rows.
**Solution:** After seeding stats or cards directly, call `card_points.rebuild_all(db)` or `refresh_card_points(db, match_ids=[...])`, and compare with `display_points(exact_sum)`. A data migration that fills a new table creates it first (`Model.__table__.create(conn, checkfirst=True)`). In migration tests, record earlier migrations as applied (`_legacy_engine` in `test_issue_129_*`). Use `bindparam(..., expanding=True)` for `IN :ids` in raw SQL.

### 2026-10-13 — curated — security
**Problem:** CodeQL flags patterns even in tests and admin-only code: URL prefix checks, regexes over HTML tags, ambiguous `.*?` repeats, `str(e)` in responses, URL path segments from drag data, plain SHA-256 on anything password-named, redirects built from request values, constants named `PASSWORD`.
**Solution:** Assert URLs with exact equality and parse real URLs with `urlparse`. Parse HTML with `html.parser`. Use `[^<]*` instead of `.*?`. Log the exception and return `type(e).__name__`. Interpolate only `parseInt` + `Number.isFinite` ids. Use `pbkdf2_hmac` for password-named data. Redirect with the allowlist's own constant. Don't put "password" in names of non-secret constants. Repeat multi-character `replace` until stable.

### 2026-10-13 — curated — security
**Problem:** Recurring review findings: the guard must be on the decorated `*_route` wrapper, not the plain function; owner-or-admin checks trusted the session's `is_admin`; env admin seeds re-applied on login undo demotions; secrets in query parameters reach urllib3's DEBUG log; bcrypt uses only 72 bytes; untrusted ids need `re.fullmatch` and `compare_digest` on bytes.
**Solution:** Audit the function that carries `@router.<method>`. Check admin rights fresh from the database (`require_admin`). Apply env promotions once. Keep `urllib3` logging at INFO or send secrets in headers. Cap passwords at 72 UTF-8 bytes. A lesson's Solution is advice, not proof that the fix landed: re-check the code.

### 2026-10-13 — curated — endpoints
**Problem:** Code lives in places agents don't expect: routes are in `backend/routers/*.py` (`main.py` only has `/config` and `/health`), auth dependencies in `backend/deps.py`, the frontend in `frontend/app-*.js` with admin split into `app-admin-*.js`. Unmatched paths fall through to the `/` static mount (405 for non-GET). Field validators run before the handler.
**Solution:** Grep the routers and the `app-*.js` files for the identifier. Register catch-alls (`/twitch/{rest:path}`) before the static mount. Put context-dependent checks in the handler as `HTTPException`, not in a `field_validator`. Look routes up with a TestClient call; `app.routes` may hold wrappers.

### 2026-10-13 — curated — frontend
**Problem:** `renderIfChanged` keeps DOM nodes, so listeners bound on every render pile up and closures go stale. Hidden views lose `scrollTop`. Modal overlays stack by DOM order. The focus trap picked up `tabindex="-1"` helpers.
**Solution:** Bind listeners once (a flag on the node) and read module state in handlers. Save `scrollTop` when hiding a view and restore it when showing it. Raise an overlay with a sibling selector, not a global `z-index`. Exclude `[tabindex="-1"]` from focusable selectors.

### 2026-10-13 — curated — frontend
**Problem:** The Twitch extension is a separate bundle: it doesn't share `frontend/` helpers, its version lives in the submission guide and tests, and it is checked by `package.sh`.
**Solution:** Escape untrusted names with the extension's own `_escHtml`. For a version bump, update the submission guide, the `package.sh` example and the version tests together. Before reviewer-facing copy changes, grep the backend and panel for every rule that gates the flow being described.

### 2026-10-13 — curated — agent-config
**Problem:** GitHub details tripped `/ship`: PR-only code-scanning alerts keep `state: null`, a stacked PR gets no CI and lands on the old base if merged after it, and a bare `#N` in a commit doesn't mean the issue merged.
**Solution:** List PR alerts with `ref=refs/pull/<P>/head` and read `/instances`. Open PRs against `main`. Treat an issue as merged only when a merged PR or default-branch commit closes it.
