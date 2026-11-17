"""
Tests for plan-issue-246-obs-last-game-overlay.md (resolves GitHub issue #246).

A public OBS browser-source page, `/obs/last-game.html?teams=<id>,<id>`, shows the
last finished game of the series being streamed: result, series score and each
player's raw points (issue 244's `schedule.game_players`). It polls a new public
endpoint, `GET /obs/last-game?teams=<id>,<id>`, every 30 seconds. How to Play ›
Streamers gains an overview of every streamer tool, a URL builder for the overlay,
and sections for the viewer MVP vote and the Kana Cards MVP Vote extension. One
class per user story, one stub per acceptance criterion plus the primary failure
path.

Developer notes
---------------

  Existing code these tests target (verified 2026-11-17)
    - backend/schedule.py `game_players(db, match_id)` (issue 244): returns
      `{"match_id", "parse_status", "excluded_from_scoring", "teams"}` or None
      for an unknown match. `teams` is RADIANT THEN DIRE (falling back to the
      order team ids appear in the stats when a side is NULL), each
      `{"team_id", "team_name", "players"}`, players sorted by raw points desc
      with keys `player_id, player_name, hero_id, hero_icon, kills, deaths,
      assists, raw_points, is_mvp, top` (`top` = the game's highest raw score
      across BOTH teams, ties included; `raw_points` already one-decimal via
      `display_points`). Hero icons come only from `cached_hero_maps()` (never
      fetches); on a cold hero cache `hero_icon` is None and the answer is not
      cached. Cache: `_game_players_cache` {match_id: (monotonic, data)},
      expires after `CACHE_TTL` (3600 s), cleared by `bust_cache()` (MVP confirm,
      admin MVP, retry-parse, scoring toggle). The overlay's column order follows
      `teams` from game_players unless you reorder it: the URL's team order is
      NOT radiant/dire. Pick one rule (suggest: the order of the response's
      top-level `teams`, i.e. the URL order) and map game_players' teams onto it.
    - backend/routers/players.py `get_match_players` (`GET
      /matches/{match_id}/players`, `Path(ge=1, le=2**63 - 1)`, public, no auth
      dependency, 404 "Match not found"). players.py is 223 lines, no line cap
      (test_issue_85's 350-line cap is only for routers/admin_*.py). A new
      `routers/obs.py` is also fine, but then add `app.include_router(...)` in
      main.py next to the others (lines ~945-973), i.e. BEFORE the `/` static
      mount (line ~1077), or `/obs/last-game` falls through to StaticFiles.
    - `GET /schedule` is NOT in players.py: it is `schedule_endpoint` in
      routers/admin_ingest.py (public). Both are rate limited only by the
      global limit.
    - Series gap: there are FOUR copies of 6 hours today:
      `routers/weekly_summary._SERIES_GAP = 6 * 3600`,
      a local `GAP = 6 * 3600` inside `schedule._build_unscheduled_results`,
      `routers/admin_ingest.SERIES_GAP_SECONDS = 6 * 3600`, and
      `const _SERIES_GAP_SECONDS = 6 * 3600;` in frontend/app-admin-matches.js
      (pinned verbatim by test_issue_193). Importing a constant from a router
      (`routers.weekly_summary`) into a service module inverts layering.
      Suggest: add `SERIES_GAP_SECONDS = 6 * 3600` to schedule.py, use it in
      `_build_unscheduled_results`, and have weekly_summary
      (`_SERIES_GAP = schedule.SERIES_GAP_SECONDS`, keep the name) and
      admin_ingest import it; obs_overlay imports it from schedule. No test pins
      the Python constants' locations. The gap is measured start_time to
      start_time (`m["start_time"] - previous["start_time"] <= gap`), inclusive.
    - Missing side ids: `_build_games(db, match_ids, team1_id, team2_id)` does not
      decide teams, the caller passes them. `_build_unscheduled_results` selects
      only `WHERE radiant_team_id IS NOT NULL AND dire_team_id IS NOT NULL`;
      `resolve_series_result` matches the exact column pair in either order;
      weekly_summary puts a match with a NULL side in a series of its own;
      team_insights uses `player_insights.won()`, which answers None for a side
      it can't place. So the rule to follow: a match belongs to the pair only
      when `{radiant_team_id, dire_team_id}` equals the two ids; a match with a
      NULL side is never part of the series (and is not "game N").
    - Wins: `schedule._tally_wins(rows, team1_id)` with rows
      `(radiant_team_id, radiant_win)`; a NULL `radiant_win` counts for nobody.
      Reuse it for `series_score`.
    - `models.LiveMatch` (`live_matches`): `match_id` PK, `league_id`,
      `radiant_team_id`, `dire_team_id` (nullable, from Steam's
      team_id_radiant/dire), `first_seen_at`, `last_seen_at`, `ended_at`
      (set by `ingest.store_live_matches` when a poll no longer sees it). Rows
      are DELETED when the match's stats are stored (`ingest.py` ~line 395) and
      by `store_live_matches` once ingested or not seen for 24 h, so the "no
      player_match_stats" check is mostly redundant; keep it anyway, as
      `main._has_recently_ended_live_match` does (`~exists()` on
      PlayerMatchStats.match_id == LiveMatch.match_id). Rows only exist for
      monitored leagues while the Steam live thread runs (STEAM_API_KEY set);
      without it `pending_game` is simply always null.
    - `INGEST_POST_MATCH_FAST_POLL_MINUTES` is read ONLY in main.py, at import:
      `main._INGEST_POST_MATCH_FAST_POLL_MINUTES = int(os.getenv(..., "20"))`;
      `<= 0` turns fast polling off. Do NOT import main from obs_overlay (heavy
      import, startup checks). Either read the same env var with the same
      default in obs_overlay (module-level `PENDING_WINDOW_MINUTES`, so tests
      can monkeypatch it), or move the parse to a small shared module and import
      it in both. `<= 0` should mean "never pending". test_issue_139 pins
      `main._INGEST_POST_MATCH_FAST_POLL_MINUTES == 20`; keep that name in main.
    - Time: use `int(time.time())` for `now` in the route and pass it into
      `last_game(db, team_a, team_b, now)` so tests control it.
    - Static serving: `_FrontendStaticFiles(directory=frontend/, html=True)`
      mounted at "/" serves `frontend/obs/last-game.{html,js,css}` at
      `/obs/last-game.*` with `Cache-Control: no-cache` (the suffix check uses
      `os.path.splitext(path)`, so subdirectories work). Security headers come
      from `SecurityHeadersMiddleware` in main.py: `X-Content-Type-Options:
      nosniff`, `Referrer-Policy`, and a CSP of ONLY `frame-ancestors 'self'
      https://www.twitch.tv https://*.ext-twitch.tv` (+ HSTS with HTTPS_ONLY).
      There is no script-src / style-src / img-src / connect-src, so the page's
      own JS and CSS, same-origin fetch and the steamstatic hero icons all load;
      OBS loads it top-level, so frame-ancestors does not apply. No main.py
      change needed. Test pattern: `_main_client()` from
      tests/test_issue_150_steam_login.py and the assertions of
      test_issue_213 `TestDonePage.test_done_page_served_by_static_mount`
      (status 200, content-type, nosniff, frame-ancestors, no-cache). CSP
      directive parsing: test_security_headers.py
      `test_content_security_policy_frame_ancestors_present` (split on ";",
      compare token sets; never URL substring checks, CodeQL).
    - Fonts and tokens: frontend/colors_and_type.css defines the tokens, the
      Big Shoulders @font-face with a RELATIVE url('fonts/...') and sets
      `html { background: var(--bg) }` and `body { background: var(--bg) }`.
      Linking `/colors_and_type.css` from the overlay works (the font URL
      resolves against the stylesheet, i.e. /fonts/...) and avoids a third copy
      of the tokens (lessons: tokens live only in colors_and_type.css; the
      design/ copy must stay identical, test_issue_217). If you link it,
      `theme=transparent` must override BOTH html and body backgrounds. The plan
      says "copies"; either is allowed by the stubs below, which only require
      that the page's stylesheets are same-origin local files.
    - Escaping: `_escHtml` lives in app-globals.js and the overlay may not load
      app modules, so it needs its own escaper (or build with textContent).
    - How to Play › Streamers: frontend/index.html `<!-- Streamers subtab -->`
      (~line 1131), `<div id="howtoplay-panel-streamers" x-cloak x-show=
      "howToPlayTab === 'streamers'" class="grid">`, today two panels:
      "Applying & Installing" (Getting access: "still in Twitch testing
      (<strong>Local Test</strong>) ... test install link", "Once the extension
      is publicly released ..."; Installing: "No URL configuration is needed")
      and "Selecting a Match MVP". The How to Play JS is `loadHowToPlay()` in
      frontend/app-init.js (called from `switchTab` in app-globals.js); subtab
      switching is Alpine (x-data/x-show), and test_frontend_framework_evaluation
      forbids `function switchHowToPlayTab` / `function initHowToPlayTabs` in
      app-init.js. Put the URL builder's logic in small top-level functions in
      app-init.js (e.g. `obsOverlayUrl(origin, teamA, teamB, transparent)`,
      `obsOverlayCopyEnabled(teamA, teamB)`) so a Node harness can extract them
      (`_fn_source` in test_issue_211, `_extract_js_function` in
      test_how_to_play_role_subtabs: 2-space bodies, closing `\\n}`). Team
      pickers: `GET /teams` rows have `id` and `name` but are ordered by
      division then series wins and include every row of `teams`: sort by name.
    - Tests that pin the Streamers panel (update them with the text):
      test_how_to_play_role_subtabs.py `TestStreamersSubtab` asserts in the
      panel slice (`_extract_panel`, from `id="howtoplay-panel-streamers"` to
      `id="howtoplay-panel-developers"`): "Local Test", "test install link",
      "publicly released", "Extension Manager", "no url configuration" (lower),
      "Quick Actions", "Select match MVP", "series", "confirm", "token drop",
      "one-time", "fantasy score bonus", and NO "EBS" / "set-ebs-url" (so don't
      mention the EBS in the new sections). test_issue_149 asserts its rounding
      footnote is not in the streamers panel. test_frontend_framework_evaluation
      needs >= 4 `x-cloak` and `howToPlayTab === 'streamers'`. No
      test_issue_157_* test pins the Streamers panel (its How to Play pins are in
      the Users panel).
    - Twitch review status (from the two submission guides' "Review history"):
      full extension (twitch-extension-review-submission.md): 1.1.5 Pending
      Approval (2026-09), 1.1.7 rejected under 4.5 (2026-10), 1.2.1 Pending
      Approval again on 4.2 (2026-10), "To be resubmitted as version 1.3.0 ...
      Record the submission date and outcome here once known" (no approval
      recorded). 1.4.0, which carries the viewer MVP vote (#234), is "Planned
      for S17, after 1.3.0 passes review ... Not yet built or submitted". Vote
      extension (twitch-vote-extension-review-submission.md): "Not submitted
      yet." So, as of today: NEITHER extension is approved or released; the
      full extension is still installed through a test install link; the
      viewer vote is not in a submitted version; the MVP Vote extension has not
      been submitted. The text may say "waiting for Twitch review" / "not yet
      released"; it must not say "approved", "released", "available in the
      Extension Manager" or name a status the guides don't record. If the
      guides change before shipping, follow them and update
      `_STATUS_FORBIDDEN` below.
    - Real broadcaster controls (twitch-extension/live_config.html):
      "Select match MVP", "Start viewer vote", "End now", "Cancel vote",
      "Confirm MVP &amp; Drop Tokens" (the plan's "Confirm MVP" is a prefix).
      Vote durations 1, 2 or 3 minutes (twitch-mvp-viewer-poll.md). MVP Vote
      extension facts: markdown/features/reference/twitch-mvp-vote-extension.md
      (any Twitch-logged-in viewer votes; voters who share identity can win a
      token; pending tokens claimed when the Twitch id is attached to an
      account at kana-cards.com).
    - In-page links: app-auth.js reads `location.hash` only for
      `#(login|welcome|profile|admin)?...`, so `href="#htp-..."` anchors don't
      trigger routing, but they do change the hash. Use ids with a unique
      prefix (e.g. `htp-streamers-overlay`) placed inside the streamers panel.

  Reusable helpers / fixtures (all exist today)
    - tests/test_issue_244_schedule_player_performance.py: `db` (StaticPool,
      shared with TestClient threads), autouse `_no_network` (stubs
      `_fetch_hero_icon_map`, `warm_hero_maps_in_background`, empties the hero
      caches, `bust_cache()` before/after), `_seed_game(db, mid=900,
      **match_kw)` (teams 1 "Reds" radiant / 2 "Blues" dire, ten players, MVP on
      team 1; pass `ts=` for start_time), `_expected_raw(db, mid)`,
      `_players(data)`, `_PLAYER_KEYS`, `_EVIL`, `_Tags` / `_parse` /
      `_classes` (html.parser helpers). Fixtures are NOT imported here (a
      module's own fixture wins and import-only fixtures are easy to lose):
      define `db` and `_no_network` in this module by copying them.
    - tests/test_issue_211_team_view_enhancements.py: `_client(db)` (players
      router only: if the route goes to a new router, build an equivalent
      client around it), `_weights(db)`, `_seed_teams(db)`, `_match(db, mid,
      ts=None, radiant=1, dire=2, rw=True, ...)` (default start_time is
      `_BASE_TS + mid * 3600`, so ALWAYS pass `ts=` in series tests or match ids
      decide the gaps), `_stat(db, pid, mid, team=1, mvp=False, hero=None,
      **over)`, `_BASE_TS = 1_760_000_000`, `_fn_source(js, name)`.
    - tests/test_issue_234_mvp_poll_for_watchers.py: `_seed_ten(db, match_id,
      start_time)` (teams 11 vs 12, flat stats; only where values don't matter).
    - tests/test_issue_150_steam_login.py: `_main_client()`.
    - Node harness for a standalone page: tests/test_issue_213
      `_node()`, `_run_node(script)` (last stdout line as JSON) and
      `_done_page(...)`: a fake `window` / `document` built in a script string,
      then the page's JS appended, then `console.log(JSON.stringify(...))`.
      For the overlay build a harness that provides: `window.location.search`,
      `window.innerWidth/innerHeight` and `addEventListener('resize', ...)`,
      a `document` with the stage element(s) (record `innerHTML` writes or use
      `replaceChildren`), a `fetch` that serves queued responses per call
      (JSON body, `{ok:false,status:500}` or a rejected promise) and logs URLs,
      and `setInterval` / `setTimeout` stubs that RECORD the callback and delay
      instead of scheduling, so the test triggers each refresh by hand and
      awaits it (have the page's refresh function return its promise).
      `_node` also exists in test_issue_159 (falls back to /usr/local/bin/node).
    - Rate limit: lessons say never reload `rate_limit`. To show the route is
      under the global limit, mount the router on a fresh FastAPI app with a
      fresh `slowapi.Limiter(key_func=get_remote_address,
      default_limits=["2/minute"])`, `SlowAPIMiddleware` and the 429 handler,
      and check the third call answers 429; plus a source check that the route
      has no `@limiter.exempt`.

  Imports
    - `import models` stays at module level so the db fixture creates every
      table. Import `obs_overlay` and the new router INSIDE each test.

  Pitfalls
    - `teams` is one query string: FastAPI can't bound a comma list, so parse it
      in the handler and raise `HTTPException(422)` (not a field_validator).
      Bound each id to 1..2**63-1 (lessons 2026-10-14: OverflowError -> 500).
      Decide whitespace ("1, 2") explicitly; the stubs treat it as 422 only if
      you say so (not pinned).
    - Known teams with no current series answer 200 with `game: null`; 404 is
      only for a team id missing from `teams`.
    - Never parse HTML with regexes in new tests (html.parser); assert URLs with
      exact equality (CodeQL).
    - The overlay page must not call `/matches/...`, `/teams`, `/me` or any app
      endpoint: one call, `/obs/last-game?teams=...`.

  Ambiguities to settle in review
    - Game 1 ended without stats: story 2 says both "Before the series' first
      game has stats ... the waiting line and no older game" and "While a game
      ... has ended and has no stats yet ... 'Game N stats are on their way'".
      The stub below pins: `game` null + `pending_game` 1 shows the team names
      and "Game 1 stats are on their way" (instead of the waiting line), and no
      older game. Change the stub if review decides otherwise.
    - A page URL with a missing or malformed `teams` parameter is not covered by
      the plan; the stub pins "no request, a short setup line".
"""

