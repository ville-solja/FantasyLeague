# Lessons Learned

Persistent notes written by agents during their runs. Read this before starting work.
Append new entries when you encounter a novel problem not already documented here.

Entries are sorted newest-first. Entries are append-only — do not rewrite or delete existing entries.

Format:

---

### 2026-10-07 — developer — testing
**Problem:** For #171, adding `@limiter.limit(...)` to the existing `POST /twitch/heartbeat` made every direct call of the handler in tests raise ("parameter `request` must be an instance of starlette.requests.Request"): slowapi checks the `request` argument whenever the limiter is enabled, which it is in the suite. Separately, `test_issue_136._build_main_client` read `TWITCH_EXTENSION_CLIENT_ID` from the developer shell once CORS started depending on it.
**Solution:** When a route gains a limit, split it like the other panel routes: a plain `heartbeat(payload, db)` with the logic and a `heartbeat_route(request, ...)` wrapper carrying the decorators; unit tests call the plain function, rate-limit tests go through `_twitch_app` + TestClient. Any import-time env read that a shared test helper depends on must be cleared in that helper (`monkeypatch.delenv`) before applying the test's own env.

### 2026-10-07 — test-planner — endpoints
**Problem:** Plan #171 lists `GET /teams` and `GET /teams/{team_id}` (routers/players.py) among responses that must sanitise team logos, but neither returns a logo field; the plan also misses `backend/image.py`, which fetches `team_logo_url` server-side for card images. Separately, a new eligibility rule on the drop pool (soft accounts must be 24 h old) silently breaks older drop tests that build pools from brand-new `_join` accounts.
**Solution:** Before pinning "every response that carries X" in tests, grep the field across `backend/` (`grep -rn logo_url --include=*.py`) and compare with the plan's list; report extra and missing call sites. When a rule narrows who qualifies, grep tests for the fixtures that create the affected rows (`_join`, `TwitchPresence(`) and list them for the developer.

### 2026-10-07 — security-reviewer — endpoints
**Problem:** An env-based admin list that is re-applied on every sign-in (`_apply_admin_seed` for `SEED_ADMIN_STEAM_IDS`) silently undoes an in-app demotion: a demoted account whose id is still listed is promoted again at its next login, so demoting a compromised admin does nothing until the env changes and the app restarts.
**Solution:** Apply env promotions once per id (record that the seed was applied, or skip accounts with a later demotion in the audit log) so an in-app demotion sticks; review any "promote on login" path for this.

### 2026-10-07 — developer — frontend
**Problem:** Plan #169 asked for the ADMIN badge and the Verified/Self-reported label on "own Profile and the user profile view", but the website has no view of another user's profile: `loadProfile` only fetches `GET /profile/{activeUserId}`, and the past-season and leaderboard rows don't link to profiles. Separately, a "no exact `User.username ==` query left" source check over whole modules fails on `POST /login` and `/forgot-password`, which deliberately keep exact lookups.
**Solution:** Grep the frontend for the endpoint (`profile/\${`) before planning UI on a "view" of it, and say in the plan and UI docs where the element really appears. Scope source-pattern tests to the functions that create names (`inspect.getsource(module.register)` etc.), not whole files.

### 2026-10-07 — test-planner — endpoints
**Problem:** Plan #169 puts the reserved-word check in `auth.check_username` with a 422 "This name is reserved" and a skip when the rename keeps the current name, but `check_username` is a Pydantic field-validator body: its ValueError becomes FastAPI's list-shaped 422 `detail`, and it can't see the current user. Separately, "the leak test" for user `player_id` can't search bodies for the number: card rows carry public league-player `player_id`s that may equal a user's linked id.
**Solution:** Before pinning an error string or a context-dependent rule on a validator helper, check whether it runs as a `field_validator` (grep `field_validator(...)(check_...)`); context-dependent checks go in the handler as `HTTPException`. Scope "no id leak" assertions to objects that carry a user identity (`id`/`user_id` + `username`).

### 2026-10-07 — developer — endpoints
**Problem:** For #150, two Python details nearly let forged Steam OpenID input through or crash the callback: `re.match(r"...(\d{17})$")` accepts a trailing newline (`$` matches before a final `\n`) and `\d` matches non-ASCII digits; and `hmac.compare_digest(a, b)` on `str` raises `TypeError` when either side has a non-ASCII character, which a query string can carry (a 500 instead of a refusal). Separately, test_issue_117's `#reauthModal` regex ends at the first `</div>\s*</div>`, so a nested block placed before the form cut the match short.
**Solution:** Use `re.fullmatch` with `[0-9]{17}` for ids from untrusted input, and compare with `hmac.compare_digest(a.encode(), b.encode())`. When adding markup to a modal that older tests parse with a non-greedy `</div></div>` regex, put the new block after the elements those tests look for.

### 2026-10-07 — test-planner — endpoints
**Problem:** Plan #150 lists "token grants" among destructive admin actions that keep "the recent re-auth" plus a typed `confirm` field, but `POST /grant-tokens` has no `require_recent_reauth` today; the backup download it also lists is a `GET` (no body for `confirm`); and "demo accounts" have no flag on `User` (only `demo%` usernames / `@demo.local` emails from `/admin/demo/seed-accounts`).
**Solution:** Before pinning "in addition to X" or "demo accounts can't Y" in tests, grep the route's `dependencies=` and the model for the marker; list the gaps in the stub module docstring and the report so the developer adds the guard, uses a query parameter for GET routes, and picks a reliable demo marker.

### 2026-10-06 — developer — endpoints
**Problem:** For #160, removing `POST /twitch/link-code` made it answer 405, not 404: the `/` `StaticFiles` mount catches every unmatched path and refuses non-GET methods. Separately, a callback URL's one-time code and state would reach uvicorn's access log (it logs the full path with query), and `caplog` in a TestClient test also captures httpx's own "HTTP Request: GET …?code=…" lines from the client side.
**Solution:** Register an app-level catch-all (`@app.api_route("/twitch/{rest:path}", …)` raising 404) after the routers and before the static mount. Add a `logging.Filter` on `uvicorn.access` that strips the query of sensitive paths (`twitch_oauth.RedactSignInQuery`). In log-secret tests, ignore records from `httpx`/`httpcore` loggers (the browser side) and assert on the app's records.

### 2026-10-06 — test-planner — models
**Problem:** Plan #160 has the website account W and the waiting soft account S both holding the same `twitch_account_id` (the callback stores `sub` on W while S still has it, and the merge prompt finds S by W's id), but #157 made `users.twitch_account_id` unique, so the callback's write would fail with an IntegrityError (and `record_twitch_account_id` treats S as a holder, giving 409 `twitch_identity_in_use`).
**Solution:** Before pinning tests on cross-account Twitch id states, check the column's constraints in `backend/models.py` / the migration; the developer must choose where the pending link lives (e.g. clear the id on S at connect time and find S another way, keep it only on S until merge, or store W's verified id elsewhere) and update the plan.

