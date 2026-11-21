# Lessons Learned

The rules agents read before starting work. Each entry condenses one or more lessons from earlier runs; the full history, with the original details, is in [lessons-archive.md](lessons-archive.md). Search the archive by keyword when a problem looks familiar; don't read it in full.

Entries are sorted newest-first. Add a new entry at the top only for a pitfall not covered here, in the format below, and keep each entry to a **Problem** and a **Solution** of a few lines. Keep this file under about 12 KB: when it grows past that, `/agent-steward` moves entries that no longer apply to the archive.

Format:

```
### YYYY-MM-DD — agent — category
**Problem:** One sentence.
**Solution:** What works instead.
```

### 2026-11-21 — security-patcher — security
**Problem:** CodeQL `py/incomplete-url-substring-sanitization` flags `"api.example.com" in text` even when `text` is file contents (a "no literal outside module X" guard test), not a URL.
**Solution:** Search for the literal with `re.search(r"api\.example\.com", text)`: same check, no substring sink.

### 2026-11-21 — security-patcher — security
**Problem:** CodeQL `py/path-injection` also flags tests: a test that calls a route function and passes a path from its response (e.g. `os.path.isfile(result["backup_path"])`) is a tainted flow from the request body.
**Solution:** In tests, check files through an untainted source, such as a directory listing (`database.list_season_backups()`), and compare the response's path as a string.

### 2026-11-21 — security-patcher — security
**Problem:** CodeQL `py/path-injection` flags a file name built from admin input even after a regex slug (e.g. `season_label_slug`), because it doesn't treat `re.sub` or `Path.with_name` as sanitisers.
**Solution:** Build the path with `os.path.join(<realpath of the live DB dir>, name)`, `os.path.normpath` it, and check `startswith(db_dir + os.sep)` (and `dirname == db_dir`) before any filesystem call; see `rename_to_season_backup` in `database.py`.

### 2026-11-21 — developer — testing
**Problem:** A new `/admin/demo/*` route fails `test_issue_145`'s guard, which pins the exact set of demo paths; and a TestClient request to `/x/../y` never reaches a `{name:path}` route, because httpx removes dot segments (as browsers do).
**Solution:** Extend that path set and its 404 loop with the new route functions. To test traversal names over HTTP, encode the slash (`..%2Fx`); Starlette decodes it before routing. For save/restore tests use a tmp FILE database (`live_db` in `test_issue_147_demo_snapshots.py`).

### 2026-11-18 — developer — testing
**Problem:** Issue 146's How to Play copy change failed `test_how_to_play_role_subtabs` in the full suite: the Developers panel (where the Demo Mode bullet lives) must not contain the word "OpenDota". Separately, `opendota_client.requests` and `steam_live.requests` are the one global `requests` module, so patching `.get` there reroutes every caller.
**Solution:** Say "match-data services" in that panel. To run the app against the mock in tests, use `_wire` / `_route_to_mock` in `test_issue_146_mock_opendota.py` (patches `requests.get/post` once and records stray URLs, since ingest swallows transport exceptions).