import pytest

# Registers every existing table on Base before the db fixture runs create_all.
import models  # noqa: F401


# Phrases the Streamers panel must not contain while the submission guides record
# no approval (see Developer notes, "Twitch review status").
_STATUS_FORBIDDEN = ("approved by Twitch", "is now live on Twitch", "publicly available",
                     "now released", "has been released")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

import json
import os
import re
import subprocess
import time
from html.parser import HTMLParser

from tests.test_how_to_play_role_subtabs import _extract_panel
from tests.test_issue_159_flicker_free_tab_switching import _node
from tests.test_issue_211_team_view_enhancements import _BASE_TS, _match, _seed_teams, _stat, _weights
from tests.test_issue_244_schedule_player_performance import (
    _EVIL, _PLAYER_KEYS, _expected_raw, _p, _players, _seed_game,
)

_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
T = _BASE_TS


@pytest.fixture
def db():
    """In-memory database on one shared connection, so a TestClient's request
    thread sees the same data (overrides conftest's `db`)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No OpenDota hero maps and an empty schedule cache before and after each test."""
    import schedule
    monkeypatch.setattr(schedule, "_fetch_hero_icon_map", lambda: {})
    monkeypatch.setattr(schedule, "warm_hero_maps_in_background", lambda: None)
    monkeypatch.setattr(schedule, "_hero_icon_cache", None)
    monkeypatch.setattr(schedule, "_hero_name_cache", {})
    schedule.bust_cache()
    yield
    schedule.bust_cache()


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _live(db, mid, radiant, dire, ended_at, now):
    db.add(models.LiveMatch(match_id=mid, league_id=1, radiant_team_id=radiant, dire_team_id=dire,
                            players_json="[]", first_seen_at=now - 3600, last_seen_at=now - 600,
                            ended_at=ended_at))
    db.commit()