### 2026-10-06 — developer — testing
**Problem:** For #157, rate-limit tests of `/twitch/*` routes can't use `rate_limit.limiter`: other test files reload `rate_limit` (and `routers.cards`, `main`), so a module that wasn't reloaded (`twitch`) keeps decorators bound to an older `Limiter` instance, whose counters and `enabled` flag are the ones that apply. Separately, the plan said a short-token draw "returns the same 400 as the website" and a full-team draw "returns the website's error", but the website answers 409 and lets a complete team draw a duplicate.
**Solution:** In a TestClient test, build a small FastAPI app with the router, set `app.state.limiter = <module>.limiter`, and `reset()` / restore `enabled` on that same instance; give the app a `StaticPool` + `check_same_thread=False` engine since endpoints run in a threadpool. Check the website function's actual status before pinning "same as the website" in tests, and fix the plan and stories when they disagree.

### 2026-10-06 — security-reviewer — endpoints
**Problem:** A secret sent as a query parameter (`requests.get(url, params={"key": ...})`, e.g. the Steam Web API key) is written to the logs by urllib3's `connectionpool` DEBUG line whenever the root logger runs at DEBUG (`DEBUG=true`, as in `docker-compose.dev.yml`), even though the app's own log calls never print the URL.
**Solution:** Keep the `urllib3` logger at INFO or above (`logging.getLogger("urllib3").setLevel(logging.INFO)` after `basicConfig`), or send the secret in a header where the API allows it; check `logging.getLogger("urllib3.connectionpool").getEffectiveLevel()` in a test.

### 2026-10-06 — developer — testing
**Problem:** For #161, `test_test_background_task_isolation.py`'s in-process lifespan test failed only on a machine whose shell exports `STEAM_API_KEY`: `steam_live` reads the key at import, so the lifespan started a fifth thread (`_live_poll_loop`) and the "four threads" assertion broke. Its subprocess tests inherit the shell env too, and a changed DEMO_MODE log line broke an exact-string assertion there.
**Solution:** Any test that depends on whether an env-gated thread starts must pin the module attribute (`monkeypatch.setattr(steam_live, "STEAM_API_KEY", "")`) and pop the variable from subprocess envs (`_run_child`). Never assume the developer shell is clean of real keys, and keep existing start-up log lines verbatim; add new lines next to them instead of rewording.

### 2026-10-05 — developer — testing
**Problem:** For #156, four older test files (`test_mvp_visibility.py`, `test_issue_135_security_review_fixes.py`, `test_issue_159_flicker_free_tab_switching.py`, `test_issue_101_schedule_fixtures_api.py`) pin Schedule markup and escaping inside the body of `loadSchedule` (`_fn_body` / `_function_source`), so moving row rendering into top-level helpers would break them. Also, `main.app.routes` entries report `path` as `None` in this FastAPI version, so a test cannot find `/schedule` there, and the 135 escaping check flags any `${...}` whose leftover text still names `s.team1` (for example `${teamHtml(s.team1_id, s.team1)}`, since only `_escHtml`/`teamLink`/`playerLink` calls are stripped).
**Solution:** Keep the Schedule renderers as closures inside `loadSchedule`, store the latest one in `_schedRerender` for click handlers, and keep pure helpers at top level. Compute team markup into local variables before the template. Look up routes on the router module (`routers.admin_ingest.router.routes`). For behaviour tests, run the whole `app-players.js` under Node against a fake DOM, fetch and localStorage (`_run_schedule` in `test_issue_156_schedule_visuals.py`), and return early instead of skipping when Node is missing so the #85 tripwire stays exact.