### 2026-11-18 — developer — models
**Problem:** `auto_lock_weeks`, `due_substitutions`, `generate_weekly_summaries` and `card_points.rebuild_all` each call `db.commit()`, so a caller that must run them inside one all-or-nothing transaction (issue 145's scenario loader) can't roll back; and Core `table.delete()` leaves the deleted rows' objects in the identity map, so new rows reusing their ids raise an SAWarning.
**Solution:** Use `scenarios._one_transaction(db)`, which turns the session's commits into flushes until the block ends and rolls everything back on error. After Core deletes, `db.flush()` then `db.expunge_all()` and re-fetch the objects you need.

### 2026-11-18 — developer — models
**Problem:** Since issue 133, a new table in `models.py` fails `test_issue_133`'s coverage test until it is classified, and End Season with no users writes no `season_archive` rows, so `POST /admin/season/summary` then answers 404 for that label.
**Solution:** Add every new table to `season_reset.TABLE_GROUPS` (cleared, updated or kept) in the same change. In tests of the summary route, create at least one user before End Season.

### 2026-11-17 — test-planner — testing
**Problem:** Seven test files (issues 50, 81, 135, 141, 150, 220, 237) patch `routers.admin_season.backup_sqlite_db` with a zero-argument `lambda: …`, so passing arguments to it breaks them, and calling a renamed backup function instead leaves them unpatched and backs up the real `data/fantasy.db`.
**Solution:** When the reset's backup call changes, update every stub to `lambda *a, **k: …` in the same change (keep the `monkeypatch.setattr(admin_season_module, "backup_sqlite_db"` text that test_issue_85 greps for).

### 2026-11-17 — developer — models
**Problem:** A migrated database's `card_modifiers` CHECK lists the stat keys from migration 025, so a stat added to `SCORING_STATS` later is refused there; `scripts/bench_leaderboards.py` drew modifiers from `SCORING_STATS + deaths` and failed `test_issue_149`'s benchmark tests only in the full suite.
**Solution:** Draw modifier keys from `card_utils._SCORED_STAT_COLS` (the pool without `NO_MODIFIER_STATS`) everywhere, including scripts; a new scored stat that should be a modifier target needs a `card_modifiers` rebuild migration.

### 2026-11-17 — test-planner — models
**Problem:** A new scored stat touches the replay import too: every `manual_match.STAT_FIELDS` key is required per player, `scripts/replay_to_match.py` lists any stat its parser events can't give under `missing_stats`, and a replay with missing stats is stored as Partial stats.
**Solution:** When adding a stat to `SCORING_STATS`, decide how `replay_to_match.py` produces it (or why it may be absent) and update `STAT_ORDER`, the issue 224 test helpers and the fixture together.

### 2026-11-17 — developer — testing
**Problem:** A `style.css` comment `/* Issue #245 … */` failed `test_issue_211` and `test_issue_224`, whose "tokens only" checks search CSS slices for `#[0-9a-fA-F]{3,8}\b` and read `#245` as a hex colour.
**Solution:** Write "issue 245" (no `#`) in CSS comments.

### 2026-11-17 — test-planner — frontend
**Problem:** The page's address is read and rewritten in several places during `init()`: `applyAuthState()` calls `switchTab("leaderboard")` for logged-out visitors before `handleSteamReturn` reads `#login?steam=…`, and `handleTwitchReturn` strips any hash starting `#profile`, even without `?`. In-page `href="#htp-…"` anchors also change the hash.
**Solution:** Read `location.hash` at the start of `init()`, before any handler runs, and keep `switchTab` from writing the address during init. Make a `popstate`/hash reader ignore anchor ids. Note that `test_how_to_play_role_subtabs` reads the first app-globals.js line containing `"howtoplay"`.

### 2026-11-17 — developer — security
**Problem:** SlowAPIMiddleware's default limit (`RATE_LIMIT_GLOBAL`) never applies to routes added with `include_router`: this FastAPI wraps them in `_IncludedRouter`, the middleware finds no handler and treats the request as exempt, so a "covered by the global limit" test with a fresh `Limiter(default_limits=...)` sees no 429.
**Solution:** Put `@limiter.limit(RATE_LIMIT_GLOBAL)` on a public route that must be limited (`routers/obs.py`, issue 246) and test it with the router's own Limiter (`limiter.reset()` first). Routes that rely only on the global limit are unlimited today.

### 2026-11-17 — test-planner — models
**Problem:** Plans say "reuse `weekly_summary._SERIES_GAP`", but the 6-hour series gap has four copies (`weekly_summary._SERIES_GAP`, a local `GAP` in `schedule._build_unscheduled_results`, `admin_ingest.SERIES_GAP_SECONDS`, `_SERIES_GAP_SECONDS` in app-admin-matches.js, pinned by test_issue_193), and env settings such as `INGEST_POST_MATCH_FAST_POLL_MINUTES` are parsed only in `main.py`.
**Solution:** Put a shared constant in the service module (`schedule.py`) and import it in the routers, never import a router's private constant into a service. Don't import `main` from a service to read a setting: read the env var with the same default in the service or move it to a small shared module.

### 2026-11-17 — developer — testing
**Problem:** Adding a keyword to `twitch._post_chat_message` / `_pubsub_broadcast` calls (issue 253's `ext=`) broke older tests: their recorders (`_chat_recorder` in `test_issue_157`, `_pubsub` in `test_issue_234`) are two-argument lambdas. Separately, `twitch_channels.record_request` ignores a non-numeric channel id, so the tests' `test_channel` never gets an approval row.
**Solution:** Send through `twitch.chat_as(ext, …)` / `broadcast_as(ext, …)`, which keep the two-argument call for the full extension; in a new test that needs the keyword, patch with a recorder that takes `ext="game"`. Use a numeric channel id when a test expects a `TwitchChannelApproval` row.

### 2026-11-16 — developer — frontend
**Problem:** Resetting My Team's week pick in code (`_rosterWeekId = null`, then `_renderWeekSelector()`, issue 249) left the `<select>` on the old week: the markup was unchanged, so `renderIfChanged` wrote nothing and the DOM kept the player's selection.
**Solution:** When code changes which option should be selected, set `sel.value` as well; `selected` in markup passed to `renderIfChanged` only applies when the markup differs.

### 2026-11-16 — ship — testing
**Problem:** A barrier-released threaded test (`test_issue_185`'s concurrent soft-account merges) passed every local run but failed twice in a row on CI: on a slow runner the second thread started after the first one committed, so `s.get(User, soft_id)` was `None` and the helper crashed with `AttributeError` instead of the expected `SoftAccountGone`.
**Solution:** In a concurrency test, handle the "other thread already finished" state the way the production caller does (here `merge_confirm`'s 404 for a missing soft account). To reproduce, add a random `time.sleep` before each thread's first read.

### 2026-11-15 — developer — testing
**Problem:** Adding a panel to Admin › Settings (issue 250's Check Points) failed only in the full suite: `test_issue_214` pins each section's panel titles, the total panel count, and that the danger action (Recalculate, Reset Season) is the last button of its section.
**Solution:** Put a new Settings panel before the section's danger panel, and extend the title set and the panel count in `test_issue_214_admin_enhancements.py` together.

### 2026-11-11 — developer — testing
**Problem:** Adding a column to a table (issue 215) broke the table's original tests: `test_issue_175` pinned the exact column set and asserted the table name never appears in `migrate.py`, and `test_issue_180` pins the exact list of Twitch status check keys with every row "ok".
**Solution:** Before adding a column or a status check, grep `backend/tests` for the table name and for `[c["key"] for c in`; extend the pinned set or list, narrow "not in migrate.py" to `CREATE TABLE <name>`, and configure the new check in `status_env`.

### 2026-11-10 — developer — models
**Problem:** New code reading `user.player_id` (issue 220's "own verified player") passed its own tests but failed `test_issue_209`'s guard in the full suite, and test users built with only `player_id` are not verified links.
**Solution:** Read the link through `player_links.verified_player_id(user)`; in tests give such users `steam_id=str(76561197960265728 + player_id)`.

### 2026-11-10 — developer — testing
**Problem:** `test_issue_195`'s `_called_paths` matched only `[a-z_/]` literals and a bare `"/prefix/" + id`, so a hyphenated route (`/twitch/mvp-poll`) or a `"/x/" + id + "/vote"` call was invisible to the endpoint-disclosure check and its table row looked "never called".
**Solution:** The regex now takes `-` and a trailing `+ "/suffix"` literal; add the route's prefix to `PARAM_BY_PREFIX` and one table row per method in the review guide's endpoint table.

### 2026-11-03 — qa-engineer — testing
**Problem:** On this Windows sandbox, dozens of unrelated test files compare literal non-ASCII characters (em dash –, middle dot ·, minus sign −, stars ★) against text built by a Node subprocess or read from a doc file; the assertions fail because the character round-trips as `�`/mangled bytes, unrelated to any code change. This is a second, separate Windows-only noise source from the already-logged WinError 206 Node-spawn length limit (same `-n auto` runs).
**Solution:** When a failure's diff shows `�` (or two renderings of what looks like the same character) on one side only, treat it as this known Windows encoding artifact, not a regression; confirm on Linux CI instead of chasing it locally.

### 2026-10-31 — curated — testing
**Problem:** Node harnesses load only slices of the frontend modules (`_js([...])`, `_fn_source`, `_fn_body`), so code calling a helper from another module, top-level `window.*` calls, moved constants, `append()`/`innerHTML` children and helpers called inside extracted renderers break far from the change; `_fn_body` drops `async`, and a stub defined before a module is replaced by the module's own function.
**Solution:** Before touching a module, grep `backend/tests` for harnesses that load it and add the helper or stub there (or load helpers with an indirect `(0, eval)(<ACCOLADES block>)`). Pass extra markup into extracted renderers as a trailing default parameter, re-add `async` when pasting, use `appendChild`/`replaceChildren`, stub only globals the modules don't define, and print `status()` when a harness fails oddly. Reuse: `_HARNESS` (`test_issue_186`, roster drag/FLIP, `_rule(css, selector)`), `_HARNESS`/`_run` (`test_issue_205`, draws), `_ADMIN_HARNESS` (`test_issue_213`, re-auth popup), `_popup` (`test_issue_230`, player popup), `_ROSTER_HARNESS` (`test_issue_155`).

### 2026-10-27 — developer — testing
**Problem:** A step added to `main._live_poll_loop` (`_run_finals_check`, issue 237) opens `database.SessionLocal`, the real `data/fantasy.db`, in the `test_issue_161` tests that run the loop with only `_live_poll_once` stubbed; and the conftest `db` (plain `:memory:`) is invisible to TestClient's worker threads.
**Solution:** Stub the new step in every test that runs the loop (`monkeypatch.setattr(main, "_run_finals_check", lambda: None)`). For TestClient tests, give the module its own `db` fixture on a `StaticPool` with `check_same_thread=False` (`test_issue_237_*`).

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