def _obs_client(db, app=None):
    """A small app around the OBS router, sharing `db`."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from database import get_db
    from routers import obs
    if app is None:
        import rate_limit
        app = FastAPI()
        app.state.limiter = rate_limit.limiter
    app.include_router(obs.router)

    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


# --- A tiny DOM from html.parser (no regexes over HTML) ---------------------

_VOID = {"img", "br", "input", "meta", "link", "hr", "source"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def walk(self):
        for c in self.children:
            if isinstance(c, _Node):
                yield c
                yield from c.walk()

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def by_class(self, cls):
        return [n for n in self.walk() if cls in n.classes()]

    def by_tag(self, tag):
        return [n for n in self.walk() if n.tag == tag]


class _TreeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = _Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(html):
    p = _TreeParser()
    p.feed(html)
    p.close()
    return p.root


def _css_rules(css):
    """[(selectors list, body)] of a flat stylesheet, comments and @media wrappers ignored."""
    css = re.sub(r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/", "", css)
    css = re.sub(r"@media[^{]*\{", "", css)
    return [([s.strip() for s in sel.split(",")], body)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


# --- Overlay page Node harness ----------------------------------------------

_OVERLAY_HARNESS = r"""
(async () => {
const SEARCH = __SEARCH__;
const QUEUE = __QUEUE__;
const fetchLog = [];
let writes = 0;
const intervals = [];
let reloads = 0;
const stage = { _html: "", style: {} };
Object.defineProperty(stage, "innerHTML", {
  get() { return this._html; },
  set(v) { this._html = String(v); writes++; },
});
const rootClasses = new Set();
const document = {
  getElementById: id => id === "obs-stage" ? stage : null,
  documentElement: { classList: {
    add: c => rootClasses.add(c), remove: c => rootClasses.delete(c), contains: c => rootClasses.has(c),
  } },
};
const listeners = {};
const window = {
  location: { search: SEARCH, reload: () => { reloads++; } },
  innerWidth: __W__, innerHeight: __H__,
  addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
};
const location = window.location;
const fetch = url => {
  fetchLog.push(url);
  const r = QUEUE.length ? QUEUE.shift() : { kind: "reject" };
  if (r.kind === "reject") return Promise.reject(new Error("network down"));
  if (r.kind === "error") return Promise.resolve({ ok: false, status: r.status, json: async () => ({ detail: "boom" }) });
  return Promise.resolve({ ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(r.body)) });
};
const setInterval = (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; };
const flush = () => new Promise(r => setImmediate(r));
const snaps = [];
const snap = label => snaps.push({ label, html: stage._html, writes, fetches: fetchLog.length });
const tick = async () => { await intervals[0].fn(); await flush(); await flush(); };
const resize = (w, h) => { window.innerWidth = w; window.innerHeight = h; (listeners.resize || []).forEach(f => f()); };
const transforms = [];
__PAGE__
await flush(); await flush();
transforms.push(stage.style.transform);
snap("load");
__STEPS__
console.log(JSON.stringify({ fetchLog, writes, intervals: intervals.map(i => i.ms), reloads, snaps,
  html: stage._html, transforms, rootClasses: [...rootClasses] }));
})().catch(e => { console.error(e && e.stack || String(e)); process.exit(1); });
"""


def _run_js(script):
    node = _node()
    if not node:
        pytest.skip("node not available")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def _overlay(search="?teams=1,2", queue=(), steps="", w=1920, h=1080):
    script = (_OVERLAY_HARNESS
              .replace("__SEARCH__", json.dumps(search))
              .replace("__QUEUE__", json.dumps(list(queue)))
              .replace("__W__", str(w)).replace("__H__", str(h))
              .replace("__STEPS__", steps)
              .replace("__PAGE__", _read("frontend", "obs", "last-game.js")))
    return _run_js(script)


def _ok(body):
    return {"kind": "json", "body": body}


def _team(tid, name, players):
    return {"team_id": tid, "team_name": name, "players": players}


def _default_teams(names=("Reds", "Blues")):
    return [
        _team(1, names[0], [_p(11, "Ann", 20.5, top=True, mvp=True), _p(12, "Bob", 12, k=9, d=1, a=4),
                            _p(13, "Cat", 8.3), _p(14, "Dan", 5.1), _p(15, "Eve", 2.0, icon=None)]),
        _team(2, names[1], [_p(21, "Fay", 15.2), _p(22, "Gus", 10.0), _p(23, "Hal", 7.7),
                            _p(24, "Ivy", 3.3), _p(25, "Jon", 1.1)]),
    ]


def _data(game_number=2, match_id=902, winner=1, duration=2145, score=(2, 0), pending=None,
          game=True, names=("Reds", "Blues"), teams=None):
    g = None
    if game:
        g = {"match_id": match_id, "game_number": game_number, "winner_team_id": winner,
             "duration": duration, "start_time": T, "parse_status": "parsed",
             "excluded_from_scoring": False,
             "teams": teams if teams is not None else _default_teams(names)}
    return {"teams": [{"team_id": 1, "team_name": names[0]}, {"team_id": 2, "team_name": names[1]}],
            "series_score": {"1": score[0], "2": score[1]}, "pending_game": pending, "game": g}


# --- How to Play URL builder Node harness -----------------------------------

_BUILDER_HARNESS = r"""
(async () => {
const els = {};
const mk = id => { els[id] = { id, value: "", innerHTML: "", disabled: false, checked: false, dataset: {},
  attrs: {}, textContent: "", selected: false,
  setAttribute(k, v) { this.attrs[k] = String(v); }, removeAttribute(k) { delete this.attrs[k]; },
  select() { this.selected = true; } }; };
["obs-team-a", "obs-team-b", "obs-url", "obs-copy", "obs-preview", "obs-transparent", "obs-copy-status"].forEach(mk);
els["obs-copy"].disabled = true;
const document = { getElementById: id => els[id] || null };
const location = { origin: "https://kana-cards.com" };
const API = "";
const TEAMS = __TEAMS__;
const fetchLog = [];
const fetch = async url => { fetchLog.push(url); return { ok: true, json: async () => JSON.parse(JSON.stringify(TEAMS)) }; };
const CLIP = __CLIP__;
const copied = [];
const navigator = CLIP === "missing" ? {} : { clipboard: { writeText: async t => {
  if (CLIP === "reject") throw new Error("denied"); copied.push(t); } } };
__FUNCS__
const out = {};
__STEPS__
console.log(JSON.stringify({ out, fetchLog, copied, els }));
})().catch(e => { console.error(e && e.stack || String(e)); process.exit(1); });
"""

_BUILDER_FUNCS = ("obsOverlayCopyEnabled", "obsOverlayUrl", "obsOverlayTeamOptions",
                  "loadObsOverlayBuilder", "updateObsOverlayUrl", "copyObsOverlayUrl")


def _js_fn(js, name):
    """A top-level function's source (with `async` when it has it), up to its `\\n}\\n`."""
    start = js.index(f"function {name}(")
    if js[max(0, start - 6):start] == "async ":
        start -= 6
    return js[start:js.index("\n}\n", start) + 2]


def _builder(steps, teams=None, clip="ok"):
    init = _read("frontend", "app-init.js")
    funcs = "\n".join(_js_fn(init, n) for n in _BUILDER_FUNCS)
    funcs += "\n" + _js_fn(_read("frontend", "app-globals.js"), "_escHtml")
    script = (_BUILDER_HARNESS
              .replace("__TEAMS__", json.dumps(teams if teams is not None else []))
              .replace("__CLIP__", json.dumps(clip))
              .replace("__STEPS__", steps)
              .replace("__FUNCS__", funcs))
    return _run_js(script)


# --- Streamers panel slices --------------------------------------------------

def _streamers():
    return _extract_panel(_read("frontend", "index.html"), "streamers")


_SECTION_IDS = ["htp-streamers-overlay", "htp-streamers-extension", "htp-streamers-viewer-vote",
                "htp-streamers-mvp-vote"]


def _section(sid):
    panel = _streamers()
    start = panel.rindex("<div", 0, panel.index(f'id="{sid}"'))
    i = _SECTION_IDS.index(sid)
    if i + 1 < len(_SECTION_IDS):
        end = panel.rindex("<div", 0, panel.index(f'id="{_SECTION_IDS[i + 1]}"'))
    else:
        end = len(panel)
    return panel[start:end]


def _text(html):
    return " ".join(_tree(html).text().split())


# ---------------------------------------------------------------------------
# Story: Show the Last Game on the Pause Screen
# ---------------------------------------------------------------------------