### 2026-10-05 — developer — frontend
**Problem:** For #159, skipping unchanged `innerHTML` writes exposed code that relied on every render creating fresh nodes. `_initDragAndDrop` added grid-level listeners on every `loadRoster` (they piled up, and the oldest closure's stale `benchCards` won), and slot handlers captured the card arrays of the render that bound them. Separately, `index.html` has no viewport meta, so CDP `Emulation.setDeviceMetricsOverride` with `mobile: true` lays the page out 980 px wide (no 600 px media rules, `vh` scaled up); use `mobile: false` with `width: 375` to test narrow layouts.
**Solution:** When a renderer may keep DOM nodes, make listener wiring idempotent (a `_dndBound` flag on the node, grid listeners bound once) and have handlers read module state (`_rosterActive`/`_rosterBench`) rather than closure arguments. Route every write to a managed element through `renderIfChanged`, and call `forgetRendered(el)` before rebuilding its children by hand (the #152 recap does).

### 2026-10-05 — developer — frontend
**Problem:** For #158, wrapping inputs in a `<form>` and adding visually hidden helper inputs had two side effects: the modal focus trap (`_getFocusableIn` in `app-init.js`) selects `input:not([disabled])`, so a clip-hidden `tabindex="-1"` helper counted as focusable (it has an `offsetParent`) and could become the trap's first/last stop; and `test_issue_117_longer_sessions.py` asserted `submitReauth()` inline in the `#reauthModal` markup, which moving submission to a form `submit` listener removes. Separately, the plan described login's field clearing "as today" wrongly (a failed login clears neither field; success clears only the password).
**Solution:** Exclude `[tabindex="-1"]` from the focus-trap input selector, and check submit wiring in JS (`getElementById("<form>").addEventListener("submit", ...)`) instead of inline handlers. Read the current function before pinning "as today" behaviour in tests, and fix the plan and stories when they disagree. To check layout is unchanged, serve `git archive HEAD frontend` and the working tree on two ports and compare `getBoundingClientRect()` of the same ids over CDP.

### 2026-10-03 — developer — testing
**Problem:** Plan #153 said the new tour step shows "5 / 7", but inserting it after Points (step 5) makes it step 6; the test-planner's stub docstring copied the wrong index (4). Plans that state a step number or counter value can be off by one when written from the insertion point rather than the final list.
**Solution:** Count the final list in the code before pinning an index in tests or docs, and fix the plan and stories to match. To reuse another test module's helpers, import them as `from tests.test_issue_144_guided_tour import _read, ...` (`backend/tests/` is a package); import only underscore names so pytest doesn't collect the other module's tests twice.

### 2026-10-03 — developer — frontend
**Problem:** Screenshotting the #152 reveal animation with `chromium --headless=new --virtual-time-budget=N --screenshot` froze it at the first frame: virtual time advanced `setTimeout` but no `requestAnimationFrame` tween or CSS transition ran, so every shot showed the card stuck off-screen. Separately, adding a field to a #151 roster card broke `test_build_week_summary_roster_cards_match_roster_response_order`, which asserts the exact key set (`_CARD_KEYS`).
**Solution:** Drive Chromium in real time over CDP: launch it with `--remote-debugging-port`, read the page's `webSocketDebuggerUrl` from `http://127.0.0.1:<port>/json`, and send `Page.navigate` / `Page.captureScreenshot` / `Runtime.evaluate` with Node 22's built-in `WebSocket` (no Playwright or pip install needed). When a later plan adds a roster card field, extend the #151 key-set assertion (`_CARD_KEYS | {...}`) rather than dropping it.

### 2026-10-03 — developer — frontend
**Problem:** Issue #151 needed `.reveal-overlay` (the card viewer) above `.modal-overlay` so it opens on top of the Weekly Report. Raising its `z-index` alone would have hidden the player popup opened from the viewer's player link (on My Team too), since every `.modal-overlay` shares one `z-index` and stacks by DOM order. Separately, the bare `python3 -c "import main"` check fails outside pytest with the SECRET_KEY guard; conftest sets `DEBUG=true`, the shell does not.
**Solution:** Keep the DOM-order stacking: `.reveal-overlay { z-index: 350 }` plus `.reveal-overlay ~ .modal-overlay { z-index: 360 }`, so popups placed after `#revealModal` (player, team) still open above the viewer and the report (before it) stays below. Run the import check as `DEBUG=true python3 -c "import main"`.

### 2026-10-02 — developer — docs
**Problem:** For the #108 Option A deep dive, the hub's `README.architecture.md` layering diagram says models use `db/ (Knex)`, but runtime models run raw SQL through `mysql2` (`apps/backend/src/db/mysqlRunQuery.ts`); Knex only runs migrations. Separately, a hand-summed effort total (44–68) did not match its rows (43.5–68).
**Solution:** Confirm hub READMEs against the code they describe (grep the imports) before repeating them. For an effort table, add a test that sums the rows and compares the Total row (see `test_effort_table_has_sizes_person_weeks_and_total`).

### 2026-10-02 — technical-writer — docs
**Problem:** The first #108 draft said the hub's `LinkedAccounts.provider` allows only `steam`, read from the migration that created the table. Two later migrations widened the enum (`discord`, then `pubg` in `20260615120000_add_pubg_provider_to_linked_accounts.ts`), so the claim was stale at the pinned commit.
**Solution:** For a Knex (or any migration-based) schema claim, grep every migration that alters the column (`grep -rn "<column>" apps/backend/migrations`) and quote the latest one, citing that file.

### 2026-10-02 — developer — file-paths
**Problem:** For issue #108 the production backups `data/fantasy.db.backup-*` are owned by root with mode 0600, so a read-only count as the normal user fails with "unable to open database file". The readable `data/fantasy.db` is a seeded development copy (every account created within one minute), so its counts are not production figures. Separately, the GitLab code search API (`/projects/:id/search`) returns 401 without a token, even for the public Kana Hub project.
**Solution:** Report which file was read and say plainly when it is not production data; give the exact read-only `sqlite3 "file:...?mode=ro"` query for the operator to run on a production backup, recording aggregates only. To search the hub source, download the archive of a pinned commit (`/repository/archive.tar.gz?sha=<sha>`) into the scratchpad and grep it; never install or run it.

### 2026-10-01 — developer — testing
**Problem:** The conftest `db` fixture calls `Base.metadata.create_all` on whatever models are registered at that moment. A test file that only imports `main` inside the test body (the `get_config(db=db)` pattern from `test_issue_83_demo_mode.py`) passes in the full suite but fails alone with `no such table: weights`, because the fixture runs before `main` (and so `models`) is first imported.
**Solution:** Add `import models  # noqa: F401` at module level in such test files so every table is registered before the fixture runs (see `test_issue_144_guided_tour.py`).

### 2026-10-01 — developer — testing
**Problem:** `scripts/bench_leaderboards.py` sets `DATABASE_URL` to its own temp file at import and then imports `database`, binding `engine`/`SessionLocal` to it. Inside pytest, `database` is already imported (bound to another URL), so importing the bench module in-process seeds and reads the wrong database. Separately, since issue #149 every reader returns points already rounded to one decimal by `scoring.display_points`, so tests comparing a reader's value to an exact stored sum with `pytest.approx(x)` or `round(x, 2)` fail.
**Solution:** Run the bench season in a subprocess (`sys.executable -c ...`, cwd = repo root, `BACKGROUND_TASKS_ENABLED=false`, `DEBUG=true`, no `DATABASE_URL`) and print results as JSON (see `_bench_comparison` in `test_issue_149_points_rounding.py`). Compare reader output to `display_points(exact_sum)`; when checking that card values add up to a total, compare the exact stored sums or allow up to about 0.1.

### 2026-10-01 — developer — testing
**Problem:** A migration test that seeds legacy rows into `weekly_roster_entries` and then calls `migrate.run_migrations` on a fresh engine finds the table empty: migration `010_weeks_epoch0_reset` runs first (nothing is recorded in `schema_migrations` yet) and deletes every roster entry. Separately, since issue #129 `weekly_roster_entries` also holds saved bench rows (`is_bench = 1`), so any new query over it that counts or sums roster cards must apply `match_scoring.counted_roster_entry_sql()` (or `is_bench = 0` for plain counts).
**Solution:** In such a test, call `migrate._ensure_migrations_table(conn)` and `migrate._record(conn, id)` for every earlier migration before running, as a production DB would have them applied (see `_legacy_engine` in `test_issue_129_automatic_bench_substitution.py`).

### 2026-10-01 — developer — testing
**Problem:** Since issue #117 a session is valid only when the cookie's `{"sid"}` has a `user_sessions` row (sha256 hash) within the role's limits, so the 2026-09-29 advice below (add `"sv"` to hand-built sessions) no longer works. Also, the cookie no longer carries `user_id`, so `rate_limit.key_by_user_or_ip` silently fell back to per-IP keys until it was changed to read `request.state.session_user_id`, which `get_current_user` sets before slowapi checks the limit.
**Solution:** For a hand-built session use `session = {"sid": sessions.create_session(db, user)}` (flushes a row in the same `db`), or `sessions.start_session(request, db, user)` plus a commit in a test-only login route; better still, `POST /login`. To control session time, monkeypatch `sessions._now`. Destructive admin endpoints carry `require_recent_reauth` as a route-level dependency, so HTTP tests must `POST /reauth` first, while direct function calls are unaffected.

### 2026-09-30 — developer — scoring
**Problem:** The 2026-09-25 entry below says card points are recomputed from aggregate stat sums with a death pool that scales with `match_count`, so a match's contribution to a card is not its own points. Issue #141 superseded that premise: card points are now stored per (card, match) in `card_match_points`, computed one match at a time (`match_count=1`, death bonus floored per match), and every reader sums the stored rows. The aggregate `match_count` path in `card_fantasy_score`/`_compute_card_points` survives only for API compatibility. Separately, `POST /recalculate` used to lose its `fantasy_points` pass when `rebuild_all` failed, because `rebuild_all` rolls back the whole session on error.
**Solution:** A match's contribution to a card is now exactly its stored `card_match_points.points` row; the older entry's excluded/cleared/deleted comparison still works but is no longer required. Before calling `card_points.rebuild_all(db)` after other writes, commit those writes first, since its rollback would discard them.

### 2026-09-30 — developer — testing
**Problem:** Since issue #141, My Team, the weekly and season leaderboards and End Season sum stored `card_match_points` rows. A test (or script such as `scripts/bench_leaderboards.py`) that seeds `PlayerMatchStats`/`Card` rows directly, or deletes stat rows with `db.delete`, reads zero or stale card totals, because only the app's write paths (ingest, MVP, draw, reroll, recalculate) refresh the stored rows. Separately, on SQLite, grouping the wide joined rows (users × roster × stored points, with username/player-name text columns in the GROUP BY) was about 3× slower than summing per (user, card) in an integer-keyed subquery and joining names afterwards.
**Solution:** After seeding, call `card_points.rebuild_all(db)`; after changing stats or MVP flags directly, call `card_points.refresh_card_points(db, match_ids=[...])` (it also drops rows whose stat row is gone). For leaderboard SQL, aggregate in a subquery on integer keys, then join display columns; check with `EXPLAIN QUERY PLAN` and the bench script.

### 2026-09-30 — technical-writer — docs
**Problem:** A README draft led with "Kana Cards" and "Kanaliiga", but those are the branding of one deployment; the project itself (Fantasy League) is league-agnostic.
**Solution:** In repo-level docs (README, setup and deployment text), describe the product generically and use neutral examples (`https://your-deployment.example.com`). Kanaliiga and Kana Cards names belong only in deployment-specific content such as the in-app text, the Twitch extension and hoster notes.

### 2026-09-30 — technical-writer — docs
**Problem:** Treating "concise" as "shorter" produced a trimmed draft for the How to Play → Developers subtab, but the maintainer wants developer-facing overview pages to be fuller: how the system fits together, why each choice was made, and its trade-offs.
**Solution:** For developer and architecture overviews, aim for complete and well structured rather than short; still leave code-level detail to the README and `markdown/features/` and link to them. Ask about depth up front when the audience is developers.

### 2026-09-30 — technical-writer — docs
**Problem:** In-app help text in `frontend/index.html` (How to Play) is pinned by phrase-level assertions in `test_how_to_play_role_subtabs.py` and `test_issue_103_team_draw_explanation.py` ("Draw a card", "5 cards", "locks automatically", the whole team-draw bullet), so a pure rewording breaks the suite.
**Solution:** Before rewording UI copy, grep `backend/tests/` for the panel id and quoted phrases; keep pinned phrases or propose the test change as a separate choice.

### 2026-09-30 — developer — file-paths
**Problem:** `twitch-extension/*.zip` is gitignored, so building a zip with `package.sh` does not record an extension version bump. The submitted version is tracked in `markdown/features/reference/twitch-extension-review-submission.md` (header and checklist), and `backend/tests/test_twitch_review_resubmission.py::test_submission_doc_references_current_version` asserts that exact version.
**Solution:** To bump the extension version, update the submission doc's header, checklist and review-history change log, the `package.sh` usage example, the `package.sh <version>` line in `markdown/features/core/twitch-extension.md`, and that test's expected version. The operator builds the zip with `bash twitch-extension/package.sh <version>` at release time.

---

### 2026-09-29 — developer — testing
**Problem:** After issue #119 (session revocation), a session is valid only when it carries `"sv"` equal to `users.session_version`. Tests that build sessions by hand, without going through `/login` or `/register`, broke silently into 401s or logged-out behaviour. Examples were `FakeRequest`/`AuthRequest` classes with `session = {"user_id": ...}` in `test_team_booster_draws.py` and the `/_test/login/{user_id}` helper in `test_issue_135_security_review_fixes.py`.
**Solution:** Any hand-built session must include `"sv": user.session_version or 0` (`deps.SESSION_VERSION_KEY`). A signed test cookie needs it too. Better still, log in through `POST /login`. `deps.get_current_user(request)` can still be called with only a logged-out request, because it returns 401 before touching `db`.

---

### 2026-09-28 — security-patcher — testing
**Problem:** CodeQL `py/bad-tag-filter` (CWE-20/116/185/186) flags any regex that matches HTML tags, e.g. `re.findall(r"<script\b[^>]*>", html)`, including in static-check tests (alerts #26 and #27 in `test_issue_135_security_review_fixes.py`). Such a regex really does miss `<SCRIPT>`, single-quoted attributes and `>` inside attribute values.
**Solution:** Parse the HTML with the standard library's `html.parser.HTMLParser` (lower-cases tag and attribute names, handles quoting) and inspect the attribute dicts (see `_script_tags()` / `_external_scripts()`). Don't just add `re.IGNORECASE`, which leaves the other regex gaps and can draw the same alert again.

---

### 2026-09-28 — developer — testing
**Problem:** Plan #118 (and its test stubs) said the backend suite imports `main` with `DEBUG=true` set by conftest. It did not. `backend/tests/conftest.py` never set `DEBUG`; individual tests `monkeypatch.setenv("DEBUG", "true")` before their first `import main`, and files such as `test_issue_109_opendota_query_prioritization.py` import `main` bare. Those only passed because an earlier test had already imported `main`, so running one alone could hit the import-time SECRET_KEY (now also HTTPS_ONLY) check. Separately, `_run_import_main` subprocess helpers that strip dev flags now also need `HTTPS_ONLY=true` to reach the check they are testing.
**Solution:** conftest now does `os.environ.setdefault("DEBUG", "true")` before any app import. Subprocess tests that strip `DEBUG` must pass `HTTPS_ONLY=true` (and a 32+ char `SECRET_KEY` for `ENV=production`) unless they are testing the HTTPS_ONLY refusal itself.

---

### 2026-09-28 — developer — testing
**Problem:** Root cause of the `test_issue_124_roster_mutation_rate_limiting.py` flake (404/409 on just-seeded cards, `assert 6 == 5` on the roster limit), also seen in `test_issue_121_rate_limiting.py` and noted in the 2026-09-24 entry below. Each `with TestClient(main.app)` ran the lifespan, which started the ingest-poll, week-maintenance and profile-enrichment loops. Each loop runs its first pass at once. The test fixtures use a `StaticPool` in-memory engine, which is one SQLite connection shared by every thread. So every session a loop closed issued a `ROLLBACK` on the test's own connection, sometimes between a request's write and its commit. A `do_rollback` trace caught all three loops rolling back during a failing test, and the enrichment executor thread kept doing so into teardown. Targeted runs with threads on failed 2 in 15. With threads off they failed 0 in 15. Rate-limiter reloads and module reload order were not the cause.
**Solution:** `backend/tests/conftest.py` sets `BACKGROUND_TASKS_ENABLED=false` before any app import, and the lifespan skips starting the four threads when that variable is `false`. With that change, 10 of 10 full-suite runs were clean. To exercise a loop, call its function directly. For real threads, use a subprocess with the variable unset and `DATABASE_URL` pointed at `tmp_path` (see `test_test_background_task_isolation.py`). To reproduce the old behaviour, run `BACKGROUND_TASKS_ENABLED=true python3 -m pytest ...`; conftest uses `setdefault`, so the override wins. Also note that the first rate-limited request starts a `threading.Timer` (the `limits` MemoryStorage expiry timer), so thread-count assertions should not make requests.

---

### 2026-09-28 — developer — testing
**Problem:** Two surprises implementing issue #136. First, PyYAML is importable locally (5.4.1) but is not in `backend/requirements*.txt`, so a test that `import yaml`s to parse `.github/workflows/*.yml` would fail in a clean env. Second, `PUT /profile/username` does `body.username.strip()` in the endpoint, but Pydantic field validators run first, so a charset validator rejects `" bob"` with 422 before the strip ever runs.
**Solution:** Check workflow files with plain text splits (see `_workflow_steps` in `test_issue_136_security_audit_3.py`) and validate YAML by hand locally. Remember that endpoint-level normalisation runs after body validation; trim in the frontend (it already does) or normalise inside the validator.

### 2026-09-27 — security-reviewer — endpoints
**Problem:** Rate-limited routes are registered through `*_route` wrapper functions (`redeem_code_route`, `link_account_route`, `get_card_image_route`, the roster `*_route`s) that delegate to plain functions of the same name without the suffix. An auth audit that reads the plain function's `Depends()` checks code FastAPI never registers, so a wrapper missing its guard would go unnoticed.
**Solution:** Audit the function that carries the `@router.<method>` decorator. It is the wrapper, and it must declare `get_current_user` / `require_admin` / `verify_twitch_jwt` itself. The plain function's `Depends()` defaults only apply to direct calls from tests.

### 2026-09-27 — developer — testing
**Problem:** A rate-limit test helper that did `importlib.reload(importlib.import_module("routers.x"))` after reloading `rate_limit` counted every request twice (a 5/minute limit returned 429 on the 3rd call). When the router module had not been imported yet in that process, `import_module` decorated its routes against the fresh `Limiter`, and the immediate `reload` decorated them again against the same instance, so slowapi registered two identical limits under one endpoint name. It only showed up when the test ran in isolation or first, not in the full suite.
**Solution:** Reload only modules already in `sys.modules`; import the rest once: `importlib.reload(sys.modules[n]) if n in sys.modules else importlib.import_module(n)` (see `_build_app` in `test_issue_135_security_review_fixes.py`). Build a minimal `FastAPI()` with only the routers under test, `SessionMiddleware`, and `app.state.limiter = rate_limit.limiter` rather than reloading `main`, which starts lifespan background loops.

---

### 2026-09-25 — developer — testing
**Problem:** When a test must show that excluding a match removes "exactly its points", comparing the card totals to `before - match.fantasy_points` does not work. Card points (`_compute_card_points`) are recomputed from aggregate stat sums, and the death pool scales with `match_count`, so a match's contribution to a card is not its own `fantasy_points`. Also, `plan-unparseable-match-handling` said `card_draw.py` uses points for pick weighting. It does not: picks are weighted by how many cards the user owns.
**Solution:** Measure the aggregate three times: with the match excluded, with the flag cleared, and after deleting that match's stat rows. Then assert excluded == deleted, excluded != baseline, and cleared == baseline (see `_assert_exclusion_removes_exactly_that_match` in `test_unparseable_match_handling.py`). Check a plan's claims about a module against the code before filtering it.

---

### 2026-09-24 — security-reviewer — endpoints
**Problem:** Password fields allow `max_length=128` characters, but bcrypt 4.x (`bcrypt>=4.2,<5.0`, 4.3.0 installed) silently uses only the first 72 **bytes** — `checkpw(b'a'*72 + b'ZZZZZZZZ', hashpw(b'a'*80, ...))` returns `True`. bcrypt 5.x instead raises `ValueError` for >72-byte input, so lifting the `<5.0` pin would turn long passwords into 500s.
**Solution:** When touching password handling, cap password fields at 72 bytes (validate the UTF-8 encoded length, not character count), or pre-hash before bcrypt. Check this before bumping bcrypt past 5.0.

---

### 2026-09-24 — developer — testing
**Problem:** Tests that open `TestClient(main.app)` as a context manager (e.g.
`test_issue_124_roster_mutation_rate_limiting.py`'s `client` fixture) run the lifespan, which
starts `_backup_loop` — and those fixtures patch `database.engine`/`SessionLocal` but not
`database.DATABASE_URL`, so the loop calls `backup_sqlite_db()` against the real
`data/fantasy.db`. On a host where `data/` is root-owned (Docker bind mount), this showed up as an
intermittent `sqlite3.OperationalError: unable to open database file` and a
`test_issue_125_concurrent_activate_volume_does_not_trip_default_rate_limit` failure (4 == 5)
roughly 1 run in 5, which also trips the suite-size tripwire in `test_issue_85_split_admin_router.py`.
**Solution:** Re-run before blaming the current change. Any new test that touches backups must
`monkeypatch.setattr(database, "DATABASE_URL", f"sqlite:///{tmp_path / 'fantasy.db'}")` —
the backup helpers in `database.py` read that module global at call time, so patching it alone
redirects `backup_sqlite_db()`, `list_sqlite_backups()` and `cleanup_old_backups()`.

---

### 2026-09-18 — developer — testing
**Problem:** `plan-opendota-parse-retry`'s endpoint stubs assumed the background thread spawned
by `POST /ingest/retry-unparsed` could write its audit row through a monkeypatched
`admin_ingest.SessionLocal = lambda: db` (the conftest in-memory fixture). It cannot: SQLAlchemy
gives `sqlite:///:memory:` a `SingletonThreadPool`, so a second thread checks out a *different*
connection — an empty database (`no such table: audit_logs`) — and if the main thread already
holds the session's connection the worker instead hits pysqlite's
`check_same_thread` error. Separately, SQLite (no `AUTOINCREMENT`) reuses freed rowids, so
"delete rows then re-insert" tests cannot prove replacement by comparing primary-key id sets,
and a bulk `query.delete()` followed by inserts that land on the same ids raises
`SAWarning: Identity map already had an identity`.
**Solution:** Keep every DB write that a test must observe on the request thread — the
endpoint writes `parse_retry_triggered` via `db=Depends(get_db)` before spawning the thread,
which also satisfies the "never use raw `SessionLocal()` in endpoints" rule — and have tests
verify the thread only through a patched pure-function recorder plus polling
`INGEST_LOCK.acquire(blocking=False)` (release in `finally`). For replace-rows logic, delete
ORM-style (`db.delete(row)` + `db.flush()`) before re-inserting, and assert on replaced column
values / row count instead of id sets.

---

### 2026-09-14 — developer — testing
**Problem:** Implementing `plan-issue-111-week-boundary-formula.md`'s `_derive_week_times`
change (start_time 00:00→03:00 UTC, end_time 03:00→02:59:59 UTC) made the new
`test_issue_111_week_boundary_formula.py` stubs pass immediately, but broke three *pre-existing*
tests in `test_issue_81_season_lifecycle.py`
(`test_create_week_derives_start_time_midnight_utc`,
`test_create_week_derives_end_time_3am_day_after_end_date`,
`test_patch_week_accepts_date_only_inputs`) that hardcoded the exact old-formula timestamps as
their expected values — a full-suite run is required to catch this, since the new test file's
own green run gives no signal about collateral breakage in unrelated older files that encode the
same function's prior behavior as literal assertions.
**Solution:** When a plan explicitly changes a function's documented output (not just adds new
behavior), grep the whole `backend/tests/` tree for other direct/indirect callers of that
function before declaring done, not just the plan's own new test file — `grep -rn
"_derive_week_times\|start_date=\|end_date="` (adjust per feature) found the three
`test_issue_81_season_lifecycle.py` stubs here. Update their expected values to match the new,
intentionally-changed formula (renaming the test itself if the old name encodes the old
behavior, e.g. `..._midnight_utc` → `..._three_am_utc`) rather than treating the failure as a
regression to revert.

---

### 2026-09-14 — test-planner — file-paths
**Problem:** `plan-issue-84-week-management-editing.md`'s Critical Files table (and Step 2)
cites `frontend/app-admin.js` as the file to rewrite for inline week-table editing
(`loadAdminWeeks`, `openWeekEdit`/`saveWeekEdit`/`cancelWeekEdit`, the new
`saveWeekChanges()`). That file now only owns the admin tab bar (`initAdminTabs`,
`switchAdminTab`) — its own header comment says so — because it was already split into
sibling `app-admin-*.js` files, one per `backend/routers/admin_*.py` module, before this plan
was written. The actual week-management logic (including the Nordic date-picker helpers
`dateInputIso`/`setDateInputIso`/`_openDatePicker`/`_initNordicDateInput` referenced by this
plan's Story 1) lives in `frontend/app-admin-weeks.js`. Same class of drift the plan already
self-corrects for the backend (`admin.py` -> `admin_weeks.py`), just not caught for the
frontend half.
**Solution:** When a plan's Critical Files table names `frontend/app-admin.js` for anything
beyond the tab bar itself, check the actual `app-admin-*.js` split first (grep the target
function/identifier across `frontend/app-admin-*.js`) rather than trusting the plan's path —
write tests/implementation against whichever sibling file actually contains the logic.

---

### 2026-09-14 — developer — testing
**Problem:** Adding an unconditional real network call (`get_live_match_league_ids()`, a `GET
{OPEN_DOTA_URL}/live` request) inside `backend/main.py::_ingest_poll_loop` — run every cycle
regardless of whether any league is monitored — made the full `backend/tests/` suite
intermittently flaky (1-in-a-few runs, different unrelated test failing/erroring each time:
`test_security_headers.py`, `test_draw_panel_redesign.py`). Root cause: many tests instantiate
`TestClient(app)` without `DEMO_MODE=true`, which starts the real `_ingest_poll_loop` daemon
thread against the real dev DB/network on app startup; a real, possibly slow/rate-limited
OpenDota HTTP call on that background thread introduced timing variance that occasionally
collided with other tests' shared/global state. Confirmed via a 5-run comparison: baseline
(no live-match call) was 5/5 clean; with the unconditional call, failures/errors appeared in
~1 of 5 full-suite runs even though the new feature's own test file passed every time in
isolation.
**Solution:** Guard the network call behind the condition it actually needs
(`if monitored: get_live_match_league_ids() & set(monitored)`), so it's skipped entirely when
no league is monitored — which is the state of any fresh test DB. This restores the pre-change
no-network-calls-in-tests behavior while still meeting the feature's actual acceptance criterion
("one OpenDota request per poll cycle regardless of how many leagues are monitored" — zero
monitored leagues means nothing to protect, so zero requests is consistent with that). When a
background poll loop's new step makes a real external call, verify full-suite stability with a
multi-run comparison (`for i in 1..5; do pytest tests/ -q; done`) before and after, not just a
single green run — single-run flakiness in this suite is otherwise silent because the
background thread is a daemon and doesn't fail the test that started it.

---

### 2026-09-13 — claude — security
**Problem:** `twitch-extension/live_config.js` built HTML by string-concatenating team/player
names straight into `.innerHTML`. Those names originate from OpenDota/Steam data ingested
verbatim with no server-side sanitization (`backend/ingest.py`) — a real stored-XSS vector inside
a Twitch-hosted iframe, and a direct violation of Twitch's extension-review "DOM injection
security" requirement. `twitch-extension/` is a separate JS bundle from `frontend/` (uploaded to
Twitch's CDN independently) so it doesn't share `frontend/app-globals.js`'s existing `_escHtml()`
helper — the rest of the extension's own files (`panel.js`, `extension.js`) already used
`.textContent` correctly for the same class of data; only `live_config.js` used raw `innerHTML`.
**Solution:** Added an equivalent `_escHtml()` helper directly to `twitch-extension/extension.js`
(shared across panel/config/live_config) and applied it at every `innerHTML` site interpolating
untrusted names. When adding new UI to `twitch-extension/*`, treat every OpenDota/Steam-sourced
name field as untrusted the same way `frontend/` does — never assume a separate bundle inherits
sibling-bundle sanitization helpers.

---

### YYYY-MM-DD — [agent-name] — [category]
**Problem:** One-sentence description of the pitfall or recurring issue.
**Solution:** What to do instead, or the correct approach.

---

### 2026-09-07 — security-patcher — security
**Problem:** CodeQL `py/incomplete-url-substring-sanitization` (CWE-20) flags any
`str.startswith("https://host…")` / `"host" in url` / `url.endswith("host")` check against a
URL-shaped literal as a bypassable sanitizer — including plain **test assertions** that only
verify a value was echoed back (CodeQL still reports it, tagged `["test"]`).
**Solution:** In tests, assert exact equality (`result["url_prefix"] == "https://feed.test/api/fixtures.json"`)
instead of a `startswith` prefix check — stronger assertion, no sink. In real guards, parse
with `urllib.parse.urlparse` and check `hostname` against an allowlist / `.endswith(".example.com")`.

---

### 2026-09-07 — developer — testing
**Problem:** A test that only does `import schedule` and uses the `conftest.py` `db` fixture
hits `sqlite3.OperationalError: no such table: matches` from `get_schedule()` /
`_build_unscheduled_results()` — `backend/schedule.py` has no ORM model imports, so
`Base.metadata.create_all()` in the fixture registers nothing.
**Solution:** Add `from models import Match, Team  # noqa: F401` (or the specific models the
code path touches) at the top of the test module so the tables are registered on `Base` before
the fixture creates them — this is what `test_schedule_independent_results.py` already does.

---

### 2026-09-07 — test-planner — testing
**Problem:** `test_issue_99_admin_player_add_progress.py`'s docstring claims "FastAPI is not
importable in the local test environment," which reads as a standing environment fact and
could steer a future agent into unconditionally using the replicated-logic-helper pattern
(re-implementing endpoint bodies as plain functions in the test file). In the environment used
for `plan-issue-100-weekly-report-fixes.md`'s test stubs, `import fastapi` and
`from routers.weekly_summary import get_weekly_summary` both worked fine, and
`test_issue_51_weekly_summary.py` (the direct predecessor plan for the same router) already
imports router functions straight from `routers.weekly_summary` and passes the full existing
suite (642 passed) that way.
**Solution:** Don't treat "FastAPI is not importable" as a fixed property of this repo's test
environment — verify it fresh each session (`python3 -c "import fastapi"` and a direct import
of the target router) before choosing between the two established patterns: direct router-
function imports (test_issue_51_weekly_summary.py) when imports succeed, or replicated pure-
logic helpers (test_issue_99_admin_player_add_progress.py) only when they genuinely don't.

---

### 2026-08-31 — security-reviewer — endpoints
**Problem:** A version pin's upper bound can silently block a Dependabot fix from ever being
picked up even by a routine `pip install --upgrade` within the declared constraint —
`backend/requirements.txt` pins `pillow>=11.0,<12.0`, but all 12 currently-open Pillow
Dependabot alerts (10 high, 2 medium; CVE-2026-59197 through -59205, -54058, -55379,
-55798, -54060, -55380) are fixed only in `12.3.0`, which the `<12.0` ceiling excludes
entirely. Likewise `backend/requirements-dev.txt`'s `pytest>=8.0,<9.0` excludes the
`9.0.3` fix for the one open pytest alert. A quick glance at "is Pillow pinned" says yes;
it takes actually cross-referencing each open alert's `first_patched_version` against the
constraint to see the pin itself is the blocker.
**Solution:** When auditing dependencies (now part of `/security-reviewer`'s scope, added this
session), don't stop at "is there a pin" — fetch open Dependabot alerts
(`gh api repos/{owner}/{repo}/dependabot/alerts --paginate`) and check whether each one's
`first_patched_version` actually satisfies the current constraint's upper bound. A pin that
looks conservative/reasonable can be the exact reason a fix never lands.

---

### 2026-08-31 — security-patcher — agent-config
**Problem:** `actions/missing-workflow-permissions` (CWE-275) flagged
`.github/workflows/unit-tests.yml` for having no explicit `permissions:` block, meaning it
inherits the repository/org default `GITHUB_TOKEN` scope (often broader read-write) instead of
declaring only what the job actually needs. This alert's flagged file
(`.github/workflows/`) falls outside `/security-patcher`'s declared Scope section
(`backend/` or `frontend/` only) — worth noting since a future run may want to either widen
the declared scope to cover `.github/workflows/` explicitly, or route Actions-category alerts
to a different process instead of this agent.
**Solution:** Add a root-level `permissions:\n  contents: read` block — the job only checks
out code, installs deps, and runs pytest; it never pushes, comments, or publishes anything, so
read-only `contents` is the correct minimal grant (matches CodeQL's own suggested minimal
starting point exactly). Two sibling workflows (`docker-publish.yml`, `ui-tests.yml`) have the
same gap but were not touched here since they weren't the flagged file for this alert.

---

### 2026-08-31 — security-patcher — frontend
**Problem:** `js/incomplete-multi-character-sanitization` (CWE-20/80/116) flagged
`twitch-extension/dev-harness.html`'s single-pass `html.replace(/<script[^>]*twitch-ext\.min\.js[^>]*><\/script>/gi, "")` used to strip the Twitch CDN script tag from a
fetched HTML file before injecting it into an iframe via `srcdoc`. A single substitution
pass over a multi-character pattern can, for crafted/overlapping input, leave a still-matching
tag behind rather than fully removing it — the classic "remove `<!--`, but `<!<!---->` only
partially strips" class of bug. Low real-world risk here (the fetched file is a
developer-controlled local dev-harness asset, not user input), but the pattern itself is what
CodeQL flags regardless of actual exploitability in this call site.
**Solution:** Wrap the `.replace()` call in a `do { prev = html; html = html.replace(...) }
while (html !== prev)` loop so the substitution repeats until no further match is found,
matching CodeQL's own documented fix for this rule. Verified behavior is unchanged for normal
input (stabilizes after exactly one real removal + one no-op confirmation pass) and the loop
cannot hang since each pass only ever shrinks or leaves the string unchanged, never grows it.

---

### 2026-08-31 — developer — models
**Problem:** `backend/routers/admin_demo.py`'s `set_demo_clock()` synchronously re-runs
`auto_lock_weeks(db)` right after moving the clock override ("make the lock transition
observable immediately"), but `plan-issue-51-weekly-summary` added a second `_week_maintenance_loop`
step, `generate_weekly_summaries(db)`, without also adding it to `set_demo_clock()`. Result:
manually demoing the feature (set clock past a week's end_time, log in as a demo user) granted
the week-lock token immediately but the Weekly Report never appeared, because
`generate_weekly_summaries` only ran on the background loop's real-wall-clock timer
(`WEEK_CHECK_INTERVAL`, default 300s) — which the demo clock override does not speed up.
**Solution:** Whenever a new step is added to `_week_maintenance_loop` in `backend/main.py`,
also add it to `set_demo_clock()` in `backend/routers/admin_demo.py` (right after
`auto_lock_weeks(db)`) — Demo Mode exists specifically so the season lifecycle can be
demonstrated without waiting for real time to pass, so every "runs when a week's clock
boundary passes" background step needs a synchronous counterpart there, not just the original
one. When adding a similar background-loop step in the future, grep `set_demo_clock` and add
the same call there in the same edit.

---

### 2026-08-31 — security-reviewer — endpoints
**Problem:** Two findings from the 2026-08-12 security-reviewer entries below are still present
in the current codebase, unfixed: (1) `GET /roster/{user_id}` (`backend/routers/cards.py:621`)
still authorizes with the session-cached `current_user.get("is_admin")` instead of
`Depends(require_admin)`/a fresh DB check — the exact gap that entry describes. (2) The
2026-08-12 session-leak entry's stated **Solution** was "wrap `enrich_players()`'s body in
try/finally, matching the sibling function `run_profile_enrichment()`" — but only
`run_profile_enrichment()` (`backend/enrich.py`) actually has that wrapping today;
`enrich_players()` (same file) still opens `db = SessionLocal()` with `db.close()`
only on two normal-exit paths, no try/finally, and is still reachable synchronously from
`POST /ingest/league/{league_id}` via `run_enrichment()`. The lessons-learned entry recorded a
fix that was never actually applied to the code (or was applied and later reverted/lost).
**Solution:** A lessons-learned "Solution" describes correct guidance, not confirmation the fix
landed — don't treat a past entry as proof an issue is resolved. When a security-reviewer run
finds a pattern that matches an existing entry, re-verify the actual current file content before
marking it fixed/skip-worthy; grep for the exact flagged line/pattern first. Both findings are
re-reported in this session's `/security-reviewer` output rather than assumed closed.

---

### 2026-08-12 — security-reviewer — endpoints
**Problem:** `GET /roster/{user_id}` (`backend/routers/cards.py`) authorizes cross-user access with
its own inline `if user_id != current_user["user_id"] and not current_user.get("is_admin")` check
instead of composing with `Depends(require_admin)`. `current_user["is_admin"]` comes from
`get_current_user()`, which reads the session-cached value set at login — it is never
re-verified against the DB. `require_admin` (`backend/deps.py`) was hardened earlier this session
to re-check `is_admin` against the DB on every call specifically to close this class of gap (a
demoted admin keeping destructive access until their session expires), but that fix only helps
endpoints that actually depend on `require_admin`. Any endpoint that reimplements its own
`is_admin` check inline — as `get_roster` does — silently misses the hardening.
**Solution:** When an endpoint needs "owner OR admin" access (not a pure admin-only gate), do not
inline a session-trusting `is_admin` check. Either call `require_admin`'s logic explicitly (query
`User.is_admin` fresh) or add a small shared helper (e.g. `is_admin_fresh(db, user_id) -> bool`)
that both `require_admin` and mixed owner/admin endpoints can call, so there is one DB-authoritative
place this check lives. When auditing, grep for `current_user.get("is_admin")` /
`current_user["is_admin"]` outside `deps.py` — every hit is a candidate for this same gap.

---

### 2026-08-12 — security-reviewer — endpoints
**Problem:** `enrich.py::enrich_players()` opens `db = SessionLocal()` with no enclosing
`try/finally` — only calls `db.close()` at two normal-exit points (early return, end of
function). If `db.query(Player)...all()` itself raises, the session leaks. This function isn't
just a background-thread helper (which would be exempt from the session-leak check) — it's also
reachable synchronously from `POST /ingest/league/{league_id}` (`admin_ingest.py`) via
`run_enrichment()`, so it's in an actual request path.
**Solution:** Wrap the function body in `try: ... finally: db.close()`, matching the pattern
already used correctly by the sibling function in the same file, `run_profile_enrichment()`.
When auditing for session leaks, don't stop at "this function is called from a background loop"
— trace all callers, since the same helper can be shared between a background loop and a
request-time endpoint.

---

### 2026-08-12 — security-patcher — testing
**Problem:** `py/redos` (CWE-1333/400/730) flagged `r'<thead><tr>(<th>.*?</th>)+</tr></thead>...'`
in `backend/tests/test_mvp_visibility.py`. The inner `.*?` (non-greedy, `re.S` so it also
matches newlines) inside a `+`-repeated group is the classic ambiguous-repetition ReDoS shape:
`.*?` can match across a `</th>` boundary into the next `<th>`, so the regex engine has multiple
ways to partition the same input across repetitions of the group, causing exponential
backtracking on crafted input. Low real-world risk here (the match target is a static,
developer-controlled `frontend/index.html`, not user input), but the pattern itself is the
security-relevant thing CodeQL flags, and the same shape could reappear in a genuinely
user-facing regex later.
**Solution:** Replace the ambiguous `.*?` with a negated character class scoped to what the
content actually needs — `[^<]*` — since real `<th>` cells here contain only plain text, never
nested tags. `[^<]*` can never match the `<` that starts `</th>`, removing the overlap between
repetitions entirely and eliminating the backtracking blowup while matching the exact same
strings as before. General pattern: for `(TAG_OPEN.*?TAG_CLOSE)+`-style regexes over HTML/XML-ish
text, prefer a negated-class exclusion of the tag-opening character over `.*?` whenever the
content is known not to contain nested tags.

---

### 2026-08-11 — security-patcher — endpoints
**Problem:** `py/stack-trace-exposure` (CWE-209) flagged `result["error"] = str(e)` in the
admin-only `GET /admin/schedule/debug` diagnostic endpoint (`backend/routers/admin_ingest.py`).
The endpoint's entire purpose is surfacing why `SCHEDULE_SHEET_URL` fetches fail, so returning
nothing useful would defeat it — but CodeQL's taint tracker doesn't model `Depends(require_admin)`
as a sanitizer, so raw exception-message flow to any HTTP response is flagged regardless of auth.
**Solution:** Log the full exception server-side via `logger.exception(...)` (this repo's
established `logging.getLogger(__name__)` pattern, e.g. `backend/routers/auth.py`'s forgot-password
handler), and return only `type(e).__name__` (e.g. `"ConnectionError"`, `"Timeout"`) to the caller
instead of `str(e)`. This keeps the endpoint diagnostically useful (failure category is visible)
without leaking exception message text, which breaks CodeQL's taint flow since the exception class
name is a different derivation than the message content the query tracks.

---

### 2026-08-03 — developer — testing
**Problem:** `test_issue_85_split_admin_router.py::test_full_suite_pass_skip_counts_match_pre_split_baseline` hardcodes an exact `"448 passed"` string from a subprocess run of the whole suite ("as of this writing") — it breaks the instant any other plan adds new passing tests anywhere, even in unrelated files, which is the normal/expected outcome of this repo's plan-driven workflow.
**Solution:** When a change legitimately adds N new passing tests, bump that hardcoded count (and the mirrored docstring number) by N rather than treating the failure as a regression in the new work — but only after confirming via `git stash` that the rest of the suite (`--ignore` both that file and the new test file) still matches the pre-change baseline exactly.

---

### 2026-08-03 — developer — models
**Problem:** For raw `sqlalchemy.text()` queries with a dynamic `WHERE col IN (...)` list (used throughout `backend/schedule.py`, which has no ORM model imports), `text("... IN :ids")` alone does not expand a Python list into `(?, ?, ?)` placeholders.
**Solution:** Chain `.bindparams(bindparam("ids", expanding=True))` onto the `text(...)` statement, e.g. `text("SELECT ... WHERE match_id IN :ids").bindparams(bindparam("ids", expanding=True))`, then pass `{"ids": match_ids}` to `execute()`.

---

### 2026-07-22 — security-patcher — frontend
**Problem:** CodeQL `js/request-forgery` fires when a value from `e.dataTransfer.getData()` is interpolated directly into a fetch URL path segment, even when the base URL is fixed and the ID was originally an integer.
**Solution:** Parse with `parseInt(val, 10)` and guard with `Number.isFinite()` before interpolating into the URL — integers cannot contain path-traversal characters, which both eliminates the actual risk and breaks the taint chain.

---

### 2026-05-25 — security-reviewer — endpoints
**Problem:** `POST /forgot-password` returns immediately for unknown usernames but runs bcrypt + SMTP (1-3s) for valid ones — a timing side channel that reveals whether a username exists.
**Solution:** Call `verify_password("dummy", _DUMMY_HASH)` on the fast-exit path to equalise bcrypt latency. Store `_DUMMY_HASH = hash_password("dummy-timing-equalizer")` at module load time (runs once, not per request).

---

### 2026-05-25 — developer — testing
**Problem:** Helper functions defined inside `routers/cards.py` cannot be imported in `backend/tests/` because importing the router module triggers `from fastapi import ...`, which fails when FastAPI is not installed locally.
**Solution:** Extract pure-logic helpers (like `_roll_rarity` and `_pick_player`) into a separate `backend/card_draw.py` module that only imports from `models` and stdlib. The router then imports from `card_draw`, and tests import from `card_draw` directly without triggering the FastAPI dependency.

---

### 2026-05-25 — developer — testing
**Problem:** `seed_admin_from_env()` uses `SessionLocal()` internally, so the `db` fixture cannot inject the in-memory test DB directly.
**Solution:** Patch `seed.SessionLocal` via `monkeypatch.setattr` to return the in-memory session before calling the function under test.

---

### 2026-05-25 — agent-steward — endpoints
**Problem:** `get_current_user` and `require_admin` auth dependencies are not defined in `backend/main.py` or `backend/auth.py`.
**Solution:** Read `backend/deps.py` — that is where both dependencies are defined.

---

### 2026-05-25 — agent-steward — endpoints
**Problem:** Almost all FastAPI endpoints are in `backend/routers/*.py`, not `backend/main.py`; reading only `main.py` misses all endpoint definitions.
**Solution:** Read every file under `backend/routers/` to get the full endpoint list.

---

### 2026-05-25 — agent-steward — file-paths
**Problem:** `frontend/app.js` no longer exists; the frontend is split into `frontend/app-*.js` modules, one per tab.
**Solution:** Reference the correct module files: `frontend/app-globals.js`, `frontend/app-init.js`, `frontend/app-auth.js`, `frontend/app-cards.js`, `frontend/app-admin.js`, `frontend/app-roster.js`, `frontend/app-leaderboard.js`, `frontend/app-players.js`, `frontend/app-profile.js`.

---
