# Lessons Learned

The rules agents read before starting work. Each entry condenses one or more lessons from earlier runs; the full history, with the original details, is in [lessons-archive.md](lessons-archive.md). Search the archive by keyword when a problem looks familiar; don't read it in full.

Entries are sorted newest-first. Add a new entry at the top only for a pitfall not covered here, in the format below, and keep each entry to a **Problem** and a **Solution** of a few lines. Keep this file under about 12 KB: when it grows past that, `/agent-steward` moves entries that no longer apply to the archive.

Format:

```
### YYYY-MM-DD — agent — category
**Problem:** One sentence.
**Solution:** What works instead.
```

---

### 2026-10-14 — developer — testing
**Problem:** Some static CSS tests slice `style.css` from a section header to the end of the file (`test_issue_144_guided_tour` checks every rule after "GUIDED TOUR"), so a block appended at the end inherits that section's rules (no `50%` radius, no `rgba`).
**Solution:** Put a new CSS block before the "GUIDED TOUR (issue #144)" section, next to related rules, not at the end of `style.css`.

### 2026-10-13 — curated — plans
**Problem:** Plans and stubs are often wrong about the code: file paths after a split, "as today" behaviour, step numbers, which rules gate a flow, token sources, status codes, model constraints.
**Solution:** Before pinning a plan's claim in a test, in reviewer-facing copy or in docs, check it in the code (grep the function, route, column or text). When they disagree, follow the code and fix the plan and stories.

### 2026-10-13 — curated — testing
**Problem:** Changing a function's output or signature, moving a route between modules, or rewording UI text breaks older tests far from the change: pinned literals, key-set assertions, route lookups per module, Node harnesses that stub `extension.js` globals, regexes over markup.
**Solution:** Before the change, grep `backend/tests` for the function, route path, quoted phrase or element id. Add new parameters as trailing optional ones, keep message literals inside the functions tests extract, put new markup after the elements older regexes look for, and add stubs to harnesses (`_LIVE_CONFIG_HARNESS`, `_EXT_HARNESS`).

### 2026-10-13 — curated — testing
**Problem:** Concurrency tests passed against broken code: with pysqlite's legacy transactions, the first write takes SQLite's write lock, so threads were already serialised.
**Solution:** Run a race test against the old code first and confirm it fails. For "insert once, then credit", use `INSERT … ON CONFLICT DO NOTHING` and act only when `rowcount == 1`. In multi-statement roster changes, free the slot first and stop on `rowcount == 0`.

### 2026-10-13 — curated — testing
**Problem:** The test environment is easy to break: the `db` fixture only creates tables for models already imported; the shell may export real keys (`STEAM_API_KEY`) that start extra threads; `DEBUG` and `BACKGROUND_TASKS_ENABLED` come from conftest, not the shell; backups default to the real `data/fantasy.db`.
**Solution:** Import `models` at module level in test files. Pin env-dependent module attributes with `monkeypatch` and pop real keys from subprocess envs. Run the import check as `DEBUG=true python3 -c "import main"`. Point backup tests at `tmp_path` by patching `database.DATABASE_URL`. Keep DB writes a test must see on the request thread (in-memory SQLite gives each thread its own connection).

### 2026-10-13 — curated — testing
**Problem:** Sessions, re-auth and rate limits make hand-built requests fail: sessions need a `user_sessions` row, destructive admin routes need a recent re-auth, and slowapi checks `request` on every decorated call; reloaded modules keep decorators bound to an older `Limiter`.
**Solution:** Build sessions with `{"sid": sessions.create_session(db, user)}` or log in through `POST /login`, and `POST /reauth` before destructive admin calls. Split a limited route into a plain function plus a `*_route` wrapper; unit tests call the plain function. For limit tests, build a small FastAPI app with the router and `app.state.limiter = <module>.limiter`, and reload only modules already in `sys.modules`.

### 2026-10-13 — curated — models
**Problem:** Scoring and migrations have traps: card points are stored per match in `card_match_points` and readers return rounded `display_points`; a migration test's legacy engine runs migrations before `create_all`; earlier migrations can delete seeded rows.
**Solution:** After seeding stats or cards directly, call `card_points.rebuild_all(db)` or `refresh_card_points(db, match_ids=[...])`, and compare with `display_points(exact_sum)`. A data migration that fills a new table creates it first (`Model.__table__.create(conn, checkfirst=True)`). In migration tests, record earlier migrations as applied (`_legacy_engine` in `test_issue_129_*`). Use `bindparam(..., expanding=True)` for `IN :ids` in raw SQL.