class TestShowLastGameOnPauseScreen:

    def test_last_game_returns_newest_game_of_current_series(self, db):
        """`obs_overlay.last_game(db, 1, 2, now)` with games 900 (ts T), 901 (T+1h),
        902 (T+2h) between teams 1 and 2 and now = T+3h returns `game.match_id`
        902, `game_number` 3, `winner_team_id` from 902's `radiant_win`,
        `duration` and `start_time` equal to the stored match's values."""
        import obs_overlay
        for i, mid in enumerate((900, 901, 902)):
            _seed_game(db, mid, ts=T + i * 3600, rw=(mid != 902), duration=1700 + i)
        out = obs_overlay.last_game(db, 1, 2, T + 3 * 3600)
        game = out["game"]
        assert game["match_id"] == 902
        assert game["game_number"] == 3
        assert game["winner_team_id"] == 2  # 902: radiant (team 1) lost
        stored = db.get(models.Match, 902)
        assert game["duration"] == stored.duration == 1702
        assert game["start_time"] == stored.start_time == T + 2 * 3600

    def test_last_game_series_score_counts_wins_up_to_newest_game(self, db):
        """With team 1 winning 900 and team 2 winning 901 (radiant/dire swapped on
        901), `series_score` is `{"<team 1 id>": 1, "<team 2 id>": 1}` (or the
        agreed shape: one win count per team id, both present); a game with NULL
        `radiant_win` counts for nobody (`schedule._tally_wins`)."""
        import obs_overlay
        _seed_game(db, 900, ts=T, radiant=1, dire=2, rw=True)
        _seed_game(db, 901, ts=T + 3600, radiant=2, dire=1, rw=True)
        out = obs_overlay.last_game(db, 1, 2, T + 2 * 3600)
        assert out["series_score"] == {"1": 1, "2": 1}
        assert out["game"]["winner_team_id"] == 2

        _seed_game(db, 902, ts=T + 2 * 3600, rw=None)
        out = obs_overlay.last_game(db, 1, 2, T + 3 * 3600)
        assert out["series_score"] == {"1": 1, "2": 1}
        assert out["game"]["game_number"] == 3
        assert out["game"]["winner_team_id"] is None

    def test_last_game_game_payload_is_game_players_output(self, db):
        """`game` carries `parse_status`, `excluded_from_scoring` and `teams`
        exactly as `schedule.game_players(db, match_id)` returns them for the
        newest game: both teams, five players each, `raw_points` equal to
        `_expected_raw(db, mid)`, `is_mvp` on the MVP, `top` on the highest raw
        score."""
        import obs_overlay
        import schedule
        _seed_game(db, 900, ts=T)
        game = obs_overlay.last_game(db, 1, 2, T + 600)["game"]
        expected = schedule.game_players(db, 900)
        assert game["parse_status"] == expected["parse_status"] == "parsed"
        assert game["excluded_from_scoring"] is expected["excluded_from_scoring"] is False
        assert game["teams"] == expected["teams"]
        assert [t["team_id"] for t in game["teams"]] == [1, 2]
        assert [len(t["players"]) for t in game["teams"]] == [5, 5]
        raw = _expected_raw(db, 900)
        for p in _players(game):
            assert set(p) == _PLAYER_KEYS
            assert p["raw_points"] == raw[p["player_id"]]
        assert [p["player_id"] for p in _players(game) if p["is_mvp"]] == [90004]
        best = max(raw.values())
        tops = [p for p in _players(game) if p["top"]]
        assert tops and all(p["raw_points"] == best for p in tops)

    def test_overlay_page_loads_only_own_script_and_stylesheet(self):
        """frontend/obs/last-game.html exists; parsed with html.parser its only
        `<script>` is `{"src": "/obs/last-game.js"}` (no inline script body, no
        `on*` attributes, no external or app-module scripts such as
        app-globals.js or alpinejs), and every stylesheet `<link>` is a local
        same-origin path (`/obs/last-game.css`, optionally
        `/colors_and_type.css`); no `http://` or `https://` URL in the HTML."""
        html = _read("frontend", "obs", "last-game.html")
        root = _tree(html)
        scripts = root.by_tag("script")
        assert [s.attrs for s in scripts] == [{"src": "/obs/last-game.js"}]
        assert all(s.text().strip() == "" for s in scripts)
        for node in root.walk():
            assert not any(k.startswith("on") for k in node.attrs), node.attrs
        hrefs = [n.attrs.get("href") for n in root.by_tag("link") if n.attrs.get("rel") == "stylesheet"]
        assert "/obs/last-game.css" in hrefs
        assert set(hrefs) <= {"/obs/last-game.css", "/colors_and_type.css"}
        assert "http://" not in html and "https://" not in html
        assert "app-globals.js" not in html and "alpine" not in html.lower()

    def test_overlay_page_served_by_static_mount_with_security_headers(self):
        """On `_main_client()`, GET `/obs/last-game.html`, `/obs/last-game.js` and
        `/obs/last-game.css` answer 200 with text/html, javascript and text/css
        content types, `x-content-type-options: nosniff`,
        `cache-control: no-cache`, and a CSP whose directive set has no
        `script-src`, `style-src`, `default-src`, `connect-src` or `img-src`
        that would block the page's own files (parse directives as
        test_security_headers does)."""
        from tests.test_issue_150_steam_login import _main_client
        client = _main_client()
        for path, kind in (("/obs/last-game.html", "text/html"), ("/obs/last-game.js", "javascript"),
                           ("/obs/last-game.css", "text/css")):
            resp = client.get(path)
            assert resp.status_code == 200, path
            assert kind in resp.headers["content-type"], path
            assert resp.headers["x-content-type-options"] == "nosniff"
            assert resp.headers["cache-control"] == "no-cache"
            csp = resp.headers.get("content-security-policy", "")
            directives = {parts[0]: set(parts[1:]) for d in csp.split(";") if (parts := d.strip().split())}
            assert "frame-ancestors" in directives
            for blocked in ("script-src", "style-src", "default-src", "connect-src", "img-src"):
                assert blocked not in directives, (path, blocked)

    def test_overlay_page_header_shows_teams_game_number_winner_duration_score(self):
        """Node harness: with a response for "Reds" vs "Blues", game 2, winner
        Reds, duration 2145 s, series score 2-0, the rendered stage contains both
        team names, "Game 2", the winner's name marked as winner, the duration
        "35:45" and "Series 2–0" (en dash, first number for the first team of
        the URL)."""
        out = _overlay(queue=[_ok(_data(game_number=2, winner=1, duration=2145, score=(2, 0)))])
        root = _tree(out["html"])
        header = root.by_class("obs-header")
        assert len(header) == 1
        text = " ".join(header[0].text().split())
        assert "Reds" in text and "Blues" in text
        assert "Game 2" in text
        assert "35:45" in text
        assert "Series 2\u20130" in text
        winners = root.by_class("obs-winner")
        assert len(winners) == 1
        assert "Reds" in winners[0].text() and "Winner" in winners[0].text()
        assert "obs-team-a" in winners[0].classes()

    def test_overlay_page_player_columns_sorted_with_hero_kda_and_one_decimal(self):
        """Node harness: two columns, one per team, five rows each in raw-points
        order (highest first), each with the player name, an `<img>` with the
        hero icon URL (no `<img>` or a placeholder when `hero_icon` is null),
        "K / D / A" as `kills / deaths / assists` and raw points with one
        decimal ("12.0", not "12"); the row with `top: true` carries a highlight
        class and the `is_mvp` row a star."""
        out = _overlay(queue=[_ok(_data())])
        root = _tree(out["html"])
        cols = root.by_class("obs-col")
        assert len(cols) == 2
        expected = _default_teams()
        for col, team in zip(cols, expected):
            assert team["team_name"] in col.by_class("obs-col-title")[0].text()
            rows = col.by_class("obs-row")
            assert len(rows) == 5
            for row, p in zip(rows, team["players"]):
                assert p["player_name"] in row.by_class("obs-name")[0].text()
                imgs = row.by_tag("img")
                if p["hero_icon"]:
                    assert [i.attrs["src"] for i in imgs] == [p["hero_icon"]]
                else:
                    assert imgs == []
                assert row.by_class("obs-kda")[0].text() == f"{p['kills']} / {p['deaths']} / {p['assists']}"
                assert row.by_class("obs-pts")[0].text() == f"{float(p['raw_points']):.1f}"
                assert ("obs-top" in row.classes()) is p["top"]
                stars = row.by_class("obs-mvp")
                assert (len(stars) == 1) is p["is_mvp"]
                if stars:
                    assert stars[0].text() == "\u2605"
        bob = cols[0].by_class("obs-row")[1]
        assert bob.by_class("obs-pts")[0].text() == "12.0"

    def test_overlay_page_shows_raw_points_label(self):
        """Node harness: the rendered game view contains the exact text
        "Raw fantasy points: before card bonuses"."""
        out = _overlay(queue=[_ok(_data())])
        assert "Raw fantasy points: before card bonuses" in _text(out["html"])

    def test_overlay_page_fixed_stage_scaled_to_window(self):
        """last-game.css gives the stage `width: 1920px; height: 1080px`; Node
        harness: with window 1280x720 the stage's `style.transform` is
        `scale(0.6666...)` (min of width/1920 and height/1080), and after a
        `resize` event to 1920x1080 it is `scale(1)`. Body text in the CSS is at
        least 28px at 1920 width (readable at 720p)."""
        css = _read("frontend", "obs", "last-game.css")
        stage = [body for sels, body in _css_rules(css) if ".obs-stage" in sels]
        assert stage
        decl = " ".join(stage[0].split())
        assert "width: 1920px" in decl and "height: 1080px" in decl
        sizes = [int(px) for px in re.findall(r"font-size:\s*(\d+)px", css)]
        assert sizes and min(sizes) >= 28
        assert re.search(r"font-size:\s*(\d+)px", decl) and int(re.search(r"font-size:\s*(\d+)px", decl).group(1)) >= 28

        out = _overlay(queue=[_ok(_data())], w=1280, h=720,
                       steps="resize(1920, 1080); transforms.push(stage.style.transform);")
        assert out["transforms"][0] == f"scale({min(1280 / 1920, 720 / 1080)})"
        assert out["transforms"][0].startswith("scale(0.6666")
        assert out["transforms"][1] == "scale(1)"

    def test_overlay_page_theme_transparent_drops_background(self):
        """Node harness with `?teams=1,2&theme=transparent`: the page marks the
        document (e.g. a `theme-transparent` class or `data-theme` on `<html>`)
        and last-game.css has a rule for that marker setting `background:
        transparent` on html AND body (colors_and_type.css sets both to
        var(--bg)); without `theme` the marker is absent and the stage uses the
        site's dark background token."""
        on = _overlay(search="?teams=1,2&theme=transparent", queue=[_ok(_data())])
        off = _overlay(search="?teams=1,2", queue=[_ok(_data())])
        assert "theme-transparent" in on["rootClasses"]
        assert "theme-transparent" not in off["rootClasses"]
        assert on["fetchLog"] == ["/obs/last-game?teams=1,2"]

        rules = _css_rules(_read("frontend", "obs", "last-game.css"))

        def _transparent(selector):
            return any(selector in sels and re.search(r"background:\s*transparent", body) for sels, body in rules)
        assert _transparent("html.theme-transparent")
        assert _transparent("html.theme-transparent body")
        assert _transparent("html.theme-transparent .obs-stage")
        stage = [body for sels, body in rules if ".obs-stage" in sels]
        assert re.search(r"background:\s*var\(--bg\)", stage[0])
        assert '<link rel="stylesheet" href="/colors_and_type.css">' in _read("frontend", "obs", "last-game.html")

    def test_overlay_page_escapes_team_and_player_names(self):
        """Failure path. Node harness: team and player names equal to `_EVIL`
        (`<img src=x onerror=alert(1)>`) appear in the rendered markup only as
        `&lt;img src=x onerror=alert(1)&gt;`, never as a tag; hero icon URLs
        are put in `src` attributes escaped as well."""
        bad_icon = 'https://cdn.example/h.png?a="><script>alert(1)</script>'
        teams = [_team(1, _EVIL, [_p(11, _EVIL, 9.0, top=True, icon=bad_icon)]),
                 _team(2, _EVIL, [_p(21, _EVIL, 1.0)])]
        out = _overlay(queue=[_ok(_data(names=(_EVIL, _EVIL), teams=teams))])
        html = out["html"]
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
        assert _EVIL not in html
        assert "<script" not in html
        root = _tree(html)
        for node in root.walk():
            assert not any(k.startswith("on") for k in node.attrs), node.attrs
        srcs = [n.attrs.get("src") for n in root.by_tag("img")]
        assert "x" not in srcs
        assert bad_icon in srcs  # one attribute value, escaped in the markup
        assert "&quot;&gt;&lt;script&gt;" in html

    def test_overlay_page_without_valid_teams_param_makes_no_request(self):
        """Failure path. Node harness with no `teams`, `?teams=1`, or
        `?teams=a,b`: the page makes no fetch and shows a short setup line
        (e.g. naming How to Play › Streamers), not an error over the stream."""
        for search in ("", "?teams=1", "?teams=a,b", "?teams=1,1", "?teams=0,2"):
            out = _overlay(search=search, queue=[_ok(_data())])
            assert out["fetchLog"] == [], search
            assert out["intervals"] == [], search
            text = _text(out["html"])
            assert "How to Play" in text and "Streamers" in text, search
            assert "error" not in text.lower()


# ---------------------------------------------------------------------------
# Story: Follow the Series Without Touching OBS
# ---------------------------------------------------------------------------

class TestFollowSeriesWithoutTouchingObs:

    def test_overlay_page_polls_obs_endpoint_every_30_seconds(self):
        """Node harness with `?teams=1,2`: the page fetches exactly
        `/obs/last-game?teams=1,2` on load, registers one 30000 ms interval
        (or a 30000 ms setTimeout chain), and every fetched URL in the run is
        that one URL (no `/matches/`, `/teams`, `/me` or other calls)."""
        out = _overlay(queue=[_ok(_data()), _ok(_data()), _ok(_data())],
                       steps="await tick(); await tick();")
        assert out["snaps"][0]["fetches"] == 1
        assert out["fetchLog"][0] == "/obs/last-game?teams=1,2"
        assert out["intervals"] == [30000]
        assert out["fetchLog"] == ["/obs/last-game?teams=1,2"] * 3

    def test_overlay_page_redraws_only_when_data_changes(self):
        """Node harness: two refreshes with an identical response write the stage
        once; a third with a changed `raw_points` or `pending_game` writes it
        again (count stage writes)."""
        import copy
        base = _data()
        changed = copy.deepcopy(base)
        changed["game"]["teams"][0]["players"][0]["raw_points"] = 21.5
        pending = copy.deepcopy(changed)
        pending["pending_game"] = 3
        out = _overlay(queue=[_ok(base), _ok(base), _ok(changed), _ok(pending)],
                       steps='await tick(); snap("same"); await tick(); snap("changed"); await tick(); snap("pending");')
        assert [s["writes"] for s in out["snaps"]] == [1, 1, 2, 3]
        assert "21.5" in out["snaps"][2]["html"]
        assert "Game 3 stats are on their way" in out["snaps"][3]["html"]

    def test_overlay_page_moves_to_game_2_without_reload(self):
        """Node harness: first response game 1 (match 901), next refresh game 2
        (match 902): the stage now shows "Game 2" and game 2's players, with no
        `location.reload` call."""
        game1 = _data(game_number=1, match_id=901, score=(1, 0))
        game2 = _data(game_number=2, match_id=902, score=(1, 1), winner=2, teams=[
            _team(1, "Reds", [_p(16, "Kim", 4.0, top=False)]),
            _team(2, "Blues", [_p(26, "Zed", 18.8, top=True)]),
        ])
        out = _overlay(queue=[_ok(game1), _ok(game2)], steps='snap("g1"); await tick();')
        first, last = _text(out["snaps"][0]["html"]), _text(out["html"])
        assert "Game 1" in first and "Ann" in first
        assert "Game 2" in last and "Zed" in last and "Kim" in last
        assert "Ann" not in last
        assert "Series 1\u20131" in last
        assert out["reloads"] == 0

    def test_last_game_reports_pending_game_while_stats_missing(self, db):
        """With game 900 stored (ts = now - 1h) and a `LiveMatch` 901 for teams 2
        (radiant) and 1 (dire) with `ended_at = now - 5 min` and no stats,
        `last_game(db, 1, 2, now)` returns `pending_game` 2 and `game.match_id`
        900."""
        import obs_overlay
        now = T + 10 * 3600
        _seed_game(db, 900, ts=now - 3600)
        _live(db, 901, 2, 1, ended_at=now - 5 * 60, now=now)
        out = obs_overlay.last_game(db, 1, 2, now)
        assert out["pending_game"] == 2
        assert out["game"]["match_id"] == 900

    def test_last_game_pending_game_cleared_once_stats_arrive(self, db):
        """Failure path. The same LiveMatch once 901's stats are stored (match row
        plus player_match_stats) gives `pending_game` None and `game.match_id`
        901, `game_number` 2."""
        import obs_overlay
        now = T + 10 * 3600
        _seed_game(db, 900, ts=now - 3600)
        _live(db, 901, 2, 1, ended_at=now - 5 * 60, now=now)
        _seed_game(db, 901, ts=now - 2400, radiant=2, dire=1)
        out = obs_overlay.last_game(db, 1, 2, now)
        assert out["pending_game"] is None
        assert out["game"]["match_id"] == 901
        assert out["game"]["game_number"] == 2

    def test_last_game_pending_window_follows_fast_poll_minutes(self, db, monkeypatch):
        """A LiveMatch that ended longer ago than the fast-poll window (20
        minutes by default, the same env var `INGEST_POST_MATCH_FAST_POLL_MINUTES`
        main reads; monkeypatch obs_overlay's module-level value) gives
        `pending_game` None; a row with `ended_at` None (still live) is never
        pending; with the window set to 0 nothing is pending."""
        import obs_overlay
        assert obs_overlay.PENDING_WINDOW_MINUTES == int(os.getenv("INGEST_POST_MATCH_FAST_POLL_MINUTES", "20"))
        src = _read("backend", "obs_overlay.py")
        assert "INGEST_POST_MATCH_FAST_POLL_MINUTES" in src and "import main" not in src
        monkeypatch.setattr(obs_overlay, "PENDING_WINDOW_MINUTES", 20)
        now = T + 10 * 3600
        _seed_teams(db)
        _live(db, 901, 1, 2, ended_at=now - 21 * 60, now=now)
        assert obs_overlay.last_game(db, 1, 2, now)["pending_game"] is None
        _live(db, 902, 1, 2, ended_at=None, now=now)
        assert obs_overlay.last_game(db, 1, 2, now)["pending_game"] is None
        _live(db, 903, 1, 2, ended_at=now - 5 * 60, now=now)
        assert obs_overlay.last_game(db, 1, 2, now)["pending_game"] == 1
        monkeypatch.setattr(obs_overlay, "PENDING_WINDOW_MINUTES", 0)
        assert obs_overlay.last_game(db, 1, 2, now)["pending_game"] is None
        monkeypatch.setattr(obs_overlay, "PENDING_WINDOW_MINUTES", -5)
        assert obs_overlay.last_game(db, 1, 2, now)["pending_game"] is None

    def test_last_game_pending_ignores_other_team_pairs(self, db):
        """Failure path. A recently ended LiveMatch between team 1 and team 3, or
        with one team id NULL, gives `pending_game` None for teams 1 and 2."""
        import obs_overlay
        now = T + 10 * 3600
        _seed_teams(db)
        db.add(models.Team(id=3, name="Greens"))
        db.commit()
        _live(db, 901, 1, 3, ended_at=now - 60, now=now)
        _live(db, 902, 1, None, ended_at=now - 60, now=now)
        _live(db, 903, None, 2, ended_at=now - 60, now=now)
        out = obs_overlay.last_game(db, 1, 2, now)
        assert out["pending_game"] is None
        assert out["game"] is None

    def test_overlay_page_pending_line_above_last_game(self):
        """Node harness: a response with `pending_game` 2 and game 1 shows
        "Game 2 stats are on their way" before (above, in document order) game
        1's header and player table."""
        out = _overlay(queue=[_ok(_data(game_number=1, match_id=901, score=(1, 0), pending=2))])
        html = out["html"]
        line = "Game 2 stats are on their way"
        assert line in html
        assert html.index(line) < html.index("Game 1") < html.index("obs-players")
        assert html.index(line) < html.index('class="obs-header"')

    def test_last_game_before_first_game_has_null_game(self, db):
        """With teams 1 and 2 known and their only meeting 3 days before `now`,
        `last_game` returns `game` None, `series_score` zero for both and
        `pending_game` None: an old meeting is never shown."""
        import obs_overlay
        now = T + 30 * 86400
        _seed_game(db, 900, ts=now - 3 * 86400)
        out = obs_overlay.last_game(db, 1, 2, now)
        assert out["game"] is None
        assert out["series_score"] == {"1": 0, "2": 0}
        assert out["pending_game"] is None
        assert out["teams"] == [{"team_id": 1, "team_name": "Reds"}, {"team_id": 2, "team_name": "Blues"}]

    def test_last_game_gap_over_6_hours_starts_new_series(self, db):
        """Games at T, T+1h, then T+8h (now = T+8.5h): the series is only the T+8h
        game (`game_number` 1, score 1-0 or 0-1), while games exactly 6 h apart
        still belong together (inclusive, as weekly_summary)."""
        import obs_overlay
        _seed_game(db, 900, ts=T)
        _seed_game(db, 901, ts=T + 3600)
        _seed_game(db, 902, ts=T + 8 * 3600)
        out = obs_overlay.last_game(db, 1, 2, T + 8 * 3600 + 1800)
        assert out["game"]["match_id"] == 902
        assert out["game"]["game_number"] == 1
        assert out["series_score"] == {"1": 1, "2": 0}

        db.add_all([models.Team(id=3, name="Greens"), models.Team(id=4, name="Golds")])
        db.commit()
        _match(db, 950, ts=T, radiant=3, dire=4)
        _match(db, 951, ts=T + 6 * 3600, radiant=4, dire=3)
        out = obs_overlay.last_game(db, 3, 4, T + 6 * 3600 + 60)
        assert out["game"]["match_id"] == 951
        assert out["game"]["game_number"] == 2
        assert out["series_score"] == {"3": 1, "4": 1}
        # Exactly 6 hours after the newest game's start still counts as the current series.
        assert obs_overlay.last_game(db, 3, 4, T + 12 * 3600)["game"]["match_id"] == 951
        assert obs_overlay.last_game(db, 3, 4, T + 12 * 3600 + 1)["game"] is None

    def test_last_game_series_gap_is_shared_constant(self):
        """Source check: backend/obs_overlay.py contains no `6 * 3600` / `21600`
        literal and uses the shared series-gap constant (e.g.
        `schedule.SERIES_GAP_SECONDS`, also used by
        `routers.weekly_summary._SERIES_GAP`)."""
        import inspect
        import schedule
        from routers import admin_ingest, weekly_summary
        src = _read("backend", "obs_overlay.py")
        assert "6 * 3600" not in src and "21600" not in src
        assert "SERIES_GAP_SECONDS" in src
        assert schedule.SERIES_GAP_SECONDS == 6 * 3600
        assert weekly_summary._SERIES_GAP == schedule.SERIES_GAP_SECONDS
        assert admin_ingest.SERIES_GAP_SECONDS == schedule.SERIES_GAP_SECONDS
        assert "6 * 3600" not in inspect.getsource(schedule._build_unscheduled_results)
        for path in (("backend", "routers", "weekly_summary.py"), ("backend", "routers", "admin_ingest.py")):
            assert "6 * 3600" not in _read(*path), path

    def test_last_game_teams_in_either_order_same_answer(self, db):
        """`last_game(db, 1, 2, now)` and `last_game(db, 2, 1, now)` return the same
        `game` and `pending_game`; `teams` and `series_score` follow the order
        given."""
        import obs_overlay
        now = T + 3 * 3600
        _seed_game(db, 900, ts=T, rw=True)
        _seed_game(db, 901, ts=T + 3600, rw=False)
        _live(db, 902, 1, 2, ended_at=now - 60, now=now)
        ab = obs_overlay.last_game(db, 1, 2, now)
        ba = obs_overlay.last_game(db, 2, 1, now)
        assert ab["pending_game"] == ba["pending_game"] == 3
        strip = lambda g: {k: v for k, v in g.items() if k != "teams"}
        assert strip(ab["game"]) == strip(ba["game"])
        assert ba["game"]["teams"] == list(reversed(ab["game"]["teams"]))
        assert [t["team_id"] for t in ab["teams"]] == [1, 2]
        assert [t["team_id"] for t in ba["teams"]] == [2, 1]
        assert list(ab["series_score"].items()) == [("1", 1), ("2", 1)]
        assert list(ba["series_score"].items()) == [("2", 1), ("1", 1)]

    def test_last_game_ignores_matches_with_missing_side_id(self, db):
        """A newer match with `radiant_team_id` 1 and `dire_team_id` NULL (stats
        rows for teams 1 and 2) is not part of the series: `game` stays the
        newest match whose radiant/dire ids are exactly {1, 2} (the rule
        `_build_unscheduled_results` and `resolve_series_result` use)."""
        import obs_overlay
        _seed_game(db, 900, ts=T)
        _match(db, 901, ts=T + 3600, radiant=1, dire=None)
        _stat(db, 90101, 901, team=1)
        _stat(db, 90102, 901, team=2)
        out = obs_overlay.last_game(db, 1, 2, T + 2 * 3600)
        assert out["game"]["match_id"] == 900
        assert out["game"]["game_number"] == 1
        assert out["series_score"] == {"1": 1, "2": 0}

    def test_overlay_page_waiting_line_before_first_game(self):
        """Node harness: a response with `game` null and `pending_game` null shows
        both team names and "Stats appear here a few minutes after each game
        ends." and no player table."""
        out = _overlay(queue=[_ok(_data(game=False, pending=None, score=(0, 0)))])
        text = _text(out["html"])
        assert "Reds" in text and "Blues" in text
        assert "Stats appear here a few minutes after each game ends." in text
        assert "stats are on their way" not in text
        assert "<table" not in out["html"]
        assert _tree(out["html"]).by_class("obs-row") == []

    def test_overlay_page_game_1_pending_shows_pending_line_without_old_game(self):
        """Node harness: `game` null with `pending_game` 1 shows both team names
        and "Game 1 stats are on their way", and no player table (see the
        ambiguity note in the module docstring)."""
        out = _overlay(queue=[_ok(_data(game=False, pending=1, score=(0, 0)))])
        text = _text(out["html"])
        assert "Reds" in text and "Blues" in text
        assert "Game 1 stats are on their way" in text
        assert "Stats appear here" not in text
        assert "<table" not in out["html"]

    def test_overlay_page_failed_request_keeps_last_view_and_retries(self):
        """Failure path. Node harness: after a good response, a refresh answering
        500 and a refresh whose fetch rejects leave the stage markup unchanged,
        show no error text, and the next refresh with a good response renders
        again (the interval keeps running)."""
        import copy
        good = _data()
        later = copy.deepcopy(good)
        later["game"]["teams"][1]["players"][0]["player_name"] = "Newcomer"
        out = _overlay(queue=[_ok(good), {"kind": "error", "status": 500}, {"kind": "reject"}, _ok(later)],
                       steps='await tick(); snap("500"); await tick(); snap("reject"); await tick(); snap("again");')
        load, e500, rejected, again = out["snaps"]
        assert e500["html"] == load["html"] and rejected["html"] == load["html"]
        assert e500["writes"] == rejected["writes"] == 1
        for snap in (e500, rejected):
            text = _text(snap["html"]).lower()
            assert "error" not in text and "500" not in text and "network" not in text
        assert again["writes"] == 2 and "Newcomer" in again["html"]
        assert out["intervals"] == [30000]
        assert len(out["fetchLog"]) == 4