### 2026-10-13 — curated — security
**Problem:** CodeQL flags patterns even in tests and admin-only code: URL prefix checks, regexes over HTML tags, ambiguous `.*?` repeats, `str(e)` in responses, URL path segments from drag data, plain SHA-256 on anything password-named, redirects built from request values, constants named `PASSWORD`.
**Solution:** Assert URLs with exact equality and parse real URLs with `urlparse`. Parse HTML with `html.parser`. Use `[^<]*` instead of `.*?`. Log the exception and return `type(e).__name__`. Interpolate only `parseInt` + `Number.isFinite` ids. Use `pbkdf2_hmac` for password-named data. Redirect with the allowlist's own constant. Don't put "password" in names of non-secret constants. Repeat multi-character `replace` until stable.

### 2026-10-13 — curated — security
**Problem:** Recurring review findings: the guard must be on the decorated `*_route` wrapper, not the plain function; owner-or-admin checks trusted the session's `is_admin`; env admin seeds re-applied on login undo demotions; secrets in query parameters reach urllib3's DEBUG log; bcrypt uses only 72 bytes; untrusted ids need `re.fullmatch` and `compare_digest` on bytes.
**Solution:** Audit the function that carries `@router.<method>`. Check admin rights fresh from the database (`require_admin`). Apply env promotions once. Keep `urllib3` logging at INFO or send secrets in headers. Cap passwords at 72 UTF-8 bytes. A lesson's Solution is advice, not proof that the fix landed: re-check the code.

### 2026-10-13 — curated — security
**Problem:** Dependabot alerts can be blocked by a pin's upper bound, and in cloud sessions the alerts API answers 403.
**Solution:** Compare each open alert's `first_patched_version` with the constraint in `backend/requirements*.txt`. On 403, report the dependency check as "not checked (403)".

### 2026-10-13 — curated — endpoints
**Problem:** Code lives in places agents don't expect: routes are in `backend/routers/*.py` (`main.py` only has `/config` and `/health`), auth dependencies in `backend/deps.py`, the frontend in `frontend/app-*.js` with admin split into `app-admin-*.js`. Unmatched paths fall through to the `/` static mount (405 for non-GET). Field validators run before the handler.
**Solution:** Grep the routers and the `app-*.js` files for the identifier. Register catch-alls (`/twitch/{rest:path}`) before the static mount. Put context-dependent checks in the handler as `HTTPException`, not in a `field_validator`. Look routes up with a TestClient call; `app.routes` may hold wrappers.

### 2026-10-13 — curated — frontend
**Problem:** `renderIfChanged` keeps DOM nodes, so listeners bound on every render pile up and closures go stale. Hidden views lose `scrollTop`. Modal overlays stack by DOM order. The focus trap picked up `tabindex="-1"` helpers.
**Solution:** Bind listeners once (a flag on the node) and read module state in handlers. Save `scrollTop` when hiding a view and restore it when showing it. Raise an overlay with a sibling selector, not a global `z-index`. Exclude `[tabindex="-1"]` from focusable selectors.

### 2026-10-13 — curated — frontend
**Problem:** The Twitch extension is a separate bundle: it doesn't share `frontend/` helpers, its version lives in the submission guide and tests, and it is checked by `package.sh`.
**Solution:** Escape untrusted names with the extension's own `_escHtml`. For a version bump, update the submission guide, the `package.sh` example and the version tests together. Before reviewer-facing copy changes, grep the backend and panel for every rule that gates the flow being described.

### 2026-10-13 — curated — frontend
**Problem:** Browser checks mislead: headless Chromium hides scrollbars, `--virtual-time-budget` freezes animations, `page.click` scrolls the target first, and without a viewport meta `mobile: true` lays out at 980 px.
**Solution:** Launch Playwright with `ignoreDefaultArgs: ["--hide-scrollbars"]`, drive animations in real time over CDP, read `scrollTop` after clicks, and emulate narrow layouts with `mobile: false, width: 375`.

### 2026-10-13 — curated — models
**Problem:** Demo Mode moves the clock but not the background loop's timer, so a new week-maintenance step didn't run in demos.
**Solution:** When adding a step to `_week_maintenance_loop` in `backend/main.py`, add the same call to `set_demo_clock()` in `backend/routers/admin_demo.py`.

### 2026-10-13 — curated — agent-config
**Problem:** GitHub details tripped `/ship`: PR-only code-scanning alerts keep `state: null`, a stacked PR gets no CI and lands on the old base if merged after it, and a bare `#N` in a commit doesn't mean the issue merged.
**Solution:** List PR alerts with `ref=refs/pull/<P>/head` and read `/instances`. Open PRs against `main`. Treat an issue as merged only when a merged PR or default-branch commit closes it.

### 2026-10-13 — curated — docs
**Problem:** Repo-level docs used the deployment's branding, developer overviews were trimmed too far, and external-repo claims came from READMEs instead of code.
**Solution:** Describe the product generically in repo docs (Kana Cards and Kanaliiga names only in deployment content). Keep developer overviews complete and structured. Confirm claims about other repos against their code and latest migrations.