# ---------------------------------------------------------------------------
# Story: Build the Overlay URL
# ---------------------------------------------------------------------------

class TestBuildOverlayUrl:

    def test_streamers_overlay_section_has_builder_controls(self):
        """In `#howtoplay-panel-streamers` (frontend/index.html), a section titled
        "Pause screen overlay" contains two `<select>` team pickers, a checkbox
        labelled "Transparent background", a read-only `<input>` for the URL, a
        "Copy" button and an "Open preview" link with `target="_blank"` and
        `rel="noopener"` (html.parser)."""
        section = _tree(_section("htp-streamers-overlay"))
        assert [h.text().strip() for h in section.by_tag("h2")] == ["Pause screen overlay"]
        selects = section.by_tag("select")
        assert [s.attrs.get("id") for s in selects] == ["obs-team-a", "obs-team-b"]
        inputs = section.by_tag("input")
        boxes = [i for i in inputs if i.attrs.get("type") == "checkbox"]
        assert len(boxes) == 1
        label = boxes[0].parent
        assert label.tag == "label" and "Transparent background" in label.text()
        url = [i for i in inputs if i.attrs.get("id") == "obs-url"]
        assert len(url) == 1 and "readonly" in url[0].attrs
        buttons = [b for b in section.by_tag("button") if b.text().strip() == "Copy"]
        assert len(buttons) == 1 and "disabled" in buttons[0].attrs
        links = [a for a in section.by_tag("a") if a.text().strip() == "Open preview"]
        assert len(links) == 1
        assert links[0].attrs.get("target") == "_blank"
        assert "noopener" in links[0].attrs.get("rel", "").split()

    def test_streamers_overlay_section_explains_obs_steps(self):
        """The Pause screen overlay section has a three-item list: add a Browser
        Source, paste the URL, set width 1920 and height 1080 ("1920" and "1080"
        both present)."""
        section = _tree(_section("htp-streamers-overlay"))
        steps = section.by_class("obs-steps")
        assert len(steps) == 1 and steps[0].tag == "ol"
        items = [" ".join(li.text().split()) for li in steps[0].by_tag("li")]
        assert len(items) == 3
        assert "Browser Source" in items[0]
        assert "Paste the URL" in items[1]
        assert "1920" in items[2] and "1080" in items[2]

    def test_overlay_url_builder_fills_pickers_from_teams_by_name(self):
        """Node harness over the builder functions in app-init.js: given a
        `GET /teams` response ordered by division (`[{id: 2, name: "Zeta"},
        {id: 1, name: "Alpha"}]`), the pickers list "Alpha" then "Zeta" with
        values "1" and "2", names escaped."""
        teams = [{"id": 2, "name": "Zeta"}, {"id": 1, "name": "Alpha"}, {"id": 3, "name": "Mid " + _EVIL}]
        out = _builder("await loadObsOverlayBuilder();", teams=teams)
        assert out["fetchLog"] == ["/teams"]
        for pid in ("obs-team-a", "obs-team-b"):
            html = out["els"][pid]["innerHTML"]
            options = [(o.attrs.get("value"), o.text()) for o in _tree(html).by_tag("option")]
            assert options[0][0] == ""
            assert options[1:] == [("1", "Alpha"), ("3", "Mid " + _EVIL), ("2", "Zeta")]
            assert "&lt;img src=x onerror=alert(1)&gt;" in html
            assert [n for n in _tree(html).walk() if n.tag == "img"] == []

    def test_overlay_url_builder_builds_exact_url(self):
        """Node harness: `obsOverlayUrl("https://kana-cards.com", 3, 7, false)` (or
        the agreed function) equals exactly
        `https://kana-cards.com/obs/last-game.html?teams=3,7`, and with
        transparent checked
        `https://kana-cards.com/obs/last-game.html?teams=3,7&theme=transparent`;
        the URL field and the preview link's href get that value, built from
        `location.origin`."""
        steps = """
        out.plain = obsOverlayUrl("https://kana-cards.com", 3, 7, false);
        out.transparent = obsOverlayUrl("https://kana-cards.com", 3, 7, true);
        els["obs-team-a"].value = "3"; els["obs-team-b"].value = "7";
        updateObsOverlayUrl();
        out.field1 = els["obs-url"].value; out.href1 = els["obs-preview"].attrs.href;
        els["obs-transparent"].checked = true;
        updateObsOverlayUrl();
        out.field2 = els["obs-url"].value; out.href2 = els["obs-preview"].attrs.href;
        """
        out = _builder(steps)["out"]
        plain = "https://kana-cards.com/obs/last-game.html?teams=3,7"
        transparent = "https://kana-cards.com/obs/last-game.html?teams=3,7&theme=transparent"
        assert out["plain"] == plain
        assert out["transparent"] == transparent
        assert out["field1"] == plain and out["href1"] == plain
        assert out["field2"] == transparent and out["href2"] == transparent
        assert "location.origin" in _js_fn(_read("frontend", "app-init.js"), "updateObsOverlayUrl")

    def test_overlay_url_builder_copy_uses_clipboard_with_fallback(self):
        """Node harness: Copy calls `navigator.clipboard.writeText(url)`; when the
        Clipboard API is missing or rejects, the URL field is selected
        (`select()`) instead and no exception escapes."""
        steps = """
        els["obs-team-a"].value = "3"; els["obs-team-b"].value = "7";
        updateObsOverlayUrl();
        await copyObsOverlayUrl();
        out.selected = els["obs-url"].selected;
        """
        url = "https://kana-cards.com/obs/last-game.html?teams=3,7"
        ok = _builder(steps, clip="ok")
        assert ok["copied"] == [url] and ok["out"]["selected"] is False
        for clip in ("missing", "reject"):
            res = _builder(steps, clip=clip)
            assert res["copied"] == [], clip
            assert res["out"]["selected"] is True, clip

    def test_overlay_url_builder_copy_disabled_until_two_different_teams(self):
        """Failure path. Node harness: with no team, one team, or the same team in
        both pickers, Copy is `disabled`, the URL field is empty and the preview
        link is disabled or has no usable href; picking two different teams
        enables Copy."""
        steps = """
        out.rows = [];
        for (const [a, b] of [["", ""], ["3", ""], ["", "7"], ["3", "3"], ["3", "7"]]) {
          els["obs-team-a"].value = a; els["obs-team-b"].value = b;
          updateObsOverlayUrl();
          out.rows.push({ a, b, disabled: els["obs-copy"].disabled, url: els["obs-url"].value,
            href: els["obs-preview"].attrs.href ?? null, aria: els["obs-preview"].attrs["aria-disabled"] ?? null,
            enabled: obsOverlayCopyEnabled(a, b) });
        }
        """
        rows = _builder(steps)["out"]["rows"]
        for row in rows[:-1]:
            assert row["disabled"] is True, row
            assert row["url"] == "" and row["href"] is None and row["aria"] == "true", row
            assert row["enabled"] is False, row
        last = rows[-1]
        assert last["disabled"] is False and last["enabled"] is True
        assert last["href"] == last["url"] == "https://kana-cards.com/obs/last-game.html?teams=3,7"
        assert last["aria"] is None


# ---------------------------------------------------------------------------
# Story: Streamers Tab Lists Every Streamer Tool
# ---------------------------------------------------------------------------

class TestStreamersTabListsEveryTool:

    def test_streamers_overview_lists_four_tools_with_in_page_links(self):
        """The streamers panel opens (before any tool section) with a list of four
        one-line items, in order, naming "Pause screen overlay", "Kana Cards
        extension", "Viewer MVP vote" and "Kana Cards MVP Vote", each with an
        `<a href="#...">` link; the overlay item says it needs no extension."""
        panel = _streamers()
        first_section = panel.index('id="htp-streamers-overlay"')
        overview = _tree(panel[:first_section])
        lists = overview.by_class("htp-tool-list")
        assert len(lists) == 1
        items = lists[0].by_tag("li")
        assert len(items) == 4
        names = ["Pause screen overlay", "Kana Cards extension", "Viewer MVP vote", "Kana Cards MVP Vote"]
        for li, name in zip(items, names):
            links = li.by_tag("a")
            assert len(links) == 1 and links[0].text().strip() == name
            assert links[0].attrs["href"].startswith("#")
        assert "no extension needed" in items[0].text()

    def test_streamers_overview_links_resolve_to_sections_in_panel(self):
        """Failure path. Every overview `href="#id"` names an element id that
        exists exactly once in index.html and lies inside the streamers panel
        slice (`_extract_panel(html, "streamers")` of
        test_how_to_play_role_subtabs)."""
        html = _read("frontend", "index.html")
        panel = _streamers()
        overview = _tree(panel[:panel.index('id="htp-streamers-overlay"')])
        hrefs = [a.attrs["href"] for a in overview.by_class("htp-tool-list")[0].by_tag("a")]
        assert [h[1:] for h in hrefs] == _SECTION_IDS
        ids = [n.attrs.get("id") for n in _tree(html).walk()]
        panel_ids = [n.attrs.get("id") for n in _tree(panel).walk()]
        for href in hrefs:
            target = href[1:]
            assert ids.count(target) == 1, target
            assert target in panel_ids, target

    def test_streamers_viewer_mvp_vote_section_names_real_controls(self):
        """The Viewer MVP vote section names Quick Actions, "Select match MVP",
        "Start viewer vote" with 1, 2 or 3 minutes, that joined viewers vote in
        the panel, "End now", "Cancel vote", and "Confirm MVP" setting the MVP
        and dropping tokens like a hand pick; each control label also appears in
        twitch-extension/live_config.html."""
        raw = _section("htp-streamers-viewer-vote")
        text = _text(raw)
        for phrase in ("Quick Actions", "Select match MVP", "Start viewer vote", "1, 2 or 3 minutes",
                       "Joined viewers vote in the Kana Cards panel", "End now", "Cancel vote",
                       "Confirm MVP & Drop Tokens", "sets the MVP and drops tokens just like a hand pick"):
            assert phrase in text, phrase
        live_config = _read("twitch-extension", "live_config.html")
        for label in ("Select match MVP", "Start viewer vote", "Open vote", "End now", "Cancel vote",
                      "Confirm MVP &amp; Drop Tokens"):
            assert label in raw, label
            assert label in live_config, label

    def test_streamers_mvp_vote_extension_section(self):
        """The Kana Cards MVP Vote section says it is for a vote without the card
        game, that any viewer logged in to Twitch can vote, that voters who share
        their Twitch identity can win a token claimed at kana-cards.com, and that
        a channel normally installs one of the two extensions."""
        raw = _section("htp-streamers-mvp-vote")
        text = _text(raw)
        for phrase in ("without the card game", "Any viewer logged in to Twitch can vote",
                       "share their Twitch identity", "can win a token", "kana-cards.com",
                       "normally installs one of the two extensions"):
            assert phrase in text, phrase
        vote_config = _read("twitch-vote-extension", "live_config.html")
        assert "Confirm MVP" in text and ">Confirm MVP<" in vote_config
        assert "Drop Tokens" not in text
        for label in ("Select match MVP", "Start viewer vote", "End now", "Cancel vote"):
            assert label in text and label in vote_config, label

    def test_streamers_status_text_matches_submission_guides(self):
        """Failure path. While the Review history of
        twitch-extension-review-submission.md records no approval and
        twitch-vote-extension-review-submission.md says "Not submitted yet.",
        the streamers panel contains none of `_STATUS_FORBIDDEN` and does not
        say the viewer vote or the MVP Vote extension is available on Twitch;
        the Getting access text says the extensions await Twitch review /
        are not yet released and keeps the test install link step."""
        full = _read("markdown", "features", "reference", "twitch-extension-review-submission.md")
        vote = _read("markdown", "features", "reference", "twitch-vote-extension-review-submission.md")
        history = full[full.index("## Review history"):]
        assert not re.search(r"\b(Approved|Released|Live on Twitch)\b", history)
        assert "Not yet built or submitted" in history  # 1.4.0, which carries the viewer vote
        assert "Not submitted yet." in vote[vote.index("## Review history"):]

        panel = _text(_streamers())
        # "not yet approved by Twitch" is the honest status; only a claim of approval fails.
        claims = panel.lower().replace("not yet approved by twitch", "")
        for phrase in _STATUS_FORBIDDEN:
            assert phrase.lower() not in claims, phrase
        assert "Local Test" not in panel
        access = _text(_section("htp-streamers-extension"))
        assert "not yet approved by Twitch" in access and "not yet available on Twitch" in access
        assert "test install link" in access
        viewer_vote = _text(_section("htp-streamers-viewer-vote"))
        assert "coming with version 1.4.0" in viewer_vote and "not yet available on Twitch" in viewer_vote
        mvp_vote = _text(_section("htp-streamers-mvp-vote"))
        assert "not yet been submitted for Twitch review" in mvp_vote and "not yet available on Twitch" in mvp_vote

    def test_streamers_extension_sections_repeat_league_approval(self):
        """The Kana Cards extension, Viewer MVP vote and Kana Cards MVP Vote
        sections each say a channel needs the league's approval before it can set
        MVPs, and the Pause screen overlay section says it needs no approval."""
        for sid in ("htp-streamers-extension", "htp-streamers-viewer-vote", "htp-streamers-mvp-vote"):
            assert "needs the league's approval before it can set MVPs" in _text(_section(sid)), sid
        overlay = _text(_section("htp-streamers-overlay"))
        assert "no approval" in overlay
        assert "league's approval" not in overlay

    def test_streamers_existing_pins_still_hold(self):
        """The updated panel still satisfies (or the same edit updated)
        test_how_to_play_role_subtabs.py `TestStreamersSubtab`: "Extension
        Manager", "no url configuration", "Quick Actions", "Select match MVP",
        "token drop", "one-time", "fantasy score bonus", no "EBS"; and the
        status pins ("Local Test", "publicly released") match the new Getting
        access wording."""
        panel = _streamers()
        for phrase in ("Extension Manager", "Quick Actions", "Select match MVP", "test install link"):
            assert phrase in panel, phrase
        lower = panel.lower()
        for phrase in ("no url configuration", "token drop", "one-time", "fantasy score bonus",
                       "publicly released", "series", "confirm"):
            assert phrase in lower, phrase
        assert "EBS" not in panel and "set-ebs-url" not in panel
        # "Local Test" is replaced by the review status (test_how_to_play_role_subtabs updated with it).
        assert "Local Test" not in panel


# ---------------------------------------------------------------------------
# Story: Public Endpoint for the Last Game
# ---------------------------------------------------------------------------

class TestPublicEndpointForLastGame:

    def test_obs_last_game_is_public_and_returns_shape(self, db):
        """`GET /obs/last-game?teams=1,2` with no session answers 200 with top-level
        keys exactly `teams`, `series_score`, `pending_game`, `game`; `teams` is
        two entries with the ids (in URL order) and names; `game` has exactly
        `match_id`, `game_number`, `winner_team_id`, `duration`, `start_time`,
        `parse_status`, `excluded_from_scoring`, `teams` (or the game_players
        payload nested under one key, as agreed)."""
        now = int(time.time())
        _seed_game(db, 900, ts=now - 1200)
        res = _obs_client(db).get("/obs/last-game", params={"teams": "1,2"})
        assert res.status_code == 200
        data = res.json()
        assert set(data) == {"teams", "series_score", "pending_game", "game"}
        assert data["teams"] == [{"team_id": 1, "team_name": "Reds"}, {"team_id": 2, "team_name": "Blues"}]
        assert data["series_score"] == {"1": 1, "2": 0}
        assert data["pending_game"] is None
        assert set(data["game"]) == {"match_id", "game_number", "winner_team_id", "duration", "start_time",
                                     "parse_status", "excluded_from_scoring", "teams"}
        assert data["game"]["match_id"] == 900 and data["game"]["game_number"] == 1
        reversed_ = _obs_client(db).get("/obs/last-game", params={"teams": " 2 , 1 "}).json()
        assert [t["team_id"] for t in reversed_["teams"]] == [2, 1]

    def test_obs_last_game_reachable_on_main_app_without_login(self, db):
        """On `main.app` (TestClient, `get_db` overridden as in test_issue_244), an
        anonymous `GET /obs/last-game?teams=1,2` answers 200 JSON, not the static
        mount's response or 401/403."""
        import main
        from fastapi.testclient import TestClient
        from database import get_db
        _seed_teams(db)

        def _get_db():
            yield db
        main.app.dependency_overrides[get_db] = _get_db
        try:
            res = TestClient(main.app).get("/obs/last-game?teams=1,2")
        finally:
            main.app.dependency_overrides.pop(get_db, None)
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/json")
        assert set(res.json()) == {"teams", "series_score", "pending_game", "game"}

    def test_obs_last_game_known_teams_without_series_returns_null_game(self, db):
        """Teams 1 and 2 exist with no matches: 200 with `game` null,
        `pending_game` null and zero scores (not 404)."""
        _seed_teams(db)
        res = _obs_client(db).get("/obs/last-game?teams=1,2")
        assert res.status_code == 200
        data = res.json()
        assert data["game"] is None and data["pending_game"] is None
        assert data["series_score"] == {"1": 0, "2": 0}

    @pytest.mark.parametrize("teams", ["", "1", "1,2,3", "1,1", "a,b", "1,", "0,2", "-1,2",
                                       f"1,{2**63}"])
    def test_obs_last_game_bad_teams_param_422(self, db, teams):
        """Failure path. `teams` that is not exactly two different integers in
        1..2**63-1 answers 422 (never 500); a missing `teams` parameter also
        answers 422."""
        _seed_teams(db)
        client = _obs_client(db)
        res = client.get("/obs/last-game", params={"teams": teams})
        assert res.status_code == 422, (teams, res.text)
        assert client.get("/obs/last-game").status_code == 422

    def test_obs_last_game_unknown_team_404(self, db):
        """Failure path. `teams=1,999999` with team 999999 not in `teams` answers
        404."""
        _seed_teams(db)
        res = _obs_client(db).get("/obs/last-game?teams=1,999999")
        assert res.status_code == 404
        assert _obs_client(db).get("/obs/last-game?teams=999999,2").status_code == 404

    def test_obs_last_game_returns_no_user_or_card_data(self, db):
        """With a user owning cards (and card_match_points) of the game's players,
        the JSON contains none of "owner", "user_id", "username", "card_id",
        "fantasy_points" or the user's name; player keys are exactly
        `_PLAYER_KEYS`."""
        import card_points
        now = int(time.time())
        pids = _seed_game(db, 900, ts=now - 600)
        user = models.User(username="SecretOwner", email="owner@example.com", password_hash="x")
        db.add(user)
        db.commit()
        for pid in pids[:3]:
            db.add(models.Card(player_id=pid, owner_id=user.id, card_type="rare", is_active=True))
        db.commit()
        card_points.rebuild_all(db)
        assert db.query(models.CardMatchPoints).count() > 0
        res = _obs_client(db).get("/obs/last-game?teams=1,2")
        assert res.status_code == 200
        body = res.text
        for word in ("owner", "user_id", "username", "card_id", "fantasy_points", "SecretOwner", "owner@example.com"):
            assert word not in body, word
        for p in _players(res.json()["game"]):
            assert set(p) == _PLAYER_KEYS

    def test_obs_last_game_covered_by_global_rate_limit(self, db):
        """The route has no `@limiter.exempt` and is limited per IP at the global
        rate (`RATE_LIMIT_GLOBAL`). Built: the limit sits on the route itself
        (`@limiter.limit(RATE_LIMIT_GLOBAL)` from `routers.obs.limiter`), because
        SlowAPIMiddleware's default limit never reaches routes added with
        `include_router` in the FastAPI this project runs (they are wrapped in
        `_IncludedRouter`; a fresh `Limiter(default_limits=["2/minute"])` lets every
        call through). The request after the budget answers 429 (no reload of
        `rate_limit`; the router's own Limiter is reset first)."""
        import inspect
        from limits import parse
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        from fastapi import FastAPI
        from routers import obs
        src = inspect.getsource(obs)
        assert "exempt" not in src
        assert "@limiter.limit(RATE_LIMIT_GLOBAL)" in src
        _seed_teams(db)
        app = FastAPI()
        app.state.limiter = obs.limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        client = _obs_client(db, app=app)
        budget = parse(obs.RATE_LIMIT_GLOBAL).amount
        assert budget < 2000
        # Other test files switch the shared limiter off (some without restoring it), so
        # turn it on for this test only, as test_issue_234 does.
        was_enabled = obs.limiter.enabled
        obs.limiter.enabled = True
        obs.limiter.reset()
        try:
            codes = [client.get("/obs/last-game?teams=1,2").status_code for _ in range(budget + 1)]
        finally:
            obs.limiter.reset()
            obs.limiter.enabled = was_enabled
        assert set(codes[:budget]) == {200}
        assert codes[budget] == 429
